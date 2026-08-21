import importlib
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

import rest_server.main as main_module


@asynccontextmanager
async def _no_op_lifespan(_app):
    yield


@pytest.fixture
def hf_import_app(monkeypatch):
    """Reload rest_server.main with ENABLE_HF_IMPORT=true so the router is
    registered, and swap in a no-op lifespan (matches
    tests/test_model_card_fallbacks.py) so no real DB connection is attempted.

    is_hf_import_enabled() is checked at module-import time in main.py (same
    as is_ask_patra_enabled()), so exercising the flag requires reloading the
    module rather than monkeypatching the function directly. This is safe:
    other test files already did `from rest_server.main import app` at
    collection time and keep their own bound reference to the original app
    object — reloading only reassigns `rest_server.main.app` going forward.
    """
    monkeypatch.setenv("ENABLE_HF_IMPORT", "true")
    importlib.reload(main_module)
    main_module.app.router.lifespan_context = _no_op_lifespan
    yield main_module.app
    monkeypatch.setenv("ENABLE_HF_IMPORT", "false")
    importlib.reload(main_module)


def test_hf_import_model_card_success(hf_import_app, monkeypatch, tapis_headers):
    async def fake_import(url, asset_type, request_tapis_token=None):
        assert url == "https://huggingface.co/distilbert/distilbert-base-uncased"
        assert asset_type == "model_card"
        return {
            "name": "Distilbert Base Uncased",
            "author": "distilbert",
            "license": "apache-2.0",
            "framework": "PyTorch",
            "keywords": "text-classification, en",
            "documentation": "https://huggingface.co/distilbert/distilbert-base-uncased",
            "location": "https://huggingface.co/distilbert/distilbert-base-uncased",
            "short_description": "DistilBERT is a small, fast model.",
            "full_description": "DistilBERT is a small, fast model. It was trained by distilling BERT base.",
            "is_gated": False,
        }

    monkeypatch.setattr("rest_server.routes.hf_import.import_from_huggingface", fake_import)

    with TestClient(hf_import_app) as client:
        resp = client.post(
            "/v1/hf-import/preview",
            json={"url": "https://huggingface.co/distilbert/distilbert-base-uncased", "asset_type": "model_card"},
            headers=tapis_headers,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Distilbert Base Uncased"
    assert body["is_gated"] is False
    # datasheet-only keys must not leak into a model_card response
    assert "title" not in body
    assert "download_url" not in body


def test_hf_import_datasheet_success(hf_import_app, monkeypatch, tapis_headers):
    async def fake_import(url, asset_type, request_tapis_token=None):
        assert asset_type == "datasheet"
        return {
            "title": "Squad",
            "creator": "rajpurkar",
            "download_url": "https://huggingface.co/datasets/rajpurkar/squad",
            "description": "SQuAD is a reading comprehension dataset.",
            "subjects": "question-answering, en",
            "license": "cc-by-4.0",
        }

    monkeypatch.setattr("rest_server.routes.hf_import.import_from_huggingface", fake_import)

    with TestClient(hf_import_app) as client:
        resp = client.post(
            "/v1/hf-import/preview",
            json={"url": "https://huggingface.co/datasets/rajpurkar/squad", "asset_type": "datasheet"},
            headers=tapis_headers,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Squad"
    assert body["download_url"] == "https://huggingface.co/datasets/rajpurkar/squad"
    assert "name" not in body  # model_card-only key must not leak


def test_hf_import_repo_not_found(hf_import_app, monkeypatch, tapis_headers):
    from rest_server.features.hf_import.service import HuggingFaceRepoNotFoundError

    async def fake_import(url, asset_type, request_tapis_token=None):
        raise HuggingFaceRepoNotFoundError("repo not found on Hugging Face")

    monkeypatch.setattr("rest_server.routes.hf_import.import_from_huggingface", fake_import)

    with TestClient(hf_import_app) as client:
        resp = client.post(
            "/v1/hf-import/preview",
            json={"url": "https://huggingface.co/nobody/does-not-exist", "asset_type": "model_card"},
            headers=tapis_headers,
        )

    assert resp.status_code == 404


def test_hf_import_gated_repo_fails_clearly(hf_import_app, monkeypatch, tapis_headers):
    from rest_server.features.hf_import.service import HuggingFaceGatedOrPrivateError

    async def fake_import(url, asset_type, request_tapis_token=None):
        raise HuggingFaceGatedOrPrivateError("This Hugging Face repo is gated.")

    monkeypatch.setattr("rest_server.routes.hf_import.import_from_huggingface", fake_import)

    with TestClient(hf_import_app) as client:
        resp = client.post(
            "/v1/hf-import/preview",
            json={"url": "https://huggingface.co/meta-llama/Llama-3.1-8B", "asset_type": "model_card"},
            headers=tapis_headers,
        )

    assert resp.status_code == 403
    assert "gated" in resp.json()["detail"].lower()


def test_hf_import_upstream_error(hf_import_app, monkeypatch, tapis_headers):
    from rest_server.features.hf_import.service import HuggingFaceUpstreamError

    async def fake_import(url, asset_type, request_tapis_token=None):
        raise HuggingFaceUpstreamError("Hugging Face metadata lookup failed: timed out")

    monkeypatch.setattr("rest_server.routes.hf_import.import_from_huggingface", fake_import)

    with TestClient(hf_import_app) as client:
        resp = client.post(
            "/v1/hf-import/preview",
            json={"url": "https://huggingface.co/org/repo", "asset_type": "model_card"},
            headers=tapis_headers,
        )

    assert resp.status_code == 502


def test_hf_import_malformed_url_returns_422(hf_import_app, tapis_headers):
    # No monkeypatch needed: URL parsing is pure/local, runs before any
    # network call, so the real service function raises this itself.
    with TestClient(hf_import_app) as client:
        resp = client.post(
            "/v1/hf-import/preview",
            json={"url": "https://github.com/some/repo", "asset_type": "model_card"},
            headers=tapis_headers,
        )
    assert resp.status_code == 422


def test_hf_import_asset_type_mismatch_returns_422(hf_import_app, tapis_headers):
    # A real dataset URL submitted while importing a model_card.
    with TestClient(hf_import_app) as client:
        resp = client.post(
            "/v1/hf-import/preview",
            json={"url": "https://huggingface.co/datasets/rajpurkar/squad", "asset_type": "model_card"},
            headers=tapis_headers,
        )
    assert resp.status_code == 422
    assert "dataset" in resp.json()["detail"].lower()


def test_hf_import_requires_auth(hf_import_app):
    # No X-Tapis-Token and no configured asset-ingest keys in this test env:
    # require_asset_ingest_principal reports 503 (auth not configured) rather
    # than 401 in that specific combination — this is existing behavior of
    # the shared dependency, not something new to hf_import. Either way, the
    # request must not succeed without credentials.
    with TestClient(hf_import_app) as client:
        resp = client.post(
            "/v1/hf-import/preview",
            json={"url": "https://huggingface.co/org/repo", "asset_type": "model_card"},
        )
    assert resp.status_code in (401, 503)


def test_hf_import_route_absent_when_flag_disabled(monkeypatch, tapis_headers):
    monkeypatch.setenv("ENABLE_HF_IMPORT", "false")
    importlib.reload(main_module)
    main_module.app.router.lifespan_context = _no_op_lifespan

    with TestClient(main_module.app) as client:
        resp = client.post(
            "/v1/hf-import/preview",
            json={"url": "https://huggingface.co/org/repo", "asset_type": "model_card"},
            headers=tapis_headers,
        )

    assert resp.status_code == 404  # route doesn't exist at all
