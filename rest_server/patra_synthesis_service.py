import csv
import json
import urllib.request
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from rest_server.patra_agent_service import (
    DEFAULT_LLM_API_BASE,
    DEFAULT_LLM_API_KEY,
    DEFAULT_LLM_MODEL,
    AgentServiceError,
    _modules,
    _normalize_cache_dir,
    _pair_map,
)


class SynthesisServiceError(AgentServiceError):
    pass


def _artifact_root(cache_dir: str) -> Path:
    root = Path(cache_dir) / "generated"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _field_properties(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    properties = schema.get("properties", {})
    return properties if isinstance(properties, dict) else {}


def _raw_headers(raw_schema: dict[str, Any]) -> list[str]:
    return list(_field_properties(raw_schema).keys())


def _lower_header_map(raw_schema: dict[str, Any]) -> dict[str, str]:
    return {name.lower(): name for name in _raw_headers(raw_schema)}


def _find_headers(raw_lookup: dict[str, str], *needles: str) -> list[str]:
    found: list[str] = []
    for lowered, original in raw_lookup.items():
        if any(needle in lowered for needle in needles):
            found.append(original)
    return sorted(set(found))


def _pick_first(candidates: list[str], preferred: tuple[str, ...] = ()) -> str | None:
    if not candidates:
        return None
    lowered = {candidate.lower(): candidate for candidate in candidates}
    for item in preferred:
        if item.lower() in lowered:
            return lowered[item.lower()]
    return candidates[0]


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _best_direct_source(target_field: str, raw_lookup: dict[str, str]) -> str | None:
    if target_field in raw_lookup.values():
        return target_field
    if target_field == "LAT":
        return _pick_first(_find_headers(raw_lookup, "latitude", "lat"), ("lat", "latitude"))
    if target_field == "LON":
        return _pick_first(_find_headers(raw_lookup, "longitude", "long", "lon"), ("lon", "long", "longitude"))
    if target_field == "yield":
        return _pick_first(_find_headers(raw_lookup, "yield", "yield_kg", "real_tch"))
    if target_field == "Year":
        year_headers = _find_headers(raw_lookup, "year")
        if year_headers:
            return _pick_first(year_headers, ("year",))
    return None


def _build_deterministic_plan(
    query_schema: dict[str, Any],
    candidate_pair: Any,
    selected_fields: list[str] | None,
) -> dict[str, Any]:
    modules = _modules()
    decisions = modules["analyze_missing_columns"](query_schema, candidate_pair.schema, candidate_pair.raw_schema)
    summary = modules["build_derivation_summary"](decisions)
    raw_lookup = _lower_header_map(candidate_pair.raw_schema)
    selected_set = set(selected_fields or [])

    direct_fields: list[dict[str, Any]] = []
    derived_fields: list[dict[str, Any]] = []
    rejected_fields: list[str] = []
    planner_notes: list[str] = []

    for row in summary["rows"]:
        target = row["target_field"]
        if row["status"] == "directly available":
            source_field = _best_direct_source(target, raw_lookup)
            if source_field is None and row["source_fields"]:
                source_field = row["source_fields"][0]
            if source_field is None:
                rejected_fields.append(target)
                planner_notes.append(f"Skipped direct field {target} because no raw source column was available.")
                continue
            direct_fields.append(
                {
                    "target_field": target,
                    "mode": "direct_copy",
                    "source_fields": [source_field],
                    "aggregate": "identity",
                    "output_kind": "json_array" if _field_properties(query_schema).get(target, {}).get("type") == "array" else "scalar",
                    "notes": "Direct field copied from the candidate dataset.",
                }
            )
            continue

        if row["status"] != "derivable with provenance":
            rejected_fields.append(target)
            continue

        if selected_set and target not in selected_set:
            rejected_fields.append(target)
            continue

        if target == "Year":
            date_field = _pick_first(row["source_fields"], ("harvest date", "date", "last cut date"))
            if date_field is None:
                rejected_fields.append(target)
                planner_notes.append("Could not resolve a deterministic date source for Year.")
                continue
            derived_fields.append(
                {
                    "target_field": target,
                    "mode": "extract_year",
                    "source_fields": [date_field],
                    "date_field": date_field,
                    "aggregate": "identity",
                    "output_kind": "scalar",
                    "notes": "Extract calendar year from the selected date column.",
                }
            )
            continue

        if target in {"Tmax_monthly", "Tmin_monthly", "PRE_monthly", "NDVI_monthly", "SM_monthly"}:
            preferred_value = {
                "Tmax_monthly": ("Tmax", "tmax"),
                "Tmin_monthly": ("Tmin", "tmin"),
                "PRE_monthly": ("pr", "precipitation", "pre"),
                "NDVI_monthly": ("ndvi",),
                "SM_monthly": ("soil_moisture", "sm"),
            }[target]
            value_field = _pick_first(row["source_fields"], preferred_value)
            date_field = _pick_first(row["source_fields"], ("date", "observation_date", "harvest date", "last cut date"))
            aggregate = {
                "Tmax_monthly": "max",
                "Tmin_monthly": "min",
                "PRE_monthly": "sum",
                "NDVI_monthly": "mean",
                "SM_monthly": "mean",
            }[target]
            if value_field is None or date_field is None:
                rejected_fields.append(target)
                planner_notes.append(f"Could not resolve deterministic monthly aggregation inputs for {target}.")
                continue
            derived_fields.append(
                {
                    "target_field": target,
                    "mode": "monthly_aggregate",
                    "source_fields": _dedupe_preserve([value_field, date_field]),
                    "date_field": date_field,
                    "value_field": value_field,
                    "aggregate": aggregate,
                    "months": list(range(1, 13)),
                    "output_kind": "json_array",
                    "notes": "Aggregate dated observations into a 12-month series.",
                }
            )
            continue

        if target in {"LAT", "LON", "yield"}:
            source_field = _pick_first(row["source_fields"])
            if source_field is None:
                rejected_fields.append(target)
                continue
            derived_fields.append(
                {
                    "target_field": target,
                    "mode": "direct_copy",
                    "source_fields": [source_field],
                    "aggregate": "identity",
                    "output_kind": "scalar",
                    "notes": "Normalize the source field into the PATRA target field.",
                }
            )
            continue

        rejected_fields.append(target)

    group_by_fields: list[str] = []
    if "plot_code" in raw_lookup.values():
        group_by_fields.append("plot_code")
    else:
        lat_field = _best_direct_source("LAT", raw_lookup)
        lon_field = _best_direct_source("LON", raw_lookup)
        group_by_fields.extend([item for item in (lat_field, lon_field) if item])

    date_field = None
    for field in derived_fields:
        if field.get("date_field"):
            date_field = field["date_field"]
            break
    if date_field:
        group_by_fields.append(f"calendar_year({date_field})")

    planner_notes.append("Planner restricted to deterministic transforms, explicit source columns, and auditable provenance.")
    return {
        "planner_mode": "deterministic",
        "group_by_fields": group_by_fields,
        "direct_fields": direct_fields,
        "derived_fields": derived_fields,
        "rejected_fields": sorted(set(rejected_fields)),
        "planner_notes": planner_notes,
    }


def _llm_plan_json_schema(allowed_fields: list[str], raw_headers: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "group_by_fields": {
                "type": "array",
                "items": {"type": "string", "enum": raw_headers},
            },
            "planner_notes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "derived_fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "target_field": {"type": "string", "enum": allowed_fields},
                        "mode": {"type": "string", "enum": ["direct_copy", "extract_year", "monthly_aggregate"]},
                        "source_fields": {
                            "type": "array",
                            "items": {"type": "string", "enum": raw_headers},
                        },
                        "date_field": {"type": ["string", "null"], "enum": raw_headers + [None]},
                        "value_field": {"type": ["string", "null"], "enum": raw_headers + [None]},
                        "aggregate": {"type": ["string", "null"], "enum": ["max", "min", "sum", "mean", "identity", None]},
                        "months": {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 1, "maximum": 12},
                        },
                        "output_kind": {"type": "string", "enum": ["scalar", "json_array"]},
                        "notes": {"type": "string"},
                    },
                    "required": ["target_field", "mode", "source_fields", "output_kind", "notes"],
                },
            },
        },
        "required": ["group_by_fields", "planner_notes", "derived_fields"],
    }


def _extract_json_object(content: str) -> dict[str, Any]:
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise SynthesisServiceError("LLM plan did not return a JSON object.")
    return payload


def _request_llm_plan(
    query_schema: dict[str, Any],
    candidate_pair: Any,
    deterministic_plan: dict[str, Any],
    api_base: str | None,
    model: str | None,
    api_key: str | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    resolved_api_base = (api_base or DEFAULT_LLM_API_BASE or "").rstrip("/")
    resolved_model = model or DEFAULT_LLM_MODEL
    resolved_api_key = api_key or DEFAULT_LLM_API_KEY
    if not resolved_api_base or not resolved_model:
        raise SynthesisServiceError("LLM planning requires an API base and model.")

    allowed_fields = [item["target_field"] for item in deterministic_plan["derived_fields"]]
    if not allowed_fields:
        raise SynthesisServiceError("No derivable fields are available for LLM planning.")

    raw_headers = _raw_headers(candidate_pair.raw_schema)
    prompt = {
        "task": "Produce a deterministic transformation plan only. Do not generate values.",
        "target_schema_properties": list(_field_properties(query_schema).keys()),
        "allowed_derived_fields": allowed_fields,
        "raw_headers": raw_headers,
        "allowed_operations": {
            "direct_copy": "copy or normalize a single raw source field",
            "extract_year": "extract calendar year from a date field",
            "monthly_aggregate": "aggregate a dated numeric field into a 12-month array using max/min/sum/mean",
        },
        "deterministic_baseline_plan": deterministic_plan,
        "requirements": [
            "Choose only from the provided raw headers.",
            "Do not invent source columns, units, or derived fields.",
            "Return only plans that are auditable and executable by code.",
            "Use monthly_aggregate only for monthly series target fields.",
            "Use extract_year only for Year.",
        ],
    }
    payload = {
        "model": resolved_model,
        "temperature": 0.0,
        "max_tokens": 1200,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a deterministic data transformation planner. "
                    "Return strict JSON only. Never invent columns or values."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=True)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "patra_synthesis_plan",
                "schema": _llm_plan_json_schema(allowed_fields, raw_headers),
            },
        },
    }
    request = urllib.request.Request(
        url=f"{resolved_api_base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {resolved_api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw)
    content = parsed["choices"][0]["message"]["content"]
    return _extract_json_object(content)


def _validate_llm_plan(
    llm_plan: dict[str, Any],
    deterministic_plan: dict[str, Any],
    raw_schema: dict[str, Any],
) -> dict[str, Any]:
    raw_headers = set(_raw_headers(raw_schema))
    raw_lookup = _lower_header_map(raw_schema)
    allowed_targets = {item["target_field"] for item in deterministic_plan["derived_fields"]}
    validated_fields: list[dict[str, Any]] = []

    for item in llm_plan.get("derived_fields", []):
        target = item.get("target_field")
        mode = item.get("mode")
        source_fields = item.get("source_fields", [])
        date_field = item.get("date_field")
        value_field = item.get("value_field")
        if target not in allowed_targets:
            raise SynthesisServiceError(f"LLM plan proposed unsupported target field: {target}")
        if any(field not in raw_headers for field in source_fields):
            raise SynthesisServiceError(f"LLM plan referenced an unknown source field for {target}.")
        if date_field is None:
            date_field = _pick_first(
                [field for field in source_fields if "date" in field.lower() or "time" in field.lower()],
                ("date", "observation_date", "harvest date", "last cut date"),
            )
        if value_field is None and mode == "monthly_aggregate":
            value_field = _pick_first(
                [field for field in source_fields if field != date_field],
                (target.replace("_monthly", ""),),
            )
        if date_field is not None and date_field not in raw_headers:
            raise SynthesisServiceError(f"LLM plan referenced an unknown date field for {target}.")
        if value_field is not None and value_field not in raw_headers:
            raise SynthesisServiceError(f"LLM plan referenced an unknown value field for {target}.")
        if mode == "extract_year" and target != "Year":
            raise SynthesisServiceError("LLM plan used extract_year for a non-Year target.")
        if mode == "monthly_aggregate" and not target.endswith("_monthly"):
            raise SynthesisServiceError("LLM plan used monthly_aggregate for a non-monthly target.")
        if mode == "extract_year" and date_field is None:
            raise SynthesisServiceError("LLM plan omitted the date field needed for Year extraction.")
        if mode == "monthly_aggregate" and (date_field is None or value_field is None):
            raise SynthesisServiceError(f"LLM plan omitted required monthly aggregation inputs for {target}.")
        validated_fields.append(
            {
                "target_field": target,
                "mode": mode,
                "source_fields": source_fields,
                "date_field": date_field,
                "value_field": value_field,
                "aggregate": item.get("aggregate"),
                "months": item.get("months") or list(range(1, 13)),
                "output_kind": item.get("output_kind"),
                "notes": item.get("notes", ""),
            }
        )

    return {
        "planner_mode": "llm",
        "group_by_fields": llm_plan.get("group_by_fields", deterministic_plan["group_by_fields"]),
        "direct_fields": deterministic_plan["direct_fields"],
        "derived_fields": validated_fields,
        "rejected_fields": deterministic_plan["rejected_fields"],
        "planner_notes": _dedupe_preserve(deterministic_plan["planner_notes"] + llm_plan.get("planner_notes", [])),
    }


def _build_plan(
    query_schema: dict[str, Any],
    candidate_pair: Any,
    selected_fields: list[str] | None,
    use_llm_plan: bool,
    api_base: str | None,
    model: str | None,
    api_key: str | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    deterministic_plan = _build_deterministic_plan(query_schema, candidate_pair, selected_fields)
    if not use_llm_plan or not deterministic_plan["derived_fields"]:
        return deterministic_plan
    try:
        llm_plan = _request_llm_plan(
            query_schema,
            candidate_pair,
            deterministic_plan,
            api_base,
            model,
            api_key,
            timeout_seconds,
        )
        return _validate_llm_plan(llm_plan, deterministic_plan, candidate_pair.raw_schema)
    except Exception as exc:  # noqa: BLE001
        fallback = dict(deterministic_plan)
        fallback["planner_mode"] = "deterministic_fallback"
        fallback["planner_notes"] = list(deterministic_plan["planner_notes"]) + [
            f"LLM planning was attempted but fell back to deterministic planning: {exc}"
        ]
        return fallback


def _group_dimensions(raw_headers: list[str], plan: dict[str, Any]) -> tuple[list[str], str | None]:
    raw_lookup = {item.lower(): item for item in raw_headers}
    entity_fields: list[str] = []
    for preferred in ("plot_code", "plot", "region", "county", "district", "admin_unit", "id"):
        if preferred in raw_lookup:
            entity_fields.append(raw_lookup[preferred])
            break
    if not entity_fields:
        lat_field = raw_lookup.get("lat") or raw_lookup.get("latitude")
        lon_field = raw_lookup.get("lon") or raw_lookup.get("long") or raw_lookup.get("longitude")
        entity_fields.extend([item for item in (lat_field, lon_field) if item])

    year_date_field = None
    for item in plan["derived_fields"]:
        if item["mode"] == "extract_year" and item.get("date_field"):
            year_date_field = item["date_field"]
            break
    if year_date_field is None:
        for item in plan["derived_fields"]:
            if item["mode"] in {"extract_year", "monthly_aggregate"} and item.get("date_field"):
                year_date_field = item["date_field"]
                break
    return entity_fields, year_date_field


def _aggregate(values: list[float], operation: str) -> float | None:
    if not values:
        return None
    if operation == "max":
        return max(values)
    if operation == "min":
        return min(values)
    if operation == "sum":
        return sum(values)
    if operation == "mean":
        return sum(values) / len(values)
    return values[0]


def _coerce_value(value: Any, schema_property: dict[str, Any]) -> Any:
    target_type = schema_property.get("type")
    if target_type == "integer":
        return _safe_int(value)
    if target_type == "number":
        return _safe_float(value)
    if target_type == "array":
        return value
    return value


def _execute_plan(
    query_schema: dict[str, Any],
    candidate_pair: Any,
    plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    csv_path = candidate_pair.meta.get("local_cache_path")
    if not csv_path or not Path(csv_path).exists():
        raise SynthesisServiceError(
            f"Candidate dataset {candidate_pair.dataset_id} does not have a downloadable local CSV for synthesis."
        )

    raw_headers = _raw_headers(candidate_pair.raw_schema)
    entity_fields, year_date_field = _group_dimensions(raw_headers, plan)
    query_properties = _field_properties(query_schema)
    issues: list[dict[str, Any]] = []

    with Path(csv_path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}

    for row in rows:
        derived_year = None
        if year_date_field:
            parsed_date = _parse_iso_date(row.get(year_date_field))
            if parsed_date is None:
                issues.append(
                    {
                        "field": year_date_field,
                        "severity": "warning",
                        "message": f"Skipped a source row because {year_date_field} could not be parsed as a date.",
                    }
                )
                continue
            derived_year = parsed_date.year

        key_parts = [row.get(field, "") for field in entity_fields]
        if derived_year is not None:
            key_parts.append(str(derived_year))
        if not key_parts:
            key_parts = [f"row-{len(grouped) + 1}"]
        group_key = tuple(key_parts)
        bucket = grouped.setdefault(
            group_key,
            {
                "direct": defaultdict(list),
                "monthly": defaultdict(lambda: defaultdict(list)),
                "year": derived_year,
            },
        )

        for item in plan["direct_fields"]:
            source_field = item["source_fields"][0]
            value = row.get(source_field)
            if value not in (None, ""):
                bucket["direct"][item["target_field"]].append(value)

        for item in plan["derived_fields"]:
            target = item["target_field"]
            mode = item["mode"]
            if mode == "direct_copy":
                source_field = item["source_fields"][0]
                value = row.get(source_field)
                if value not in (None, ""):
                    bucket["direct"][target].append(value)
                continue
            if mode == "extract_year":
                date_field = item["date_field"]
                parsed_date = _parse_iso_date(row.get(date_field))
                if parsed_date is not None:
                    bucket["year"] = parsed_date.year
                continue
            if mode == "monthly_aggregate":
                date_field = item["date_field"]
                value_field = item["value_field"]
                parsed_date = _parse_iso_date(row.get(date_field))
                value = _safe_float(row.get(value_field))
                if parsed_date is None or value is None:
                    continue
                bucket["monthly"][target][parsed_date.month].append(value)

    output_rows: list[dict[str, Any]] = []
    for index, (group_key, bucket) in enumerate(grouped.items(), start=1):
        entity_id = "|".join(str(item) for item in group_key if item not in (None, ""))
        output_row: dict[str, Any] = {
            "patra_entity_id": entity_id or f"group-{index}",
            "source_dataset_id": candidate_pair.dataset_id,
        }

        for item in plan["direct_fields"]:
            target = item["target_field"]
            schema_property = query_properties.get(target, {})
            values = [value for value in bucket["direct"][target] if value not in (None, "")]
            if not values:
                output_row[target] = None
                continue
            unique_values = sorted(set(values))
            chosen = unique_values[0]
            if len(unique_values) > 1:
                issues.append(
                    {
                        "field": target,
                        "severity": "warning",
                        "message": f"Multiple source values were observed for {target}; using the first unique value per grouped row.",
                    }
                )
            output_row[target] = _coerce_value(chosen, schema_property)

        for item in plan["derived_fields"]:
            target = item["target_field"]
            schema_property = query_properties.get(target, {})
            if item["mode"] == "direct_copy":
                values = [value for value in bucket["direct"][target] if value not in (None, "")]
                output_row[target] = _coerce_value(values[0], schema_property) if values else None
                continue
            if item["mode"] == "extract_year":
                output_row[target] = bucket["year"]
                continue
            if item["mode"] == "monthly_aggregate":
                months = item.get("months") or list(range(1, 13))
                series = [
                    _aggregate(bucket["monthly"][target].get(month, []), item.get("aggregate") or "mean")
                    for month in months
                ]
                output_row[target] = series

        output_rows.append(output_row)

    return output_rows, issues


def _build_generated_schema(query_schema: dict[str, Any], plan: dict[str, Any], artifact_title: str, candidate_pair: Any) -> dict[str, Any]:
    query_properties = _field_properties(query_schema)
    generated_properties: dict[str, Any] = {
        "patra_entity_id": {
            "type": "string",
            "description": "Stable grouped entity identifier generated by PATRA synthesis.",
        },
        "source_dataset_id": {
            "type": "string",
            "description": "Original candidate dataset identifier used to synthesize this artifact.",
        },
    }
    required = ["patra_entity_id", "source_dataset_id"]

    for item in plan["direct_fields"] + plan["derived_fields"]:
        target = item["target_field"]
        prop = dict(query_properties.get(target, {"type": "string"}))
        prop["x-patra-provenance-mode"] = item["mode"]
        prop["x-patra-source-fields"] = item.get("source_fields", [])
        generated_properties[target] = prop
        required.append(target)

    return {
        "type": "object",
        "description": (
            f"{artifact_title}. Synthesized by PATRA from candidate dataset "
            f"{candidate_pair.dataset_id} using deterministic execution over an auditable plan."
        ),
        "properties": generated_properties,
        "required": required,
        "additionalProperties": False,
        "x-patra-generated": True,
        "x-patra-source-dataset-id": candidate_pair.dataset_id,
        "x-patra-rejected-fields": plan["rejected_fields"],
    }


def _validate_output_rows(
    query_schema: dict[str, Any],
    generated_schema: dict[str, Any],
    output_rows: list[dict[str, Any]],
    execution_issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues = list(execution_issues)
    query_properties = _field_properties(query_schema)

    if not output_rows:
        issues.append(
            {
                "field": "dataset",
                "severity": "error",
                "message": "Synthesis produced zero output rows.",
            }
        )
        return issues

    for field, schema_property in query_properties.items():
        if field not in _field_properties(generated_schema):
            continue
        values = [row.get(field) for row in output_rows]
        if schema_property.get("type") == "array":
            lengths = [len(value) for value in values if isinstance(value, list)]
            if lengths and any(length != lengths[0] for length in lengths):
                issues.append(
                    {
                        "field": field,
                        "severity": "error",
                        "message": "Generated monthly arrays have inconsistent lengths.",
                    }
                )
            if lengths and lengths[0] != 12:
                issues.append(
                    {
                        "field": field,
                        "severity": "warning",
                        "message": f"Generated monthly arrays have length {lengths[0]} instead of the default 12-month template.",
                    }
                )
        elif schema_property.get("type") == "integer":
            invalid = sum(1 for value in values if value not in (None, "") and not isinstance(value, int))
            if invalid:
                issues.append(
                    {
                        "field": field,
                        "severity": "error",
                        "message": f"{invalid} generated values for {field} are not integers.",
                    }
                )
        elif schema_property.get("type") == "number":
            invalid = sum(1 for value in values if value not in (None, "") and not isinstance(value, (int, float)))
            if invalid:
                issues.append(
                    {
                        "field": field,
                        "severity": "error",
                        "message": f"{invalid} generated values for {field} are not numeric.",
                    }
                )

    return issues


def _serialize_csv_rows(output_rows: list[dict[str, Any]], output_fields: list[str], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields)
        writer.writeheader()
        for row in output_rows:
            serialized = {}
            for field in output_fields:
                value = row.get(field)
                serialized[field] = json.dumps(value) if isinstance(value, list) else value
            writer.writerow(serialized)


def generate_synthesized_dataset(
    query_schema: dict[str, Any],
    candidate_dataset_id: str,
    selected_fields: list[str] | None,
    use_llm_plan: bool,
    submitted_by: str | None,
    api_base: str | None,
    model: str | None,
    api_key: str | None,
    timeout_seconds: int,
    cache_dir: str | None,
) -> dict[str, Any]:
    normalized_cache = _normalize_cache_dir(cache_dir)
    lookup = _pair_map(normalized_cache)
    if candidate_dataset_id not in lookup:
        raise SynthesisServiceError(f"Unknown candidate dataset id: {candidate_dataset_id}")

    candidate_pair = lookup[candidate_dataset_id]
    plan = _build_plan(
        query_schema,
        candidate_pair,
        selected_fields,
        use_llm_plan,
        api_base,
        model,
        api_key,
        timeout_seconds,
    )
    generated_rows, execution_issues = _execute_plan(query_schema, candidate_pair, plan)

    artifact_key = uuid.uuid4().hex[:16]
    artifact_title = f"PATRA synthesized dataset for {candidate_pair.title}"
    generated_schema = _build_generated_schema(query_schema, plan, artifact_title, candidate_pair)
    validation_issues = _validate_output_rows(query_schema, generated_schema, generated_rows, execution_issues)

    artifact_dir = _artifact_root(normalized_cache) / artifact_key
    output_fields = list(_field_properties(generated_schema).keys())
    csv_path = artifact_dir / "synthesized_dataset.csv"
    schema_path = artifact_dir / "synthesized_schema.json"
    plan_path = artifact_dir / "derivation_plan.json"
    validation_path = artifact_dir / "validation_report.json"

    _serialize_csv_rows(generated_rows, output_fields, csv_path)
    schema_path.write_text(json.dumps(generated_schema, indent=2), encoding="utf-8")
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    validation_path.write_text(json.dumps(validation_issues, indent=2), encoding="utf-8")

    return {
        "status": "ok",
        "message": "Synthesized dataset generated under strict plan-and-validate boundaries.",
        "artifact": {
            "artifact_key": artifact_key,
            "title": artifact_title,
            "source_dataset_id": candidate_pair.dataset_id,
            "planner_mode": plan["planner_mode"],
            "row_count": len(generated_rows),
            "generated_fields": [item["target_field"] for item in plan["direct_fields"] + plan["derived_fields"]],
            "rejected_fields": plan["rejected_fields"],
            "output_csv_download_url": f"/agent-tools/generated-artifacts/{artifact_key}/download.csv",
            "output_schema_download_url": f"/agent-tools/generated-artifacts/{artifact_key}/download-schema",
            "review_submission_id": None,
        },
        "plan": plan,
        "validation_issues": validation_issues,
        "preview_rows": generated_rows[:5],
        "storage": {
            "output_csv_path": str(csv_path),
            "output_schema_path": str(schema_path),
            "query_schema": query_schema,
            "generated_schema": generated_schema,
            "derivation_plan": plan,
            "validation_report": validation_issues,
            "metadata": {
                "candidate_title": candidate_pair.title,
                "candidate_source_family": candidate_pair.source_family,
                "candidate_source_url": candidate_pair.source_url,
                "submitted_by": submitted_by,
                "cache_dir": normalized_cache,
                "selected_fields": selected_fields or [],
                "local_source_csv_path": candidate_pair.meta.get("local_cache_path"),
                "local_source_meta": candidate_pair.meta,
            },
        },
    }
