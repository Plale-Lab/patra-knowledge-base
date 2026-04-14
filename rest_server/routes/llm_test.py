from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from rest_server.deps import PatraActor, require_authenticated_actor
from rest_server.features.ask_patra.service import _llm_api_base, _llm_model, _provider_label, _resolve_llm_auth
from rest_server.features.shared.openai_compat import chat_text_with_model_fallback


router = APIRouter(prefix="/api/llm-test", tags=["llm-test"])
log = logging.getLogger(__name__)


class LlmTestMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class LlmTestChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=8000)
    history: list[LlmTestMessage] = Field(default_factory=list, max_length=12)


class LlmTestChatResponse(BaseModel):
    mode: Literal["llm", "error"]
    provider: str
    model_used: str | None = None
    answer: str = ""
    error: str | None = None
    api_base: str
    requested_model: str | None = None


def _request_tapis_token(request: Request) -> str | None:
    x_tapis_token = (request.headers.get("X-Tapis-Token") or "").strip()
    if x_tapis_token:
        return x_tapis_token
    authorization = (request.headers.get("Authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


@router.post("/chat", response_model=LlmTestChatResponse)
async def chat(
    payload: LlmTestChatRequest,
    request: Request,
    actor: PatraActor = Depends(require_authenticated_actor),
) -> LlmTestChatResponse:
    api_base = _llm_api_base()
    model = _llm_model()
    request_tapis_token = _request_tapis_token(request)
    print(
        "llm_test.route_debug "
        f"path={request.url.path} actor={getattr(actor, 'username', None)} role={getattr(actor, 'role', None)} "
        f"x_tapis_token_present={bool(request_tapis_token)} "
        f"authorization_present={bool((request.headers.get('Authorization') or '').strip())} "
        f"api_base={api_base} model={model}",
        flush=True,
    )
    if not api_base:
        return LlmTestChatResponse(
            mode="error",
            provider=_provider_label(),
            error="No LLM API base is configured.",
            api_base="",
            requested_model=model,
        )

    api_key, extra_headers = _resolve_llm_auth(api_base, request_tapis_token)
    messages = [{"role": item.role, "content": item.content} for item in payload.history[-12:]]
    messages.append({"role": "user", "content": payload.message})
    try:
        answer, model_used = chat_text_with_model_fallback(
            api_base=api_base,
            model=model,
            messages=messages,
            api_key=api_key,
            extra_headers=extra_headers,
            timeout_seconds=90,
            temperature=0.2,
            max_tokens=900,
        )
        print(f"llm_test.chat_success model_used={model_used} answer_len={len(answer)}", flush=True)
        return LlmTestChatResponse(
            mode="llm",
            provider=_provider_label(),
            model_used=model_used,
            answer=answer,
            api_base=api_base,
            requested_model=model,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("llm_test.chat_failed")
        print(f"llm_test.chat_failed error={type(exc).__name__}: {exc}", flush=True)
        return LlmTestChatResponse(
            mode="error",
            provider=_provider_label(),
            error=f"{type(exc).__name__}: {exc}",
            api_base=api_base,
            requested_model=model,
        )
