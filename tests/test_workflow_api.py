import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest

from rest_server.database import get_pool
from rest_server.deps import get_admin_users
from rest_server.main import app


class MockWorkflowConn:
    def __init__(self):
        self.ticket_id_seq = 0
        self.submission_id_seq = 0
        self.asset_id_seq = 500
        self.tickets: list[dict] = []
        self.submissions: list[dict] = []

    async def fetch(self, query: str, *args):
        if "FROM support_tickets" in query:
            return self._filter_rows(self.tickets, query, *args)
        if "FROM submission_queue" in query:
            return self._filter_rows(self.submissions, query, *args)
        return []

    async def fetchrow(self, query: str, *args):
        if "INSERT INTO support_tickets" in query:
            self.ticket_id_seq += 1
            now = datetime.now(timezone.utc)
            row = {
                "id": self.ticket_id_seq,
                "subject": args[0],
                "category": args[1],
                "priority": args[2],
                "status": "open",
                "description": args[3],
                "submitted_by": args[4],
                "submitted_at": now,
                "admin_response": None,
                "updated_at": now,
                "reviewed_by": None,
                "reviewed_at": None,
            }
            self.tickets.append(row)
            return row
        if "UPDATE support_tickets" in query:
            ticket = self._find_by_id(self.tickets, args[0])
            if not ticket:
                return None
            ticket.update({
                "status": args[1],
                "admin_response": args[2],
                "reviewed_by": args[3],
                "reviewed_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            })
            return ticket
        if "INSERT INTO submission_queue" in query:
            self.submission_id_seq += 1
            now = datetime.now(timezone.utc)
            row = {
                "id": self.submission_id_seq,
                "submission_type": args[0],
                "status": "pending",
                "submitted_by": args[1],
                "submitted_at": now,
                "title": args[2],
                "data": args[3],
                "asset_payload": args[4],
                "admin_notes": None,
                "reviewed_by": None,
                "reviewed_at": None,
                "created_asset_id": None,
                "created_asset_type": None,
                "error_message": None,
            }
            self.submissions.append(row)
            return row
        if "FROM submission_queue" in query and "WHERE id = $1" in query:
            return self._find_by_id(self.submissions, args[0])
        if "UPDATE submission_queue" in query:
            submission = self._find_by_id(self.submissions, args[0])
            if not submission:
                return None
            submission.update({
                "status": args[1],
                "admin_notes": args[2],
                "reviewed_by": args[3],
                "reviewed_at": datetime.now(timezone.utc),
                "created_asset_id": args[4],
                "created_asset_type": args[5],
                "error_message": args[6],
            })
            return submission
        if "FROM model_cards" in query:
            return None
        return None

    async def fetchval(self, query: str, *args):
        if "INSERT INTO model_cards" in query or "INSERT INTO datasheets" in query:
            self.asset_id_seq += 1
            return self.asset_id_seq
        if "SELECT id" in query and "FROM publishers" in query:
            return None
        if "INSERT INTO publishers" in query:
            return 1
        return None

    async def execute(self, query: str, *args):
        return None

    async def executemany(self, query: str, rows):
        return None

    @asynccontextmanager
    async def transaction(self):
        yield self

    @staticmethod
    def _find_by_id(items: list[dict], item_id: int):
        for item in items:
            if int(item["id"]) == int(item_id):
                return item
        return None

    @staticmethod
    def _filter_rows(items: list[dict], query: str, *args):
        params = list(args)
        limit = params[-2]
        offset = params[-1]
        filters = params[:-2]
        rows = list(items)

        if "status =" in query and filters:
            rows = [item for item in rows if item["status"] == filters[0]]
            filters = filters[1:]

        if "submitted_by =" in query and filters:
            rows = [item for item in rows if item["submitted_by"] == filters[0]]

        rows.sort(key=lambda item: (item["submitted_at"], item["id"]), reverse=True)
        return rows[offset : offset + limit]


class MockWorkflowPool:
    def __init__(self, conn: MockWorkflowConn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


@pytest.fixture()
def workflow_client(monkeypatch):
    conn = MockWorkflowConn()
    pool = MockWorkflowPool(conn)
    monkeypatch.delenv("PATRA_ADMIN_USERS", raising=False)
    get_admin_users.cache_clear()

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
    get_admin_users.cache_clear()


def test_create_and_review_submission_queue_item(workflow_client):
    client, conn = workflow_client

    create_response = client.post(
        "/submissions",
        headers={
            "X-Tapis-Token": "token",
            "X-Patra-Username": "alice",
        },
        json={
            "type": "model_card",
            "submitted_by": "ignored",
            "title": "Queued Model",
            "data": {
                "form_name": "Queued Model",
                "intake_method": "manual",
            },
            "asset_payload": {
                "name": "Queued Model",
                "version": "1.0",
                "short_description": "Needs review",
                "author": "alice",
            },
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["status"] == "pending"
    assert created["submitted_by"] == "alice"

    list_response = client.get(
        "/submissions",
        headers={
            "X-Tapis-Token": "token",
            "X-Patra-Username": "alice",
        },
    )
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    review_response = client.put(
        f"/submissions/{created['id']}",
        headers={
            "X-Tapis-Token": "admin-token",
            "X-Patra-Username": "williamq96",
        },
        json={
            "status": "approved",
            "admin_notes": "Looks good",
        },
    )

    assert review_response.status_code == 200
    reviewed = review_response.json()
    assert reviewed["status"] == "approved"
    assert reviewed["reviewed_by"] == "williamq96"
    assert reviewed["created_asset_id"] is not None
    assert conn.asset_id_seq > 500


def test_bulk_submission_queue_creation(workflow_client):
    client, _ = workflow_client
    response = client.post(
        "/submissions/bulk",
        headers={
            "X-Tapis-Token": "token",
            "X-Patra-Username": "alice",
        },
        json={
            "type": "datasheet",
            "submitted_by": "alice",
            "items": [
                {
                    "title": "Dataset A",
                    "data": {
                        "asset_url": "https://example.com/dataset-a",
                        "intake_method": "asset_link",
                    },
                    "asset_payload": {
                        "titles": [{"title": "Dataset A"}],
                        "creators": [{"creator_name": "alice"}],
                    },
                },
                {
                    "title": "Dataset B",
                    "data": {
                        "asset_url": "https://example.com/dataset-b",
                        "intake_method": "asset_link",
                    },
                    "asset_payload": {
                        "titles": [{"title": "Dataset B"}],
                        "creators": [{"creator_name": "alice"}],
                    },
                },
            ],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["created"] == 2
    assert data["failed"] == 0
    assert all(item["submission_id"] for item in data["results"])


def test_ticket_create_and_admin_update(workflow_client):
    client, _ = workflow_client
    create_response = client.post(
        "/tickets",
        headers={
            "X-Tapis-Token": "token",
            "X-Patra-Username": "alice",
        },
        json={
            "submitted_by": "ignored",
            "subject": "Need access",
            "category": "Access Request",
            "priority": "High",
            "description": "Please review my account.",
        },
    )

    assert create_response.status_code == 201
    ticket = create_response.json()
    assert ticket["status"] == "open"
    assert ticket["submitted_by"] == "alice"

    update_response = client.put(
        f"/tickets/{ticket['id']}",
        headers={
            "X-Tapis-Token": "admin-token",
            "X-Patra-Username": "williamq96",
        },
        json={
            "status": "resolved",
            "admin_response": "Access granted.",
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["status"] == "resolved"
    assert updated["reviewed_by"] == "williamq96"
    assert updated["admin_response"] == "Access granted."


def test_submission_row_decoder_accepts_json_strings():
    from rest_server.routes.submissions import _row_to_submission

    row = {
        "id": 1,
        "submission_type": "model_card",
        "status": "pending",
        "submitted_by": "alice",
        "submitted_at": datetime.now(timezone.utc),
        "title": "Queued Model",
        "data": json.dumps({"asset_url": "https://example.com/model"}),
        "asset_payload": json.dumps({"name": "Queued Model"}),
        "admin_notes": None,
        "reviewed_by": None,
        "reviewed_at": None,
        "created_asset_id": None,
        "created_asset_type": None,
        "error_message": None,
    }

    submission = _row_to_submission(row)
    assert submission.data["asset_url"] == "https://example.com/model"
