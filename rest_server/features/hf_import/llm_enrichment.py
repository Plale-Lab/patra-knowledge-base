"""LLM-backed enrichment for the HuggingFace import feature (M1+M3 hybrid).

Ports the two-tier augmentation algorithm from the research POC
(poc/research/augment_poc_v2.py in the Plale-Lab/patra-metadata-augmentation-study
work) into the production import path:

Tier 1 (deterministic, always attempted first): pipeline_tag / config.model_type
lookup tables, ported verbatim from poc/research/generate_synthetic_dataset.py:1257-1347.

Tier 2 (LLM, only for whatever Tier 1 left null):
  - M1-style classifier (`classify_missing_lookup_fields`): ONE call, restricted
    to category/input_type/model_type, and only fires for whichever of those
    Tier 1's lookup table missed. No other field is ever touched by this call.
  - M3-style chain-of-thought (`reason_missing_hybrid_fields`): for
    foundational_model/input_data -- the two fields no lookup table can answer,
    since they require actually reading the README -- 3 sequential calls:
    analyze (no fill), generate (fill), verify (self-correct).

`citation` is never LLM-generated, under any tier, by design: a fabricated
citation is worse than an absent one. It is deterministic-only (BibTeX block
extraction), matching the POC's `never_llm` constraint exactly.

Every LLM call is wrapped so a failure (disabled config, timeout, malformed
JSON, off-vocabulary output) degrades to leaving the field null. This
endpoint must never fail or 5xx just because the LLM was slow, down, or
returned garbage -- the caller always gets back whatever Tier 1 produced.
"""

from __future__ import annotations

import json
import logging
import os
import re

from rest_server.features.shared.openai_compat import chat_text_with_model_fallback

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier 1 lookup tables -- ported verbatim from
# poc/research/generate_synthetic_dataset.py:1257-1347
# ---------------------------------------------------------------------------

PIPELINE_TO_CATEGORY = {
    "image-classification": "classification",
    "object-detection": "computer vision",
    "mask-generation": "computer vision",
    "fill-mask": "natural language processing",
    "text-generation": "natural language processing",
    "text2text-generation": "natural language processing",
    "automatic-speech-recognition": "classification",
    "text-to-audio": "generative modeling",
    "text-to-image": "generative modeling",
    "tabular-classification": "classification",
    "tabular-regression": "regression",
    "zero-shot-image-classification": "classification",
    "image-text-to-text": "natural language processing",
    "image-to-text": "generative modeling",
    "token-classification": "classification",
    "audio-classification": "classification",
    "graph-ml": "graph neural networks",
    "sentence-similarity": "natural language processing",
}

PIPELINE_TO_INPUT_TYPE = {
    "image-classification": "Image",
    "object-detection": "Image",
    "mask-generation": "Image",
    "fill-mask": "Text",
    "text-generation": "Text",
    "text2text-generation": "Text",
    "automatic-speech-recognition": "Audio",
    "text-to-audio": "Text",
    "text-to-image": "Text",
    "tabular-classification": "Tabular",
    "tabular-regression": "Tabular",
    "zero-shot-image-classification": "Multimodal",
    "image-text-to-text": "Multimodal",
    "image-to-text": "Image",
    "token-classification": "Text",
    "audio-classification": "Audio",
    "graph-ml": "Tabular",
    "sentence-similarity": "Text",
}

# ai_model.model_type enum: cnn, decision_tree, dnn, rnn, svm, kmeans, llm, random_forest, lstm, gnn, other
MODEL_TYPE_MAP = {
    "resnet": "cnn", "vit": "cnn", "convnext": "cnn", "efficientnet": "cnn",
    "bert": "dnn", "roberta": "dnn", "distilbert": "dnn", "electra": "dnn",
    "llama": "llm", "gpt2": "llm", "mistral": "llm", "falcon": "llm", "qwen": "llm",
    "t5": "dnn", "bart": "dnn",
    "whisper": "dnn",
    "lstm": "lstm", "gru": "rnn",
    "clip": "dnn",
    "gcn": "gnn", "gat": "gnn",
}

VALID_CATEGORIES = {
    "classification", "regression", "clustering", "anomaly detection",
    "dimensionality reduction", "reinforcement learning", "natural language processing",
    "computer vision", "recommendation systems", "time series forecasting",
    "graph learning", "graph neural networks", "generative modeling",
    "transfer learning", "self-supervised learning", "semi-supervised learning",
    "unsupervised learning", "causal inference", "multi-task learning",
    "metric learning", "density estimation", "multi-label classification",
    "ranking", "structured prediction", "neural architecture search",
    "sequence modeling", "embedding learning", "other",
}
VALID_INPUT_TYPES = {"Image", "Text", "Audio", "Tabular", "Multimodal", "Video"}
VALID_MODEL_TYPES = {
    "cnn", "decision_tree", "dnn", "rnn", "svm", "kmeans", "llm",
    "random_forest", "lstm", "gnn", "other",
}

_VALID_BY_FIELD = {
    "category": VALID_CATEGORIES,
    "input_type": VALID_INPUT_TYPES,
    "model_type": VALID_MODEL_TYPES,
}

# ---------------------------------------------------------------------------
# Config -- read at call time, not import time (mirrors
# rest_server/features/ask_patra/service.py's ASK_PATRA_LLM_* convention).
# ---------------------------------------------------------------------------


def _llm_enabled() -> bool:
    api_base = os.getenv("HF_IMPORT_LLM_API_BASE", "").strip()
    return bool(api_base) and os.getenv("HF_IMPORT_LLM_ENABLED", "true").strip().lower() == "true"


def _resolve_llm_auth(api_base: str, request_tapis_token: str | None) -> tuple[str | None, dict[str, str]]:
    # Mirrors rest_server/features/ask_patra/service.py's _resolve_llm_auth:
    # prefer a pod-level service token if one is ever configured, otherwise
    # fall back to the calling user's own Tapis token (hf-import is only
    # reachable by logged-in users via require_asset_ingest_principal, and
    # the frontend already forwards X-Tapis-Token on every request).
    service_tapis_token = os.getenv("HF_IMPORT_TAPIS_TOKEN", "").strip()
    if "litellm.pods.tacc.tapis.io" in api_base.lower() and service_tapis_token:
        return None, {"X-Tapis-Token": service_tapis_token}
    if "litellm.pods.tacc.tapis.io" in api_base.lower() and (request_tapis_token or "").strip():
        return None, {"X-Tapis-Token": request_tapis_token.strip()}
    api_key = os.getenv("HF_IMPORT_LLM_API_KEY", "").strip() or None
    return api_key, {}


def _call_llm(
    messages: list[dict[str, str]],
    *,
    request_tapis_token: str | None = None,
    max_tokens: int = 400,
    temperature: float = 0.2,
) -> str | None:
    """Returns raw text, or None if the LLM is disabled/unreachable/erroring.

    Never raises. Every caller treats None as "leave the field(s) null" --
    an LLM outage must degrade this feature, not break it.
    """
    if not _llm_enabled():
        return None
    api_base = os.getenv("HF_IMPORT_LLM_API_BASE", "").strip()
    api_key, extra_headers = _resolve_llm_auth(api_base, request_tapis_token)
    model = os.getenv("HF_IMPORT_LLM_MODEL", "").strip() or None
    timeout_seconds = int(os.getenv("HF_IMPORT_LLM_TIMEOUT_SECONDS", "60") or "60")
    try:
        text, _model_used = chat_text_with_model_fallback(
            api_base=api_base,
            model=model,
            api_key=api_key,
            extra_headers=extra_headers,
            messages=messages,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return text
    except Exception as exc:  # noqa: BLE001 -- LLM failure must never fail the whole preview
        log.warning("hf_import LLM call failed, degrading to deterministic-only: %s", exc)
        return None


def _parse_json_object(raw: str | None) -> dict:
    """Best-effort JSON object parse. Never raises -- returns {} on any failure."""
    if not raw:
        return {}
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Tier 1: deterministic derivation (no LLM)
# ---------------------------------------------------------------------------


def derive_category(pipeline_tag: str | None) -> str | None:
    return PIPELINE_TO_CATEGORY.get(pipeline_tag) if pipeline_tag else None


def derive_input_type(pipeline_tag: str | None) -> str | None:
    return PIPELINE_TO_INPUT_TYPE.get(pipeline_tag) if pipeline_tag else None


def derive_model_type(config: dict | None, name: str) -> str | None:
    """config.model_type first (a literal field in the model's config.json),
    then a name-pattern match. Returns None only if both miss -- the M1
    classifier fallback is the only thing that can still fill it then."""
    raw_type = ((config or {}).get("model_type") or "").strip().lower()
    if raw_type and raw_type in MODEL_TYPE_MAP:
        return MODEL_TYPE_MAP[raw_type]
    name_lower = name.lower()
    for pattern, mtype in MODEL_TYPE_MAP.items():
        if pattern in name_lower:
            return mtype
    return None


_CITATION_BIBTEX_RE = re.compile(r"```bibtex\s*\n(.*?)```", re.DOTALL)


def derive_citation(readme_text: str | None) -> str | None:
    """Deterministic-only, by design -- never LLM-generated. A hallucinated
    citation is worse than an absent one."""
    if not readme_text:
        return None
    match = _CITATION_BIBTEX_RE.search(readme_text)
    if not match:
        return None
    text = match.group(1).strip()
    return text or None


def derive_foundational_model(tags: list | None) -> str | None:
    for tag in tags or []:
        if not isinstance(tag, str) or not tag.startswith("base_model:"):
            continue
        raw = tag.removeprefix("base_model:")
        if raw.startswith("finetune:"):
            raw = raw.removeprefix("finetune:")
        raw = raw.strip()
        if raw:
            return raw.rsplit("/", 1)[-1]
    return None


def derive_input_data(tags: list | None) -> str | None:
    datasets = [
        tag.removeprefix("dataset:").strip()
        for tag in (tags or [])
        if isinstance(tag, str) and tag.startswith("dataset:") and tag.removeprefix("dataset:").strip()
    ]
    if not datasets:
        return None
    return ", ".join(f"https://huggingface.co/datasets/{d}" for d in datasets)


# ---------------------------------------------------------------------------
# M1-style: narrow LLM classifier -- category/input_type/model_type only,
# one call covering whichever of the three Tier 1 missed.
# ---------------------------------------------------------------------------

_CLASSIFIER_PROMPT = """You are classifying a Hugging Face model into Patra's controlled vocabulary.

## Model
name: {name}
pipeline_tag: {pipeline_tag}
library_name: {library_name}
README excerpt: {readme_excerpt}

## Fields to classify
{fields_json}

## Allowed values
category: one of: {category_list}
input_type: one of: {input_type_list}
model_type: one of: {model_type_list}

Return ONLY valid JSON, no markdown fences, only the keys listed above under "Fields to classify":
{{"category": "<value or null>", "input_type": "<value or null>", "model_type": "<value or null>"}}"""


def classify_missing_lookup_fields(
    *,
    name: str,
    pipeline_tag: str | None,
    library_name: str | None,
    readme_text: str | None,
    missing: dict[str, bool],
    request_tapis_token: str | None = None,
) -> dict[str, str]:
    """`missing` = {"category": bool, "input_type": bool, "model_type": bool} --
    only fields marked True are asked for. Returns {} if the LLM is disabled,
    fails, or every response value is off-vocabulary -- never raises."""
    fields_to_ask = [field for field, is_missing in missing.items() if is_missing]
    if not fields_to_ask:
        return {}

    prompt = _CLASSIFIER_PROMPT.format(
        name=name,
        pipeline_tag=pipeline_tag or "(none)",
        library_name=library_name or "(none)",
        readme_excerpt=(readme_text or "")[:1500] or "(no README available)",
        fields_json=json.dumps({field: None for field in fields_to_ask}),
        category_list=", ".join(sorted(VALID_CATEGORIES)),
        input_type_list=", ".join(sorted(VALID_INPUT_TYPES)),
        model_type_list=", ".join(sorted(VALID_MODEL_TYPES)),
    )
    raw = _call_llm(
        [{"role": "user", "content": prompt}],
        request_tapis_token=request_tapis_token,
        max_tokens=300,
        temperature=0.0,
    )
    parsed = _parse_json_object(raw)

    result: dict[str, str] = {}
    for field in fields_to_ask:
        value = parsed.get(field)
        if isinstance(value, str) and value in _VALID_BY_FIELD[field]:
            result[field] = value
        # else: off-vocabulary or missing -- discarded, not passed through as garbage
    return result


# ---------------------------------------------------------------------------
# M3-style: 3-pass chain-of-thought -- foundational_model/input_data only,
# the two fields no lookup table can answer. `citation` is intentionally
# excluded from this path entirely (see derive_citation's docstring).
# ---------------------------------------------------------------------------

_ANALYSIS_PROMPT = """Analyze this Hugging Face model to prepare metadata.

## Model
name: {name}
pipeline_tag: {pipeline_tag}
README excerpt:
{readme_excerpt}

Answer briefly:
1. Is this a fine-tune of another named base model? If so, which one?
2. What dataset(s) was it trained on, if named?

Write 2-3 sentences. Do not fill any fields yet -- just reason."""

_GENERATE_PROMPT = """Based on your analysis below, fill in these fields.

## Your analysis
{analysis}

## Fields to fill
{fields_json}

Rules:
- foundational_model: the specific named base architecture only (e.g. "BERT", "ResNet-50"), not a full repo path.
- input_data: a URL or dataset name for the training data.
- If you cannot infer a value with reasonable confidence, use null -- do not guess.

Return ONLY valid JSON, no markdown fences, only the keys listed above under "Fields to fill":
{{"foundational_model": "<value or null>", "input_data": "<value or null>"}}"""

_VERIFY_PROMPT = """Review this generated metadata for internal consistency with the model info below.

## Model
name: {name}
pipeline_tag: {pipeline_tag}

## Generated
{generated_json}

If a value is wrong, unsupported, or contradicted by the model info, correct it or set it to null.
Return ONLY valid JSON in the same shape, corrected if needed:
{{"foundational_model": "<value or null>", "input_data": "<value or null>"}}"""

_HYBRID_FIELDS = ("foundational_model", "input_data")


def reason_missing_hybrid_fields(
    *,
    name: str,
    pipeline_tag: str | None,
    readme_text: str | None,
    missing: dict[str, bool],
    request_tapis_token: str | None = None,
) -> dict[str, str]:
    """`missing` = {"foundational_model": bool, "input_data": bool}.

    3 sequential calls: analyze (no fill) -> generate (fill) -> verify
    (self-correct). If the analysis call itself fails, returns {} (no
    partial nonsense). If generation produces nothing usable, returns {}.
    If verification fails to parse, falls back to the unverified
    generation rather than discarding it -- matches the POC's
    `call_llm_cot` behavior exactly (see augment_poc_v2.py:1013-1024).
    """
    fields_to_ask = [field for field in _HYBRID_FIELDS if missing.get(field)]
    if not fields_to_ask:
        return {}

    readme_excerpt = (readme_text or "")[:3000] or "(no README available)"

    analysis = _call_llm(
        [{"role": "user", "content": _ANALYSIS_PROMPT.format(
            name=name, pipeline_tag=pipeline_tag or "(none)", readme_excerpt=readme_excerpt,
        )}],
        request_tapis_token=request_tapis_token,
        max_tokens=300,
    )
    if analysis is None:
        return {}

    gen_raw = _call_llm(
        [{"role": "user", "content": _GENERATE_PROMPT.format(
            analysis=analysis, fields_json=json.dumps({field: None for field in fields_to_ask}),
        )}],
        request_tapis_token=request_tapis_token,
        max_tokens=300,
    )
    generated = {
        field: value
        for field, value in _parse_json_object(gen_raw).items()
        if field in fields_to_ask and isinstance(value, str) and value.strip()
    }
    if not generated:
        return {}

    verify_raw = _call_llm(
        [{"role": "user", "content": _VERIFY_PROMPT.format(
            name=name, pipeline_tag=pipeline_tag or "(none)", generated_json=json.dumps(generated),
        )}],
        request_tapis_token=request_tapis_token,
        max_tokens=300,
        temperature=0.0,
    )
    verified = _parse_json_object(verify_raw)
    if not verified:
        return generated  # verification failed to parse -- use the unverified generation, not nothing

    result: dict[str, str] = {}
    for field in fields_to_ask:
        value = verified.get(field, generated.get(field))
        if isinstance(value, str) and value.strip():
            result[field] = value.strip()
    return result
