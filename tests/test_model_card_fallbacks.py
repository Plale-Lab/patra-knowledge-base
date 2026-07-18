from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from rest_server.database import get_pool
from rest_server.main import app
from tests.conftest import uuid_for_id

_TEST_MC_UUID = uuid_for_id(1)


class MissingModelConn:
    async def fetchrow(self, query: str, *args):
        if "FROM model_cards mc" in query and "WHERE mc.uuid = $1" in query:
            return {
                "id": 1,
                "uuid": _TEST_MC_UUID,
                "name": "Segment Anything Model 3 (SAM 3)",
                "version": "SAM3-ViT-L",
                "short_description": "Foundation model for promptable concept segmentation.",
                "full_description": "Synthetic test row for model fallback behavior.",
                "keywords": "segmentation",
                "author": "Meta AI",
                "citation": None,
                "input_data": "https://huggingface.co/datasets/segment-anything/sa-1b",
                "input_type": "images, videos",
                "output_data": "https://huggingface.co/meta-sam/sam3",
                "foundational_model": "SAM3",
                "category": "segmentation",
                "documentation": None,
                "training_datasheet_uuid": None,
                "is_private": False,
                "is_gated": False,
            }
        if "FROM models" in query and "WHERE model_card_id = $1" in query:
            return None
        return None

    async def fetch(self, query: str, *args):
        if "FROM experiments e" in query:
            return []
        return []

    async def fetchval(self, query: str, *args):
        if query.strip() == "SELECT 1":
            return 1
        return None


class MissingModelPool:
    def __init__(self):
        self.conn = MissingModelConn()

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


def test_model_detail_falls_back_to_external_metadata(monkeypatch):
    async def fake_external_metadata(_row):
        return {
            "owner": "meta-sam",
            "location": "https://huggingface.co/meta-sam/sam3",
            "license": "apache-2.0",
            "framework": "Transformers",
            "model_type": "mask-generation",
            "is_gated": True,
        }

    @asynccontextmanager
    async def _no_op_lifespan(_):
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _no_op_lifespan
    app.dependency_overrides[get_pool] = lambda: MissingModelPool()
    monkeypatch.setattr(
        "rest_server.routes.model_cards._fetch_external_model_metadata",
        fake_external_metadata,
    )

    with TestClient(app) as client:
        detail = client.get(f"/modelcard/{_TEST_MC_UUID}")
        download = client.get(f"/modelcard/{_TEST_MC_UUID}/download_url")
        deployments = client.get(f"/modelcard/{_TEST_MC_UUID}/deployments")

    app.dependency_overrides.clear()
    app.router.lifespan_context = original_lifespan

    assert detail.status_code == 200
    detail_json = detail.json()
    assert detail_json["is_gated"] is True
    assert detail_json["ai_model"]["framework"] == "Transformers"
    assert detail_json["ai_model"]["license"] == "apache-2.0"
    assert detail_json["ai_model"]["owner"] == "meta-sam"
    assert detail_json["ai_model"]["location"] == "https://huggingface.co/meta-sam/sam3"

    assert download.status_code == 200
    assert download.json()["download_url"] == "https://huggingface.co/meta-sam/sam3"

    assert deployments.status_code == 200
    assert deployments.json() == []
