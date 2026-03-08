"""Shared fixtures for API tests.

Provides a mock asyncpg pool that returns 10 model cards (5 public,
5 private) and 10 datasheets (5 public, 5 private), plus helpers
for the X-Tapis-Token header used by the patra-toolkit.
IDs are integers (1–10) matching db/schema.dbml.
"""

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# ── Fake row data (integer IDs per schema) ─────────────────────────────────────

PUBLIC_MC_IDS = [1, 2, 3, 4, 5]
PRIVATE_MC_IDS = [6, 7, 8, 9, 10]
ALL_MC_IDS = list(range(1, 11))


def _mc_row(mc_id: int, private: bool) -> dict:
    return {
        "id": mc_id,
        "name": f"Model {mc_id}",
        "category": "classification",
        "author": "tester",
        "version": "1.0",
        "short_description": f"Description for {mc_id}",
        "is_private": private,
    }


def _mc_detail_row(mc_id: int, private: bool) -> dict:
    base = _mc_row(mc_id, private)
    base.update({
        "full_description": "Full desc",
        "keywords": "test",
        "author": "tester",
        "citation": "",
        "input_data": "images",
        "input_type": "images",
        "output_data": "labels",
        "foundational_model": "TestModel",
        "category": "classification",
        "documentation": "",
        "model_id": mc_id,
        "model_name": "TestModel",
        "model_version": "1.0",
        "model_description": "A test model",
        "owner": "tester",
        "location": "",
        "license": "MIT",
        "framework": "PyTorch",
        "model_type": "cnn",
        "test_accuracy": Decimal("0.95"),
    })
    return base


ALL_MC_ROWS = sorted(
    [_mc_row(i, False) for i in PUBLIC_MC_IDS]
    + [_mc_row(i, True) for i in PRIVATE_MC_IDS],
    key=lambda r: r["id"],
)
PUBLIC_MC_ROWS = sorted(
    [_mc_row(i, False) for i in PUBLIC_MC_IDS],
    key=lambda r: r["id"],
)

PUBLIC_DS_IDENTIFIERS = list(range(1, 6))
PRIVATE_DS_IDENTIFIERS = list(range(6, 11))


def _ds_row(ident: int, private: bool) -> dict:
    return {
        "identifier": ident,
        "publication_year": 2024,
        "resource_type": "images",
        "resource_type_general": "Dataset",
        "size": "1 GB",
        "format": "jpeg",
        "version": "1.0",
        "is_private": private,
        "model_card_id": 1,
        "dataset_schema_id": None,
        # First title / creator / subject used in summary endpoint
        "summary_title": f"Dataset {ident}",
        "summary_creator": "tester",
        "summary_category": "test",
    }


ALL_DS_ROWS = (
    [_ds_row(i, False) for i in PUBLIC_DS_IDENTIFIERS]
    + [_ds_row(i, True) for i in PRIVATE_DS_IDENTIFIERS]
)
PUBLIC_DS_ROWS = [_ds_row(i, False) for i in PUBLIC_DS_IDENTIFIERS]


def _ds_detail_row(ident: int, private: bool) -> dict:
    base = _ds_row(ident, private)
    base.update({
        "updated_at": None,
        # Publisher
        "publisher_name": "Test Publisher",
        "publisher_identifier": None,
        "publisher_identifier_scheme": None,
        "publisher_scheme_uri": None,
        "publisher_lang": None,
        # Creators
        "creators": [
            {
                "creator_name": "tester",
                "name_type": "Personal",
                "lang": "en",
                "given_name": "Test",
                "family_name": f"User{ident}",
                "name_identifier": None,
                "name_identifier_scheme": None,
                "name_id_scheme_uri": None,
                "affiliation": "Test Org",
                "affiliation_identifier": None,
                "affiliation_identifier_scheme": None,
                "affiliation_scheme_uri": None,
            }
        ],
        # Titles
        "titles": [
            {
                "title": f"Dataset {ident}",
                "title_type": None,
                "lang": "en",
            }
        ],
        # Subjects
        "subjects": [
            {
                "subject": "test",
                "subject_scheme": None,
                "scheme_uri": None,
                "value_uri": None,
                "classification_code": None,
                "lang": "en",
            }
        ],
        # Rights
        "rights_list": [
            {
                "rights": "public",
                "rights_uri": None,
                "rights_identifier": None,
                "rights_identifier_scheme": None,
                "scheme_uri": None,
                "lang": "en",
            }
        ],
        # Descriptions
        "descriptions": [
            {
                "description": "Test dataset",
                "description_type": "Abstract",
                "lang": "en",
            }
        ],
        # Geo locations
        "geo_locations": [
            {
                "geo_location_place": "global",
                "point_longitude": None,
                "point_latitude": None,
                "box_west": None,
                "box_east": None,
                "box_south": None,
                "box_north": None,
                "polygon": None,
            }
        ],
        # Empty lists for other nested fields
        "contributors": [],
        "dates": [],
        "alternate_identifiers": [],
        "related_identifiers": [],
        "funding_references": [],
    })
    return base


# ── Mock pool ────────────────────────────────────────────────────────────────
def _make_mock_pool():
    pool = MagicMock()
    conn = AsyncMock()

    async def _fetch(query: str, *args):
        if "model_cards" in query:
            rows = PUBLIC_MC_ROWS if "is_private = false" in query else ALL_MC_ROWS
            limit = args[0] if args else 50
            offset = args[1] if len(args) > 1 else 0
            return rows[offset : offset + limit]
        if "FROM datasheets d" in query:
            base_rows = PUBLIC_DS_ROWS if "d.is_private = false" in query else ALL_DS_ROWS
            limit = args[0] if args else 50
            offset = args[1] if len(args) > 1 else 0
            sliced = base_rows[offset : offset + limit]
            return [
                {
                    "identifier": r["identifier"],
                    "title": r["summary_title"],
                    "creator": r["summary_creator"],
                    "category": r["summary_category"],
                }
                for r in sliced
            ]
        if "FROM datasheet_creators" in query and args:
            ident = args[0]
            private = ident in PRIVATE_DS_IDENTIFIERS
            return _ds_detail_row(ident, private)["creators"]
        if "FROM datasheet_titles" in query and args:
            ident = args[0]
            private = ident in PRIVATE_DS_IDENTIFIERS
            return _ds_detail_row(ident, private)["titles"]
        if "FROM datasheet_subjects" in query and args:
            ident = args[0]
            private = ident in PRIVATE_DS_IDENTIFIERS
            return _ds_detail_row(ident, private)["subjects"]
        if "FROM datasheet_contributors" in query and args:
            ident = args[0]
            private = ident in PRIVATE_DS_IDENTIFIERS
            return _ds_detail_row(ident, private)["contributors"]
        if "FROM datasheet_dates" in query and args:
            ident = args[0]
            private = ident in PRIVATE_DS_IDENTIFIERS
            return _ds_detail_row(ident, private)["dates"]
        if "FROM datasheet_alternate_identifiers" in query and args:
            ident = args[0]
            private = ident in PRIVATE_DS_IDENTIFIERS
            return _ds_detail_row(ident, private)["alternate_identifiers"]
        if "FROM datasheet_related_identifiers" in query and args:
            ident = args[0]
            private = ident in PRIVATE_DS_IDENTIFIERS
            return _ds_detail_row(ident, private)["related_identifiers"]
        if "FROM datasheet_rights" in query and args:
            ident = args[0]
            private = ident in PRIVATE_DS_IDENTIFIERS
            return _ds_detail_row(ident, private)["rights_list"]
        if "FROM datasheet_descriptions" in query and args:
            ident = args[0]
            private = ident in PRIVATE_DS_IDENTIFIERS
            return _ds_detail_row(ident, private)["descriptions"]
        if "FROM datasheet_geo_locations" in query and args:
            ident = args[0]
            private = ident in PRIVATE_DS_IDENTIFIERS
            return _ds_detail_row(ident, private)["geo_locations"]
        if "FROM datasheet_funding_references" in query and args:
            ident = args[0]
            private = ident in PRIVATE_DS_IDENTIFIERS
            return _ds_detail_row(ident, private)["funding_references"]
        return []

    async def _fetchrow(query: str, *args):
        if "model_cards" in query and args:
            raw = args[0]
            mc_id = int(raw) if isinstance(raw, str) and raw.isdigit() else raw
            if isinstance(mc_id, int) and mc_id in ALL_MC_IDS:
                return _mc_detail_row(mc_id, mc_id in PRIVATE_MC_IDS)
            return None
        if "FROM datasheets d" in query and args:
            ident = args[0]
            if ident in PUBLIC_DS_IDENTIFIERS or ident in PRIVATE_DS_IDENTIFIERS:
                private = ident in PRIVATE_DS_IDENTIFIERS
                return _ds_detail_row(ident, private)
            return None
        return None

    conn.fetch = _fetch
    conn.fetchrow = _fetchrow

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    return pool


# ── Fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture()
def client():
    """TestClient with a mocked DB pool (no real database needed)."""
    from api_server.database import get_pool
    from api_server.main import app

    mock_pool = _make_mock_pool()

    @asynccontextmanager
    async def _no_op_lifespan(a):
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _no_op_lifespan
    app.dependency_overrides[get_pool] = lambda: mock_pool

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    app.router.lifespan_context = original_lifespan


@pytest.fixture()
def tapis_headers() -> dict:
    """Headers with a valid X-Tapis-Token (any non-empty value suffices)."""
    return {"X-Tapis-Token": "fake-tapis-access-token-for-testing"}
