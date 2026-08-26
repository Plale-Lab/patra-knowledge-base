from __future__ import annotations

from dataclasses import dataclass

import httpx

from shared.config import (
    get_tapis_oauth_client_id,
    get_tapis_oauth_client_key,
    get_tapis_tenant_base_url,
)


class TapisOAuthError(Exception):
    """Base class for tapis_oauth failures."""


class TapisOAuthNotConfiguredError(TapisOAuthError):
    """TAPIS_OAUTH_CLIENT_ID / TAPIS_OAUTH_CLIENT_KEY are not set."""


class TapisTokenExchangeError(TapisOAuthError):
    """Tapis rejected the authorization code / redirect_uri combination."""


class TapisUserinfoError(TapisOAuthError):
    """Token exchange succeeded but /v3/oauth2/userinfo failed."""


@dataclass(frozen=True)
class TapisLoginResult:
    access_token: str
    username: str
    expires_at: int | None


def _require_client_credentials() -> tuple[str, str, str]:
    client_id = get_tapis_oauth_client_id()
    client_key = get_tapis_oauth_client_key()
    if not client_id or not client_key:
        raise TapisOAuthNotConfiguredError(
            "TAPIS_OAUTH_CLIENT_ID/TAPIS_OAUTH_CLIENT_KEY are not configured"
        )
    return client_id, client_key, get_tapis_tenant_base_url()


def exchange_code_for_token(*, code: str, redirect_uri: str, timeout_seconds: int = 10) -> dict:
    client_id, client_key, base_url = _require_client_credentials()
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(
                f"{base_url}/v3/oauth2/tokens",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                auth=(client_id, client_key),
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise TapisTokenExchangeError(str(exc)) from exc


def fetch_tapis_userinfo(*, access_token: str, timeout_seconds: int = 10) -> dict:
    base_url = get_tapis_tenant_base_url()
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.get(
                f"{base_url}/v3/oauth2/userinfo",
                headers={"X-Tapis-Token": access_token},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise TapisUserinfoError(str(exc)) from exc


def complete_tapis_login(*, code: str, redirect_uri: str) -> TapisLoginResult:
    """Server-side half of the Tapis OAuth2 authorization-code flow.

    Tapis's authenticator does not support PKCE, so the code->token exchange
    requires a confidential-client secret (client_id/client_key via HTTP
    Basic Auth) and must run here rather than in browser JS. The username is
    resolved via /v3/oauth2/userinfo rather than trusted from a
    client-decoded JWT claim.
    """
    token_payload = exchange_code_for_token(code=code, redirect_uri=redirect_uri)
    access_token = (
        token_payload.get("result", {}).get("access_token", {}).get("access_token")
        or token_payload.get("access_token")
    )
    if not access_token:
        raise TapisTokenExchangeError("Tapis token response did not include an access token")

    userinfo = fetch_tapis_userinfo(access_token=access_token)
    username = (userinfo.get("result") or {}).get("username") or userinfo.get("username")
    if not username:
        raise TapisUserinfoError("Tapis userinfo response did not include a username")

    return TapisLoginResult(access_token=access_token, username=username, expires_at=None)
