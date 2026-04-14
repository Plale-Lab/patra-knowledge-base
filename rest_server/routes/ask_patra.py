from __future__ import annotations

import asyncpg
import logging
from fastapi import APIRouter, Depends, Request

from rest_server.deps import get_request_actor
from rest_server.database import get_pool
from rest_server.features.ask_patra.models import (
    AskPatraBootstrapResponse,
    AskPatraChatRequest,
    AskPatraChatResponse,
    AskPatraExecuteRequest,
    AskPatraExecuteResponse,
)
from rest_server.features.ask_patra.service import _provider_label, answer_question, ensure_ask_patra_storage, execute_tool_action
from rest_server.features.ask_patra.tool_registry import get_tool_capabilities


router = APIRouter(prefix="/api/ask-patra", tags=["ask-patra"])
log = logging.getLogger(__name__)


def _request_tapis_token(request: Request) -> str | None:
    x_tapis_token = (request.headers.get("X-Tapis-Token") or "").strip()
    if x_tapis_token:
        return x_tapis_token
    authorization = (request.headers.get("Authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


@router.get("/bootstrap", response_model=AskPatraBootstrapResponse)
async def ask_patra_bootstrap(actor=Depends(get_request_actor)):
    log.info("ask_patra.bootstrap actor=%s role=%s", getattr(actor, "username", None), getattr(actor, "role", None))
    starters = ensure_ask_patra_storage()
    return AskPatraBootstrapResponse(
        enabled=True,
        provider=_provider_label(),
        starter_prompts=starters,
        tool_capabilities=get_tool_capabilities(actor),
    )


async def _ask_patra_chat_impl(
    payload: AskPatraChatRequest,
    request: Request,
    actor=Depends(get_request_actor),
    pool: asyncpg.Pool = Depends(get_pool),
):
    log.info(
        "ask_patra.chat.start actor=%s role=%s conversation_id=%s message_len=%s path=%s",
        getattr(actor, "username", None),
        getattr(actor, "role", None),
        payload.conversation_id,
        len(payload.message or ""),
        request.url.path,
    )
    print(
        "ask_patra.route_debug "
        f"path={request.url.path} "
        f"x_tapis_token_present={bool((request.headers.get('X-Tapis-Token') or '').strip())} "
        f"authorization_present={bool((request.headers.get('Authorization') or '').strip())} "
        f"actor={getattr(actor, 'username', None)} role={getattr(actor, 'role', None)}",
        flush=True,
    )
    async with pool.acquire() as conn:
        conversation_id, answer, model_used, citations, messages, starters, intent, tool_cards, suggested_actions, handoff, execution = await answer_question(
            conn,
            actor=actor,
            message=payload.message,
            conversation_id=payload.conversation_id,
            reset=payload.reset,
            request_tapis_token=_request_tapis_token(request),
        )
    response = AskPatraChatResponse(
        conversation_id=conversation_id,
        answer=answer,
        mode="llm" if model_used else "code_fallback",
        provider=_provider_label(),
        model_used=model_used,
        citations=citations,
        messages=messages,
        starter_prompts=starters,
        intent=intent,
        tool_cards=tool_cards,
        suggested_actions=suggested_actions,
        handoff=handoff,
        execution=execution,
    )
    log.info(
        "ask_patra.chat.done conversation_id=%s mode=%s model_used=%s citations=%s intent=%s tool_cards=%s",
        conversation_id,
        response.mode,
        model_used,
        len(citations),
        getattr(intent, "category", None),
        len(tool_cards),
    )
    return response


@router.post("", response_model=AskPatraChatResponse, include_in_schema=False)
async def ask_patra_chat_legacy(
    payload: AskPatraChatRequest,
    request: Request,
    actor=Depends(get_request_actor),
    pool: asyncpg.Pool = Depends(get_pool),
):
    log.warning("ask_patra.chat.legacy_endpoint_used path=%s", request.url.path)
    return await _ask_patra_chat_impl(payload, request, actor, pool)


@router.post("/", response_model=AskPatraChatResponse, include_in_schema=False)
async def ask_patra_chat_legacy_slash(
    payload: AskPatraChatRequest,
    request: Request,
    actor=Depends(get_request_actor),
    pool: asyncpg.Pool = Depends(get_pool),
):
    log.warning("ask_patra.chat.legacy_slash_endpoint_used path=%s", request.url.path)
    return await _ask_patra_chat_impl(payload, request, actor, pool)


@router.post("/chat", response_model=AskPatraChatResponse)
async def ask_patra_chat(
    payload: AskPatraChatRequest,
    request: Request,
    actor=Depends(get_request_actor),
    pool: asyncpg.Pool = Depends(get_pool),
):
    return await _ask_patra_chat_impl(payload, request, actor, pool)


@router.post("/execute", response_model=AskPatraExecuteResponse)
async def ask_patra_execute(
    payload: AskPatraExecuteRequest,
    request: Request,
    actor=Depends(get_request_actor),
    pool: asyncpg.Pool = Depends(get_pool),
):
    log.info(
        "ask_patra.execute.start actor=%s role=%s tool_id=%s conversation_id=%s",
        getattr(actor, "username", None),
        getattr(actor, "role", None),
        payload.tool_id,
        payload.conversation_id,
    )
    print(
        "ask_patra.execute_route_debug "
        f"path={request.url.path} tool_id={payload.tool_id} "
        f"x_tapis_token_present={bool((request.headers.get('X-Tapis-Token') or '').strip())} "
        f"authorization_present={bool((request.headers.get('Authorization') or '').strip())} "
        f"actor={getattr(actor, 'username', None)} role={getattr(actor, 'role', None)}",
        flush=True,
    )
    conversation_id, messages, execution = await execute_tool_action(
        actor=actor,
        tool_id=payload.tool_id,
        message=payload.message,
        conversation_id=payload.conversation_id,
        pool=pool,
        query=payload.query,
        prefilled_payload=payload.prefilled_payload,
        disable_llm=payload.disable_llm,
        request_tapis_token=_request_tapis_token(request),
    )
    response = AskPatraExecuteResponse(
        conversation_id=conversation_id,
        messages=messages,
        execution=execution,
    )
    log.info(
        "ask_patra.execute.done conversation_id=%s tool_id=%s state=%s",
        conversation_id,
        payload.tool_id,
        execution.state,
    )
    return response
