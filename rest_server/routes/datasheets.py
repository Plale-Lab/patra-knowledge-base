import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query

import asyncpg

from rest_server.database import get_pool
from rest_server.deps import get_include_private, require_admin_actor, require_authenticated_actor, PatraActor
from rest_server.errors import asset_not_available_or_visible, not_found
from rest_server.models import (
    DatasheetAlternateIdentifier,
    DatasheetContributor,
    DatasheetCreator,
    DatasheetDate,
    DatasheetDescription,
    DatasheetDetail,
    DatasheetFundingReference,
    DatasheetGeoLocation,
    DatasheetPublisher,
    DatasheetRelatedIdentifier,
    DatasheetRights,
    DatasheetSubject,
    DatasheetSummary,
    DatasheetTitle,
    DatasheetUpdate,
)

router = APIRouter(tags=["datasheets"])


def _normalize_polygon(value):
    if value in (None, "", "null"):
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


@router.get("/datasheets", response_model=list[DatasheetSummary])
async def list_datasheets(
    pool: asyncpg.Pool = Depends(get_pool),
    include_private: bool = Depends(get_include_private),
    q: str | None = Query(default=None, max_length=255),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """List all datasheets. JWT bearer shows private; unauthenticated shows only public.

    Summary view flattens the first title, creator, and subject (category) per datasheet.
    """
    params: list[object] = []
    filters: list[str] = []
    if not include_private:
        filters.append("d.is_private = false")
    query_text = q.strip() if q else None
    if query_text:
        params.append(f"%{query_text}%")
        filters.append(
            f"""(
                EXISTS (
                    SELECT 1
                    FROM datasheet_titles dt
                    WHERE dt.datasheet_id = d.identifier
                      AND dt.title ILIKE ${len(params)}
                )
                OR EXISTS (
                    SELECT 1
                    FROM datasheet_creators dc
                    WHERE dc.datasheet_id = d.identifier
                      AND dc.creator_name ILIKE ${len(params)}
                )
                OR EXISTS (
                    SELECT 1
                    FROM datasheet_descriptions dd
                    WHERE dd.datasheet_id = d.identifier
                      AND dd.description ILIKE ${len(params)}
                )
            )"""
        )
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.extend([limit, skip])
    query = f"""
        SELECT
            d.identifier,
            d.uuid,
            t.title,
            c.creator,
            s.subject AS category,
            d.is_private,
            d.updated_at
        FROM datasheets d
        LEFT JOIN LATERAL (
            SELECT title
            FROM datasheet_titles
            WHERE datasheet_id = d.identifier
            ORDER BY id
            LIMIT 1
        ) AS t ON TRUE
        LEFT JOIN LATERAL (
            SELECT creator_name AS creator
            FROM datasheet_creators
            WHERE datasheet_id = d.identifier
            ORDER BY id
            LIMIT 1
        ) AS c ON TRUE
        LEFT JOIN LATERAL (
            SELECT subject
            FROM datasheet_subjects
            WHERE datasheet_id = d.identifier
            ORDER BY id
            LIMIT 1
        ) AS s ON TRUE
        {where}
        ORDER BY LOWER(COALESCE(t.title, '')), d.identifier
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [
        DatasheetSummary(
            identifier=r["identifier"],
            uuid=str(r["uuid"]),
            title=r["title"] or "",
            creator=r["creator"],
            category=r["category"],
            is_private=bool(r["is_private"]),
            updated_at=r["updated_at"].isoformat() if r["updated_at"] else None,
        )
        for r in rows
    ]


async def resolve_datasheet_identifier(conn: asyncpg.Connection, datasheet_uuid: UUID | str) -> int | None:
    """Resolve a datasheet's external uuid to its internal bigint identifier (FK target).

    Returns None for both a malformed uuid string and a well-formed uuid that
    doesn't match any datasheet, so callers can treat both as "not found".
    """
    try:
        normalized = str(UUID(str(datasheet_uuid)))
    except ValueError:
        return None
    return await conn.fetchval("SELECT identifier FROM datasheets WHERE uuid = $1::uuid", normalized)


@router.get("/datasheet/{uuid}", response_model=DatasheetDetail)
async def get_datasheet(
    uuid: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
    include_private: bool = Depends(get_include_private),
):
    """Get a single datasheet by UUID. Returns 404 if private and caller has no JWT."""
    core_query = """
        SELECT
            d.identifier,
            d.uuid,
            d.publication_year,
            d.resource_type,
            d.resource_type_general,
            d.size,
            d.format,
            d.version,
            d.is_private,
            d.updated_at,
            p.name AS publisher_name,
            p.publisher_identifier,
            p.publisher_identifier_scheme,
            p.scheme_uri AS publisher_scheme_uri,
            p.lang AS publisher_lang
        FROM datasheets d
        LEFT JOIN datasheet_publishers p ON p.id = d.publisher_id
        WHERE d.uuid = $1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(core_query, uuid)
    if not row:
        raise asset_not_available_or_visible()
    if row["is_private"] and not include_private:
        raise asset_not_available_or_visible()

    identifier = int(row["identifier"])

    async with pool.acquire() as conn:
        creators_rows = await conn.fetch(
            """
            SELECT creator_name, name_type, lang, given_name, family_name,
                   name_identifier, name_identifier_scheme, name_id_scheme_uri,
                   affiliation, affiliation_identifier,
                   affiliation_identifier_scheme, affiliation_scheme_uri
            FROM datasheet_creators
            WHERE datasheet_id = $1
            ORDER BY id
            """,
            identifier,
        )
        titles_rows = await conn.fetch(
            """
            SELECT title, title_type, lang
            FROM datasheet_titles
            WHERE datasheet_id = $1
            ORDER BY id
            """,
            identifier,
        )
        subjects_rows = await conn.fetch(
            """
            SELECT subject, subject_scheme, scheme_uri, value_uri,
                   classification_code, lang
            FROM datasheet_subjects
            WHERE datasheet_id = $1
            ORDER BY id
            """,
            identifier,
        )
        contributors_rows = await conn.fetch(
            """
            SELECT contributor_type, contributor_name, name_type,
                   given_name, family_name,
                   name_identifier, name_identifier_scheme, name_id_scheme_uri,
                   affiliation, affiliation_identifier,
                   affiliation_identifier_scheme, affiliation_scheme_uri
            FROM datasheet_contributors
            WHERE datasheet_id = $1
            ORDER BY id
            """,
            identifier,
        )
        dates_rows = await conn.fetch(
            """
            SELECT date, date_type, date_information
            FROM datasheet_dates
            WHERE datasheet_id = $1
            ORDER BY id
            """,
            identifier,
        )
        alt_ids_rows = await conn.fetch(
            """
            SELECT alternate_identifier, alternate_identifier_type
            FROM datasheet_alternate_identifiers
            WHERE datasheet_id = $1
            ORDER BY id
            """,
            identifier,
        )
        rel_ids_rows = await conn.fetch(
            """
            SELECT related_identifier, related_identifier_type, relation_type,
                   related_metadata_scheme, scheme_uri, scheme_type,
                   resource_type_general
            FROM datasheet_related_identifiers
            WHERE datasheet_id = $1
            ORDER BY id
            """,
            identifier,
        )
        rights_rows = await conn.fetch(
            """
            SELECT rights, rights_uri, rights_identifier,
                   rights_identifier_scheme, scheme_uri, lang
            FROM datasheet_rights
            WHERE datasheet_id = $1
            ORDER BY id
            """,
            identifier,
        )
        descriptions_rows = await conn.fetch(
            """
            SELECT description, description_type, lang
            FROM datasheet_descriptions
            WHERE datasheet_id = $1
            ORDER BY id
            """,
            identifier,
        )
        geo_rows = await conn.fetch(
            """
            SELECT geo_location_place,
                   point_longitude, point_latitude,
                   box_west, box_east, box_south, box_north,
                   polygon
            FROM datasheet_geo_locations
            WHERE datasheet_id = $1
            ORDER BY id
            """,
            identifier,
        )
        funding_rows = await conn.fetch(
            """
            SELECT funder_name, funder_identifier, funder_identifier_type,
                   scheme_uri, award_number, award_uri, award_title
            FROM datasheet_funding_references
            WHERE datasheet_id = $1
            ORDER BY id
            """,
            identifier,
        )

    publisher = None
    if row["publisher_name"] is not None:
        publisher = DatasheetPublisher(
            name=row["publisher_name"],
            publisher_identifier=row["publisher_identifier"],
            publisher_identifier_scheme=row["publisher_identifier_scheme"],
            scheme_uri=row["publisher_scheme_uri"],
            lang=row["publisher_lang"],
        )

    return DatasheetDetail(
        identifier=row["identifier"],
        uuid=str(row["uuid"]),
        publication_year=row["publication_year"],
        resource_type=row["resource_type"],
        resource_type_general=row["resource_type_general"],
        size=row["size"],
        format=row["format"],
        version=row["version"],
        is_private=row["is_private"],
        updated_at=row["updated_at"].isoformat() if row["updated_at"] else None,
        creators=[
            DatasheetCreator(
                creator_name=r["creator_name"],
                name_type=r["name_type"],
                lang=r["lang"],
                given_name=r["given_name"],
                family_name=r["family_name"],
                name_identifier=r["name_identifier"],
                name_identifier_scheme=r["name_identifier_scheme"],
                name_id_scheme_uri=r["name_id_scheme_uri"],
                affiliation=r["affiliation"],
                affiliation_identifier=r["affiliation_identifier"],
                affiliation_identifier_scheme=r["affiliation_identifier_scheme"],
                affiliation_scheme_uri=r["affiliation_scheme_uri"],
            )
            for r in creators_rows
        ],
        titles=[
            DatasheetTitle(
                title=r["title"],
                title_type=r["title_type"],
                lang=r["lang"],
            )
            for r in titles_rows
        ],
        publisher=publisher,
        subjects=[
            DatasheetSubject(
                subject=r["subject"],
                subject_scheme=r["subject_scheme"],
                scheme_uri=r["scheme_uri"],
                value_uri=r["value_uri"],
                classification_code=r["classification_code"],
                lang=r["lang"],
            )
            for r in subjects_rows
        ],
        contributors=[
            DatasheetContributor(
                contributor_type=r["contributor_type"],
                contributor_name=r["contributor_name"],
                name_type=r["name_type"],
                given_name=r["given_name"],
                family_name=r["family_name"],
                name_identifier=r["name_identifier"],
                name_identifier_scheme=r["name_identifier_scheme"],
                name_id_scheme_uri=r["name_id_scheme_uri"],
                affiliation=r["affiliation"],
                affiliation_identifier=r["affiliation_identifier"],
                affiliation_identifier_scheme=r["affiliation_identifier_scheme"],
                affiliation_scheme_uri=r["affiliation_scheme_uri"],
            )
            for r in contributors_rows
        ],
        dates=[
            DatasheetDate(
                date=r["date"],
                date_type=r["date_type"],
                date_information=r["date_information"],
            )
            for r in dates_rows
        ],
        alternate_identifiers=[
            DatasheetAlternateIdentifier(
                alternate_identifier=r["alternate_identifier"],
                alternate_identifier_type=r["alternate_identifier_type"],
            )
            for r in alt_ids_rows
        ],
        related_identifiers=[
            DatasheetRelatedIdentifier(
                related_identifier=r["related_identifier"],
                related_identifier_type=r["related_identifier_type"],
                relation_type=r["relation_type"],
                related_metadata_scheme=r["related_metadata_scheme"],
                scheme_uri=r["scheme_uri"],
                scheme_type=r["scheme_type"],
                resource_type_general=r["resource_type_general"],
            )
            for r in rel_ids_rows
        ],
        rights_list=[
            DatasheetRights(
                rights=r["rights"],
                rights_uri=r["rights_uri"],
                rights_identifier=r["rights_identifier"],
                rights_identifier_scheme=r["rights_identifier_scheme"],
                scheme_uri=r["scheme_uri"],
                lang=r["lang"],
            )
            for r in rights_rows
        ],
        descriptions=[
            DatasheetDescription(
                description=r["description"],
                description_type=r["description_type"],
                lang=r["lang"],
            )
            for r in descriptions_rows
        ],
        geo_locations=[
            DatasheetGeoLocation(
                geo_location_place=r["geo_location_place"],
                point_longitude=float(r["point_longitude"]) if r["point_longitude"] is not None else None,
                point_latitude=float(r["point_latitude"]) if r["point_latitude"] is not None else None,
                box_west=float(r["box_west"]) if r["box_west"] is not None else None,
                box_east=float(r["box_east"]) if r["box_east"] is not None else None,
                box_south=float(r["box_south"]) if r["box_south"] is not None else None,
                box_north=float(r["box_north"]) if r["box_north"] is not None else None,
                polygon=_normalize_polygon(r["polygon"]),
            )
            for r in geo_rows
        ],
        funding_references=[
            DatasheetFundingReference(
                funder_name=r["funder_name"],
                funder_identifier=r["funder_identifier"],
                funder_identifier_type=r["funder_identifier_type"],
                scheme_uri=r["scheme_uri"],
                award_number=r["award_number"],
                award_uri=r["award_uri"],
                award_title=r["award_title"],
            )
            for r in funding_rows
        ],
    )


_DS_UPDATE_COLUMNS = {
    "version": "version",
    "publication_year": "publication_year",
    "is_private": "is_private",
}


@router.put("/datasheet/{uuid}", response_model=DatasheetDetail)
async def update_datasheet(
    body: DatasheetUpdate,
    uuid: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
    include_private: bool = Depends(get_include_private),
    actor: PatraActor = Depends(require_authenticated_actor),
):
    """Update a datasheet (authenticated users only)."""
    async with pool.acquire() as conn:
        identifier_val = await conn.fetchval(
            "SELECT identifier FROM datasheets WHERE uuid = $1", uuid
        )
    if identifier_val is None:
        raise asset_not_available_or_visible()
    identifier = int(identifier_val)

    updates = body.model_dump(exclude_none=True)
    title_val = updates.pop("title", None)
    description_val = updates.pop("description", None)

    if not updates and title_val is None and description_val is None:
        return await get_datasheet(uuid=uuid, pool=pool, include_private=include_private)

    async with pool.acquire() as conn:
        # Update core datasheet columns
        if updates:
            set_parts = []
            values = []
            idx = 2  # $1 is the identifier
            for field, value in updates.items():
                col = _DS_UPDATE_COLUMNS.get(field)
                if col is None:
                    continue
                set_parts.append(f"{col} = ${idx}")
                values.append(value)
                idx += 1

            if set_parts:
                set_parts.append("updated_at = NOW()")
                query = f"UPDATE datasheets SET {', '.join(set_parts)} WHERE identifier = $1"
                result = await conn.execute(query, identifier, *values)
                if result == "UPDATE 0":
                    raise asset_not_available_or_visible()

        # Update first title row (or insert if none exists)
        if title_val is not None:
            existing_title = await conn.fetchval(
                "SELECT id FROM datasheet_titles WHERE datasheet_id = $1 ORDER BY id LIMIT 1",
                identifier,
            )
            if existing_title is not None:
                await conn.execute(
                    "UPDATE datasheet_titles SET title = $1 WHERE id = $2",
                    title_val, existing_title,
                )
            else:
                await conn.execute(
                    "INSERT INTO datasheet_titles (datasheet_id, title) VALUES ($1, $2)",
                    identifier, title_val,
                )

        # Update first description row (or insert if none exists)
        if description_val is not None:
            existing_desc = await conn.fetchval(
                "SELECT id FROM datasheet_descriptions WHERE datasheet_id = $1 ORDER BY id LIMIT 1",
                identifier,
            )
            if existing_desc is not None:
                await conn.execute(
                    "UPDATE datasheet_descriptions SET description = $1 WHERE id = $2",
                    description_val, existing_desc,
                )
            else:
                await conn.execute(
                    "INSERT INTO datasheet_descriptions (datasheet_id, description, description_type) VALUES ($1, $2, 'Abstract')",
                    identifier, description_val,
                )

    return await get_datasheet(uuid=uuid, pool=pool, include_private=include_private)


@router.delete("/datasheet/{uuid}", status_code=204)
async def delete_datasheet(
    uuid: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
    actor: PatraActor = Depends(require_admin_actor),
):
    """Delete a datasheet (admin only). Child rows cascade; linked model_cards.training_datasheet_id is set NULL."""
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM datasheets WHERE uuid = $1", uuid)
    if result == "DELETE 0":
        raise not_found("Datasheet")
