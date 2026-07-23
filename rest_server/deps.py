import logging
import hashlib
import hmac
import json
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Header, HTTPException, Request

from shared.config import get_admin_users_csv, get_asset_ingest_keys_json, get_default_admin_users
from rest_server.errors import auth_required, admin_required, service_not_configured

log = logging.getLogger(__name__)

TAPIS_TOKEN_HEADER = "X-Tapis-Token"
ASSET_INGEST_ORG_HEADER = "X-Asset-Org"
ASSET_INGEST_KEY_HEADER = "X-Asset-Api-Key"
PATRA_USERNAME_HEADER = "X-Patra-Username"


@dataclass(frozen=True)
class AssetIngestPrincipal:
    organization: str


@dataclass(frozen=True)
class PatraActor:
    username: str | None
    role: str = "guest"
    auth_type: str = "guest"

    @property
    def is_authenticated(self) -> bool:
        return self.auth_type != "guest"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_include_private(request: Request) -> bool:
    """Return True when the caller presents a Tapis token via X-Tapis-Token.

    The patra-toolkit authenticates against Tapis OAuth2 and passes the
    resulting access token in the ``X-Tapis-Token`` header.  Presence of
    any non-empty value is treated as authenticated (matching the legacy
    Flask server behaviour).  No token falls back to public-only.
    """
    token = request.headers.get(TAPIS_TOKEN_HEADER)
    if not token:
        return False
    log.debug("X-Tapis-Token present – including private records")
    return True


@lru_cache(maxsize=1)
def get_admin_users() -> set[str]:
    configured = get_admin_users_csv()
    values = {item.strip().lower() for item in configured.split(",") if item.strip()}
    return set(get_default_admin_users()) | values


def get_request_actor(request: Request) -> PatraActor:
    username = (request.headers.get(PATRA_USERNAME_HEADER) or "").strip()
    token = (request.headers.get(TAPIS_TOKEN_HEADER) or "").strip()

    if not token:
        return PatraActor(username=username or None)

    normalized_username = username.lower() if username else None
    is_admin = normalized_username in get_admin_users() if normalized_username else False
    return PatraActor(
        username=username or None,
        role="admin" if is_admin else "user",
        auth_type="tapis",
    )


def require_authenticated_actor(request: Request) -> PatraActor:
    """Return the actor if authenticated, otherwise raise 401."""
    actor = get_request_actor(request)
    if not actor.is_authenticated:
        raise auth_required()
    return actor


def require_admin_actor(request: Request) -> PatraActor:
    actor = get_request_actor(request)
    if not actor.is_admin:
        raise admin_required()
    return actor


@lru_cache(maxsize=1)
def get_asset_ingest_keys() -> dict[str, str]:
    raw = get_asset_ingest_keys_json()
    if not raw:
        return {}
    try:
        config = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PATRA_ASSET_INGEST_KEYS_JSON must be valid JSON") from exc
    if not isinstance(config, dict):
        raise RuntimeError("PATRA_ASSET_INGEST_KEYS_JSON must be a JSON object")
    normalized: dict[str, str] = {}
    for org, secret in config.items():
        if not isinstance(org, str) or not isinstance(secret, str) or not org.strip() or not secret.strip():
            raise RuntimeError("PATRA_ASSET_INGEST_KEYS_JSON entries must map non-empty strings to non-empty strings")
        normalized[org.strip()] = secret.strip()
    return normalized


def _extract_asset_api_key(authorization: str | None, x_asset_api_key: str | None) -> str | None:
    if x_asset_api_key:
        return x_asset_api_key.strip()
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _matches_configured_secret(presented: str, configured: str) -> bool:
    if configured.startswith("sha256:"):
        presented_hash = hashlib.sha256(presented.encode("utf-8")).hexdigest()
        return hmac.compare_digest(presented_hash, configured.removeprefix("sha256:"))
    return hmac.compare_digest(presented, configured)


def require_asset_ingest_principal(
    x_asset_org: str | None = Header(default=None, alias=ASSET_INGEST_ORG_HEADER),
    x_asset_api_key: str | None = Header(default=None, alias=ASSET_INGEST_KEY_HEADER),
    x_tapis_token: str | None = Header(default=None, alias=TAPIS_TOKEN_HEADER),
    authorization: str | None = Header(default=None),
) -> AssetIngestPrincipal:
    if (x_tapis_token or "").strip():
        return AssetIngestPrincipal(organization="tapis")

    try:
        configured_keys = get_asset_ingest_keys()
    except RuntimeError as exc:
        log.error("Asset ingest auth config invalid: %s", exc)
        raise service_not_configured("Asset ingest API")
    if not configured_keys:
        raise service_not_configured("Asset ingest API")
    organization = (x_asset_org or "").strip()
    presented_key = _extract_asset_api_key(authorization, x_asset_api_key)
    if not organization or not presented_key:
        raise HTTPException(status_code=401, detail="Missing asset ingest credentials")
    configured_secret = configured_keys.get(organization)
    if not configured_secret or not _matches_configured_secret(presented_key, configured_secret):
        raise HTTPException(status_code=401, detail="Invalid asset ingest credentials")
    return AssetIngestPrincipal(organization=organization)
