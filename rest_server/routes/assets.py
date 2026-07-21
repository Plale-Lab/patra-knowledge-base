import logging
import json
from collections.abc import Sequence

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from rest_server.database import get_pool
from rest_server.deps import AssetIngestPrincipal, get_request_actor, require_asset_ingest_principal
from rest_server.asset_create_models import (
    AssetBulkDatasheetCreate,
    AssetBulkIngestResult,
    AssetBulkItemResult,
    AssetBulkModelCardCreate,
    AssetDatasheetCreate,
    AssetIngestResult,
    AssetModelCardCreate,
    AssetUpdateResult,
)
from rest_server.models import EditableRecordSummary, ModelCardUpdate
from rest_server.routes.datasheets import resolve_datasheet_identifier
from rest_server.routes.model_cards import _apply_model_card_update

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/assets", tags=["assets"])


async def _find_duplicate_model_card(conn: asyncpg.Connection, asset: AssetModelCardCreate) -> int | None:
    row = await conn.fetchrow(
        """
        SELECT id
        FROM model_cards
        WHERE name = $1
          AND COALESCE(version, '') = COALESCE($2, '')
          AND COALESCE(author, '') = COALESCE($3, '')
          AND COALESCE(short_description, '') = COALESCE($4, '')
        LIMIT 1
        """,
        asset.name,
        asset.version,
        asset.author,
        asset.short_description,
    )
    return int(row["id"]) if row else None


async def _create_model_card_in_tx(
    conn: asyncpg.Connection,
    asset: AssetModelCardCreate,
    organization: str,
) -> AssetIngestResult:
    duplicate_id = await _find_duplicate_model_card(conn, asset)
    if duplicate_id is not None:
        return AssetIngestResult(
            asset_type="model_card",
            asset_id=duplicate_id,
            organization=organization,
            created=False,
            duplicate=True,
        )

    training_datasheet_id = None
    if asset.training_datasheet_uuid is not None:
        training_datasheet_id = await resolve_datasheet_identifier(conn, asset.training_datasheet_uuid)
        if training_datasheet_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="training_datasheet_uuid does not match an existing datasheet",
            )

    model_card_row = await conn.fetchrow(
        """
        INSERT INTO model_cards (
            name, version, uuid, is_private, is_gated,
            short_description, full_description, keywords, author, citation,
            input_data, input_type, output_data, foundational_model, category, documentation,
            training_datasheet_id,
            created_at, updated_at
        )
        VALUES (
            $1, $2, COALESCE($3::uuid, gen_random_uuid()), $4, $5,
            $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16,
            $17,
            NOW(), NOW()
        )
        RETURNING id, uuid
        """,
        asset.name,
        asset.version,
        str(asset.uuid) if asset.uuid is not None else None,
        asset.is_private,
        asset.is_gated,
        asset.short_description,
        asset.full_description,
        asset.keywords,
        asset.author,
        asset.citation,
        asset.input_data,
        asset.input_type,
        asset.output_data,
        asset.foundational_model,
        asset.category,
        asset.documentation,
        training_datasheet_id,
    )
    model_card_id = model_card_row["id"]
    model_card_uuid = model_card_row["uuid"]

    if asset.ai_model is not None:
        await conn.execute(
            """
            INSERT INTO models (
                name, version, description, owner, location, license, framework, model_type,
                test_accuracy, model_metrics, inference_labels, model_structure,
                created_at, updated_at, model_card_id
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8,
                $9, $10::jsonb, $11::jsonb, $12::jsonb,
                NOW(), NOW(), $13
            )
            """,
            asset.ai_model.name,
            asset.ai_model.version,
            asset.ai_model.description,
            asset.ai_model.owner,
            asset.ai_model.location,
            asset.ai_model.license,
            asset.ai_model.framework,
            asset.ai_model.model_type,
            asset.ai_model.test_accuracy,
            json.dumps(asset.ai_model.model_metrics),
            json.dumps(asset.ai_model.inference_labels),
            json.dumps(asset.ai_model.model_structure),
            model_card_id,
        )

    log.info("Asset ingest: created model card %s for org %s", model_card_id, organization)
    return AssetIngestResult(
        asset_type="model_card",
        asset_id=int(model_card_id),
        asset_uuid=str(model_card_uuid),
        organization=organization,
        created=True,
    )


async def _find_publisher_id(conn: asyncpg.Connection, publisher: dict | None) -> int | None:
    if not publisher:
        return None
    existing_id = await conn.fetchval(
        """
        SELECT id
        FROM datasheet_publishers
        WHERE name = $1
          AND COALESCE(publisher_identifier, '') = COALESCE($2, '')
          AND COALESCE(publisher_identifier_scheme, '') = COALESCE($3, '')
          AND COALESCE(scheme_uri, '') = COALESCE($4, '')
          AND COALESCE(lang, '') = COALESCE($5, '')
        LIMIT 1
        """,
        publisher["name"],
        publisher.get("publisher_identifier"),
        publisher.get("publisher_identifier_scheme"),
        publisher.get("scheme_uri"),
        publisher.get("lang"),
    )
    if existing_id is not None:
        return int(existing_id)
    return int(await conn.fetchval(
        """
        INSERT INTO datasheet_publishers (
            name, publisher_identifier, publisher_identifier_scheme, scheme_uri, lang
        )
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        publisher["name"],
        publisher.get("publisher_identifier"),
        publisher.get("publisher_identifier_scheme"),
        publisher.get("scheme_uri"),
        publisher.get("lang"),
    ))


async def _find_duplicate_datasheet(conn: asyncpg.Connection, asset: AssetDatasheetCreate) -> int | None:
    primary_title = asset.titles[0].title if asset.titles else None
    primary_creator = asset.creators[0].creator_name if asset.creators else None
    row = await conn.fetchrow(
        """
        SELECT d.identifier
        FROM datasheets d
        LEFT JOIN LATERAL (
            SELECT title
            FROM datasheet_titles
            WHERE datasheet_id = d.identifier
            ORDER BY id
            LIMIT 1
        ) t ON TRUE
        LEFT JOIN LATERAL (
            SELECT creator_name
            FROM datasheet_creators
            WHERE datasheet_id = d.identifier
            ORDER BY id
            LIMIT 1
        ) c ON TRUE
        WHERE COALESCE(t.title, '') = COALESCE($1, '')
          AND COALESCE(c.creator_name, '') = COALESCE($2, '')
          AND COALESCE(d.version, '') = COALESCE($3, '')
          AND COALESCE(d.publication_year, -1) = COALESCE($4, -1)
        LIMIT 1
        """,
        primary_title,
        primary_creator,
        asset.version,
        asset.publication_year,
    )
    return int(row["identifier"]) if row else None


async def _insert_many(
    conn: asyncpg.Connection,
    query: str,
    rows: Sequence[tuple],
) -> None:
    if rows:
        await conn.executemany(query, rows)


async def _create_datasheet_in_tx(
    conn: asyncpg.Connection,
    asset: AssetDatasheetCreate,
    organization: str,
) -> AssetIngestResult:
    duplicate_id = await _find_duplicate_datasheet(conn, asset)
    if duplicate_id is not None:
        return AssetIngestResult(
            asset_type="datasheet",
            asset_id=duplicate_id,
            organization=organization,
            created=False,
            duplicate=True,
        )

    publisher_id = await _find_publisher_id(conn, asset.publisher.model_dump(exclude_none=True) if asset.publisher else None)
    datasheet_row = await conn.fetchrow(
        """
        INSERT INTO datasheets (
            uuid, publication_year, resource_type, resource_type_general, size, format, version,
            is_private, status, created_at, updated_at, publisher_id
        )
        VALUES (
            COALESCE($1::uuid, gen_random_uuid()), $2, $3, $4, $5, $6, $7,
            $8, 'approved', NOW(), NOW(), $9
        )
        RETURNING identifier, uuid
        """,
        str(asset.uuid) if asset.uuid is not None else None,
        asset.publication_year,
        asset.resource_type,
        asset.resource_type_general,
        asset.size,
        asset.format,
        asset.version,
        asset.is_private,
        publisher_id,
    )
    datasheet_id = datasheet_row["identifier"]
    datasheet_uuid = datasheet_row["uuid"]

    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_creators (
            datasheet_id, creator_name, name_type, lang, given_name, family_name,
            name_identifier, name_identifier_scheme, name_id_scheme_uri,
            affiliation, affiliation_identifier, affiliation_identifier_scheme, affiliation_scheme_uri
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """,
        [
            (
                datasheet_id,
                creator.creator_name,
                creator.name_type,
                creator.lang,
                creator.given_name,
                creator.family_name,
                creator.name_identifier,
                creator.name_identifier_scheme,
                creator.name_id_scheme_uri,
                creator.affiliation,
                creator.affiliation_identifier,
                creator.affiliation_identifier_scheme,
                creator.affiliation_scheme_uri,
            )
            for creator in asset.creators
        ],
    )
    await _insert_many(
        conn,
        "INSERT INTO datasheet_titles (datasheet_id, title, title_type, lang) VALUES ($1, $2, $3, $4)",
        [(datasheet_id, title.title, title.title_type, title.lang) for title in asset.titles],
    )
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_subjects (
            datasheet_id, subject, subject_scheme, scheme_uri, value_uri, classification_code, lang
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        [
            (
                datasheet_id,
                subject.subject,
                subject.subject_scheme,
                subject.scheme_uri,
                subject.value_uri,
                subject.classification_code,
                subject.lang,
            )
            for subject in asset.subjects
        ],
    )
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_contributors (
            datasheet_id, contributor_type, contributor_name, name_type, given_name, family_name,
            name_identifier, name_identifier_scheme, name_id_scheme_uri,
            affiliation, affiliation_identifier, affiliation_identifier_scheme, affiliation_scheme_uri
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """,
        [
            (
                datasheet_id,
                contributor.contributor_type,
                contributor.contributor_name,
                contributor.name_type,
                contributor.given_name,
                contributor.family_name,
                contributor.name_identifier,
                contributor.name_identifier_scheme,
                contributor.name_id_scheme_uri,
                contributor.affiliation,
                contributor.affiliation_identifier,
                contributor.affiliation_identifier_scheme,
                contributor.affiliation_scheme_uri,
            )
            for contributor in asset.contributors
        ],
    )
    await _insert_many(
        conn,
        "INSERT INTO datasheet_dates (datasheet_id, date, date_type, date_information) VALUES ($1, $2, $3, $4)",
        [(datasheet_id, item.date, item.date_type, item.date_information) for item in asset.dates],
    )
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_alternate_identifiers (
            datasheet_id, alternate_identifier, alternate_identifier_type
        )
        VALUES ($1, $2, $3)
        """,
        [
            (datasheet_id, item.alternate_identifier, item.alternate_identifier_type)
            for item in asset.alternate_identifiers
        ],
    )
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_related_identifiers (
            datasheet_id, related_identifier, related_identifier_type, relation_type,
            related_metadata_scheme, scheme_uri, scheme_type, resource_type_general
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        [
            (
                datasheet_id,
                item.related_identifier,
                item.related_identifier_type,
                item.relation_type,
                item.related_metadata_scheme,
                item.scheme_uri,
                item.scheme_type,
                item.resource_type_general,
            )
            for item in asset.related_identifiers
        ],
    )
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_rights (
            datasheet_id, rights, rights_uri, rights_identifier, rights_identifier_scheme, scheme_uri, lang
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        [
            (
                datasheet_id,
                item.rights,
                item.rights_uri,
                item.rights_identifier,
                item.rights_identifier_scheme,
                item.scheme_uri,
                item.lang,
            )
            for item in asset.rights_list
        ],
    )
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_descriptions (datasheet_id, description, description_type, lang)
        VALUES ($1, $2, $3, $4)
        """,
        [
            (datasheet_id, item.description, item.description_type, item.lang)
            for item in asset.descriptions
        ],
    )
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_geo_locations (
            datasheet_id, geo_location_place, point_longitude, point_latitude,
            box_west, box_east, box_south, box_north, polygon
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
        """,
        [
            (
                datasheet_id,
                item.geo_location_place,
                item.point_longitude,
                item.point_latitude,
                item.box_west,
                item.box_east,
                item.box_south,
                item.box_north,
                json.dumps(item.polygon) if item.polygon is not None else None,
            )
            for item in asset.geo_locations
        ],
    )
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_funding_references (
            datasheet_id, funder_name, funder_identifier, funder_identifier_type,
            scheme_uri, award_number, award_uri, award_title
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        [
            (
                datasheet_id,
                item.funder_name,
                item.funder_identifier,
                item.funder_identifier_type,
                item.scheme_uri,
                item.award_number,
                item.award_uri,
                item.award_title,
            )
            for item in asset.funding_references
        ],
    )

    log.info("Asset ingest: created datasheet %s for org %s", datasheet_id, organization)
    return AssetIngestResult(
        asset_type="datasheet",
        asset_id=int(datasheet_id),
        asset_uuid=str(datasheet_uuid),
        organization=organization,
        created=True,
    )


@router.post("/model-cards", response_model=AssetIngestResult, status_code=status.HTTP_201_CREATED)
async def create_model_card_asset(
    asset: AssetModelCardCreate,
    principal: AssetIngestPrincipal = Depends(require_asset_ingest_principal),
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        async with conn.transaction():
            result = await _create_model_card_in_tx(
                conn,
                asset,
                principal.organization,
            )
    if result.duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Model card already exists with id {result.asset_id}",
        )
    return result


@router.post("/datasheets", response_model=AssetIngestResult, status_code=status.HTTP_201_CREATED)
async def create_datasheet_asset(
    asset: AssetDatasheetCreate,
    principal: AssetIngestPrincipal = Depends(require_asset_ingest_principal),
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        async with conn.transaction():
            result = await _create_datasheet_in_tx(
                conn,
                asset,
                principal.organization,
            )
    if result.duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Datasheet already exists with id {result.asset_id}",
        )
    return result


@router.post("/model-cards/bulk", response_model=AssetBulkIngestResult)
async def bulk_create_model_card_assets(
    payload: AssetBulkModelCardCreate,
    principal: AssetIngestPrincipal = Depends(require_asset_ingest_principal),
    pool: asyncpg.Pool = Depends(get_pool),
):
    results: list[AssetBulkItemResult] = []
    async with pool.acquire() as conn:
        for index, asset in enumerate(payload.assets):
            try:
                async with conn.transaction():
                    result = await _create_model_card_in_tx(conn, asset, principal.organization)
                results.append(
                    AssetBulkItemResult(
                        index=index,
                        asset_type="model_card",
                        created=result.created,
                        duplicate=result.duplicate,
                        asset_id=result.asset_id,
                    )
                )
            except Exception as exc:
                log.exception("Bulk model card ingest failed at index %s", index)
                results.append(
                    AssetBulkItemResult(
                        index=index,
                        asset_type="model_card",
                        created=False,
                        error=str(exc),
                    )
                )
    return AssetBulkIngestResult(
        asset_type="model_card",
        organization=principal.organization,
        total=len(results),
        created=sum(1 for item in results if item.created),
        duplicates=sum(1 for item in results if item.duplicate),
        failed=sum(1 for item in results if item.error is not None),
        results=results,
    )


@router.post("/datasheets/bulk", response_model=AssetBulkIngestResult)
async def bulk_create_datasheet_assets(
    payload: AssetBulkDatasheetCreate,
    principal: AssetIngestPrincipal = Depends(require_asset_ingest_principal),
    pool: asyncpg.Pool = Depends(get_pool),
):
    results: list[AssetBulkItemResult] = []
    async with pool.acquire() as conn:
        for index, asset in enumerate(payload.assets):
            try:
                async with conn.transaction():
                    result = await _create_datasheet_in_tx(conn, asset, principal.organization)
                results.append(
                    AssetBulkItemResult(
                        index=index,
                        asset_type="datasheet",
                        created=result.created,
                        duplicate=result.duplicate,
                        asset_id=result.asset_id,
                    )
                )
            except Exception as exc:
                log.exception("Bulk datasheet ingest failed at index %s", index)
                results.append(
                    AssetBulkItemResult(
                        index=index,
                        asset_type="datasheet",
                        created=False,
                        error=str(exc),
                    )
                )
    return AssetBulkIngestResult(
        asset_type="datasheet",
        organization=principal.organization,
        total=len(results),
        created=sum(1 for item in results if item.created),
        duplicates=sum(1 for item in results if item.duplicate),
        failed=sum(1 for item in results if item.error is not None),
        results=results,
    )


async def _fetch_model_card_snapshot(conn: asyncpg.Connection, asset_id: int) -> dict | None:
    card = await conn.fetchrow(
        """
        SELECT id, uuid, name, version, is_private, is_gated,
               short_description, full_description, keywords, author, citation,
               input_data, input_type, output_data, foundational_model, category, documentation,
               created_at, updated_at
        FROM model_cards
        WHERE id = $1
        """,
        asset_id,
    )
    if not card:
        return None

    model = await conn.fetchrow(
        """
        SELECT id, name, version, description, owner, location, license, framework,
               model_type, test_accuracy, model_metrics, inference_labels, model_structure,
               created_at, updated_at
        FROM models
        WHERE model_card_id = $1
        LIMIT 1
        """,
        asset_id,
    )
    return {
        "asset_type": "model_card",
        "asset_id": int(card["id"]),
        "card": dict(card),
        "model": dict(model) if model else None,
    }


async def _fetch_datasheet_snapshot(conn: asyncpg.Connection, asset_id: int) -> dict | None:
    datasheet = await conn.fetchrow(
        """
        SELECT d.identifier, d.uuid, d.publication_year, d.resource_type, d.resource_type_general,
               d.size, d.format, d.version, d.is_private, d.status, d.created_at, d.updated_at,
               d.publisher_id,
               p.name AS publisher_name, p.publisher_identifier, p.publisher_identifier_scheme,
               p.scheme_uri AS publisher_scheme_uri, p.lang AS publisher_lang
        FROM datasheets d
        LEFT JOIN datasheet_publishers p ON p.id = d.publisher_id
        WHERE d.identifier = $1
        """,
        asset_id,
    )
    if not datasheet:
        return None

    tables = {
        "creators": "SELECT * FROM datasheet_creators WHERE datasheet_id = $1 ORDER BY id",
        "titles": "SELECT * FROM datasheet_titles WHERE datasheet_id = $1 ORDER BY id",
        "subjects": "SELECT * FROM datasheet_subjects WHERE datasheet_id = $1 ORDER BY id",
        "contributors": "SELECT * FROM datasheet_contributors WHERE datasheet_id = $1 ORDER BY id",
        "dates": "SELECT * FROM datasheet_dates WHERE datasheet_id = $1 ORDER BY id",
        "alternate_identifiers": "SELECT * FROM datasheet_alternate_identifiers WHERE datasheet_id = $1 ORDER BY id",
        "related_identifiers": "SELECT * FROM datasheet_related_identifiers WHERE datasheet_id = $1 ORDER BY id",
        "rights_list": "SELECT * FROM datasheet_rights WHERE datasheet_id = $1 ORDER BY id",
        "descriptions": "SELECT * FROM datasheet_descriptions WHERE datasheet_id = $1 ORDER BY id",
        "geo_locations": "SELECT * FROM datasheet_geo_locations WHERE datasheet_id = $1 ORDER BY id",
        "funding_references": "SELECT * FROM datasheet_funding_references WHERE datasheet_id = $1 ORDER BY id",
    }
    nested: dict[str, list[dict]] = {}
    for key, query in tables.items():
        rows = await conn.fetch(query, asset_id)
        nested[key] = [dict(row) for row in rows]

    return {
        "asset_type": "datasheet",
        "asset_id": int(datasheet["identifier"]),
        "core": dict(datasheet),
        **nested,
    }


async def _fetch_asset_snapshot(conn: asyncpg.Connection, asset_type: str, asset_id: int) -> dict | None:
    if asset_type == "model_card":
        return await _fetch_model_card_snapshot(conn, asset_id)
    return await _fetch_datasheet_snapshot(conn, asset_id)


async def _update_model_card_in_tx(
    conn: asyncpg.Connection,
    asset_id: int,
    asset: ModelCardUpdate,
    organization: str,
    changed_by: str | None,
) -> AssetUpdateResult:
    existing = await _fetch_model_card_snapshot(conn, asset_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Model card not found")

    await _apply_model_card_update(conn, asset_id, asset)

    return AssetUpdateResult(
        asset_type="model_card",
        asset_id=asset_id,
        organization=organization,
    )


async def _replace_datasheet_children(conn: asyncpg.Connection, datasheet_id: int, asset: AssetDatasheetCreate) -> None:
    for table_name in (
        "datasheet_creators",
        "datasheet_titles",
        "datasheet_subjects",
        "datasheet_contributors",
        "datasheet_dates",
        "datasheet_alternate_identifiers",
        "datasheet_related_identifiers",
        "datasheet_rights",
        "datasheet_descriptions",
        "datasheet_geo_locations",
        "datasheet_funding_references",
    ):
        await conn.execute(f"DELETE FROM {table_name} WHERE datasheet_id = $1", datasheet_id)

    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_creators (
            datasheet_id, creator_name, name_type, lang, given_name, family_name,
            name_identifier, name_identifier_scheme, name_id_scheme_uri,
            affiliation, affiliation_identifier, affiliation_identifier_scheme, affiliation_scheme_uri
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """,
        [
            (
                datasheet_id,
                creator.creator_name,
                creator.name_type,
                creator.lang,
                creator.given_name,
                creator.family_name,
                creator.name_identifier,
                creator.name_identifier_scheme,
                creator.name_id_scheme_uri,
                creator.affiliation,
                creator.affiliation_identifier,
                creator.affiliation_identifier_scheme,
                creator.affiliation_scheme_uri,
            )
            for creator in asset.creators
        ],
    )
    await _insert_many(conn, "INSERT INTO datasheet_titles (datasheet_id, title, title_type, lang) VALUES ($1, $2, $3, $4)",
        [(datasheet_id, title.title, title.title_type, title.lang) for title in asset.titles])
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_subjects (
            datasheet_id, subject, subject_scheme, scheme_uri, value_uri, classification_code, lang
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        [(datasheet_id, subject.subject, subject.subject_scheme, subject.scheme_uri, subject.value_uri, subject.classification_code, subject.lang) for subject in asset.subjects],
    )
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_contributors (
            datasheet_id, contributor_type, contributor_name, name_type, given_name, family_name,
            name_identifier, name_identifier_scheme, name_id_scheme_uri,
            affiliation, affiliation_identifier, affiliation_identifier_scheme, affiliation_scheme_uri
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """,
        [(datasheet_id, c.contributor_type, c.contributor_name, c.name_type, c.given_name, c.family_name, c.name_identifier, c.name_identifier_scheme, c.name_id_scheme_uri, c.affiliation, c.affiliation_identifier, c.affiliation_identifier_scheme, c.affiliation_scheme_uri) for c in asset.contributors],
    )
    await _insert_many(conn, "INSERT INTO datasheet_dates (datasheet_id, date, date_type, date_information) VALUES ($1, $2, $3, $4)",
        [(datasheet_id, item.date, item.date_type, item.date_information) for item in asset.dates])
    await _insert_many(conn, "INSERT INTO datasheet_alternate_identifiers (datasheet_id, alternate_identifier, alternate_identifier_type) VALUES ($1, $2, $3)",
        [(datasheet_id, item.alternate_identifier, item.alternate_identifier_type) for item in asset.alternate_identifiers])
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_related_identifiers (
            datasheet_id, related_identifier, related_identifier_type, relation_type,
            related_metadata_scheme, scheme_uri, scheme_type, resource_type_general
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        [(datasheet_id, item.related_identifier, item.related_identifier_type, item.relation_type, item.related_metadata_scheme, item.scheme_uri, item.scheme_type, item.resource_type_general) for item in asset.related_identifiers],
    )
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_rights (
            datasheet_id, rights, rights_uri, rights_identifier, rights_identifier_scheme, scheme_uri, lang
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        [(datasheet_id, item.rights, item.rights_uri, item.rights_identifier, item.rights_identifier_scheme, item.scheme_uri, item.lang) for item in asset.rights_list],
    )
    await _insert_many(conn, "INSERT INTO datasheet_descriptions (datasheet_id, description, description_type, lang) VALUES ($1, $2, $3, $4)",
        [(datasheet_id, item.description, item.description_type, item.lang) for item in asset.descriptions])
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_geo_locations (
            datasheet_id, geo_location_place, point_longitude, point_latitude,
            box_west, box_east, box_south, box_north, polygon
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
        """,
        [(datasheet_id, item.geo_location_place, item.point_longitude, item.point_latitude, item.box_west, item.box_east, item.box_south, item.box_north, json.dumps(item.polygon) if item.polygon is not None else None) for item in asset.geo_locations],
    )
    await _insert_many(
        conn,
        """
        INSERT INTO datasheet_funding_references (
            datasheet_id, funder_name, funder_identifier, funder_identifier_type,
            scheme_uri, award_number, award_uri, award_title
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        [(datasheet_id, item.funder_name, item.funder_identifier, item.funder_identifier_type, item.scheme_uri, item.award_number, item.award_uri, item.award_title) for item in asset.funding_references],
    )


async def _update_datasheet_in_tx(
    conn: asyncpg.Connection,
    asset_id: int,
    asset: AssetDatasheetCreate,
    organization: str,
    changed_by: str | None,
) -> AssetUpdateResult:
    existing = await _fetch_datasheet_snapshot(conn, asset_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Datasheet not found")

    publisher_id = await _find_publisher_id(conn, asset.publisher.model_dump(exclude_none=True) if asset.publisher else None)

    await conn.execute(
        """
        UPDATE datasheets SET
            publication_year = $2, resource_type = $3, resource_type_general = $4,
            size = $5, format = $6, version = $7, is_private = $8,
            publisher_id = $9, updated_at = NOW()
        WHERE identifier = $1
        """,
        asset_id,
        asset.publication_year,
        asset.resource_type,
        asset.resource_type_general,
        asset.size,
        asset.format,
        asset.version,
        asset.is_private,
        publisher_id,
    )

    await _replace_datasheet_children(conn, asset_id, asset)
    return AssetUpdateResult(
        asset_type="datasheet",
        asset_id=asset_id,
        organization=organization,
    )


@router.get("/records", response_model=list[EditableRecordSummary])
async def list_editable_records(
    principal: AssetIngestPrincipal = Depends(require_asset_ingest_principal),
    pool: asyncpg.Pool = Depends(get_pool),
    q: str | None = Query(default=None, max_length=255),
    limit: int = Query(20, ge=1, le=100),
):
    query_text = q.strip() if q else None
    params: list[object] = []
    model_filter = ""
    datasheet_filter = ""
    if query_text:
        params.append(f"%{query_text}%")
        model_filter = f"""
            AND (
                mc.name ILIKE ${len(params)}
                OR COALESCE(mc.author, '') ILIKE ${len(params)}
                OR COALESCE(mc.short_description, '') ILIKE ${len(params)}
                OR COALESCE(mc.full_description, '') ILIKE ${len(params)}
                OR COALESCE(mc.keywords, '') ILIKE ${len(params)}
                OR COALESCE(mc.category, '') ILIKE ${len(params)}
                OR COALESCE(mc.input_data, '') ILIKE ${len(params)}
                OR COALESCE(mc.output_data, '') ILIKE ${len(params)}
                OR COALESCE(mc.citation, '') ILIKE ${len(params)}
                OR COALESCE(mc.foundational_model, '') ILIKE ${len(params)}
                OR COALESCE(mc.documentation, '') ILIKE ${len(params)}
                OR COALESCE(m.framework, '') ILIKE ${len(params)}
                OR COALESCE(m.license, '') ILIKE ${len(params)}
                OR COALESCE(m.owner, '') ILIKE ${len(params)}
                OR COALESCE(m.model_type, '') ILIKE ${len(params)}
            )
        """
        datasheet_filter = f"""
            AND (
                EXISTS (SELECT 1 FROM datasheet_titles dt WHERE dt.datasheet_id = d.identifier AND dt.title ILIKE ${len(params)})
                OR EXISTS (SELECT 1 FROM datasheet_creators dc WHERE dc.datasheet_id = d.identifier AND dc.creator_name ILIKE ${len(params)})
                OR EXISTS (SELECT 1 FROM datasheet_descriptions dd WHERE dd.datasheet_id = d.identifier AND dd.description ILIKE ${len(params)})
                OR EXISTS (SELECT 1 FROM datasheet_subjects ds WHERE ds.datasheet_id = d.identifier AND ds.subject ILIKE ${len(params)})
                OR EXISTS (SELECT 1 FROM datasheet_contributors dco WHERE dco.datasheet_id = d.identifier AND dco.contributor_name ILIKE ${len(params)})
                OR EXISTS (SELECT 1 FROM datasheet_related_identifiers dri WHERE dri.datasheet_id = d.identifier AND dri.related_identifier ILIKE ${len(params)})
                OR EXISTS (SELECT 1 FROM datasheet_alternate_identifiers dai WHERE dai.datasheet_id = d.identifier AND dai.alternate_identifier ILIKE ${len(params)})
                OR COALESCE(p.name, '') ILIKE ${len(params)}
                OR COALESCE(d.resource_type, '') ILIKE ${len(params)}
                OR COALESCE(d.resource_type_general, '') ILIKE ${len(params)}
                OR COALESCE(d.size, '') ILIKE ${len(params)}
                OR COALESCE(d.format, '') ILIKE ${len(params)}
                OR COALESCE(d.version, '') ILIKE ${len(params)}
            )
        """
    params.append(limit)
    query = f"""
        WITH datasheet_titles_first AS (
            SELECT DISTINCT ON (datasheet_id) datasheet_id, title
            FROM datasheet_titles
            ORDER BY datasheet_id, id
        ),
        datasheet_creators_first AS (
            SELECT DISTINCT ON (datasheet_id) datasheet_id, creator_name
            FROM datasheet_creators
            ORDER BY datasheet_id, id
        ),
        datasheet_descriptions_first AS (
            SELECT DISTINCT ON (datasheet_id) datasheet_id, description
            FROM datasheet_descriptions
            ORDER BY datasheet_id, id
        )
        SELECT *
        FROM (
            SELECT
                'model_card' AS asset_type,
                mc.id AS asset_id,
                mc.uuid AS asset_uuid,
                mc.name AS title,
                mc.author AS subtitle,
                COALESCE(mc.short_description, mc.full_description, mc.category) AS description,
                'Model Card' AS kind_label,
                mc.updated_at
            FROM model_cards mc
            LEFT JOIN models m ON m.model_card_id = mc.id
            WHERE TRUE
            {model_filter}
            UNION ALL
            SELECT
                'datasheet' AS asset_type,
                d.identifier AS asset_id,
                d.uuid AS asset_uuid,
                COALESCE(dtf.title, 'Untitled datasheet') AS title,
                COALESCE(dcf.creator_name, p.name, 'Published datasheet') AS subtitle,
                COALESCE(ddf.description, d.resource_type) AS description,
                'Datasheet' AS kind_label,
                d.updated_at
            FROM datasheets d
            LEFT JOIN datasheet_publishers p ON p.id = d.publisher_id
            LEFT JOIN datasheet_titles_first dtf ON dtf.datasheet_id = d.identifier
            LEFT JOIN datasheet_creators_first dcf ON dcf.datasheet_id = d.identifier
            LEFT JOIN datasheet_descriptions_first ddf ON ddf.datasheet_id = d.identifier
            WHERE d.status = 'approved'
            {datasheet_filter}
        ) combined
        ORDER BY updated_at DESC NULLS LAST, LOWER(title)
        LIMIT ${len(params)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [
        EditableRecordSummary(
            asset_type=row["asset_type"],
            asset_id=int(row["asset_id"]),
            asset_uuid=str(row["asset_uuid"]),
            title=row["title"],
            subtitle=row["subtitle"],
            description=row["description"],
            kind_label=row["kind_label"],
            updated_at=row["updated_at"].isoformat() if row["updated_at"] else None,
        )
        for row in rows
    ]


@router.patch("/model-cards/{asset_id}", response_model=AssetUpdateResult)
async def update_model_card_asset(
    request: Request,
    asset_id: int = Path(..., ge=1),
    asset: ModelCardUpdate = ...,
    principal: AssetIngestPrincipal = Depends(require_asset_ingest_principal),
    pool: asyncpg.Pool = Depends(get_pool),
):
    actor = get_request_actor(request)
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await _update_model_card_in_tx(conn, asset_id, asset, principal.organization, actor.username)


@router.patch("/datasheets/{asset_id}", response_model=AssetUpdateResult)
async def update_datasheet_asset(
    request: Request,
    asset_id: int = Path(..., ge=1),
    asset: AssetDatasheetCreate = ...,
    principal: AssetIngestPrincipal = Depends(require_asset_ingest_principal),
    pool: asyncpg.Pool = Depends(get_pool),
):
    actor = get_request_actor(request)
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await _update_datasheet_in_tx(conn, asset_id, asset, principal.organization, actor.username)



