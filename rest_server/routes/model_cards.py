from fastapi import APIRouter, Depends, HTTPException, Path, Query

import asyncpg

from rest_server.database import get_pool
from rest_server.deps import get_include_private
from rest_server.models import AIModel, ModelCardDetail, ModelCardSummary

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
        raise HTTPException(status_code=404, detail="Model card not found")
    if row["is_private"] and not include_private:
        raise HTTPException(status_code=404, detail="Model card not found")
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
