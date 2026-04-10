"""asyncpg connection pool for the MCP server (read-only, standalone)."""

import asyncio
import logging
import os
import ssl
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import asyncpg

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_MAX_RETRIES = 5
_RETRY_DELAY_S = 3
_TAPIS_PODS_SUFFIX = ".pods.icicleai.tapis.io"
_TAPIS_PG_PORT = 443

DOMAIN_TABLES = {
    "animal-ecology": {
        "events": "camera_trap_events",
        "power": "camera_trap_power",
    },
    "digital-ag": {
        "events": "digital_ag_events",
        "power": "digital_ag_power",
    },
}


def _serialize_row(record: asyncpg.Record | None) -> dict | None:
    """Convert an asyncpg Record to a JSON-safe dict."""
    if record is None:
        return None
    d = dict(record)
    for k, v in d.items():
        if isinstance(v, Decimal):
            d[k] = float(v)
        elif isinstance(v, (datetime, date)):
            d[k] = v.isoformat()
    return d


def _build_connection_options(raw_url: str) -> tuple[str, ssl.SSLContext | bool, bool]:
    """Normalize asyncpg connection options for MCP deployment targets."""
    parsed = urlparse(raw_url)

    # Tapis Pods: rewrite 5432 -> 443
    host = parsed.hostname or ""
    port = parsed.port
    is_tapis_pod = host.endswith(_TAPIS_PODS_SUFFIX)
    if is_tapis_pod and port in (5432, None):
        if port:
            netloc = parsed.netloc.replace(f":{port}", f":{_TAPIS_PG_PORT}", 1)
        else:
            netloc = f"{parsed.netloc}:{_TAPIS_PG_PORT}"
        parsed = parsed._replace(netloc=netloc)
        log.info("Tapis Pods host detected for MCP DB - rewriting port %s -> %s", port, _TAPIS_PG_PORT)

    qs = parse_qs(parsed.query)
    sslmode = qs.pop("sslmode", [None])[0]
    clean_url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))

    if sslmode in ("require", "prefer"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return clean_url, ctx, False
    if sslmode in ("verify-ca", "verify-full"):
        return clean_url, ssl.create_default_context(), False
    return clean_url, False, False


async def init_pool() -> asyncpg.Pool:
    """Create connection pool with retries."""
    global _pool
    if _pool is not None:
        return _pool

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
                max_size=5,
                command_timeout=60,
                timeout=30,
            )
            log.info("MCP database pool ready (attempt %d)", attempt)
            return _pool
        except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
            if attempt == _MAX_RETRIES:
                log.exception("MCP DB connection failed after %d attempts", _MAX_RETRIES)
                raise
            log.warning(
                "DB connection attempt %d/%d failed (%s: %s), retrying in %ds ...",
                attempt,
                _MAX_RETRIES,
                type(exc).__name__,
                str(exc) or repr(exc),
                _RETRY_DELAY_S,
            )
            await asyncio.sleep(_RETRY_DELAY_S)
    raise RuntimeError("Unreachable")


async def close_pool() -> None:
    """Close connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Return the connection pool; raise if not initialised."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool
