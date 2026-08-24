import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import rest_server.main as main_module
from rest_server.features.weekly_report import service


# ---------------------------------------------------------------------------
# get_counts
# ---------------------------------------------------------------------------

def _make_mock_pool(model_count: int, dataset_count: int):
    pool = MagicMock()
    conn = AsyncMock()

    async def _fetchval(query: str, *args):
        if "model_cards" in query:
            return model_count
        if "datasheets" in query:
            return dataset_count
        return None

    conn.fetchval = _fetchval

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    return pool


@pytest.mark.asyncio
async def test_get_counts_returns_model_and_dataset_counts():
    pool = _make_mock_pool(model_count=7, dataset_count=3)

    counts = await service.get_counts(pool)

    assert counts == {"model_count": 7, "dataset_count": 3}


# ---------------------------------------------------------------------------
# build_payload
# ---------------------------------------------------------------------------

def test_build_payload_shape():
    payload = service.build_payload({"model_count": 7, "dataset_count": 3})

    assert payload["service"] == "patra"
    assert payload["model_count"] == 7
    assert payload["dataset_count"] == 3
    datetime.fromisoformat(payload["timestamp"])


# ---------------------------------------------------------------------------
# post_report -- mocked httpx.AsyncClient
# ---------------------------------------------------------------------------

class _FakeAsyncResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


class _FakeAsyncClient:
    def __init__(self, response=None, exc=None):
        self._response = response or _FakeAsyncResponse()
        self._exc = exc
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        self.post_calls.append((url, headers, json))
        if self._exc:
            raise self._exc
        return self._response


@pytest.mark.asyncio
async def test_post_report_no_url_is_noop(monkeypatch):
    monkeypatch.setattr(service, "get_weekly_report_webhook_url", lambda: None)
    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not construct a client")),
    )

    await service.post_report({"service": "patra"})


@pytest.mark.asyncio
async def test_post_report_sends_bearer_token_when_configured(monkeypatch):
    fake_client = _FakeAsyncClient()
    monkeypatch.setattr(service, "get_weekly_report_webhook_url", lambda: "https://example.com/webhook")
    monkeypatch.setattr(service, "get_weekly_report_webhook_token", lambda: "secret-token")
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: fake_client)

    await service.post_report({"service": "patra"})

    url, headers, json_body = fake_client.post_calls[0]
    assert url == "https://example.com/webhook"
    assert headers["Authorization"] == "Bearer secret-token"
    assert json_body == {"service": "patra"}


@pytest.mark.asyncio
async def test_post_report_omits_auth_header_without_token(monkeypatch):
    fake_client = _FakeAsyncClient()
    monkeypatch.setattr(service, "get_weekly_report_webhook_url", lambda: "https://example.com/webhook")
    monkeypatch.setattr(service, "get_weekly_report_webhook_token", lambda: None)
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: fake_client)

    await service.post_report({"service": "patra"})

    _url, headers, _json_body = fake_client.post_calls[0]
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_post_report_propagates_http_errors(monkeypatch):
    fake_client = _FakeAsyncClient(response=_FakeAsyncResponse(status_code=500))
    monkeypatch.setattr(service, "get_weekly_report_webhook_url", lambda: "https://example.com/webhook")
    monkeypatch.setattr(service, "get_weekly_report_webhook_token", lambda: None)
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: fake_client)

    with pytest.raises(httpx.HTTPStatusError):
        await service.post_report({"service": "patra"})


# ---------------------------------------------------------------------------
# run_report_once
# ---------------------------------------------------------------------------

def _fail(*_args, **_kwargs):
    raise AssertionError("should not have been called")


@pytest.mark.asyncio
async def test_run_report_once_flag_disabled_skips_everything(monkeypatch):
    monkeypatch.setattr(service, "is_weekly_report_enabled", lambda: False)
    monkeypatch.setattr(service, "get_weekly_report_webhook_url", _fail)
    monkeypatch.setattr(service, "get_pool", _fail)

    await service.run_report_once()


@pytest.mark.asyncio
async def test_run_report_once_no_webhook_url_skips_db(monkeypatch):
    monkeypatch.setattr(service, "is_weekly_report_enabled", lambda: True)
    monkeypatch.setattr(service, "get_weekly_report_webhook_url", lambda: None)
    monkeypatch.setattr(service, "get_pool", _fail)

    await service.run_report_once()


@pytest.mark.asyncio
async def test_run_report_once_db_unavailable_logs_and_returns(monkeypatch):
    monkeypatch.setattr(service, "is_weekly_report_enabled", lambda: True)
    monkeypatch.setattr(service, "get_weekly_report_webhook_url", lambda: "https://example.com/webhook")

    def fake_get_pool():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "get_pool", fake_get_pool)

    await service.run_report_once()


@pytest.mark.asyncio
async def test_run_report_once_webhook_post_failure_logs_and_returns(monkeypatch):
    monkeypatch.setattr(service, "is_weekly_report_enabled", lambda: True)
    monkeypatch.setattr(service, "get_weekly_report_webhook_url", lambda: "https://example.com/webhook")
    monkeypatch.setattr(service, "get_pool", lambda: object())

    async def fake_get_counts(pool):
        return {"model_count": 1, "dataset_count": 2}

    async def fake_post_report(payload):
        raise httpx.HTTPStatusError("boom", request=None, response=None)

    monkeypatch.setattr(service, "get_counts", fake_get_counts)
    monkeypatch.setattr(service, "post_report", fake_post_report)

    await service.run_report_once()


@pytest.mark.asyncio
async def test_run_report_once_success_posts_built_payload(monkeypatch):
    monkeypatch.setattr(service, "is_weekly_report_enabled", lambda: True)
    monkeypatch.setattr(service, "get_weekly_report_webhook_url", lambda: "https://example.com/webhook")
    monkeypatch.setattr(service, "get_pool", lambda: object())

    async def fake_get_counts(pool):
        return {"model_count": 4, "dataset_count": 9}

    posted = {}

    async def fake_post_report(payload):
        posted.update(payload)

    monkeypatch.setattr(service, "get_counts", fake_get_counts)
    monkeypatch.setattr(service, "post_report", fake_post_report)

    await service.run_report_once()

    assert posted["model_count"] == 4
    assert posted["dataset_count"] == 9
    assert posted["service"] == "patra"


# ---------------------------------------------------------------------------
# main.py lifespan wiring
# ---------------------------------------------------------------------------

async def _fake_init_pool():
    return None


@pytest.mark.asyncio
async def test_lifespan_starts_and_cancels_weekly_report_task_when_enabled(monkeypatch):
    started = asyncio.Event()
    cancelled = {"value": False}

    async def fake_loop():
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled["value"] = True
            raise

    monkeypatch.setattr(main_module, "init_pool", _fake_init_pool)
    monkeypatch.setattr(main_module, "is_weekly_report_enabled", lambda: True)
    monkeypatch.setattr(main_module, "run_weekly_report_loop", fake_loop)

    async with main_module.lifespan(main_module.app):
        await asyncio.wait_for(started.wait(), timeout=1)

    assert cancelled["value"] is True


@pytest.mark.asyncio
async def test_lifespan_skips_weekly_report_task_when_disabled(monkeypatch):
    monkeypatch.setattr(main_module, "init_pool", _fake_init_pool)
    monkeypatch.setattr(main_module, "is_weekly_report_enabled", lambda: False)
    monkeypatch.setattr(main_module, "run_weekly_report_loop", _fail)

    async with main_module.lifespan(main_module.app):
        await asyncio.sleep(0.05)
