import asyncio

from fastapi import APIRouter, HTTPException

from rest_server.errors import service_not_configured, upstream_fetch_failed
from rest_server.features.tapis_oauth.service import (
    TapisOAuthNotConfiguredError,
    TapisTokenExchangeError,
    TapisUserinfoError,
    complete_tapis_login,
)
from rest_server.models import TapisAuthExchangeRequest, TapisAuthExchangeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/tapis/exchange", response_model=TapisAuthExchangeResponse)
async def exchange_tapis_code(body: TapisAuthExchangeRequest):
    """Server-side half of the Tapis OAuth2 authorization-code flow.

    Tapis's authenticator does not support PKCE, so the code->token exchange
    needs a confidential-client secret (client_id/client_key) and can't run
    in browser JS. See patra-frontend/docs/tapis_redirect_login.md.
    """
    code = body.code.strip()
    redirect_uri = body.redirect_uri.strip()
    if not code or not redirect_uri:
        raise HTTPException(status_code=400, detail="code and redirect_uri are required")

    try:
        result = await asyncio.to_thread(complete_tapis_login, code=code, redirect_uri=redirect_uri)
    except TapisOAuthNotConfiguredError:
        raise service_not_configured("Tapis OAuth2 login")
    except TapisTokenExchangeError as exc:
        raise HTTPException(status_code=401, detail=f"Tapis token exchange failed: {exc}")
    except TapisUserinfoError as exc:
        raise upstream_fetch_failed("Tapis", str(exc))

    return TapisAuthExchangeResponse(
        access_token=result.access_token,
        username=result.username,
        expires_at=result.expires_at,
    )
