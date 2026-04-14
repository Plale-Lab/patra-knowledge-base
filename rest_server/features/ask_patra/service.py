from __future__ import annotations

import base64
import json
import logging
import os
import re
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import asyncpg

from rest_server.deps import PatraActor
from rest_server.features.ask_patra.inline_executor import (
    InlineExecutionContext,
    get_inline_executor_registry,
    run_inline_executor,
)
from rest_server.features.ask_patra.models import (
    AskPatraCitation,
    AskPatraExecution,
    AskPatraHandoff,
    AskPatraIntent,
    AskPatraMessage,
    AskPatraSuggestedAction,
    AskPatraToolCard,
)
from rest_server.features.ask_patra.prompts import DEFAULT_BEHAVIOR_PROMPT, DEFAULT_SYSTEM_PROMPT, ensure_prompt_templates
from rest_server.features.ask_patra.tool_registry import build_tool_navigation, classify_tool_intent, get_tool_capability_map
from rest_server.features.shared.openai_compat import chat_text_with_model_fallback

log = logging.getLogger(__name__)

STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with", "about", "me", "you",
    "can", "what", "where", "how", "show", "find", "give", "random", "look", "up", "into", "from", "that", "this",
    "is", "are", "be", "it", "i", "we", "do", "does", "help", "please",
}

GREETING_PATTERNS = {
    "hi", "hello", "hey", "yo", "hiya", "good morning", "good afternoon", "good evening",
}

LOOKUP_HINTS = {
    "find", "search", "look", "lookup", "look up", "show", "give", "browse", "list", "recommend", "related",
    "model", "models", "model card", "model cards", "datasheet", "datasheets", "record", "records",
    "author", "metadata", "keyword", "keywords", "compare",
}

LOOKUP_ROUTE_TOOL_MAP = {
    "datasheet": "browse_datasheets",
    "datasheets": "browse_datasheets",
}
INLINE_EXECUTOR_TOOL_IDS = set(get_inline_executor_registry())


def _default_storage_root() -> Path:
    data_root = Path("/data")
    if data_root.exists():
        return data_root / "ask-patra"
    return Path(__file__).resolve().parents[4] / "runlogs" / "ask-patra"


def _storage_root() -> Path:
    return Path(os.getenv("ASK_PATRA_STORAGE_ROOT", str(_default_storage_root())))


def _memory_dir() -> Path:
    return Path(os.getenv("ASK_PATRA_MEMORY_DIR", str(_storage_root() / "memory")))


def _prompts_dir() -> Path:
    return Path(os.getenv("ASK_PATRA_PROMPTS_DIR", str(_storage_root() / "prompts")))


def _provider_label() -> str:
    api_base = _llm_api_base()
    if "litellm.pods.tacc.tapis.io" in api_base:
        return "SambaNova via LiteLLM"
    if api_base:
        return "PATRA AI"
    return "PATRA AI (code fallback)"


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _llm_api_base() -> str:
    return _first_env(
        "ASK_PATRA_LLM_API_BASE",
        "ASK_PATRA_LLM_BASE_URL",
        "LITELLM_API_BASE",
        "OPENAI_API_BASE",
    )


def _llm_model() -> str | None:
    value = _first_env(
        "ASK_PATRA_LLM_MODEL",
        "ASK_PATRA_MODEL",
        "LITELLM_MODEL",
        "OPENAI_MODEL",
    )
    return value or None


def ensure_ask_patra_storage() -> list:
    memory_dir = _memory_dir()
    memory_dir.mkdir(parents=True, exist_ok=True)
    return ensure_prompt_templates(_prompts_dir())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conversation_path(conversation_id: str) -> Path:
    return _memory_dir() / f"{conversation_id}.json"


def _load_conversation(conversation_id: str) -> dict:
    path = _conversation_path(conversation_id)
    if not path.exists():
        return {
            "conversation_id": conversation_id,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "messages": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _save_conversation(payload: dict) -> None:
    path = _conversation_path(payload["conversation_id"])
    payload["updated_at"] = _now_iso()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _tokenize_query(query: str) -> list[str]:
    tokens = [token for token in re.findall(r"[a-zA-Z0-9_\\-]+", query.lower()) if len(token) > 2]
    return [token for token in tokens if token not in STOPWORDS]


def _normalized_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def _is_greeting(query: str) -> bool:
    normalized = _normalized_query(query)
    if normalized in GREETING_PATTERNS:
        return True
    if normalized in {"hi patra", "hello patra", "hey patra"}:
        return True
    tokens = _tokenize_query(normalized)
    return len(tokens) == 0 and normalized in {"hi!", "hello!", "hey!"}


def _is_capability_question(query: str) -> bool:
    normalized = _normalized_query(query)
    patterns = (
        "what can you help me do",
        "what can you do",
        "how can you help",
        "what can patra do",
        "help me with patra",
    )
    return any(pattern in normalized for pattern in patterns)


def _wants_record_lookup(query: str) -> bool:
    normalized = _normalized_query(query)
    if _is_greeting(normalized) or _is_capability_question(normalized):
        return False
    return any(hint in normalized for hint in LOOKUP_HINTS) or len(_tokenize_query(normalized)) >= 3


def _requested_record_limit(query: str, default: int = 3) -> int:
    normalized = _normalized_query(query)
    word_numbers = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    for word, value in word_numbers.items():
        if re.search(rf"\b{word}\b", normalized):
            return max(1, min(10, value))
    match = re.search(r"\b(?:top|up to|give me|show me|find|list)?\s*(\d{1,2})\s+(?:random\s+)?(?:model cards?|datasheets?|records?|items?|results?)\b", normalized)
    if match:
        return max(1, min(10, int(match.group(1))))
    return default


def _requested_resource_types(query: str) -> set[str] | None:
    normalized = _normalized_query(query)
    wants_model_cards = any(token in normalized for token in ("model card", "model cards", "models"))
    wants_datasheets = any(token in normalized for token in ("datasheet", "datasheets", "datasets"))
    if wants_model_cards and not wants_datasheets:
        return {"model_card"}
    if wants_datasheets and not wants_model_cards:
        return {"datasheet"}
    return None


def _score_text(query_tokens: list[str], *values: str | None) -> tuple[int, list[str]]:
    haystack = " ".join(value for value in values if value).lower()
    matched = [token for token in query_tokens if token in haystack]
    return len(matched), matched


async def search_pattra_records(
    conn: asyncpg.Connection,
    *,
    query: str,
    include_private: bool,
    limit: int = 3,
    resource_types: set[str] | None = None,
) -> list[AskPatraCitation]:
    query_tokens = _tokenize_query(query)
    if not query_tokens:
        return []
    resource_types = resource_types or {"model_card", "datasheet"}
    model_filter = "" if include_private else "AND mc.is_private = false"
    datasheet_filter = "" if include_private else "AND d.is_private = false"
    model_rows = []
    datasheet_rows = []
    fetch_limit = max(limit * 12, 40)
    if "model_card" in resource_types:
        model_rows = await conn.fetch(
            f"""
            WITH ranked AS (
                SELECT mc.id, mc.name, mc.author, mc.short_description, mc.full_description, mc.keywords,
                       mc.category, mc.input_data, mc.output_data, mc.foundational_model, mc.asset_version,
                       ROW_NUMBER() OVER (PARTITION BY COALESCE(mc.root_version_id, mc.id) ORDER BY mc.asset_version DESC, mc.id DESC) AS rn
                FROM model_cards mc
                WHERE mc.status = 'approved' {model_filter}
            )
            SELECT r.id, r.name, r.author, r.short_description, r.full_description, r.keywords, r.category,
                   r.input_data, r.output_data, r.foundational_model
            FROM ranked r
            WHERE r.rn = 1
            LIMIT $1
            """,
            fetch_limit,
        )
    if "datasheet" in resource_types:
        datasheet_rows = await conn.fetch(
            f"""
            WITH ranked AS (
                SELECT d.identifier, d.asset_version,
                       ROW_NUMBER() OVER (PARTITION BY COALESCE(d.root_version_id, d.identifier) ORDER BY d.asset_version DESC, d.identifier DESC) AS rn
                FROM datasheets d
                WHERE d.status = 'approved' {datasheet_filter}
            )
            SELECT r.identifier,
                   (SELECT title FROM datasheet_titles WHERE datasheet_id = r.identifier ORDER BY id LIMIT 1) AS title,
                   (SELECT creator_name FROM datasheet_creators WHERE datasheet_id = r.identifier ORDER BY id LIMIT 1) AS creator,
                   (SELECT description FROM datasheet_descriptions WHERE datasheet_id = r.identifier ORDER BY id LIMIT 1) AS description,
                   (SELECT subject FROM datasheet_subjects WHERE datasheet_id = r.identifier ORDER BY id LIMIT 1) AS subject
            FROM ranked r
            WHERE r.rn = 1
            LIMIT $1
            """,
            fetch_limit,
        )

    citations: list[tuple[int, AskPatraCitation]] = []
    for row in model_rows:
        score, matched = _score_text(
            query_tokens,
            row["name"],
            row["author"],
            row["short_description"],
            row["full_description"],
            row["keywords"],
            row["category"],
            row["input_data"],
            row["output_data"],
            row["foundational_model"],
        )
        if query_tokens and score == 0:
            continue
        citations.append((
            score,
            AskPatraCitation(
                resource_type="model_card",
                resource_id=int(row["id"]),
                title=row["name"],
                subtitle=row["author"],
                description=row["short_description"] or row["full_description"],
                route=f"/explore-model-cards/{int(row['id'])}",
                matched_on=matched,
            ),
        ))
    for row in datasheet_rows:
        score, matched = _score_text(
            query_tokens,
            row["title"],
            row["creator"],
            row["description"],
            row["subject"],
        )
        if query_tokens and score == 0:
            continue
        citations.append((
            score,
            AskPatraCitation(
                resource_type="datasheet",
                resource_id=int(row["identifier"]),
                title=row["title"] or f"Datasheet {int(row['identifier'])}",
                subtitle=row["creator"],
                description=row["description"] or row["subject"],
                route=f"/explore-datasheets/{int(row['identifier'])}",
                matched_on=matched,
            ),
        ))
    citations.sort(key=lambda item: (-item[0], item[1].title.lower()))
    return _dedupe_citations([citation for _, citation in citations], limit=limit)


def _system_prompt_text() -> str:
    ensure_ask_patra_storage()
    system_path = _prompts_dir() / "system_prompt.md"
    behavior_path = _prompts_dir() / "behavior_prompt.md"
    system = system_path.read_text(encoding="utf-8").strip() if system_path.exists() else DEFAULT_SYSTEM_PROMPT
    behavior = behavior_path.read_text(encoding="utf-8").strip() if behavior_path.exists() else DEFAULT_BEHAVIOR_PROMPT
    return f"{system}\n\n{behavior}"


def _build_context_block(citations: list[AskPatraCitation]) -> str:
    if not citations:
        return "No record citations were retrieved for this question."
    lines = []
    for citation in citations:
        lines.append(
            f"[{citation.resource_type}:{citation.resource_id}] {citation.title} | "
            f"subtitle={citation.subtitle or 'n/a'} | route={citation.route} | "
            f"description={citation.description or 'n/a'} | matched_on={', '.join(citation.matched_on) or 'none'}"
        )
    return "\n".join(lines)


def _dedupe_citations(citations: list[AskPatraCitation], *, limit: int) -> list[AskPatraCitation]:
    deduped: list[AskPatraCitation] = []
    seen: set[tuple[str, str, str]] = set()
    for citation in citations:
        key = (
            citation.resource_type,
            re.sub(r"\s+", " ", citation.title.strip().lower()),
            re.sub(r"\s+", " ", (citation.subtitle or "").strip().lower()),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
        if len(deduped) >= limit:
            break
    return deduped


def _extract_first_url(message: str) -> str | None:
    match = re.search(r"https?://[^\s)]+", message)
    return match.group(0) if match else None


def _prefill_query(message: str, *, fallback: str = "") -> str:
    compact = re.sub(r"\s+", " ", message.strip())
    return compact[:220] if compact else fallback


def _lookup_tool_id(message: str) -> str:
    normalized = _normalized_query(message)
    for token, tool_id in LOOKUP_ROUTE_TOOL_MAP.items():
        if token in normalized:
            return tool_id
    return "browse_model_cards"


def _build_capability_cards(actor: PatraActor) -> tuple[list[AskPatraToolCard], list[AskPatraSuggestedAction], AskPatraHandoff]:
    cards: list[AskPatraToolCard] = []
    actions: list[AskPatraSuggestedAction] = []
    handoff = AskPatraHandoff(kind="explanatory", tool_target=None, route=None, label="Browse PATRA tools")
    for tool_id, reason in [
        ("browse_model_cards", "Use PATRA search when you want to inspect published records."),
        ("intent_schema", "Use Intent Schema when you want PATRA to turn a modeling goal into a dataset plan."),
        ("mvp_demo_report", "Use MVP Demo Report when you want to show the current demo pipeline end to end."),
    ]:
        card, action, _ = build_tool_navigation(tool_id=tool_id, actor=actor, reason=reason)
        cards.append(card)
        actions.append(action)
    return cards, actions, handoff


def _build_tool_routing(
    *,
    actor: PatraActor,
    message: str,
    citations: list[AskPatraCitation],
) -> tuple[AskPatraIntent, list[AskPatraToolCard], list[AskPatraSuggestedAction], AskPatraHandoff, AskPatraExecution]:
    if _is_greeting(message):
        return (
            AskPatraIntent(category="greeting", confidence=0.99, tool_target=None),
            [],
            [],
            AskPatraHandoff(kind="explanatory", tool_target=None, route=None, label="Greeting"),
            AskPatraExecution(state="idle", message="No tool execution requested."),
        )

    if _is_capability_question(message):
        cards, actions, handoff = _build_capability_cards(actor)
        return (
            AskPatraIntent(category="capability", confidence=0.92, tool_target=None),
            cards,
            actions,
            handoff,
            AskPatraExecution(state="idle", message="Capability suggestions prepared."),
        )

    classified = classify_tool_intent(message)
    cards: list[AskPatraToolCard] = []
    actions: list[AskPatraSuggestedAction] = []
    handoff = AskPatraHandoff(kind="explanatory", tool_target=None, route=None, label=None)
    execution = AskPatraExecution(state="idle", message="No inline execution requested.")

    if classified.category in {"animal_ecology", "digital_agriculture"} and classified.tool_target:
        card, action, handoff = build_tool_navigation(
            tool_id=classified.tool_target,
            actor=actor,
            reason="This request matches an experiment-domain workflow.",
        )
        return classified, [card], [action], handoff, execution

    if classified.category in {
        "browse_model_cards",
        "browse_datasheets",
        "intent_schema",
        "mvp_demo_report",
        "agent_tools",
        "automated_ingestion",
        "edit_records",
        "submit_records",
        "tickets",
        "mcp_explorer",
    } and classified.tool_target:
        query: dict[str, str] = {}
        prefilled_payload: dict = {}
        cta_kind = "navigate"
        if classified.tool_target in {"browse_model_cards", "browse_datasheets"}:
            query["q"] = _prefill_query(message)
        elif classified.tool_target in {"intent_schema", "mvp_demo_report"}:
            query["intent"] = message.strip()
        elif classified.tool_target == "edit_records":
            query["q"] = _prefill_query(message)
            cta_kind = "prefill"
            prefilled_payload["query"] = _prefill_query(message)
        elif classified.tool_target == "submit_records":
            cta_kind = "prefill"
            source_url = _extract_first_url(message)
            if source_url:
                query["asset_url"] = source_url
                query["mode"] = "asset_link"
                query["type"] = "datasheet" if any(token in _normalized_query(message) for token in ("dataset", "datasheet")) else "model_card"
                prefilled_payload["asset_url"] = source_url
            prefilled_payload["intent_text"] = _prefill_query(message)
        elif classified.tool_target == "automated_ingestion":
            source_url = _extract_first_url(message)
            if source_url:
                query["source_url"] = source_url
                prefilled_payload["source_url"] = source_url
            cta_kind = "prefill"
        elif classified.tool_target == "tickets":
            cta_kind = "prefill"
            query["subject"] = _prefill_query(message, fallback="PATRA support request")
            query["description"] = message.strip()
            prefilled_payload["subject"] = _prefill_query(message, fallback="PATRA support request")
            prefilled_payload["description"] = message.strip()
        card, action, handoff = build_tool_navigation(
            tool_id=classified.tool_target,
            actor=actor,
            reason="This request maps cleanly to a PATRA tool surface.",
            query=query,
            prefilled_payload=prefilled_payload,
            cta_kind=cta_kind,
        )
        return classified, [card], [action], handoff, execution

    if classified.category == "experiments":
        for tool_id, reason in [
            ("animal_ecology", "Animal Ecology is the right surface for wildlife and camera-trap activity."),
            ("digital_agriculture", "Digital Agriculture is the right surface for crop-yield and field experiment activity."),
        ]:
            card, action, _ = build_tool_navigation(tool_id=tool_id, actor=actor, reason=reason)
            cards.append(card)
            actions.append(action)
        return (
            AskPatraIntent(category="experiments", confidence=0.8, tool_target=None),
            cards,
            actions,
            AskPatraHandoff(kind="navigate", tool_target=None, route=None, label="Choose an experiments surface"),
            execution,
        )

    if citations or _wants_record_lookup(message):
        browse_tool = _lookup_tool_id(message)
        card, action, handoff = build_tool_navigation(
            tool_id=browse_tool,
            actor=actor,
            reason="Use the full browse page if you want to expand beyond the inline record suggestions.",
            query={"q": _prefill_query(message)},
        )
        return (
            AskPatraIntent(category="record_search", confidence=0.88, tool_target=browse_tool),
            [card],
            [action],
            handoff,
            execution,
        )

    cards, actions, handoff = _build_capability_cards(actor)
    return (
        AskPatraIntent(category="general_help", confidence=0.55, tool_target=None),
        cards,
        actions,
        handoff,
        execution,
    )


def _fallback_answer(
    message: str,
    citations: list[AskPatraCitation],
    *,
    intent: AskPatraIntent,
    tool_cards: list[AskPatraToolCard],
) -> str:
    lowered = message.lower()
    if _is_greeting(lowered):
        return (
            "Hello. I can help with **record lookup**, **metadata questions**, and **PATRA workflows**.\n\n"
            "- Ask for model cards or datasheets\n"
            "- Ask how PATRA features work\n"
            "- Ask me to compare a few relevant records"
        )
    if intent.category in {"capability", "general_help"}:
        return (
            "**I can help with:**\n"
            "- finding model cards\n"
            "- finding datasheets\n"
            "- generating an intent schema\n"
            "- showing the MVP demo report\n"
            "- routing you to Agent Toolkit, MCP Explorer, experiments, tickets, and edit workflows\n\n"
            "Ask for a specific tool or task and I will route you to the right surface."
        )
    if citations:
        lines = [f"**I found {len(citations)} relevant records.**"]
        lines.extend([f"- **{item.title}** ({item.resource_type}, `{item.route}`)" for item in citations[:3]])
        if tool_cards:
            lines.append("")
            lines.append(f"Use **{tool_cards[0].title}** if you want the full browse page for this topic.")
        return "\n".join(lines)
    if tool_cards:
        card = tool_cards[0]
        if intent.category in {"intent_schema", "mvp_demo_report", "mcp_explorer", "agent_tools", "animal_ecology", "digital_agriculture"}:
            return (
                f"**This request maps to {card.title}.**\n"
                f"- {card.summary}\n"
                f"- I prepared a route handoff so you can continue in the right PATRA tool."
            )
        if intent.category in {"automated_ingestion", "edit_records", "submit_records", "tickets"}:
            return (
                f"**This request needs {card.title}.**\n"
                f"- {card.summary}\n"
                f"- I prepared a draft handoff so the workflow can continue in that tool."
            )
    return "I could not find a strong match for that query. Try naming a task, domain, author, or metadata keyword."


def _normalize_answer_markdown(answer: str) -> str:
    normalized = str(answer or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return normalized
    # Some LLMs emit inline Markdown bullets like "I can help: * A * B".
    # Convert those to proper Markdown list items before the frontend parser sees them.
    normalized = re.sub(r"(?<!\n)\s+\*\s+(?=\S)", "\n- ", normalized)
    normalized = re.sub(r"(?m)^\s*\*\s+", "- ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _message_payload(messages: list[dict]) -> list[AskPatraMessage]:
    return [AskPatraMessage.model_validate(item) for item in messages]


def _append_assistant_message(
    conversation: dict,
    *,
    content: str,
    intent: AskPatraIntent | None = None,
    tool_cards: list[AskPatraToolCard] | None = None,
    suggested_actions: list[AskPatraSuggestedAction] | None = None,
    handoff: AskPatraHandoff | None = None,
    execution: AskPatraExecution | None = None,
) -> None:
    payload: dict = {
        "role": "assistant",
        "content": content,
        "created_at": _now_iso(),
    }
    if intent is not None:
        payload["intent"] = intent.model_dump()
    if tool_cards is not None:
        payload["tool_cards"] = [item.model_dump() for item in tool_cards]
    if suggested_actions is not None:
        payload["suggested_actions"] = [item.model_dump() for item in suggested_actions]
    if handoff is not None:
        payload["handoff"] = handoff.model_dump()
    if execution is not None:
        payload["execution"] = execution.model_dump()
    conversation["messages"].append(payload)


def _coerce_int(value: object, default: int, *, minimum: int = 1, maximum: int = 50) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, coerced))


def _resolve_execution_message(
    *,
    conversation: dict,
    message: str | None,
    query: dict[str, str],
    prefilled_payload: dict,
) -> str:
    if message and message.strip():
        return message.strip()
    for candidate in (
        prefilled_payload.get("intent_text"),
        query.get("intent"),
        prefilled_payload.get("query"),
        query.get("q"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    for item in reversed(conversation.get("messages", [])):
        if item.get("role") == "user":
            candidate = str(item.get("content", "")).strip()
            if candidate:
                return candidate
    return ""


def _build_intent_schema_execution_payload(result) -> dict:
    return {
        "kind": "intent_schema",
        "intent_summary": result.intent_summary,
        "task_type": result.task_type,
        "target_column": result.target_column,
        "field_count": len(result.schema_fields),
        "ambiguity_count": len(result.ambiguity_warnings),
        "assumption_count": len(result.assumptions),
    }


def _format_intent_schema_execution_message(result) -> str:
    return (
        "**Intent Schema generated in deterministic mode.**\n"
        f"- Task type: **{result.task_type}**\n"
        f"- Target column: **{result.target_column}**\n"
        f"- Fields drafted: **{len(result.schema_fields)}**\n"
        f"- Ambiguity warnings: **{len(result.ambiguity_warnings)}**\n\n"
        "Open the full Intent Schema surface if you want to inspect the full field contract."
    )


def _build_mvp_demo_execution_payload(report) -> dict:
    preview_rows = ((report.composition_preview or {}).get("preview_rows") or [])[:3]
    return {
        "kind": "mvp_demo_report",
        "executive_summary": [item.model_dump() for item in report.executive_summary[:6]],
        "preview_row_count": len((report.composition_preview or {}).get("preview_rows") or []),
        "preview_rows": preview_rows,
        "selected_dataset_count": len((report.assembly_plan or {}).get("selected_datasets") or []),
        "gate_status": str((((report.training_stub or {}).get("summary") or {}).get("gate_status") or "unknown")),
        "execution_status": str((((report.training_stub or {}).get("summary") or {}).get("execution_status") or "unknown")),
    }


def _mcp_base_url() -> str:
    return os.getenv("MCP_BASE_URL", "http://localhost:8050").strip() or "http://localhost:8050"


def _read_mcp_endpoint(base_url: str) -> tuple[str | None, str | None]:
    request = Request(f"{base_url.rstrip('/')}/sse", headers={"Accept": "text/event-stream"})
    event_name = None
    endpoint_data = None
    with urlopen(request, timeout=5) as response:
        for _ in range(40):
            raw_line = response.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line:
                if event_name == "endpoint" and endpoint_data:
                    return endpoint_data, None
                event_name = None
                endpoint_data = None
                continue
            if line.startswith("event:"):
                event_name = line.partition(":")[2].strip()
            elif line.startswith("data:") and event_name == "endpoint":
                endpoint_data = line.partition(":")[2].strip()
    return None, "The MCP SSE endpoint did not yield a usable endpoint event."


def _post_mcp_rpc(endpoint_url: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    request = Request(
        endpoint_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=8) as response:
        payload = response.read().decode("utf-8", errors="ignore").strip()
    return json.loads(payload) if payload else {}


def _run_mcp_preview() -> dict:
    base_url = _mcp_base_url()
    endpoint_data, endpoint_error = _read_mcp_endpoint(base_url)
    if endpoint_error:
        return {
            "kind": "mcp_explorer",
            "connected": False,
            "endpoint_url": None,
            "tool_count": 0,
            "tools": [],
            "error": endpoint_error,
            "mcp_base_url": base_url,
        }
    endpoint_url = urljoin(f"{base_url.rstrip('/')}/", endpoint_data or "")
    initialize_result = _post_mcp_rpc(
        endpoint_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "ask-patra-inline", "version": "0.1.0"},
            },
        },
    )
    with suppress(Exception):
        _post_mcp_rpc(endpoint_url, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    tools_result = _post_mcp_rpc(endpoint_url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tool_entries = (((tools_result or {}).get("result") or {}).get("tools") or [])
    tool_names = [str(item.get("name")) for item in tool_entries if isinstance(item, dict) and item.get("name")]
    return {
        "kind": "mcp_explorer",
        "connected": True,
        "endpoint_url": endpoint_url,
        "tool_count": len(tool_names),
        "tools": tool_names[:8],
        "server_name": ((((initialize_result or {}).get("result") or {}).get("serverInfo") or {}).get("name") or "MCP server"),
        "mcp_base_url": base_url,
    }


def _format_mcp_execution_message(result: dict) -> str:
    if not result.get("connected"):
        return (
            "**MCP preview failed.**\n"
            f"- Endpoint: **{result.get('mcp_base_url') or 'unknown'}**\n"
            f"- Error: **{result.get('error') or 'unknown'}**\n\n"
            "Open MCP Explorer for full diagnostics."
        )
    tool_names = result.get("tools") or []
    tool_line = ", ".join(f"`{name}`" for name in tool_names[:4]) if tool_names else "No tools reported"
    return (
        "**MCP preview succeeded.**\n"
        f"- Server: **{result.get('server_name') or 'unknown'}**\n"
        f"- Tool count: **{result.get('tool_count') or 0}**\n"
        f"- Sample tools: {tool_line}\n\n"
        "Open MCP Explorer for interactive execution and resource reads."
    )


def _build_mcp_execution_payload(result: dict) -> dict:
    return {
        "kind": "mcp_explorer",
        "connected": bool(result.get("connected")),
        "mcp_base_url": result.get("mcp_base_url"),
        "endpoint_url": result.get("endpoint_url"),
        "tool_count": int(result.get("tool_count") or 0),
        "tools": list(result.get("tools") or []),
        "server_name": result.get("server_name"),
        "error": result.get("error"),
    }


async def _build_experiment_preview(*, pool: asyncpg.Pool, tool_id: str) -> dict:
    domain = "animal-ecology" if tool_id == "animal_ecology" else "digital-ag"
    tables = DOMAIN_TABLES.get(domain)
    if not tables:
        return {"kind": tool_id, "domain": domain, "available": False, "error": "Unknown experiment domain."}
    events_table = tables["events"]
    async with pool.acquire() as conn:
        user_rows = await conn.fetch(
            f"SELECT DISTINCT user_id FROM {events_table} ORDER BY user_id LIMIT 5"
        )
        summary_rows = await conn.fetch(
            f"""
            SELECT
                experiment_id,
                user_id,
                model_id,
                MAX(total_images) AS total_images,
                MAX(precision) AS precision,
                MAX(recall) AS recall,
                MAX(f1_score) AS f1_score
            FROM {events_table}
            GROUP BY experiment_id, user_id, model_id
            ORDER BY MAX(total_images) DESC NULLS LAST, experiment_id
            LIMIT 5
            """
        )
        count_row = await conn.fetchrow(f"SELECT COUNT(*)::int AS total_rows FROM {events_table}")
    summaries = [
        {
            "experiment_id": row["experiment_id"],
            "user_id": row["user_id"],
            "model_id": row["model_id"],
            "total_images": row["total_images"],
            "precision": float(row["precision"]) if row["precision"] is not None else None,
            "recall": float(row["recall"]) if row["recall"] is not None else None,
            "f1_score": float(row["f1_score"]) if row["f1_score"] is not None else None,
        }
        for row in summary_rows
    ]
    return {
        "kind": tool_id,
        "domain": domain,
        "available": True,
        "total_rows": int((count_row or {}).get("total_rows") or 0),
        "user_count": len(user_rows),
        "users": [str(row["user_id"]) for row in user_rows],
        "experiments": summaries,
    }


def _format_experiment_execution_message(result: dict) -> str:
    if not result.get("available"):
        return f"**Experiment preview failed.** {result.get('error') or 'Unknown error.'}"
    label = "Animal Ecology" if result.get("domain") == "animal-ecology" else "Digital Agriculture"
    top = (result.get("experiments") or [])[:2]
    top_lines = [f"- **{item['experiment_id']}** via `{item['model_id']}` ({item.get('total_images') or 0} images)" for item in top]
    details = "\n".join(top_lines) if top_lines else "- No experiment summaries available"
    return (
        f"**{label} preview generated.**\n"
        f"- Users indexed: **{result.get('user_count') or 0}**\n"
        f"- Event rows: **{result.get('total_rows') or 0}**\n"
        f"{details}\n\n"
        "Open the full experiments page for user selection, detailed metrics, and image traces."
    )


def _format_mvp_demo_execution_message(report) -> str:
    training_summary = (report.training_stub or {}).get("summary") or {}
    gate_status = str(training_summary.get("gate_status") or "unknown")
    execution_status = str(training_summary.get("execution_status") or "unknown")
    preview_row_count = len((report.composition_preview or {}).get("preview_rows") or [])
    return (
        "**MVP Demo Report generated in deterministic mode.**\n"
        f"- Training gate: **{gate_status}**\n"
        f"- Stub execution: **{execution_status}**\n"
        f"- Preview rows: **{preview_row_count}**\n\n"
        "Open the full MVP Demo Report surface if you want the full executive summary and raw JSON."
    )


async def execute_tool_action(
    *,
    actor: PatraActor,
    tool_id: str,
    message: str | None,
    conversation_id: str | None,
    pool: asyncpg.Pool | None = None,
    query: dict[str, str] | None = None,
    prefilled_payload: dict | None = None,
    disable_llm: bool = True,
    request_tapis_token: str | None = None,
) -> tuple[str, list[AskPatraMessage], AskPatraExecution]:
    log.info(
        "ask_patra.execute_tool_action.start tool_id=%s conversation_id=%s query_keys=%s payload_keys=%s disable_llm=%s",
        tool_id,
        conversation_id,
        sorted((query or {}).keys()),
        sorted((prefilled_payload or {}).keys()),
        disable_llm,
    )
    conversation_id = conversation_id or uuid.uuid4().hex
    conversation = _load_conversation(conversation_id)
    query = query or {}
    prefilled_payload = prefilled_payload or {}
    capability = get_tool_capability_map(actor).get(tool_id)

    if capability is None:
        log.error("ask_patra.execute_tool_action.unknown_tool tool_id=%s", tool_id)
        execution = AskPatraExecution(
            state="failed",
            message="The requested tool is not registered in Ask Patra.",
            tool_id=tool_id,
        )
        _append_assistant_message(conversation, content="**Inline execution failed.** The requested tool is unknown.", execution=execution)
        _save_conversation(conversation)
        return conversation_id, _message_payload(conversation["messages"]), execution

    if tool_id not in INLINE_EXECUTOR_TOOL_IDS or not capability.supports_inline:
        log.info("ask_patra.execute_tool_action.blocked_handoff_only tool_id=%s", tool_id)
        execution = AskPatraExecution(
            state="blocked",
            message="This tool is routed through handoff only. Continue in the target page.",
            next_step_route=capability.route,
            tool_id=tool_id,
        )
        card, action, handoff = build_tool_navigation(
            tool_id=tool_id,
            actor=actor,
            reason="This workflow is not allowed to execute inside chat.",
        )
        _append_assistant_message(
            conversation,
            content="**Inline execution is blocked for this tool.** Continue in the full tool surface to proceed.",
            intent=AskPatraIntent(category="general_help", confidence=1.0, tool_target=tool_id),
            tool_cards=[card],
            suggested_actions=[action],
            handoff=handoff,
            execution=execution,
        )
        _save_conversation(conversation)
        return conversation_id, _message_payload(conversation["messages"]), execution

    if capability.availability != "available":
        log.info("ask_patra.execute_tool_action.unavailable tool_id=%s availability=%s", tool_id, capability.availability)
        execution = AskPatraExecution(
            state="blocked",
            message=capability.availability_reason or "This tool is not available for the current actor.",
            next_step_route=capability.route,
            tool_id=tool_id,
        )
        _append_assistant_message(
            conversation,
            content=f"**Inline execution is unavailable.** {execution.message}",
            execution=execution,
        )
        _save_conversation(conversation)
        return conversation_id, _message_payload(conversation["messages"]), execution

    execution_message = _resolve_execution_message(
        conversation=conversation,
        message=message,
        query=query,
        prefilled_payload=prefilled_payload,
    )
    context = str(prefilled_payload.get("context") or query.get("context") or "").strip() or None

    try:
        log.info("ask_patra.execute_tool_action.dispatch tool_id=%s route=%s", tool_id, capability.route)
        outcome = await run_inline_executor(
            InlineExecutionContext(
                tool_id=tool_id,
                tool_route=capability.route,
                message=execution_message,
                context=context,
                query=query,
                prefilled_payload=prefilled_payload,
                disable_llm=disable_llm,
                request_tapis_token=request_tapis_token,
                pool=pool,
            )
        )
        execution = outcome.execution
        card, action, _ = build_tool_navigation(
            tool_id=tool_id,
            actor=actor,
            reason=outcome.navigation_reason,
            query=outcome.navigation_query,
        )
        _append_assistant_message(
            conversation,
            content=outcome.content,
            intent=outcome.intent,
            tool_cards=[card],
            suggested_actions=[action],
            handoff=AskPatraHandoff(kind="inline", tool_target=tool_id, route=capability.route, label=outcome.handoff_label),
            execution=execution,
        )
    except Exception as exc:
        log.exception("ask_patra.execute_tool_action.failed tool_id=%s", tool_id)
        execution = AskPatraExecution(
            state="failed",
            message=str(exc),
            next_step_route=capability.route,
            tool_id=tool_id,
        )
        card, action, handoff = build_tool_navigation(
            tool_id=tool_id,
            actor=actor,
            reason="The inline run failed. Continue in the full tool surface.",
        )
        _append_assistant_message(
            conversation,
            content=f"**Inline execution failed.** {execution.message}",
            intent=AskPatraIntent(category="general_help", confidence=1.0, tool_target=tool_id),
            tool_cards=[card],
            suggested_actions=[action],
            handoff=handoff,
            execution=execution,
        )

    _save_conversation(conversation)
    log.info("ask_patra.execute_tool_action.done tool_id=%s state=%s conversation_id=%s", tool_id, execution.state, conversation_id)
    return conversation_id, _message_payload(conversation["messages"]), execution


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


def _token_expiry_status(value: str) -> str:
    try:
        parts = value.split(".")
        if len(parts) < 2:
            return "non_jwt"
        payload_segment = parts[1]
        padded = payload_segment + "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")))
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)):
            return "jwt_no_exp"
        seconds_remaining = int(exp - datetime.now(timezone.utc).timestamp())
        state = "expired" if seconds_remaining <= 0 else "valid"
        return f"{state}:seconds_remaining={seconds_remaining}"
    except Exception:  # noqa: BLE001
        return "unreadable"


def _llm_service_tapis_token() -> str:
    for name in ("ASK_PATRA_TAPIS_TOKEN", "LITELLM_TAPIS_TOKEN", "PATRA_LITELLM_TAPIS_TOKEN"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _resolve_llm_auth(api_base: str, request_tapis_token: str | None) -> tuple[str | None, dict[str, str]]:
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
            "ask_patra.auth_debug "
            f"litellm=True service_token_present={bool(service_tapis_token)} "
            f"service_token_usable={service_token_usable} "
            f"request_token_present={bool(request_token)} request_token_usable={request_token_usable} "
            f"selected={selected} "
            f"service_token_expiry={_token_expiry_status(service_tapis_token) if service_tapis_token else 'absent'} "
            f"request_token_expiry={_token_expiry_status(request_token) if request_token else 'absent'}",
            flush=True,
        )
        if token:
            log.info("ask_patra.resolve_llm_auth using %s tapis token for LiteLLM host auth_mode=tapis_x_header_and_bearer", selected)
            extra_headers["X-Tapis-Token"] = token
            extra_headers["Authorization"] = f"Bearer {token}"
            return None, extra_headers
    api_key = os.getenv("ASK_PATRA_LLM_API_KEY", "").strip() or None
    print(
        "ask_patra.auth_debug "
        f"litellm={'litellm.pods.tacc.tapis.io' in lowered} api_key_present={bool(api_key)} "
        f"extra_headers={sorted(extra_headers.keys())}",
        flush=True,
    )
    log.info("ask_patra.resolve_llm_auth using api_key=%s extra_headers=%s", bool(api_key), sorted(extra_headers.keys()))
    return api_key, extra_headers


async def answer_question(
    conn: asyncpg.Connection,
    *,
    actor: PatraActor,
    message: str,
    conversation_id: str | None = None,
    reset: bool = False,
    request_tapis_token: str | None = None,
) -> tuple[
    str,
    str,
    str | None,
    list[AskPatraCitation],
    list[AskPatraMessage],
    list,
    AskPatraIntent,
    list[AskPatraToolCard],
    list[AskPatraSuggestedAction],
    AskPatraHandoff,
    AskPatraExecution,
]:
    log.info(
        "ask_patra.answer_question.start conversation_id=%s reset=%s message_len=%s actor=%s",
        conversation_id,
        reset,
        len(message or ""),
        getattr(actor, "username", None),
    )
    starters = ensure_ask_patra_storage()
    conversation_id = conversation_id or uuid.uuid4().hex
    conversation = _load_conversation(conversation_id)
    if reset:
        log.info("ask_patra.answer_question.reset conversation_id=%s", conversation_id)
        conversation["messages"] = []

    include_private = actor.is_authenticated
    wants_lookup = _wants_record_lookup(message)
    log.info("ask_patra.answer_question.lookup include_private=%s wants_lookup=%s", include_private, wants_lookup)
    requested_limit = _requested_record_limit(message, default=3)
    requested_resource_types = _requested_resource_types(message)
    citations = (
        await search_pattra_records(
            conn,
            query=message,
            include_private=include_private,
            limit=requested_limit,
            resource_types=requested_resource_types,
        )
        if wants_lookup
        else []
    )
    intent, tool_cards, suggested_actions, handoff, execution = _build_tool_routing(
        actor=actor,
        message=message,
        citations=citations,
    )
    log.info(
        "ask_patra.answer_question.intent category=%s confidence=%s tool_target=%s citations=%s",
        intent.category,
        intent.confidence,
        intent.tool_target,
        len(citations),
    )
    context_block = _build_context_block(citations)

    system_prompt = _system_prompt_text()
    llm_messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"User question:\n{message}\n\n"
                f"Relevant PATRA records:\n{context_block}\n\n"
                "Answer concisely in Markdown. Use bold labels and short bullet lists when useful. "
                f"Do not list more than {requested_limit} records. "
                "Each Markdown bullet must be on its own line. Do not use inline asterisk bullets. "
                "If record citations are provided, state exactly how many records you are listing and keep that count consistent with the listed records. "
                "If this is only a greeting or a broad capability question, do not enumerate records."
            ),
        },
    ]

    api_base = _llm_api_base()
    api_key, extra_headers = _resolve_llm_auth(api_base, request_tapis_token)
    model = _llm_model()
    enabled = os.getenv("ASK_PATRA_LLM_ENABLED", "true").strip().lower() == "true" and bool(api_base)
    log.info(
        "ask_patra.answer_question.llm_config enabled=%s api_base=%s model=%s extra_headers=%s",
        enabled,
        api_base,
        model,
        sorted(extra_headers.keys()),
    )

    mode = "code_fallback"
    answer = _fallback_answer(message, citations, intent=intent, tool_cards=tool_cards)
    model_used: str | None = None

    allow_llm_answer = intent.category in {"record_search", "general_help"} and not _is_greeting(message)
    log.info("ask_patra.answer_question.llm_decision allow_llm_answer=%s", allow_llm_answer)

    if enabled and allow_llm_answer:
        try:
            log.info("ask_patra.answer_question.llm_attempt conversation_id=%s", conversation_id)
            answer, model_used = chat_text_with_model_fallback(
                api_base=api_base,
                model=model,
                api_key=api_key,
                extra_headers=extra_headers,
                messages=llm_messages,
                timeout_seconds=int(os.getenv("ASK_PATRA_LLM_TIMEOUT_SECONDS", "60") or "60"),
                temperature=0.2,
                max_tokens=900,
            )
            mode = "llm"
            answer = _normalize_answer_markdown(answer)
            log.info("ask_patra.answer_question.llm_success model_used=%s", model_used)
        except Exception:
            log.exception("ask_patra.answer_question.llm_failed conversation_id=%s", conversation_id)
            mode = "code_fallback"
    else:
        log.info("ask_patra.answer_question.llm_skipped enabled=%s allow_llm_answer=%s", enabled, allow_llm_answer)

    conversation["messages"].append({"role": "user", "content": message, "created_at": _now_iso()})
    conversation["messages"].append(
        {
            "role": "assistant",
            "content": _normalize_answer_markdown(answer),
            "created_at": _now_iso(),
            "intent": intent.model_dump(),
            "tool_cards": [item.model_dump() for item in tool_cards],
            "suggested_actions": [item.model_dump() for item in suggested_actions],
            "handoff": handoff.model_dump(),
            "execution": execution.model_dump(),
        }
    )
    _save_conversation(conversation)
    log.info(
        "ask_patra.answer_question.done conversation_id=%s mode=%s model_used=%s citations=%s tool_cards=%s",
        conversation_id,
        mode,
        model_used,
        len(citations),
        len(tool_cards),
    )

    return (
        conversation_id,
        answer,
        model_used,
        citations,
        _message_payload(conversation["messages"]),
        starters,
        intent,
        tool_cards,
        suggested_actions,
        handoff,
        execution,
    )
