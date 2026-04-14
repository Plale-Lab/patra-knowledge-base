from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from rest_server.deps import PatraActor, require_authenticated_actor
from rest_server.features.intent_schema.models import (
    IntentSchemaBootstrapResponse,
    IntentSchemaRequest,
    IntentSchemaResponse,
)
from rest_server.features.intent_schema.service import bootstrap_payload, generate_schema


router = APIRouter(prefix="/api/intent-schema", tags=["intent-schema"])


def _request_tapis_token(request: Request) -> str | None:
    x_tapis_token = (request.headers.get("X-Tapis-Token") or "").strip()
    if x_tapis_token:
        return x_tapis_token
    authorization = (request.headers.get("Authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


@router.get("/bootstrap", response_model=IntentSchemaBootstrapResponse)
async def bootstrap(actor: PatraActor = Depends(require_authenticated_actor)) -> IntentSchemaBootstrapResponse:
    return bootstrap_payload()


@router.post("/generate", response_model=IntentSchemaResponse)
async def generate(
    payload: IntentSchemaRequest,
    request: Request,
    actor: PatraActor = Depends(require_authenticated_actor),
) -> IntentSchemaResponse:
    print(
        "intent_schema.route_debug "
        f"path={request.url.path} "
        f"x_tapis_token_present={bool((request.headers.get('X-Tapis-Token') or '').strip())} "
        f"authorization_present={bool((request.headers.get('Authorization') or '').strip())} "
        f"actor={getattr(actor, 'username', None)} role={getattr(actor, 'role', None)}",
        flush=True,
    )
    return generate_schema(
        intent_text=payload.intent_text,
        context=payload.context,
        max_fields=payload.max_fields,
        request_tapis_token=_request_tapis_token(request),
    )
