import json

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from rest_server.database import get_pool
from rest_server.deps import get_request_actor, require_admin_actor
from rest_server.ingest_models import AssetDatasheetCreate, AssetModelCardCreate
from rest_server.routes.assets import AssetRevisionContext, _create_datasheet_in_tx, _create_model_card_in_tx
from rest_server.workflow_models import (
    SubmissionBulkCreate,
    SubmissionBulkCreateResult,
    SubmissionBulkItemResult,
    SubmissionCreate,
    SubmissionRecord,
    SubmissionReviewUpdate,
)

router = APIRouter(tags=["submissions"])


def _decode_json_column(value):
    if isinstance(value, str):
        return json.loads(value)
    return value or {}


def _row_to_submission(row: asyncpg.Record) -> SubmissionRecord:
    return SubmissionRecord(
        id=str(row["id"]),
        type=row["submission_type"],
        status=row["status"],
        submitted_by=row["submitted_by"],
        submitted_at=row["submitted_at"],
        title=row["title"],
        data=_decode_json_column(row["data"]),
        admin_notes=row["admin_notes"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        created_asset_id=row["created_asset_id"],
        created_asset_type=row["created_asset_type"],
        error_message=row["error_message"],
    )


async def _resolve_model_card_revision_context(
    conn: asyncpg.Connection,
    previous_asset_id: int,
) -> AssetRevisionContext:
    row = await conn.fetchrow(
        """
        SELECT id, asset_version, COALESCE(root_version_id, id) AS root_version_id
        FROM model_cards
        WHERE id = $1
        """,
        previous_asset_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Source model card not found for edit request")
    return AssetRevisionContext(
        asset_version=int(row["asset_version"] or 1) + 1,
        previous_version_id=int(row["id"]),
        root_version_id=int(row["root_version_id"]),
    )


async def _resolve_datasheet_revision_context(
    conn: asyncpg.Connection,
    previous_asset_id: int,
) -> AssetRevisionContext:
    row = await conn.fetchrow(
        """
        SELECT identifier, asset_version, COALESCE(root_version_id, identifier) AS root_version_id
        FROM datasheets
        WHERE identifier = $1
        """,
        previous_asset_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Source datasheet not found for edit request")
    return AssetRevisionContext(
        asset_version=int(row["asset_version"] or 1) + 1,
        previous_version_id=int(row["identifier"]),
        root_version_id=int(row["root_version_id"]),
    )


async def _insert_submission(
    conn: asyncpg.Connection,
    submission_type: str,
    submitted_by: str,
    title: str | None,
    data: dict,
    asset_payload: dict,
    intake_method: str | None,
    submission_origin: str | None,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO submission_queue (
            submission_type, status, submitted_by, submitted_at,
            title, data, asset_payload, intake_method, submission_origin, updated_at
        )
        VALUES (
            $1, 'pending', $2, NOW(),
            $3, $4::jsonb, $5::jsonb, $6, $7, NOW()
        )
        RETURNING id, submission_type, status, submitted_by, submitted_at,
                  title, data, asset_payload, admin_notes, reviewed_by, reviewed_at,
                  created_asset_id, created_asset_type, error_message
        """,
        submission_type,
        submitted_by,
        title,
        json.dumps(data),
        json.dumps(asset_payload),
        intake_method,
        submission_origin,
    )


@router.get("/submissions", response_model=list[SubmissionRecord])
async def list_submissions(
    request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
    status_filter: str | None = Query(default=None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    actor = get_request_actor(request)
    clauses: list[str] = []
    params: list[object] = []

    if status_filter:
        clauses.append(f"status = ${len(params) + 1}")
        params.append(status_filter)

    if actor.username and not actor.is_admin:
        clauses.append(f"submitted_by = ${len(params) + 1}")
        params.append(actor.username)
    elif not actor.is_admin and not actor.username:
        return []

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, skip])
    query = f"""
        SELECT id, submission_type, status, submitted_by, submitted_at,
               title, data, asset_payload, admin_notes, reviewed_by, reviewed_at,
               created_asset_id, created_asset_type, error_message
        FROM submission_queue
        {where}
        ORDER BY submitted_at DESC, id DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [_row_to_submission(row) for row in rows]


@router.post("/submissions", response_model=SubmissionRecord, status_code=status.HTTP_201_CREATED)
async def create_submission(
    payload: SubmissionCreate,
    request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
):
    actor = get_request_actor(request)
    submitted_by = actor.username or payload.submitted_by

    async with pool.acquire() as conn:
        row = await _insert_submission(
            conn,
            payload.type,
            submitted_by,
            payload.title,
            payload.data,
            payload.asset_payload,
            payload.intake_method,
            payload.submission_origin,
        )
    return _row_to_submission(row)


@router.post("/submissions/bulk", response_model=SubmissionBulkCreateResult, status_code=status.HTTP_201_CREATED)
async def create_bulk_submissions(
    payload: SubmissionBulkCreate,
    request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
):
    actor = get_request_actor(request)
    submitted_by = actor.username or payload.submitted_by
    results: list[SubmissionBulkItemResult] = []

    async with pool.acquire() as conn:
        for index, item in enumerate(payload.items):
            try:
                row = await _insert_submission(
                    conn,
                    payload.type,
                    submitted_by,
                    item.title,
                    item.data,
                    item.asset_payload,
                    item.intake_method,
                    item.submission_origin,
                )
                submission = _row_to_submission(row)
                results.append(
                    SubmissionBulkItemResult(
                        index=index,
                        created=True,
                        submission_id=submission.id,
                        submission=submission,
                    )
                )
            except Exception as exc:
                results.append(
                    SubmissionBulkItemResult(
                        index=index,
                        created=False,
                        error=str(exc),
                    )
                )

    return SubmissionBulkCreateResult(
        total=len(results),
        created=sum(1 for item in results if item.created),
        failed=sum(1 for item in results if not item.created),
        results=results,
    )


@router.put("/submissions/{submission_id}", response_model=SubmissionRecord)
async def review_submission(
    payload: SubmissionReviewUpdate,
    submission_id: int = Path(..., ge=1),
    actor=Depends(require_admin_actor),
    pool: asyncpg.Pool = Depends(get_pool),
):
    reviewed_by = actor.username or "admin"
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT id, submission_type, status, submitted_by, submitted_at,
                       title, data, asset_payload, admin_notes, reviewed_by, reviewed_at,
                       created_asset_id, created_asset_type, error_message
                FROM submission_queue
                WHERE id = $1
                """,
                submission_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Submission not found")

            created_asset_id = row["created_asset_id"]
            created_asset_type = row["created_asset_type"]
            error_message = None
            submission_data = _decode_json_column(row["data"])

            if payload.status == "approved" and row["status"] != "approved":
                if row["submission_type"] == "model_card":
                    asset = AssetModelCardCreate.model_validate(_decode_json_column(row["asset_payload"]))
                    revision_context = None
                    if submission_data.get("intake_method") == "edit_existing_asset":
                        revision_context = await _resolve_model_card_revision_context(
                            conn,
                            int(submission_data.get("existing_asset_id", 0)),
                        )
                    ingest_result = await _create_model_card_in_tx(
                        conn,
                        asset,
                        "tapis-review",
                        revision_context=revision_context,
                    )
                else:
                    asset = AssetDatasheetCreate.model_validate(_decode_json_column(row["asset_payload"]))
                    revision_context = None
                    if submission_data.get("intake_method") == "edit_existing_asset":
                        revision_context = await _resolve_datasheet_revision_context(
                            conn,
                            int(submission_data.get("existing_asset_id", 0)),
                        )
                    ingest_result = await _create_datasheet_in_tx(
                        conn,
                        asset,
                        "tapis-review",
                        revision_context=revision_context,
                    )

                created_asset_id = ingest_result.asset_id
                created_asset_type = row["submission_type"]
                if ingest_result.duplicate:
                    error_message = "Approved against an existing matching asset."

            updated = await conn.fetchrow(
                """
                UPDATE submission_queue
                SET status = $2,
                    admin_notes = $3,
                    reviewed_by = $4,
                    reviewed_at = NOW(),
                    created_asset_id = $5,
                    created_asset_type = $6,
                    error_message = $7,
                    updated_at = NOW()
                WHERE id = $1
                RETURNING id, submission_type, status, submitted_by, submitted_at,
                          title, data, asset_payload, admin_notes, reviewed_by, reviewed_at,
                          created_asset_id, created_asset_type, error_message
                """,
                submission_id,
                payload.status,
                payload.admin_notes,
                reviewed_by,
                created_asset_id,
                created_asset_type,
                error_message,
            )
    return _row_to_submission(updated)
