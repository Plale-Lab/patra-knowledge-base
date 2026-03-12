from fastapi import APIRouter, Depends, Path, Query

import asyncpg

from rest_server.database import get_pool
from rest_server.deps import get_include_private
from rest_server.errors import asset_not_available_or_visible
from rest_server.models import (
    AIModel,
    ModelCardDetail,
    ModelCardSummary,
    ModelDeployment,
    ModelDownloadURL,
)

router = APIRouter(tags=["model_cards"])


@router.get("/modelcards", response_model=list[ModelCardSummary])
async def list_model_cards(
    pool: asyncpg.Pool = Depends(get_pool),
    include_private: bool = Depends(get_include_private),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """List all model cards. JWT bearer shows private; unauthenticated shows only public."""
    where = "" if include_private else " WHERE is_private = false"
    query = f"""
        SELECT id, name, category, author, version, short_description, is_gated
        FROM model_cards
        {where}
        ORDER BY id
        LIMIT $1 OFFSET $2
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, limit, skip)
    return [
        ModelCardSummary(
            mc_id=int(r["id"]),
            name=r["name"],
            categories=r["category"],
            author=r["author"],
            version=r["version"],
            short_description=r["short_description"],
            is_gated=r["is_gated"],
        )
        for r in rows
    ]


@router.get("/modelcard/{id}", response_model=ModelCardDetail)
async def get_model_card(
    id: int = Path(..., description="Model card ID (integer)"),
    pool: asyncpg.Pool = Depends(get_pool),
    include_private: bool = Depends(get_include_private),
):
    """Get a single model card by ID (integer). Returns 404 if private and caller has no JWT."""
    query = """
        SELECT mc.id, mc.name, mc.version, mc.short_description,
               mc.full_description, mc.keywords, mc.author, mc.citation,
               mc.input_data, mc.input_type, mc.output_data,
               mc.foundational_model, mc.category, mc.documentation,
               mc.is_private, mc.is_gated,
               m.id AS model_id, m.name AS model_name, m.version AS model_version,
               m.description AS model_description, m.owner, m.location,
               m.license, m.framework, m.model_type, m.test_accuracy
        FROM model_cards mc
        LEFT JOIN models m ON m.model_card_id = mc.id
        WHERE mc.id = $1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, id)
    if not row:
        raise asset_not_available_or_visible()
    if row["is_private"] and not include_private:
        raise asset_not_available_or_visible()
    ai_model = None
    if row["model_id"] is not None:
        ai_model = AIModel(
            model_id=int(row["model_id"]),
            name=row["model_name"],
            version=row["model_version"],
            description=row["model_description"],
            owner=row["owner"],
            location=row["location"],
            license=row["license"],
            framework=row["framework"],
            model_type=row["model_type"],
            test_accuracy=float(row["test_accuracy"]) if row["test_accuracy"] is not None else None,
        )
    return ModelCardDetail(
        external_id=int(row["id"]),
        name=row["name"],
        version=row["version"],
        short_description=row["short_description"],
        full_description=row["full_description"],
        keywords=row["keywords"],
        author=row["author"],
        input_data=row["input_data"],
        output_data=row["output_data"],
        input_type=row["input_type"],
        categories=row["category"],
        citation=row["citation"],
        foundational_model=row["foundational_model"],
        is_gated=row["is_gated"],
        ai_model=ai_model,
    )


@router.get("/modelcard/{id}/download_url", response_model=ModelDownloadURL)
async def get_model_download_url(
    id: int = Path(..., description="Model card ID (integer)"),
    pool: asyncpg.Pool = Depends(get_pool),
    include_private: bool = Depends(get_include_private),
):
    query = """
        SELECT
            mc.is_private,
            m.id AS model_id,
            m.name AS model_name,
            m.version AS model_version,
            m.location AS download_url
        FROM model_cards mc
        LEFT JOIN models m ON m.model_card_id = mc.id
        WHERE mc.id = $1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, id)
    if not row or row["model_id"] is None:
        raise asset_not_available_or_visible()
    if row["is_private"] and not include_private:
        raise asset_not_available_or_visible()
    return ModelDownloadURL(
        model_id=int(row["model_id"]),
        name=row["model_name"],
        version=row["model_version"],
        download_url=row["download_url"],
    )


@router.get("/modelcard/{id}/deployments", response_model=list[ModelDeployment])
async def get_model_deployments(
    id: int = Path(..., description="Model card ID (integer)"),
    pool: asyncpg.Pool = Depends(get_pool),
    include_private: bool = Depends(get_include_private),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    model_query = """
        SELECT
            mc.is_private,
            m.id AS model_id
        FROM model_cards mc
        LEFT JOIN models m ON m.model_card_id = mc.id
        WHERE mc.id = $1
    """
    async with pool.acquire() as conn:
        model_row = await conn.fetchrow(model_query, id)
    if not model_row or model_row["model_id"] is None:
        raise asset_not_available_or_visible()
    if model_row["is_private"] and not include_private:
        raise asset_not_available_or_visible()

    deployments_query = """
        SELECT
            e.id AS experiment_id,
            e.edge_device_id AS device_id,
            COALESCE(e.executed_at, e.model_used_at, e.start_at) AS timestamp,
            CASE
                WHEN e.executed_at IS NULL THEN 'active'
                ELSE 'completed'
            END AS status,
            e.precision,
            e.recall,
            e.f1_score,
            e.map_50,
            e.map_50_95
        FROM experiments e
        WHERE e.model_id = $1
        ORDER BY COALESCE(e.executed_at, e.model_used_at, e.start_at) DESC NULLS LAST, e.id DESC
        LIMIT $2 OFFSET $3
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(deployments_query, model_row["model_id"], limit, skip)
    return [
        ModelDeployment(
            experiment_id=int(r["experiment_id"]),
            device_id=int(r["device_id"]),
            timestamp=r["timestamp"].isoformat() if r["timestamp"] else None,
            status=r["status"],
            precision=float(r["precision"]) if r["precision"] is not None else None,
            recall=float(r["recall"]) if r["recall"] is not None else None,
            f1_score=float(r["f1_score"]) if r["f1_score"] is not None else None,
            map_50=float(r["map_50"]) if r["map_50"] is not None else None,
            map_50_95=float(r["map_50_95"]) if r["map_50_95"] is not None else None,
        )
        for r in rows
    ]
