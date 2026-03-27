import logging
import json
from collections.abc import Sequence
from typing import NamedTuple

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status

from rest_server.database import get_pool
from rest_server.deps import AssetIngestPrincipal, require_asset_ingest_principal
from rest_server.ingest_models import (
    AssetBulkDatasheetCreate,
    AssetBulkIngestResult,
    AssetBulkItemResult,
    AssetBulkModelCardCreate,
    AssetDatasheetCreate,
    AssetIngestResult,
    AssetModelCardCreate,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/assets", tags=["assets"])


class AssetRevisionContext(NamedTuple):
    asset_version: int
    previous_version_id: int | None
    root_version_id: int | None


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
    revision_context: AssetRevisionContext | None = None,
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

    model_card_id = await conn.fetchval(
        """
        INSERT INTO model_cards (
            name, version, is_private, is_gated, status,
            short_description, full_description, keywords, author, citation,
            input_data, input_type, output_data, foundational_model, category, documentation,
            created_at, updated_at, asset_version, previous_version_id, root_version_id
        )
        VALUES (
            $1, $2, $3, $4, 'approved',
            $5, $6, $7, $8, $9,
            $10, $11, $12, $13, $14, $15,
            NOW(), NOW(), $16, $17, $18
        )
        RETURNING id
        """,
        asset.name,
        asset.version,
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
        revision_context.asset_version if revision_context else 1,
        revision_context.previous_version_id if revision_context else None,
        revision_context.root_version_id if revision_context else None,
    )

    if revision_context is None:
        await conn.execute(
            """
            UPDATE model_cards
            SET root_version_id = $2
            WHERE id = $1
            """,
            model_card_id,
            model_card_id,
        )

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
        organization=organization,
        created=True,
    )


async def _find_publisher_id(conn: asyncpg.Connection, publisher: dict | None) -> int | None:
    if not publisher:
        return None
    existing_id = await conn.fetchval(
        """
        SELECT id
        FROM publishers
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
        INSERT INTO publishers (
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
    revision_context: AssetRevisionContext | None = None,
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
    datasheet_id = await conn.fetchval(
        """
        INSERT INTO datasheets (
            publication_year, resource_type, resource_type_general, size, format, version,
            is_private, status, created_at, updated_at, dataset_schema_id, publisher_id,
            asset_version, previous_version_id, root_version_id
        )
        VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, 'approved', NOW(), NOW(), $8, $9,
            $10, $11, $12
        )
        RETURNING identifier
        """,
        asset.publication_year,
        asset.resource_type,
        asset.resource_type_general,
        asset.size,
        asset.format,
        asset.version,
        asset.is_private,
        asset.dataset_schema_id,
        publisher_id,
        revision_context.asset_version if revision_context else 1,
        revision_context.previous_version_id if revision_context else None,
        revision_context.root_version_id if revision_context else None,
    )

    if revision_context is None:
        await conn.execute(
            """
            UPDATE datasheets
            SET root_version_id = $2
            WHERE identifier = $1
            """,
            datasheet_id,
            datasheet_id,
        )

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
            result = await _create_model_card_in_tx(conn, asset, principal.organization)
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
            result = await _create_datasheet_in_tx(conn, asset, principal.organization)
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
