"""Periodic reporting of aggregate asset counts to an external webhook
(Carlos's "services reporting board"). Runs as a plain asyncio background
task started from rest_server.main's lifespan. Off by default; gated by
is_weekly_report_enabled() and a no-op if WEEKLY_REPORT_WEBHOOK_URL is unset.

Payload shape below is a PLACEHOLDER pending Carlos's actual webhook spec
(URL, auth mechanism, expected JSON body). Update build_payload() and the
auth header logic in post_report() once that spec is confirmed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TypedDict

import asyncpg
import httpx

from rest_server.database import get_pool
from shared.config import (
    get_weekly_report_webhook_token,
    get_weekly_report_webhook_url,
    is_weekly_report_enabled,
)

log = logging.getLogger(__name__)

_REPORT_INTERVAL_SECONDS = 7 * 24 * 60 * 60  # 7 days
_REQUEST_TIMEOUT_SECONDS = 10


class AssetCounts(TypedDict):
    model_count: int
    dataset_count: int


async def get_counts(pool: asyncpg.Pool) -> AssetCounts:
    """Unfiltered totals -- no privacy/status filtering."""
    async with pool.acquire() as conn:
        model_count = await conn.fetchval("SELECT COUNT(*) FROM model_cards")
        dataset_count = await conn.fetchval("SELECT COUNT(*) FROM datasheets")
    return {"model_count": model_count, "dataset_count": dataset_count}


def build_payload(counts: AssetCounts) -> dict:
    """PLACEHOLDER shape -- confirm against Carlos's actual webhook spec."""
    return {
        "service": "patra",
        "model_count": counts["model_count"],
        "dataset_count": counts["dataset_count"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def post_report(payload: dict) -> None:
    """Raises on failure; caller (run_report_once) catches and logs so one
    failed run doesn't crash the loop."""
    url = get_weekly_report_webhook_url()
    if not url:
        log.info("Weekly report webhook URL not configured; skipping POST")
        return
    headers = {"Content-Type": "application/json"}
    token = get_weekly_report_webhook_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()


async def run_report_once() -> None:
    """One count-and-post cycle. Never raises -- logs and returns on any
    failure (DB unavailable, webhook down/timeout/4xx/5xx) so the caller's
    sleep loop is never broken by a bad run."""
    if not is_weekly_report_enabled():
        return
    url = get_weekly_report_webhook_url()
    if not url:
        log.info("ENABLE_WEEKLY_REPORT is true but WEEKLY_REPORT_WEBHOOK_URL is unset; skipping this run")
        return
    try:
        pool = get_pool()
    except Exception:
        log.exception("Weekly report: database pool unavailable, skipping this run")
        return
    try:
        counts = await get_counts(pool)
        payload = build_payload(counts)
        await post_report(payload)
        log.info(
            "Weekly report sent: model_count=%d dataset_count=%d",
            counts["model_count"],
            counts["dataset_count"],
        )
    except Exception:
        log.exception("Weekly report run failed")


async def run_scheduler_loop() -> None:
    """Long-running loop started via asyncio.create_task in lifespan.
    Reports once immediately, then every _REPORT_INTERVAL_SECONDS. Exits
    cleanly on asyncio.CancelledError (task cancellation at shutdown)."""
    log.info("Weekly report scheduler loop starting (interval=%ds)", _REPORT_INTERVAL_SECONDS)
    try:
        await run_report_once()
        while True:
            await asyncio.sleep(_REPORT_INTERVAL_SECONDS)
            await run_report_once()
    except asyncio.CancelledError:
        log.info("Weekly report scheduler loop cancelled, shutting down")
        raise
