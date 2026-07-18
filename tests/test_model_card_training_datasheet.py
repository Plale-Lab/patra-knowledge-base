"""Model card <-> datasheet linkage: training_datasheet_uuid.

Covers the field end to end against the shared mocked-pool `client` fixture:
GET reflects it, PUT resolves/validates it, and an unknown datasheet uuid
is rejected rather than silently stored.
"""

from tests.conftest import PUBLIC_DS_UUIDS, PUBLIC_MC_UUIDS


def test_get_model_card_training_datasheet_uuid_defaults_to_none(client):
    resp = client.get(f"/modelcard/{PUBLIC_MC_UUIDS[0]}")
    assert resp.status_code == 200
    assert resp.json()["training_datasheet_uuid"] is None


def test_put_model_card_sets_training_datasheet_uuid(client, tapis_headers):
    resp = client.put(
        f"/modelcard/{PUBLIC_MC_UUIDS[0]}",
        headers=tapis_headers,
        json={"training_datasheet_uuid": PUBLIC_DS_UUIDS[0]},
    )
    assert resp.status_code == 200


def test_put_model_card_rejects_unknown_training_datasheet_uuid(client, tapis_headers):
    resp = client.put(
        f"/modelcard/{PUBLIC_MC_UUIDS[0]}",
        headers=tapis_headers,
        json={"training_datasheet_uuid": "00000000-0000-4000-8000-999999999999"},
    )
    assert resp.status_code == 422


def test_put_model_card_requires_authentication(client):
    resp = client.put(
        f"/modelcard/{PUBLIC_MC_UUIDS[0]}",
        json={"short_description": "no auth"},
    )
    assert resp.status_code == 401
