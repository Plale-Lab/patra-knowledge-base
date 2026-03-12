"""Privacy gate tests: X-Tapis-Token controls visibility of private records.

Scenario 1 – No token:  client sees only 5 public model cards / datasheets.
Scenario 2 – Valid X-Tapis-Token: client sees all 10 model cards / datasheets.
IDs are integers (1–10) per db/schema.dbml.
"""

from rest_server.errors import ASSET_NOT_AVAILABLE_DETAIL
from tests.conftest import (
    ALL_MC_IDS,
    PRIVATE_DS_IDENTIFIERS,
    PRIVATE_MC_IDS,
    PUBLIC_DS_IDENTIFIERS,
    PUBLIC_MC_IDS,
)


# ─── Scenario 1: Without token ──────────────────────────────────────────────


class TestWithoutToken:
    """Unauthenticated requests should only receive public records."""

    def test_list_modelcards_returns_only_public(self, client):
        resp = client.get("/modelcards")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 5
        returned_ids = {mc["mc_id"] for mc in data}
        assert returned_ids == set(PUBLIC_MC_IDS)

    def test_list_datasheets_returns_only_public(self, client):
        resp = client.get("/datasheets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 5
        returned_ids = {ds["identifier"] for ds in data}
        assert returned_ids == set(PUBLIC_DS_IDENTIFIERS)

    def test_private_modelcard_detail_returns_404(self, client):
        resp = client.get(f"/modelcard/{PRIVATE_MC_IDS[0]}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == ASSET_NOT_AVAILABLE_DETAIL

    def test_public_modelcard_detail_returns_200(self, client):
        resp = client.get(f"/modelcard/{PUBLIC_MC_IDS[0]}")
        assert resp.status_code == 200
        assert resp.json()["external_id"] == PUBLIC_MC_IDS[0]

    def test_private_modelcard_download_url_returns_404(self, client):
        resp = client.get(f"/modelcard/{PRIVATE_MC_IDS[0]}/download_url")
        assert resp.status_code == 404
        assert resp.json()["detail"] == ASSET_NOT_AVAILABLE_DETAIL

    def test_public_modelcard_download_url_returns_200(self, client):
        resp = client.get(f"/modelcard/{PUBLIC_MC_IDS[0]}/download_url")
        assert resp.status_code == 200
        assert resp.json()["download_url"] == f"https://example.com/models/{PUBLIC_MC_IDS[0]}"

    def test_private_modelcard_deployments_returns_404(self, client):
        resp = client.get(f"/modelcard/{PRIVATE_MC_IDS[0]}/deployments")
        assert resp.status_code == 404
        assert resp.json()["detail"] == ASSET_NOT_AVAILABLE_DETAIL

    def test_public_modelcard_deployments_returns_200(self, client):
        resp = client.get(f"/modelcard/{PUBLIC_MC_IDS[0]}/deployments")
        assert resp.status_code == 200
        assert resp.json()[0]["experiment_id"] == PUBLIC_MC_IDS[0] * 100 + 1

    def test_private_datasheet_detail_returns_404(self, client):
        resp = client.get(f"/datasheet/{PRIVATE_DS_IDENTIFIERS[0]}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == ASSET_NOT_AVAILABLE_DETAIL

    def test_public_datasheet_detail_returns_200(self, client):
        resp = client.get(f"/datasheet/{PUBLIC_DS_IDENTIFIERS[0]}")
        assert resp.status_code == 200
        assert resp.json()["identifier"] == PUBLIC_DS_IDENTIFIERS[0]


# ─── Scenario 2: With X-Tapis-Token ─────────────────────────────────────────


class TestWithTapisToken:
    """Authenticated requests should receive all records (public + private)."""

    def test_list_modelcards_returns_all(self, client, tapis_headers):
        resp = client.get("/modelcards", headers=tapis_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 10
        returned_ids = {mc["mc_id"] for mc in data}
        assert returned_ids == set(ALL_MC_IDS)

    def test_list_datasheets_returns_all(self, client, tapis_headers):
        resp = client.get("/datasheets", headers=tapis_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 10
        returned_ids = {ds["identifier"] for ds in data}
        assert returned_ids == set(PUBLIC_DS_IDENTIFIERS + PRIVATE_DS_IDENTIFIERS)

    def test_private_modelcard_detail_returns_200(self, client, tapis_headers):
        resp = client.get(
            f"/modelcard/{PRIVATE_MC_IDS[0]}",
            headers=tapis_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["external_id"] == PRIVATE_MC_IDS[0]

    def test_private_modelcard_download_url_returns_200(self, client, tapis_headers):
        resp = client.get(
            f"/modelcard/{PRIVATE_MC_IDS[0]}/download_url",
            headers=tapis_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["download_url"] == f"https://example.com/models/{PRIVATE_MC_IDS[0]}"

    def test_private_modelcard_deployments_returns_200(self, client, tapis_headers):
        resp = client.get(
            f"/modelcard/{PRIVATE_MC_IDS[0]}/deployments",
            headers=tapis_headers,
        )
        assert resp.status_code == 200
        assert resp.json()[0]["experiment_id"] == PRIVATE_MC_IDS[0] * 100 + 1

    def test_private_datasheet_detail_returns_200(self, client, tapis_headers):
        resp = client.get(
            f"/datasheet/{PRIVATE_DS_IDENTIFIERS[0]}",
            headers=tapis_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["identifier"] == PRIVATE_DS_IDENTIFIERS[0]


# ─── Edge cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Empty or missing header should behave like no token."""

    def test_empty_tapis_token_returns_only_public(self, client):
        resp = client.get("/modelcards", headers={"X-Tapis-Token": ""})
        assert resp.status_code == 200
        assert len(resp.json()) == 5

    def test_nonexistent_modelcard_returns_404(self, client, tapis_headers):
        resp = client.get("/modelcard/99999", headers=tapis_headers)
        assert resp.status_code == 404
        assert resp.json()["detail"] == ASSET_NOT_AVAILABLE_DETAIL

    def test_nonexistent_modelcard_download_url_returns_404(self, client, tapis_headers):
        resp = client.get("/modelcard/99999/download_url", headers=tapis_headers)
        assert resp.status_code == 404
        assert resp.json()["detail"] == ASSET_NOT_AVAILABLE_DETAIL

    def test_nonexistent_modelcard_deployments_returns_404(self, client, tapis_headers):
        resp = client.get("/modelcard/99999/deployments", headers=tapis_headers)
        assert resp.status_code == 404
        assert resp.json()["detail"] == ASSET_NOT_AVAILABLE_DETAIL

    def test_invalid_modelcard_id_returns_422(self, client, tapis_headers):
        """Non-integer path (e.g. 'not-an-id') yields 422 Unprocessable Entity."""
        resp = client.get("/modelcard/not-an-id", headers=tapis_headers)
        assert resp.status_code == 422

    def test_healthz_returns_200(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_readyz_returns_200(self, client):
        resp = client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
