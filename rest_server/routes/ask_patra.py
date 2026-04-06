from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Request

from rest_server.database import get_pool
from rest_server.deps import get_request_actor
from rest_server.features.ask_patra.models import AskPatraBootstrapResponse, AskPatraChatRequest, AskPatraChatResponse
from rest_server.features.ask_patra.service import _provider_label, answer_question, ensure_ask_patra_storage


router = APIRouter(prefix="/api/ask-patra", tags=["ask-patra"])


@router.get("/bootstrap", response_model=AskPatraBootstrapResponse)
async def ask_patra_bootstrap():
    starters = ensure_ask_patra_storage()
    return AskPatraBootstrapResponse(
        enabled=True,
        provider=_provider_label(),
        starter_prompts=starters,
    )


@router.post("/chat", response_model=AskPatraChatResponse)
async def ask_patra_chat(
    payload: AskPatraChatRequest,
    request: Request,
    actor=Depends(get_request_actor),
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        conversation_id, answer, model_used, citations, messages, starters = await answer_question(
            conn,
            actor=actor,
            message=payload.message,
            conversation_id=payload.conversation_id,
            reset=payload.reset,
            request_tapis_token=(request.headers.get("X-Tapis-Token") or "").strip() or None,
        )
    return AskPatraChatResponse(
        conversation_id=conversation_id,
        answer=answer,
        mode="llm" if model_used else "code_fallback",
        provider=_provider_label(),
        model_used=model_used,
        citations=citations,
        messages=messages,
        starter_prompts=starters,
    )
