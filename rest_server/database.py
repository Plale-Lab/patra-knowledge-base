import asyncio
import logging
import os
import ssl
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import asyncpg

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_MAX_RETRIES = 5
_RETRY_DELAY_S = 3


_TAPIS_PODS_SUFFIX = ".pods.icicleai.tapis.io"
_TAPIS_PG_PORT = 443


def _build_connection_options(raw_url: str) -> tuple[str, ssl.SSLContext | bool, bool]:
    """Normalise asyncpg connection options for the active PostgreSQL backend.

    Tapis Pods exposes PostgreSQL behind a 443 endpoint. In practice this
    endpoint expects direct TLS rather than PostgreSQL's SSLRequest upgrade
    path, so asyncpg must use ``direct_tls=True`` there. If the host looks
    like a Tapis pod and the port is 5432, rewrite it to 443.

    asyncpg doesn't reliably consume the ``sslmode`` query-string parameter
    the way libpq/psycopg2 does, so we strip it and pass ``ssl`` explicitly.
    """
    parsed = urlparse(raw_url)

    # Tapis Pods: rewrite 5432 → 443
    host = parsed.hostname or ""
    port = parsed.port
    is_tapis_pod = host.endswith(_TAPIS_PODS_SUFFIX)
    if is_tapis_pod and port in (5432, None):
        netloc = parsed.netloc.replace(f":{port}", f":{_TAPIS_PG_PORT}", 1) if port else f"{parsed.netloc}:{_TAPIS_PG_PORT}"
        parsed = parsed._replace(netloc=netloc)
        log.info("Tapis Pods host detected — rewriting port %s → %s", port, _TAPIS_PG_PORT)

    qs = parse_qs(parsed.query)
    sslmode = qs.pop("sslmode", [None])[0]

    clean_url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
    effective_port = parsed.port
    direct_tls = bool(is_tapis_pod and effective_port == _TAPIS_PG_PORT)

    if sslmode in ("require", "prefer"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return clean_url, ctx, direct_tls
    if sslmode in ("verify-ca", "verify-full"):
        return clean_url, ssl.create_default_context(), direct_tls
    return clean_url, False, False


async def init_pool() -> asyncpg.Pool:
    """Create connection pool with retries. Called during app lifespan startup."""
    global _pool
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL environment variable is required")

    dsn, ssl_arg, direct_tls = _build_connection_options(url)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            _pool = await asyncpg.create_pool(
                dsn,
                ssl=ssl_arg,
                direct_tls=direct_tls,
                min_size=1,
                max_size=10,
                command_timeout=60,
                timeout=30,
            )
            log.info("Database pool ready (attempt %d)", attempt)
            return _pool
        except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
            if attempt == _MAX_RETRIES:
                raise
            log.warning(
                "DB connection attempt %d/%d failed (%s), retrying in %ds …",
                attempt, _MAX_RETRIES, exc, _RETRY_DELAY_S,
            )
            await asyncio.sleep(_RETRY_DELAY_S)
    raise RuntimeError("Unreachable")


async def close_pool() -> None:
    """Close connection pool. Called during app lifespan shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """FastAPI dependency: returns the connection pool."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool
