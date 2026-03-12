from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from rest_server.database import get_pool
from rest_server.deps import get_asset_ingest_keys
from rest_server.main import app


class MockAssetConn:
    def __init__(self):
        self.model_card_duplicate_queue: list[int] = []
        self.datasheet_duplicate_queue: list[int] = []
        self.inserted_model_card_ids: list[int] = []
        self.inserted_datasheet_ids: list[int] = []
        self.model_card_id_seq = 100
        self.datasheet_id_seq = 200
        self.executed: list[tuple[str, tuple]] = []
        self.executemany_calls: list[tuple[str, list[tuple]]] = []

    async def fetchrow(self, query: str, *args):
        if "FROM model_cards" in query:
            if self.model_card_duplicate_queue:
                return {"id": self.model_card_duplicate_queue.pop(0)}
            return None
        if "FROM datasheets d" in query:
            if self.datasheet_duplicate_queue:
                return {"identifier": self.datasheet_duplicate_queue.pop(0)}
            return None
        return None

    async def fetchval(self, query: str, *args):
        if "SELECT id" in query and "FROM publishers" in query:
            return None
        if "INSERT INTO publishers" in query:
            return 10
        if "INSERT INTO model_cards" in query:
            self.model_card_id_seq += 1
            self.inserted_model_card_ids.append(self.model_card_id_seq)
            return self.model_card_id_seq
        if "INSERT INTO datasheets" in query:
            self.datasheet_id_seq += 1
            self.inserted_datasheet_ids.append(self.datasheet_id_seq)
            return self.datasheet_id_seq
        return None

    async def execute(self, query: str, *args):
        self.executed.append((query, args))

    async def executemany(self, query: str, rows):
        self.executemany_calls.append((query, list(rows)))

    @asynccontextmanager
    async def transaction(self):
        yield self


class MockAssetPool:
    def __init__(self, conn: MockAssetConn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


@pytest.fixture()
def asset_client(monkeypatch):
    conn = MockAssetConn()
    pool = MockAssetPool(conn)

    monkeypatch.setenv("PATRA_ASSET_INGEST_KEYS_JSON", '{"org-a":"super-secret"}')
    get_asset_ingest_keys.cache_clear()

    @asynccontextmanager
    async def _no_op_lifespan(_):
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _no_op_lifespan
    app.dependency_overrides[get_pool] = lambda: pool

    with TestClient(app) as client:
        yield client, conn

    app.dependency_overrides.clear()
    app.router.lifespan_context = original_lifespan
    get_asset_ingest_keys.cache_clear()


def _asset_headers(key: str = "super-secret") -> dict[str, str]:
    return {
        "X-Asset-Org": "org-a",
        "X-Asset-Api-Key": key,
    }


def test_asset_ingest_requires_configuration(monkeypatch):
    monkeypatch.delenv("PATRA_ASSET_INGEST_KEYS_JSON", raising=False)
    get_asset_ingest_keys.cache_clear()

    @asynccontextmanager
    async def _no_op_lifespan(_):
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _no_op_lifespan
    app.dependency_overrides[get_pool] = lambda: MockAssetPool(MockAssetConn())

    with TestClient(app) as client:
        response = client.post("/v1/assets/model-cards", json={"name": "x"})

    app.dependency_overrides.clear()
    app.router.lifespan_context = original_lifespan
    get_asset_ingest_keys.cache_clear()

    assert response.status_code == 503


def test_create_model_card_asset_success(asset_client):
    client, conn = asset_client
    response = client.post(
        "/v1/assets/model-cards",
        headers=_asset_headers(),
        json={
            "name": "External Model",
            "version": "1.0",
            "short_description": "Injected model card",
            "author": "Org A",
            "ai_model": {
                "name": "External Model Binary",
                "version": "1.0",
                "framework": "PyTorch",
                "model_type": "cnn",
                "model_metrics": {"top_1_accuracy": 0.92},
            },
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["asset_type"] == "model_card"
    assert data["organization"] == "org-a"
    assert data["created"] is True
    assert conn.inserted_model_card_ids


def test_create_model_card_asset_rejects_invalid_credentials(asset_client):
    client, _ = asset_client
    response = client.post(
        "/v1/assets/model-cards",
        headers=_asset_headers("wrong-secret"),
        json={"name": "External Model"},
    )
    assert response.status_code == 401


def test_create_model_card_asset_rejects_unsafe_metric_key(asset_client):
    client, _ = asset_client
    response = client.post(
        "/v1/assets/model-cards",
        headers=_asset_headers(),
        json={
            "name": "External Model",
            "ai_model": {
                "name": "Binary",
                "model_metrics": {"bad-key` SET hacked = true": 1},
            },
        },
    )
    assert response.status_code == 422


def test_create_datasheet_asset_duplicate_returns_409(asset_client):
    client, conn = asset_client
    conn.datasheet_duplicate_queue = [42]
    response = client.post(
        "/v1/assets/datasheets",
        headers=_asset_headers(),
        json={
            "publication_year": 2025,
            "version": "1.0",
            "titles": [{"title": "Partner Dataset"}],
            "creators": [{"creator_name": "Org A"}],
        },
    )
    assert response.status_code == 409
    assert "42" in response.json()["detail"]


def test_bulk_model_card_ingest_returns_mixed_results(asset_client):
    client, conn = asset_client
    conn.model_card_duplicate_queue = [7]
    response = client.post(
        "/v1/assets/model-cards/bulk",
        headers=_asset_headers(),
        json={
            "assets": [
                {"name": "Duplicate Model", "version": "1.0"},
                {"name": "Fresh Model", "version": "2.0"},
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["duplicates"] == 1
    assert data["created"] == 1
    assert data["failed"] == 0
