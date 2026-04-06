from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

from rest_server.deps import PatraActor
from rest_server.features.ask_patra.models import AskPatraCitation, AskPatraMessage
from rest_server.features.ask_patra.prompts import DEFAULT_BEHAVIOR_PROMPT, DEFAULT_SYSTEM_PROMPT, ensure_prompt_templates
from rest_server.features.shared.openai_compat import chat_text_with_model_fallback
from rest_server.patra_agent_service import DEFAULT_LLM_API_BASE, DEFAULT_LLM_API_KEY, DEFAULT_LLM_MODEL


STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with", "about", "me", "you",
    "can", "what", "where", "how", "show", "find", "look", "up", "into", "from", "that", "this",
    "is", "are", "be", "it", "i", "we", "do", "does", "help", "please",
}


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
    api_base = os.getenv("ASK_PATRA_LLM_API_BASE", DEFAULT_LLM_API_BASE)
    if "litellm.pods.tacc.tapis.io" in api_base:
        return "SambaNova via LiteLLM"
    if "127.0.0.1:1234" in api_base or "localhost:1234" in api_base:
        return "LM Studio"
    return "OpenAI-compatible provider"


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


def _score_text(query_tokens: list[str], *values: str | None) -> tuple[int, list[str]]:
    haystack = " ".join(value for value in values if value).lower()
    matched = [token for token in query_tokens if token in haystack]
    return len(matched), matched


async def search_pattra_records(
    conn: asyncpg.Connection,
    *,
    query: str,
    include_private: bool,
    limit_per_type: int = 8,
) -> list[AskPatraCitation]:
    query_tokens = _tokenize_query(query)
    model_filter = "" if include_private else "AND mc.is_private = false"
    datasheet_filter = "" if include_private else "AND d.is_private = false"
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
        max(limit_per_type * 10, 40),
    )
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
        max(limit_per_type * 10, 40),
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
    return [citation for _, citation in citations[: limit_per_type * 2]]


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


def _fallback_answer(message: str, citations: list[AskPatraCitation]) -> str:
    lowered = message.lower()
    if "what can you help" in lowered or "what can patra do" in lowered:
        base = [
            "I can look up model cards and datasheets, summarize PATRA features, and point you to relevant records.",
            "Examples: search for crop-yield model cards, find geospatial datasheets, compare related resources, or explain Agent Toolkit, Edit Records, and Automated Ingestion.",
        ]
        if citations:
            base.append("Relevant records I found:")
            base.extend([f"- {item.title} ({item.resource_type}, {item.route})" for item in citations[:5]])
        return "\n".join(base)
    if citations:
        lines = [f"I found {len(citations)} relevant records:"]
        lines.extend([f"- {item.title} ({item.resource_type}, {item.route})" for item in citations[:6]])
        return "\n".join(lines)
    return "I could not find a strong match for that query. Try naming a task, domain, author, or metadata keyword."


def _message_payload(messages: list[dict]) -> list[AskPatraMessage]:
    return [AskPatraMessage.model_validate(item) for item in messages]


def _resolve_llm_auth(api_base: str) -> tuple[str | None, dict[str, str]]:
    extra_headers: dict[str, str] = {}
    service_tapis_token = os.getenv("ASK_PATRA_TAPIS_TOKEN", "").strip()
    if "litellm.pods.tacc.tapis.io" in (api_base or "").lower() and service_tapis_token:
        extra_headers["X-Tapis-Token"] = service_tapis_token
        return None, extra_headers
    api_key = os.getenv("ASK_PATRA_LLM_API_KEY", DEFAULT_LLM_API_KEY)
    return api_key, extra_headers


async def answer_question(
    conn: asyncpg.Connection,
    *,
    actor: PatraActor,
    message: str,
    conversation_id: str | None = None,
    reset: bool = False,
) -> tuple[str, str, str | None, list[AskPatraCitation], list[AskPatraMessage], list]:
    starters = ensure_ask_patra_storage()
    conversation_id = conversation_id or uuid.uuid4().hex
    conversation = _load_conversation(conversation_id)
    if reset:
        conversation["messages"] = []

    include_private = actor.is_authenticated
    citations = await search_pattra_records(conn, query=message, include_private=include_private)
    context_block = _build_context_block(citations)

    system_prompt = _system_prompt_text()
    llm_messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"User question:\n{message}\n\n"
                f"Relevant PATRA records:\n{context_block}\n\n"
                "Answer concisely. If you mention records, use their titles and routes."
            ),
        },
    ]

    api_base = os.getenv("ASK_PATRA_LLM_API_BASE", DEFAULT_LLM_API_BASE)
    api_key, extra_headers = _resolve_llm_auth(api_base)
    model = os.getenv("ASK_PATRA_LLM_MODEL", "").strip() or None
    enabled = os.getenv("ASK_PATRA_LLM_ENABLED", "true").strip().lower() == "true"

    mode = "code_fallback"
    answer = _fallback_answer(message, citations)
    model_used: str | None = None

    if enabled:
        try:
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
        except Exception:
            mode = "code_fallback"

    conversation["messages"].append({"role": "user", "content": message, "created_at": _now_iso()})
    conversation["messages"].append({"role": "assistant", "content": answer, "created_at": _now_iso()})
    _save_conversation(conversation)

    return conversation_id, answer, model_used, citations, _message_payload(conversation["messages"]), starters
