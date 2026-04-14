from __future__ import annotations

import json
import logging
import os
import re

from rest_server.features.intent_schema.models import (
    IntentSchemaBootstrapResponse,
    IntentSchemaField,
    IntentSchemaResponse,
    IntentSchemaResult,
)
from rest_server.features.intent_schema.prompts import STARTER_PROMPTS, SYSTEM_PROMPT, build_generation_prompt
from rest_server.features.shared.openai_compat import chat_text_with_model_fallback


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_ENUM_TOKEN_RE = re.compile(r"'([^']+)'|\"([^\"]+)\"|([A-Za-z0-9_./:+-]+)")
_DATE_HINT_RE = re.compile(r"\b(date|time|month|day|year|timestamp|season)\b", re.IGNORECASE)
log = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() == "true"


def _llm_api_base() -> str:
    configured = os.getenv("INTENT_SCHEMA_LLM_API_BASE", "").strip()
    if configured:
        return configured
    inherited = os.getenv("ASK_PATRA_LLM_API_BASE", "").strip()
    if inherited:
        return inherited
    return "http://127.0.0.1:1234/v1"


def _llm_model() -> str | None:
    configured = os.getenv("INTENT_SCHEMA_LLM_MODEL", "").strip()
    if configured:
        return configured
    inherited = os.getenv("ASK_PATRA_LLM_MODEL", "").strip()
    if inherited:
        return inherited
    api_base = _llm_api_base().lower()
    if "127.0.0.1:1234" in api_base or "localhost:1234" in api_base:
        return "llama-3.3-70b-instruct"
    return None


def _llm_api_key() -> str | None:
    configured = os.getenv("INTENT_SCHEMA_LLM_API_KEY", "").strip()
    if configured:
        return configured
    inherited = os.getenv("ASK_PATRA_LLM_API_KEY", "").strip()
    return inherited or None


def _llm_service_tapis_token() -> str:
    for name in (
        "INTENT_SCHEMA_TAPIS_TOKEN",
        "ASK_PATRA_TAPIS_TOKEN",
        "LITELLM_TAPIS_TOKEN",
        "PATRA_LITELLM_TAPIS_TOKEN",
    ):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _looks_like_placeholder_token(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized.startswith("<")
        or "valid tapis jwt" in normalized
        or "service token" in normalized
        or "replace" in normalized
        or "your-token" in normalized
    )


def _resolve_llm_auth(api_base: str, request_tapis_token: str | None = None) -> tuple[str | None, dict[str, str]]:
    extra_headers: dict[str, str] = {}
    lowered = (api_base or "").lower()
    service_tapis_token = _llm_service_tapis_token()
    request_token = (request_tapis_token or "").strip()
    service_token_usable = bool(service_tapis_token) and not _looks_like_placeholder_token(service_tapis_token)
    request_token_usable = bool(request_token) and not _looks_like_placeholder_token(request_token)
    if "litellm.pods.tacc.tapis.io" in lowered:
        token = service_tapis_token if service_token_usable else request_token if request_token_usable else ""
        selected = "service" if service_token_usable else "request" if request_token_usable else "none"
        print(
            "intent_schema.auth_debug "
            f"litellm=True service_token_present={bool(service_tapis_token)} "
            f"service_token_usable={service_token_usable} "
            f"request_token_present={bool(request_token)} request_token_usable={request_token_usable} "
            f"selected={selected}",
            flush=True,
        )
        if token:
            extra_headers["X-Tapis-Token"] = token
            extra_headers["Authorization"] = f"Bearer {token}"
            log.info(
                "intent_schema.resolve_llm_auth using %s tapis token for LiteLLM auth_mode=tapis_x_header_and_bearer",
                selected,
            )
            return None, extra_headers
    api_key = _llm_api_key()
    print(
        "intent_schema.auth_debug "
        f"litellm={'litellm.pods.tacc.tapis.io' in lowered} api_key_present={bool(api_key)} "
        f"extra_headers={sorted(extra_headers.keys())}",
        flush=True,
    )
    log.info("intent_schema.resolve_llm_auth using api_key=%s extra_headers=%s", bool(api_key), sorted(extra_headers.keys()))
    return api_key, extra_headers


def _provider_label(api_base: str) -> str:
    lowered = api_base.lower()
    if "litellm.pods.tacc.tapis.io" in lowered:
        return "SambaNova via LiteLLM"
    if "127.0.0.1:1234" in lowered or "localhost:1234" in lowered:
        return "LM Studio"
    if api_base:
        return "PATRA AI"
    return "PATRA AI (code fallback)"


def _extract_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("{") and content.endswith("}"):
        return json.loads(content)
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"Model did not return JSON: {content[:200]}")
    return json.loads(content[start : end + 1])


def _clean_field_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    if slug and slug[0].isdigit():
        slug = f"field_{slug}"
    return slug[:64] or "feature"


def _contains_cjk(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(_CJK_RE.search(value))
    if isinstance(value, dict):
        return any(_contains_cjk(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_cjk(item) for item in value)
    return False


def _normalize_task_type(value: str) -> str:
    lowered = (value or "").strip().lower()
    mapping = {
        "binary classification": "classification",
        "multiclass classification": "classification",
        "classify": "classification",
        "classification": "classification",
        "regression": "regression",
        "forecast": "forecasting",
        "forecasting": "forecasting",
        "time_series_forecasting": "forecasting",
        "ranking": "ranking",
    }
    return mapping.get(lowered, "unknown")


def _normalize_data_type(value: str) -> str:
    lowered = (value or "").strip().lower()
    mapping = {
        "int": "integer",
        "integer": "integer",
        "bigint": "integer",
        "smallint": "integer",
        "float": "float",
        "double": "float",
        "double precision": "float",
        "decimal": "float",
        "number": "float",
        "numeric": "float",
        "bool": "boolean",
        "boolean": "boolean",
        "str": "string",
        "text": "string",
        "varchar": "string",
        "category": "string",
        "categorical": "string",
        "date": "date",
        "datetime": "datetime",
        "timestamp": "datetime",
    }
    return mapping.get(lowered, "string" if not lowered else lowered)


def _normalize_prediction_horizon(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    lowered = text.lower()
    if lowered in {"short term", "short-term"}:
        return "Short term"
    if lowered in {"medium term", "medium-term"}:
        return "Medium term"
    if lowered in {"long term", "long-term"}:
        return "Long term"
    text = re.sub(r"\bday\b", "days", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmonth\b", "months", text, flags=re.IGNORECASE)
    text = re.sub(r"\byear\b", "years", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _extract_enum_values(value: str) -> list[str]:
    if not value:
        return []
    lowered = value.lower()
    explicit_enum = any(marker in lowered for marker in ("enum", "one of", "values:", "categories:", "allowed values"))
    has_delimiters = any(symbol in value for symbol in ("|", ",", "[", "]"))
    has_quotes = "'" in value or '"' in value
    if not explicit_enum and not has_delimiters:
        return []
    if explicit_enum and not has_delimiters and not has_quotes and "one of" not in lowered:
        return []
    tokens: list[str] = []
    generic_tokens = {"finite", "enum", "values", "value", "allowed", "categories", "category"}
    for match in _ENUM_TOKEN_RE.finditer(value):
        token = next((group for group in match.groups() if group), "")
        token = token.strip().strip(",")
        if not token:
            continue
        if token.lower() in {"enum", "infinity", "inf"}:
            continue
        if token.lower() in generic_tokens:
            continue
        if re.fullmatch(r"-?\d+(\.\d+)?", token):
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _normalize_string_range(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip())
    lowered = text.lower()
    enum_values = _extract_enum_values(text)
    if enum_values and not _DATE_HINT_RE.search(text):
        if len(enum_values) <= 8:
            return f"enum: {' | '.join(enum_values)}"
    if any(marker in lowered for marker in ("finite enum", "categorical", "category values")):
        return "enumerated categories"
    return text


def _normalize_expected_range(data_type: str, value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    lowered = text.lower()
    if data_type == "boolean":
        return "true/false"
    if data_type in {"date", "datetime"}:
        if "valid" in lowered:
            return f"valid {data_type}"
        return re.sub(r"\s+", " ", text)
    if data_type == "string":
        return _normalize_string_range(text)
    if "infinity" in lowered or "inf" in lowered:
        if text.startswith("[0") or text.startswith("(0") or ">=" in text or "non-negative" in lowered:
            return ">= 0"
    bracket_match = re.fullmatch(r"[\[(]\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*[\])]", text)
    if bracket_match:
        start, end = bracket_match.groups()
        return f"{start}-{end}"
    compact = text.replace(" ", "")
    if compact in {"[0,1]", "(0,1]", "[0,1)"}:
        return "0-1"
    return re.sub(r"\s+", " ", text)


def _normalize_distribution(value: str | None) -> str | None:
    if not value:
        return None
    lowered = str(value).strip().lower()
    mapping = {
        "normal": "normal",
        "normal distribution": "normal",
        "gaussian": "normal",
        "uniform": "uniform",
        "binary": "binary",
        "categorical": "categorical",
        "categorical distribution": "categorical",
        "continuous": "continuous",
        "continuous distribution": "continuous",
        "skewed": "skewed",
        "right-skewed": "right-skewed",
    }
    if lowered in mapping:
        return mapping[lowered]
    return re.sub(r"\s+", " ", str(value).strip())


def _normalize_field(field: IntentSchemaField) -> IntentSchemaField:
    data_type = _normalize_data_type(field.data_type)
    return IntentSchemaField(
        name=_clean_field_name(field.name),
        data_type=data_type,
        semantic_role=field.semantic_role,
        description=re.sub(r"\s+", " ", field.description.strip()),
        expected_range=_normalize_expected_range(data_type, field.expected_range),
        distribution_expectation=_normalize_distribution(field.distribution_expectation),
        required=field.required,
        notes=re.sub(r"\s+", " ", field.notes.strip()) if field.notes else None,
    )


def _normalize_result(result: IntentSchemaResult) -> IntentSchemaResult:
    normalized_fields: list[IntentSchemaField] = []
    seen_names: set[str] = set()
    for field in result.schema_fields:
        normalized = _normalize_field(field)
        if normalized.name in seen_names:
            suffix = 2
            base = normalized.name
            while f"{base}_{suffix}" in seen_names:
                suffix += 1
            normalized = normalized.model_copy(update={"name": f"{base}_{suffix}"})
        seen_names.add(normalized.name)
        normalized_fields.append(normalized)

    target_field = next((field for field in normalized_fields if field.semantic_role == "target"), None)
    normalized_target = _clean_field_name(result.target_column)
    if target_field is not None:
        normalized_target = target_field.name

    return IntentSchemaResult(
        intent_summary=re.sub(r"\s+", " ", result.intent_summary.strip()),
        task_type=_normalize_task_type(result.task_type),
        entity_grain=re.sub(r"\s+", " ", result.entity_grain.strip()),
        target_column=normalized_target,
        label_definition=re.sub(r"\s+", " ", result.label_definition.strip()),
        prediction_horizon=_normalize_prediction_horizon(result.prediction_horizon),
        ambiguity_warnings=[re.sub(r"\s+", " ", item.strip()) for item in result.ambiguity_warnings if item and item.strip()],
        assumptions=[re.sub(r"\s+", " ", item.strip()) for item in result.assumptions if item and item.strip()],
        schema_fields=normalized_fields,
    )


def _fallback_schema(intent_text: str, max_fields: int) -> IntentSchemaResult:
    lowered = intent_text.lower()
    if "流失" in intent_text or "churn" in lowered:
        fields = [
            IntentSchemaField(name="customer_id", data_type="string", semantic_role="identifier", description="Unique customer identifier at the customer level.", expected_range="Non-empty unique value", distribution_expectation="High-cardinality, close to one unique value per row", required=True, notes="Usually excluded from direct numeric model input"),
            IntentSchemaField(name="snapshot_date", data_type="date", semantic_role="timestamp", description="Observation cutoff date for the sample.", expected_range="Valid calendar date", distribution_expectation="Distributed across business periods", required=True),
            IntentSchemaField(name="tenure_months", data_type="integer", semantic_role="feature", description="Number of months the customer has been active.", expected_range="0-120", distribution_expectation="Right-skewed or segmented distribution", required=True),
            IntentSchemaField(name="monthly_spend", data_type="float", semantic_role="feature", description="Monthly spending amount in the latest billing cycle.", expected_range=">= 0", distribution_expectation="Right-skewed continuous distribution", required=True),
            IntentSchemaField(name="support_tickets_30d", data_type="integer", semantic_role="feature", description="Support ticket count in the last 30 days.", expected_range="0-50", distribution_expectation="Zero-inflated count distribution", required=False),
            IntentSchemaField(name="usage_activity_30d", data_type="float", semantic_role="feature", description="Recent product usage activity score over the last 30 days.", expected_range="0-1", distribution_expectation="Continuous value between 0 and 1", required=False),
            IntentSchemaField(name="plan_type", data_type="string", semantic_role="grouping", description="Customer subscription or plan category.", expected_range="Finite enum values", distribution_expectation="Categorical distribution may be imbalanced", required=False),
            IntentSchemaField(name="will_churn_90d", data_type="boolean", semantic_role="target", description="Whether the customer will churn within the next 90 days.", expected_range="true/false", distribution_expectation="Typically class-imbalanced", required=True, notes="Target label"),
        ]
        return IntentSchemaResult(
            intent_summary="Build a binary classification task that predicts future churn risk from customer snapshots.",
            task_type="classification",
            entity_grain="Each row represents one customer snapshot at one observation date.",
            target_column="will_churn_90d",
            label_definition="Label as true if the customer cancels service or becomes inactive within 90 days after the observation date.",
            prediction_horizon="90 days",
            ambiguity_warnings=["The exact churn definition may vary by business rule, such as cancellation, prolonged inactivity, or failed renewal."],
            assumptions=["Assume the task is standard tabular classification rather than sequence modeling.", "Assume supervised samples can be built at the customer-snapshot level."],
            schema_fields=fields[:max_fields],
        )

    if "产量" in intent_text or "yield" in lowered:
        fields = [
            IntentSchemaField(name="plot_code", data_type="integer", semantic_role="identifier", description="Unique field or plot identifier.", expected_range="Positive integer", distribution_expectation="High-cardinality", required=True),
            IntentSchemaField(name="harvest", data_type="integer", semantic_role="grouping", description="Harvest year or growing season reference.", expected_range="Four-digit year", distribution_expectation="Seasonal grouping distribution", required=True),
            IntentSchemaField(name="cultivar", data_type="string", semantic_role="grouping", description="Sugarcane cultivar grown on the plot.", expected_range="enumerated categories", distribution_expectation="Multiclass categorical distribution", required=True),
            IntentSchemaField(name="environment", data_type="string", semantic_role="grouping", description="Declared field environment class.", expected_range="enumerated categories", distribution_expectation="Small categorical set", required=False),
            IntentSchemaField(name="soil_type", data_type="string", semantic_role="feature", description="Soil classification for the plot.", expected_range="enumerated categories", distribution_expectation="Categorical distribution", required=False),
            IntentSchemaField(name="area", data_type="float", semantic_role="feature", description="Area of the plot or production unit.", expected_range=">= 0", distribution_expectation="Positive continuous distribution", required=True),
            IntentSchemaField(name="brix", data_type="float", semantic_role="feature", description="Observed sugar concentration measurement.", expected_range=">= 0", distribution_expectation="Positive continuous distribution", required=False),
            IntentSchemaField(name="real_tch", data_type="float", semantic_role="target", description="Observed tons of cane per hectare.", expected_range=">= 0", distribution_expectation="Positive continuous distribution", required=True, notes="Target variable"),
        ]
        return IntentSchemaResult(
            intent_summary="Build a regression task that predicts crop yield by plot and harvest season.",
            task_type="regression",
            entity_grain="Each row represents one plot in one harvest season.",
            target_column="real_tch",
            label_definition="Predict harvested tons of cane per hectare for a plot-season record.",
            prediction_horizon="One harvest season",
            ambiguity_warnings=["This deterministic draft is aligned to the currently indexed agricultural sample structure and should be generalized later when broader PATRA assets are available."],
            assumptions=["Assume the current internal sample is sugarcane yield data.", "Assume a single-plot seasonal regression task for the MVP demo."],
            schema_fields=fields[:max_fields],
        )

    generic_fields = [
        IntentSchemaField(name="entity_id", data_type="string", semantic_role="identifier", description="Unique entity identifier for each sample.", expected_range="Non-empty unique value", distribution_expectation="High-cardinality", required=True),
        IntentSchemaField(name="observation_time", data_type="datetime", semantic_role="timestamp", description="Observation timestamp for the sample.", expected_range="Valid timestamp", distribution_expectation="Distributed over business time", required=True),
        IntentSchemaField(name="feature_1", data_type="float", semantic_role="feature", description="A continuous feature relevant to the prediction task.", expected_range="Business-defined numeric range", distribution_expectation="Continuous distribution", required=True),
        IntentSchemaField(name="feature_2", data_type="string", semantic_role="grouping", description="A categorical feature relevant to the task.", expected_range="Finite enum values", distribution_expectation="Categorical distribution may be imbalanced", required=False),
        IntentSchemaField(name="target_outcome", data_type="float", semantic_role="target", description="Target prediction column.", expected_range="Business-defined range", distribution_expectation="Task-dependent", required=True),
    ]
    return IntentSchemaResult(
        intent_summary="Interpret the request as a generic draft for a tabular prediction task.",
        task_type="unknown",
        entity_grain="Each row represents one sample for one entity at one observation time.",
        target_column="target_outcome",
        label_definition="The exact target definition still needs business confirmation.",
        prediction_horizon=None,
        ambiguity_warnings=["The current intent is not specific enough to uniquely determine task type, label window, or entity grain."],
        assumptions=["Return a minimal schema draft first and wait for the user to confirm the boundary."],
        schema_fields=generic_fields[:max_fields],
    )


def _generate_with_llm(
    intent_text: str,
    context: str | None,
    max_fields: int,
    *,
    request_tapis_token: str | None = None,
) -> tuple[IntentSchemaResult, str | None]:
    api_base = _llm_api_base()
    api_key, extra_headers = _resolve_llm_auth(api_base, request_tapis_token)
    raw_text, model_used = chat_text_with_model_fallback(
        api_base=api_base,
        model=_llm_model(),
        api_key=api_key,
        extra_headers=extra_headers,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_generation_prompt(intent_text=intent_text, context=context, max_fields=max_fields)},
        ],
        timeout_seconds=int(os.getenv("INTENT_SCHEMA_LLM_TIMEOUT_SECONDS", "180") or "180"),
        temperature=0.1,
        max_tokens=1200,
    )
    payload = _extract_json(raw_text)
    result = _normalize_result(IntentSchemaResult.model_validate(payload))
    if len(result.schema_fields) > max_fields:
        result.schema_fields = result.schema_fields[:max_fields]
    if _contains_cjk(result.model_dump()):
        raise ValueError("LLM output contained non-English CJK text")
    return result, model_used


def bootstrap_payload() -> IntentSchemaBootstrapResponse:
    enabled = _env_flag("ENABLE_INTENT_SCHEMA", default=False)
    return IntentSchemaBootstrapResponse(
        enabled=enabled,
        provider=_provider_label(_llm_api_base()) if enabled else "Disabled",
        starter_prompts=STARTER_PROMPTS,
    )


def generate_schema(
    *,
    intent_text: str,
    context: str | None,
    max_fields: int,
    disable_llm: bool = False,
    request_tapis_token: str | None = None,
) -> IntentSchemaResponse:
    enabled = _env_flag("ENABLE_INTENT_SCHEMA", default=False)
    provider = _provider_label(_llm_api_base()) if enabled else "PATRA AI (code fallback)"

    if enabled and not disable_llm:
        try:
            result, model_used = _generate_with_llm(
                intent_text=intent_text,
                context=context,
                max_fields=max_fields,
                request_tapis_token=request_tapis_token,
            )
            return IntentSchemaResponse(
                **result.model_dump(),
                mode="llm",
                provider=provider,
                model_used=model_used,
                starter_prompts=STARTER_PROMPTS,
            )
        except Exception:
            log.exception("intent_schema.generate_schema.llm_failed mode=code_fallback")

    fallback = _normalize_result(_fallback_schema(intent_text=intent_text, max_fields=max_fields))
    return IntentSchemaResponse(
        **fallback.model_dump(),
        mode="code_fallback",
        provider=provider,
        model_used=None,
        starter_prompts=STARTER_PROMPTS,
    )
