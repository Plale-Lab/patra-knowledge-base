"""DELETE /datasheet/{uuid}: admin-only, cascades to child rows via FK."""

from tests.conftest import PUBLIC_DS_UUIDS

ADMIN_HEADERS = {"X-Tapis-Token": "fake-tapis-access-token-for-testing", "X-Patra-Username": "williamq96"}


def test_delete_datasheet_rejects_unauthenticated(client):
    resp = client.delete(f"/datasheet/{PUBLIC_DS_UUIDS[0]}")
    assert resp.status_code == 403


def test_delete_datasheet_rejects_non_admin(client, tapis_headers):
    resp = client.delete(f"/datasheet/{PUBLIC_DS_UUIDS[0]}", headers=tapis_headers)
    assert resp.status_code == 403


def test_delete_datasheet_as_admin_succeeds(client):
    resp = client.delete(f"/datasheet/{PUBLIC_DS_UUIDS[0]}", headers=ADMIN_HEADERS)
    assert resp.status_code == 204


def test_delete_datasheet_unknown_uuid_returns_404(client):
    resp = client.delete(
        "/datasheet/00000000-0000-4000-8000-999999999999", headers=ADMIN_HEADERS
    )
    assert resp.status_code == 404
