import asyncio
import json
import logging
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

import asyncpg

from rest_server.database import get_pool
from rest_server.deps import get_include_private, require_authenticated_actor, PatraActor
from rest_server.errors import asset_not_available_or_visible
from rest_server.models import (
    AIModel,
    ModelCardDetail,
    ModelCardSummary,
    ModelCardUpdate,
    ModelDeployment,
    ModelDownloadURL,
)
from rest_server.routes.datasheets import resolve_datasheet_identifier

router = APIRouter(tags=["model_cards"])
log = logging.getLogger(__name__)

_MODEL_COLUMNS = """
    id, name, version, description, owner, location, license,
    framework, model_type, test_accuracy
"""

_AI_MODEL_UPDATE_COLUMNS = {
    "name": "name",
    "version": "version",
    "description": "description",
    "owner": "owner",
    "location": "location",
    "license": "license",
    "framework": "framework",
    "model_type": "model_type",
    "test_accuracy": "test_accuracy",
}


def _clean_text(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _first_present(*values):
    for value in values:
        cleaned = _clean_text(value)
        if cleaned is not None:
            return cleaned
    return None


def _looks_like_url(value) -> bool:
    cleaned = _clean_text(value)
    if not cleaned:
        return False
    parsed = urlparse(cleaned)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _get_model_source_url(model_card_row: asyncpg.Record) -> str | None:
    for candidate in (
        model_card_row["output_data"],
        model_card_row["documentation"],
        model_card_row["citation"],
    ):
        if _looks_like_url(candidate):
            return candidate.strip()
    return None


def _extract_huggingface_repo_id(url: str) -> str | None:
    parsed = urlparse(url)
    if "huggingface.co" not in parsed.netloc.lower():
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] in {"datasets", "spaces"}:
        return None
    return "/".join(parts[:2])


def _extract_github_repo(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if "github.com" not in parsed.netloc.lower():
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def _license_from_tags(tags: list[str] | None) -> str | None:
    for tag in tags or []:
        if isinstance(tag, str) and tag.startswith("license:"):
            return tag.split(":", 1)[1] or None
    return None


def _framework_from_tags(tags: list[str] | None) -> str | None:
    known_frameworks = {
        "pytorch": "PyTorch",
        "tensorflow": "TensorFlow",
        "jax": "JAX",
        "transformers": "Transformers",
        "diffusers": "Diffusers",
        "timm": "timm",
        "keras": "Keras",
    }
    for tag in tags or []:
        if not isinstance(tag, str):
            continue
        normalized = tag.lower()
        if normalized in known_frameworks:
            return known_frameworks[normalized]
    return None


def _coerce_is_gated(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() not in {"", "false", "0", "none", "null"}


@lru_cache(maxsize=128)
def _fetch_huggingface_model_metadata(repo_id: str) -> dict:
    request = Request(
        f"https://huggingface.co/api/models/{repo_id}",
        headers={"User-Agent": "patra-backend/1.0"},
    )
    with urlopen(request, timeout=5) as response:
        payload = json.load(response)

    card_data = payload.get("cardData") or {}
    tags = payload.get("tags") or []

    return {
        "owner": _first_present(payload.get("author"), repo_id.split("/", 1)[0]),
        "location": _first_present(payload.get("id") and f"https://huggingface.co/{payload['id']}", f"https://huggingface.co/{repo_id}"),
        "license": _first_present(card_data.get("license"), _license_from_tags(tags)),
        "framework": _first_present(payload.get("library_name"), _framework_from_tags(tags)),
        "model_type": _first_present(payload.get("pipeline_tag"), card_data.get("pipeline_tag")),
        "is_gated": _coerce_is_gated(payload.get("gated")),
    }


@lru_cache(maxsize=128)
def _fetch_github_repo_metadata(owner: str, repo: str) -> dict:
    request = Request(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "patra-backend/1.0",
        },
    )
    with urlopen(request, timeout=5) as response:
        payload = json.load(response)

    license_info = payload.get("license") or {}
    owner_info = payload.get("owner") or {}

    return {
        "owner": _first_present(owner_info.get("login"), owner),
        "location": _first_present(payload.get("html_url"), f"https://github.com/{owner}/{repo}"),
        "license": _first_present(license_info.get("spdx_id"), license_info.get("name")),
        "framework": None,
        "model_type": None,
        "is_gated": False,
    }


async def _fetch_external_model_metadata(model_card_row: asyncpg.Record) -> dict | None:
    source_url = _get_model_source_url(model_card_row)
    if not source_url:
        return None

    try:
        hf_repo_id = _extract_huggingface_repo_id(source_url)
        if hf_repo_id:
            metadata = await asyncio.to_thread(_fetch_huggingface_model_metadata, hf_repo_id)
            metadata.setdefault("location", source_url)
            return metadata

        github_repo = _extract_github_repo(source_url)
        if github_repo:
            metadata = await asyncio.to_thread(_fetch_github_repo_metadata, github_repo[0], github_repo[1])
            metadata.setdefault("location", source_url)
            return metadata
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        log.warning("External model metadata lookup failed for %s: %s", source_url, exc)
        return {"location": source_url}

    return {"location": source_url}


async def _get_model_card_base_row(conn: asyncpg.Connection, model_card_uuid: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT mc.id, mc.uuid, mc.name, mc.version, mc.short_description,
               mc.full_description, mc.keywords, mc.author, mc.citation,
               mc.input_data, mc.input_type, mc.output_data,
               mc.foundational_model, mc.category, mc.documentation,
               mc.is_private, mc.is_gated,
               ds.uuid AS training_datasheet_uuid
        FROM model_cards mc
        LEFT JOIN datasheets ds ON ds.identifier = mc.training_datasheet_id
        WHERE mc.uuid = $1
        """,
        model_card_uuid,
    )


async def _get_linked_model_row(conn: asyncpg.Connection, model_card_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"""
        SELECT {_MODEL_COLUMNS}
        FROM models
        WHERE model_card_id = $1
        LIMIT 1
        """,
        model_card_id,
    )


def _build_ai_model(
    model_card_row: asyncpg.Record,
    model_row: asyncpg.Record | None,
    external_metadata: dict | None,
) -> AIModel | None:
    external_metadata = external_metadata or {}

    name = _first_present(
        model_row["name"] if model_row else None,
        external_metadata.get("name"),
        model_card_row["name"],
    )
    version = _first_present(
        model_row["version"] if model_row else None,
        external_metadata.get("version"),
        model_card_row["version"],
    )
    description = _first_present(
        model_row["description"] if model_row else None,
        external_metadata.get("description"),
        model_card_row["full_description"],
        model_card_row["short_description"],
    )
    owner = _first_present(
        model_row["owner"] if model_row else None,
        external_metadata.get("owner"),
        model_card_row["author"],
    )
    location = _first_present(
        model_row["location"] if model_row else None,
        external_metadata.get("location"),
        _get_model_source_url(model_card_row),
    )
    license_name = _first_present(
        model_row["license"] if model_row else None,
        external_metadata.get("license"),
    )
    framework = _first_present(
        model_row["framework"] if model_row else None,
        external_metadata.get("framework"),
    )
    model_type = _first_present(
        model_row["model_type"] if model_row else None,
        external_metadata.get("model_type"),
        model_card_row["category"],
    )
    test_accuracy = (
        float(model_row["test_accuracy"])
        if model_row and model_row["test_accuracy"] is not None
        else external_metadata.get("test_accuracy")
    )

    if not any(
        value is not None
        for value in (name, version, description, owner, location, license_name, framework, model_type, test_accuracy)
    ):
        return None

    model_id = int(model_row["id"]) if model_row and model_row["id"] is not None else int(model_card_row["id"])

    return AIModel(
        model_id=model_id,
        name=name,
        version=version,
        description=description,
        owner=owner,
        location=location,
        license=license_name,
        framework=framework,
        model_type=model_type,
        test_accuracy=test_accuracy,
    )


@router.get("/modelcards", response_model=list[ModelCardSummary])
async def list_model_cards(
    pool: asyncpg.Pool = Depends(get_pool),
    include_private: bool = Depends(get_include_private),
    q: str | None = Query(default=None, max_length=255),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """List all model cards. JWT bearer shows private; unauthenticated shows only public."""
    params: list[object] = []
    filters: list[str] = []
    if not include_private:
        filters.append("is_private = false")
    query_text = q.strip() if q else None
    if query_text:
        params.append(f"%{query_text}%")
        filters.append(
            f"(name ILIKE ${len(params)} OR COALESCE(author, '') ILIKE ${len(params)} OR COALESCE(short_description, '') ILIKE ${len(params)})"
        )
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.extend([limit, skip])
    query = f"""
        SELECT id, uuid, name, category, author, version, short_description, is_gated, is_private, updated_at
        FROM model_cards
        {where}
        ORDER BY LOWER(name), id
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [
        ModelCardSummary(
            id=int(r["id"]),
            uuid=str(r["uuid"]),
            name=r["name"],
            categories=r["category"],
            author=r["author"],
            version=r["version"],
            short_description=r["short_description"],
            is_gated=r["is_gated"],
            is_private=bool(r["is_private"]),
            updated_at=r["updated_at"].isoformat() if r["updated_at"] else None,
        )
        for r in rows
    ]


@router.get("/modelcard/{uuid}", response_model=ModelCardDetail)
async def get_model_card(
    uuid: UUID = Path(..., description="Model card UUID"),
    pool: asyncpg.Pool = Depends(get_pool),
    include_private: bool = Depends(get_include_private),
):
    """Get a single model card by UUID. Returns 404 if private and caller has no JWT."""
    async with pool.acquire() as conn:
        model_card_row = await _get_model_card_base_row(conn, uuid)
        if not model_card_row:
            raise asset_not_available_or_visible()
        mc_id = int(model_card_row["id"])
        model_row = await _get_linked_model_row(conn, mc_id)
        external_metadata = None
        if (
            model_row is None
            or any(
                _clean_text(model_row[field]) is None
                for field in ("owner", "location", "license", "framework", "model_type")
            )
        ):
            external_metadata = await _fetch_external_model_metadata(model_card_row)

    if model_card_row["is_private"] and not include_private:
        raise asset_not_available_or_visible()
    ai_model = _build_ai_model(model_card_row, model_row, external_metadata)
    is_gated = bool(model_card_row["is_gated"] or (external_metadata or {}).get("is_gated"))
    return ModelCardDetail(
        id=int(model_card_row["id"]),
        uuid=str(model_card_row["uuid"]),
        name=model_card_row["name"],
        version=model_card_row["version"],
        short_description=model_card_row["short_description"],
        full_description=model_card_row["full_description"],
        keywords=model_card_row["keywords"],
        author=model_card_row["author"],
        input_data=model_card_row["input_data"],
        output_data=model_card_row["output_data"],
        input_type=model_card_row["input_type"],
        categories=model_card_row["category"],
        citation=model_card_row["citation"],
        foundational_model=model_card_row["foundational_model"],
        training_datasheet_uuid=(
            str(model_card_row["training_datasheet_uuid"])
            if model_card_row["training_datasheet_uuid"]
            else None
        ),
        is_private=bool(model_card_row["is_private"]),
        is_gated=is_gated,
        ai_model=ai_model,
    )



# Column name mapping for model card updates (field name -> DB column)
_MC_UPDATE_COLUMNS = {
    "name": "name",
    "version": "version",
    "short_description": "short_description",
    "full_description": "full_description",
    "keywords": "keywords",
    "author": "author",
    "category": "category",
    "input_type": "input_type",
    "input_data": "input_data",
    "output_data": "output_data",
    "citation": "citation",
    "documentation": "documentation",
    "foundational_model": "foundational_model",
    "training_datasheet_uuid": "training_datasheet_id",
    "is_private": "is_private",
    "is_gated": "is_gated",
}


async def _apply_model_card_update(
    conn: asyncpg.Connection,
    model_card_id: int,
    body: ModelCardUpdate,
) -> None:
    """Apply a partial update to a model_cards row and its linked models row.

    Shared by PUT /modelcard/{uuid} and PATCH /v1/assets/model-cards/{asset_id}
    so both update paths resolve training_datasheet_uuid and build the SET
    clause the same way.
    """
    updates = body.model_dump(exclude_none=True)
    ai_model_updates = updates.pop("ai_model", None) or {}

    training_datasheet_uuid = updates.pop("training_datasheet_uuid", None)
    if training_datasheet_uuid is not None:
        datasheet_id = await resolve_datasheet_identifier(conn, training_datasheet_uuid)
        if datasheet_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="training_datasheet_uuid does not match an existing datasheet",
            )
        updates["training_datasheet_uuid"] = datasheet_id

    if not updates and not ai_model_updates:
        return

    # Update model_cards table
    if updates:
        set_parts = []
        values = []
        idx = 2  # $1 is the id
        for field, value in updates.items():
            col = _MC_UPDATE_COLUMNS.get(field)
            if col is None:
                continue
            set_parts.append(f"{col} = ${idx}")
            values.append(value)
            idx += 1

        if set_parts:
            set_parts.append("updated_at = NOW()")
            query = f"UPDATE model_cards SET {', '.join(set_parts)} WHERE id = $1"
            result = await conn.execute(query, model_card_id, *values)
            if result == "UPDATE 0":
                raise asset_not_available_or_visible()

    # Update or create linked models row
    if ai_model_updates:
        existing_model = await conn.fetchval(
            "SELECT id FROM models WHERE model_card_id = $1", model_card_id,
        )
        set_parts = []
        values = []
        idx = 2
        for field, value in ai_model_updates.items():
            col = _AI_MODEL_UPDATE_COLUMNS.get(field)
            if col is None:
                continue
            set_parts.append(f"{col} = ${idx}")
            values.append(value)
            idx += 1

        if set_parts and existing_model is not None:
            set_parts.append("updated_at = NOW()")
            query = f"UPDATE models SET {', '.join(set_parts)} WHERE model_card_id = $1"
            await conn.execute(query, model_card_id, *values)
        elif set_parts and existing_model is None:
            # Insert new models row
            col_names = ["model_card_id", "created_at", "updated_at"]
            col_vals = [model_card_id]
            placeholders = ["$1", "NOW()", "NOW()"]
            p_idx = 2
            for field, value in ai_model_updates.items():
                col = _AI_MODEL_UPDATE_COLUMNS.get(field)
                if col is None:
                    continue
                col_names.append(col)
                col_vals.append(value)
                placeholders.append(f"${p_idx}")
                p_idx += 1
            # name is NOT NULL in schema — default to model card name
            if "name" not in ai_model_updates:
                mc_name = await conn.fetchval("SELECT name FROM model_cards WHERE id = $1", model_card_id)
                col_names.append("name")
                col_vals.append(mc_name or "Unnamed")
                placeholders.append(f"${p_idx}")
            query = f"INSERT INTO models ({', '.join(col_names)}) VALUES ({', '.join(placeholders)})"
            await conn.execute(query, *col_vals)


@router.put("/modelcard/{uuid}", response_model=ModelCardDetail)
async def update_model_card(
    body: ModelCardUpdate,
    uuid: UUID = Path(..., description="Model card UUID"),
    pool: asyncpg.Pool = Depends(get_pool),
    include_private: bool = Depends(get_include_private),
    actor: PatraActor = Depends(require_authenticated_actor),
):
    """Update a model card and its linked AI model (authenticated users only)."""
    async with pool.acquire() as conn:
        id_val = await conn.fetchval("SELECT id FROM model_cards WHERE uuid = $1", uuid)
        if id_val is None:
            raise asset_not_available_or_visible()
        await _apply_model_card_update(conn, int(id_val), body)

    return await get_model_card(uuid=uuid, pool=pool, include_private=include_private)


@router.get("/modelcard/{uuid}/download_url", response_model=ModelDownloadURL)
async def get_model_download_url(
    uuid: UUID = Path(..., description="Model card UUID"),
    pool: asyncpg.Pool = Depends(get_pool),
    include_private: bool = Depends(get_include_private),
):
    async with pool.acquire() as conn:
        model_card_row = await _get_model_card_base_row(conn, uuid)
        if not model_card_row:
            raise asset_not_available_or_visible()
        mc_id = int(model_card_row["id"])
        model_row = await _get_linked_model_row(conn, mc_id)
        external_metadata = None
        if model_row is None or _clean_text(model_row["location"]) is None:
            external_metadata = await _fetch_external_model_metadata(model_card_row)

    if model_card_row["is_private"] and not include_private:
        raise asset_not_available_or_visible()
    ai_model = _build_ai_model(model_card_row, model_row, external_metadata)
    if not ai_model or not ai_model.location:
        raise asset_not_available_or_visible()
    return ModelDownloadURL(
        model_id=int(model_row["id"]) if model_row and model_row["id"] is not None else int(model_card_row["id"]),
        name=ai_model.name,
        version=ai_model.version,
        download_url=ai_model.location,
    )


@router.get("/modelcard/{uuid}/deployments", response_model=list[ModelDeployment])
async def get_model_deployments(
    uuid: UUID = Path(..., description="Model card UUID"),
    pool: asyncpg.Pool = Depends(get_pool),
    include_private: bool = Depends(get_include_private),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    async with pool.acquire() as conn:
        model_card_row = await _get_model_card_base_row(conn, uuid)
        if not model_card_row:
            raise asset_not_available_or_visible()
        mc_id = int(model_card_row["id"])
        model_row = await _get_linked_model_row(conn, mc_id)
    if model_card_row["is_private"] and not include_private:
        raise asset_not_available_or_visible()
    if not model_row or model_row["id"] is None:
        return []

    deployments_query = """
        SELECT
            e.id AS experiment_id,
            e.edge_device_id AS device_id,
            COALESCE(e.executed_at, e.start_at) AS timestamp,
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
        ORDER BY COALESCE(e.executed_at, e.start_at) DESC NULLS LAST, e.id DESC
        LIMIT $2 OFFSET $3
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(deployments_query, model_row["id"], limit, skip)
    return [
        ModelDeployment(
            experiment_id=int(r["experiment_id"]),
            device_id=r["device_id"],
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
