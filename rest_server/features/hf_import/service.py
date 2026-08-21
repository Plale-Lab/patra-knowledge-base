"""Fetch-and-normalize logic for importing a public Hugging Face model or
dataset repo into flat Patra model-card/datasheet form fields.

HF metadata/README fetch mirrors the stdlib urllib + @lru_cache pattern
already used in rest_server/routes/model_cards.py's
`_fetch_huggingface_model_metadata` (no httpx for those calls -- the
existing HF integration uses urllib and we keep that convention for
consistency). Field enrichment beyond Tier-1 deterministic extraction
(category/input_type/model_type classification, foundational_model/
input_data reasoning) goes through `llm_enrichment.py`, which does use
httpx via `rest_server/features/shared/openai_compat.py` -- see that
module's docstring for the two-tier (M1 classifier + M3 chain-of-thought)
design this ports from the research POC.

Public repos only: there is no HF_HUB_TOKEN support anywhere in this repo,
so gated/private repos fail loudly (HuggingFaceGatedOrPrivateError) instead
of silently degrading, per product decision.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from rest_server.features.hf_import import llm_enrichment
from rest_server.features.hf_import.models import HFImportFields

log = logging.getLogger(__name__)

_HF_HOSTS = {"huggingface.co", "www.huggingface.co", "hf.co", "www.hf.co"}
_USER_AGENT = "patra-backend/1.0"
_TIMEOUT_SECONDS = 5
_MAX_README_BYTES = 200_000
_SHORT_DESCRIPTION_MAX_CHARS = 400
_FULL_DESCRIPTION_MAX_CHARS = 4000


# --------------------------------------------------------------------------
# Domain errors — the route layer (rest_server/routes/hf_import.py) catches
# these and translates them into HTTPExceptions. Mirrors the
# AgentServiceError convention used by patra_agent_service.py / agent_tools.py.
# --------------------------------------------------------------------------

class HFImportError(Exception):
    """Base class for hf_import failures."""


class InvalidHuggingFaceUrlError(HFImportError):
    """URL is not a well-formed huggingface.co model/dataset URL, or doesn't
    match the requested asset_type (e.g. a dataset URL submitted while
    importing a model card)."""


class HuggingFaceRepoNotFoundError(HFImportError):
    """The repo_id doesn't exist on the Hub (404 from the HF API)."""


class HuggingFaceGatedOrPrivateError(HFImportError):
    """The repo is gated or private. This feature intentionally has no
    HF_HUB_TOKEN support, so these always fail rather than degrade."""


class HuggingFaceUpstreamError(HFImportError):
    """Any other upstream failure: network error, timeout, non-2xx/404
    status, malformed JSON."""


# --------------------------------------------------------------------------
# URL parsing
# --------------------------------------------------------------------------

def _parse_hf_repo_id(url: str, *, expect_dataset: bool) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        raise InvalidHuggingFaceUrlError("A Hugging Face URL is required.")

    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in _HF_HOSTS:
        raise InvalidHuggingFaceUrlError("Enter a valid huggingface.co URL.")

    parts = [p for p in parsed.path.split("/") if p]
    if parts[:1] == ["spaces"]:
        raise InvalidHuggingFaceUrlError("Hugging Face Spaces are not supported for import.")

    is_dataset_path = parts[:1] == ["datasets"]
    if expect_dataset and not is_dataset_path:
        raise InvalidHuggingFaceUrlError(
            "That looks like a model URL. Switch the record type to Datasheet, "
            "or paste a huggingface.co/datasets/<org>/<repo> URL."
        )
    if not expect_dataset and is_dataset_path:
        raise InvalidHuggingFaceUrlError(
            "That looks like a dataset URL. Switch the record type to Model Card, "
            "or paste a huggingface.co/<org>/<repo> URL."
        )

    # Slicing to the first two segments after an optional "datasets/" prefix
    # also naturally handles URLs like /org/repo/tree/main or /org/repo/blob/main/README.md.
    repo_parts = parts[1:] if is_dataset_path else parts
    if len(repo_parts) < 2:
        raise InvalidHuggingFaceUrlError("Could not find a namespace/repo in that URL.")
    return "/".join(repo_parts[:2])


# --------------------------------------------------------------------------
# HF Hub API fetch (metadata)
# --------------------------------------------------------------------------

def _coerce_is_gated(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() not in {"", "false", "0", "none", "null"}


def _translate_http_error(exc: HTTPError, *, context: str) -> HFImportError:
    # Hugging Face's anonymous API does not distinguish "repo doesn't exist"
    # from "repo exists but requires authentication" — both return 401, not
    # 404 (confirmed against the live API; genuinely gated repos like
    # meta-llama/Llama-3.1-8B actually return 200 with a `gated` field in the
    # body, caught separately by _enforce_not_gated). Since an unresolvable
    # typo'd URL is by far the more common case for our public-only importer,
    # treat 401 as "not found" with an honest, hedged message rather than
    # confidently (and often wrongly) asserting the repo is private.
    if exc.code in (401, 404):
        return HuggingFaceRepoNotFoundError(
            f"{context}: repo not found on Hugging Face, or it requires authentication "
            "that Patra's importer doesn't support."
        )
    if exc.code == 403:
        return HuggingFaceGatedOrPrivateError(
            f"{context}: this repo is gated or private. Patra's Hugging Face import "
            "only supports public repos."
        )
    return HuggingFaceUpstreamError(f"{context}: Hugging Face returned HTTP {exc.code}.")


@lru_cache(maxsize=128)
def _fetch_hf_metadata_json(repo_id: str, is_dataset: bool) -> dict:
    kind = "datasets" if is_dataset else "models"
    request = Request(
        f"https://huggingface.co/api/{kind}/{repo_id}",
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except HTTPError as exc:
        raise _translate_http_error(exc, context="Hugging Face metadata lookup") from exc
    except (URLError, TimeoutError) as exc:
        raise HuggingFaceUpstreamError(f"Hugging Face metadata lookup failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HuggingFaceUpstreamError(f"Hugging Face metadata lookup returned malformed JSON: {exc}") from exc


def _enforce_not_gated(payload: dict) -> None:
    if _coerce_is_gated(payload.get("gated")):
        raise HuggingFaceGatedOrPrivateError(
            "This Hugging Face repo is gated. Patra's importer only supports public, ungated repos."
        )


# --------------------------------------------------------------------------
# README fetch — never fatal. A public repo without a README, or a
# transient failure fetching it, should not sink an otherwise-real result.
# --------------------------------------------------------------------------

@lru_cache(maxsize=128)
def _fetch_hf_readme(repo_id: str, is_dataset: bool) -> str | None:
    prefix = f"datasets/{repo_id}" if is_dataset else repo_id
    request = Request(
        f"https://huggingface.co/{prefix}/resolve/main/README.md",
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            raw = response.read(_MAX_README_BYTES)
        return raw.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - README is best-effort by design
        log.warning("Hugging Face README fetch failed for %s: %s", repo_id, exc)
        return None


# --------------------------------------------------------------------------
# README -> short/full description (regex/stdlib only, no markdown/YAML dep)
# --------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")          # must run before _LINK_RE (handles nested badge-links)
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_HR_RE = re.compile(r"^\s*([-*_]\s*){3,}\s*$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_BOLD_ITALIC_RE = re.compile(r"(\*\*\*|___)(.+?)\1")
_BOLD_RE = re.compile(r"(\*\*|__)(.+?)\1")
_ITALIC_RE = re.compile(r"(\*|_)(.+?)\1")
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")


def _strip_yaml_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def _markdown_to_paragraphs(markdown: str) -> list[str]:
    text = _HTML_COMMENT_RE.sub("", markdown)
    text = _CODE_FENCE_RE.sub("", text)
    text = _IMAGE_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _HTML_TAG_RE.sub("", text)
    text = _HEADING_RE.sub("", text)
    text = _HR_RE.sub("", text)
    text = _TABLE_ROW_RE.sub("", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _BOLD_ITALIC_RE.sub(r"\2", text)
    text = _BOLD_RE.sub(r"\2", text)
    text = _ITALIC_RE.sub(r"\2", text)

    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].rstrip() + "…"


def _derive_descriptions(readme_text: str | None) -> tuple[str | None, str | None]:
    """Returns (short, full). Both None if there's no usable README prose.

    Heuristic: skip very short "paragraphs" (< 20 chars), since the first
    line after frontmatter is almost always a leftover "# Model Name" H1
    whose text survives heading-marker stripping. This is a best-effort
    pre-fill — the UI explicitly asks the user to review every field before
    submitting.
    """
    if not readme_text:
        return None, None
    body = _strip_yaml_frontmatter(readme_text)
    paragraphs = [p for p in _markdown_to_paragraphs(body) if len(p) > 20]
    if not paragraphs:
        return None, None

    short = _truncate(paragraphs[0], _SHORT_DESCRIPTION_MAX_CHARS)
    full = _truncate(" ".join(paragraphs[:8]), _FULL_DESCRIPTION_MAX_CHARS)
    return short, full


# --------------------------------------------------------------------------
# Field mapping helpers
# --------------------------------------------------------------------------

def _first_present(*values: str | None) -> str | None:
    for value in values:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
        elif value:
            return value
    return None


def _humanize_repo_name(repo_id: str) -> str:
    """'distilbert-base-uncased' -> 'Distilbert Base Uncased'. Mirrors the
    frontend's old mock `humanize()` in huggingFaceImport.js exactly
    (capitalizes only the first letter of each word, preserves the rest)."""
    repo_name = repo_id.rsplit("/", 1)[-1]
    words = [w for w in re.split(r"[-_]+", repo_name) if w]
    if not words:
        return repo_name
    return " ".join(word[:1].upper() + word[1:] for word in words)


def _license_from_tags(tags: list[str] | None) -> str | None:
    for tag in tags or []:
        if isinstance(tag, str) and tag.startswith("license:"):
            return tag.split(":", 1)[1] or None
    return None


def _framework_from_tags(tags: list[str] | None) -> str | None:
    known = {
        "pytorch": "PyTorch", "tensorflow": "TensorFlow", "jax": "JAX",
        "transformers": "Transformers", "diffusers": "Diffusers",
        "timm": "timm", "keras": "Keras",
    }
    for tag in tags or []:
        if isinstance(tag, str) and tag.lower() in known:
            return known[tag.lower()]
    return None


def _license_value(card_data: dict, tags: list) -> str | None:
    raw = card_data.get("license")
    if isinstance(raw, list):
        cleaned = [str(v).strip() for v in raw if str(v).strip()]
        raw = ", ".join(cleaned) if cleaned else None
    return _first_present(raw, _license_from_tags(tags))


_LICENSE_URI_MAP = {
    "mit": "https://opensource.org/licenses/MIT",
    "apache-2.0": "https://www.apache.org/licenses/LICENSE-2.0",
    "cc0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "cc-by-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "cc-by-sa-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "cc-by-nc-4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
    "cc-by-nc-sa-4.0": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "bsd-3-clause": "https://opensource.org/licenses/BSD-3-Clause",
    "gpl-3.0": "https://www.gnu.org/licenses/gpl-3.0.html",
}


def _license_uri_value(license_value: str | None) -> str | None:
    if not license_value:
        return None
    return _LICENSE_URI_MAP.get(license_value.strip().lower())


def _keywords_from_tags(tags: list[str] | None) -> str | None:
    """Model tags: most are plain (pytorch, text-generation, en); drop the
    handful of colon-namespaced metadata tags (license:, region:, arxiv:...)
    since those are already surfaced via dedicated fields."""
    if not tags:
        return None
    cleaned = [t for t in tags if isinstance(t, str) and t.strip() and ":" not in t]
    return ", ".join(cleaned) if cleaned else None


_DATASET_SUBJECT_NOISE_PREFIXES = (
    "license:", "region:", "doi:", "arxiv:", "base_model:", "size_categories:",
    "source_datasets:", "annotations_creators:", "language_creators:",
)


def _subjects_from_tags(tags: list[str] | None) -> str | None:
    """Dataset tags are almost all colon-namespaced (task_categories:...,
    language:en, ...), unlike model tags — so naive colon-stripping would
    yield nothing. Instead, take the value after the colon for meaningful
    namespaces and drop pure-noise ones."""
    if not tags:
        return None
    values: list[str] = []
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip():
            continue
        if tag.startswith(_DATASET_SUBJECT_NOISE_PREFIXES):
            continue
        _, _, value = tag.partition(":")
        value = (value or tag).strip()
        if value:
            values.append(value)
    seen: set[str] = set()
    deduped = []
    for v in values:
        if v.lower() not in seen:
            seen.add(v.lower())
            deduped.append(v)
    return ", ".join(deduped) if deduped else None


def _map_model_fields(repo_id: str, payload: dict, readme_text: str | None) -> HFImportFields:
    card_data = payload.get("cardData") or {}
    tags = payload.get("tags") or []
    config = payload.get("config") or {}
    pipeline_tag = payload.get("pipeline_tag")
    library_name = payload.get("library_name")
    short_desc, full_desc = _derive_descriptions(readme_text)
    hf_url = f"https://huggingface.co/{payload.get('id') or repo_id}"
    name = _humanize_repo_name(repo_id)

    # Tier 1: deterministic.
    category = llm_enrichment.derive_category(pipeline_tag)
    input_type = llm_enrichment.derive_input_type(pipeline_tag)
    model_type = llm_enrichment.derive_model_type(config, name)
    foundational_model = llm_enrichment.derive_foundational_model(tags)
    input_data = llm_enrichment.derive_input_data(tags)
    citation = llm_enrichment.derive_citation(readme_text)

    # M1-style: narrow classifier fallback, only for what Tier 1 missed.
    classified = llm_enrichment.classify_missing_lookup_fields(
        name=name,
        pipeline_tag=pipeline_tag,
        library_name=library_name,
        readme_text=readme_text,
        missing={
            "category": category is None,
            "input_type": input_type is None,
            "model_type": model_type is None,
        },
    )
    category = category or classified.get("category")
    input_type = input_type or classified.get("input_type")
    model_type = model_type or classified.get("model_type")

    # M3-style: chain-of-thought, only for what's still null.
    reasoned = llm_enrichment.reason_missing_hybrid_fields(
        name=name,
        pipeline_tag=pipeline_tag,
        readme_text=readme_text,
        missing={
            "foundational_model": foundational_model is None,
            "input_data": input_data is None,
        },
    )
    foundational_model = foundational_model or reasoned.get("foundational_model")
    input_data = input_data or reasoned.get("input_data")

    return HFImportFields(
        name=name,
        author=_first_present(payload.get("author"), repo_id.split("/", 1)[0]),
        license=_license_value(card_data, tags),
        framework=_first_present(library_name, _framework_from_tags(tags)),
        keywords=_keywords_from_tags(tags),
        documentation=hf_url,
        location=hf_url,
        short_description=short_desc,
        full_description=full_desc,
        # Always False here: _enforce_not_gated() already raised above if the
        # HF API reported this repo as gated.
        is_gated=False,
        category=category,
        input_type=input_type,
        model_type=model_type,
        foundational_model=foundational_model,
        input_data=input_data,
        citation=citation,
    )


def _map_dataset_fields(repo_id: str, payload: dict, readme_text: str | None) -> HFImportFields:
    card_data = payload.get("cardData") or {}
    tags = payload.get("tags") or []
    _, full_desc = _derive_descriptions(readme_text)  # dsForm has one `description` field; use the fuller text
    hf_url = f"https://huggingface.co/datasets/{payload.get('id') or repo_id}"

    license_value = _license_value(card_data, tags)
    creator = _first_present(payload.get("author"), repo_id.split("/", 1)[0])

    # Tier 1 only -- publisher/publication_year/license_uri are all cheaply
    # deterministic here, so there's nothing for an LLM to add. No lookup
    # table can invent a publisher HF doesn't state, so it defaults to the
    # same org/user as the creator, which is who published it in practice
    # for the overwhelming majority of HF dataset repos.
    publication_year = None
    created_at = payload.get("createdAt") or ""
    if len(created_at) >= 4:
        try:
            publication_year = int(created_at[:4])
        except ValueError:
            publication_year = None

    return HFImportFields(
        title=_humanize_repo_name(repo_id),
        creator=creator,
        license=license_value,
        download_url=hf_url,
        description=full_desc,
        subjects=_subjects_from_tags(tags),
        publisher=creator,
        publication_year=publication_year,
        license_uri=_license_uri_value(license_value),
    )


# --------------------------------------------------------------------------
# Orchestrator — the only function the route layer calls.
# --------------------------------------------------------------------------

async def import_from_huggingface(url: str, asset_type: str) -> HFImportFields:
    is_dataset = asset_type == "datasheet"
    repo_id = _parse_hf_repo_id(url, expect_dataset=is_dataset)

    payload = await asyncio.to_thread(_fetch_hf_metadata_json, repo_id, is_dataset)
    _enforce_not_gated(payload)
    readme_text = await asyncio.to_thread(_fetch_hf_readme, repo_id, is_dataset)

    # _map_model_fields/_map_dataset_fields now make blocking LLM calls
    # (via llm_enrichment) on top of the pure-regex work they used to do --
    # route through to_thread so those calls don't block the event loop.
    if is_dataset:
        return await asyncio.to_thread(_map_dataset_fields, repo_id, payload, readme_text)
    return await asyncio.to_thread(_map_model_fields, repo_id, payload, readme_text)
