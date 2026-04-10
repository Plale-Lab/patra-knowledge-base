"""Patra MCP Server — PostgreSQL-backed, read-only tools and resources."""

import asyncio
import json
import logging
import os
import re

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware

from mcp_server.db import (
    DOMAIN_TABLES,
    _serialize_row,
    close_pool,
    get_pool,
    init_pool,
)

log = logging.getLogger(__name__)

mcp = FastMCP("patra-mcp")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("modelcard://{mc_id}")
async def modelcard_resource(mc_id: int) -> str:
    """Model card with AI model detail."""
    pool = get_pool()
    async with pool.acquire() as conn:
        mc = await conn.fetchrow(
            """
            SELECT id, name, version, short_description, full_description,
                   keywords, author, input_data, output_data, input_type,
                   category, citation, foundational_model, is_gated
            FROM model_cards
            WHERE id = $1 AND is_private = false
            """,
            mc_id,
        )
        model = await conn.fetchrow(
            """
            SELECT id, name, version, description, owner, location,
                   license, framework, model_type, test_accuracy
            FROM models WHERE model_card_id = $1 LIMIT 1
            """,
            mc_id,
        ) if mc else None
    if not mc:
        return json.dumps({"error": "Not found"})
    result = _serialize_row(mc)
    result["ai_model"] = _serialize_row(model)
    return json.dumps(result)


@mcp.resource("modelcard://{mc_id}/download_url")
async def modelcard_download_url_resource(mc_id: int) -> str:
    """Model download URL."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT m.id AS model_id, m.name, m.version, m.location
            FROM models m
            JOIN model_cards mc ON mc.id = m.model_card_id
            WHERE mc.id = $1 AND mc.is_private = false
            LIMIT 1
            """,
            mc_id,
        )
    if not row or not row["location"]:
        return json.dumps({"error": "Not found"})
    return json.dumps(_serialize_row(row))


@mcp.resource("modelcard://{mc_id}/deployments")
async def modelcard_deployments_resource(mc_id: int) -> str:
    """Deployment history for a model card."""
    pool = get_pool()
    async with pool.acquire() as conn:
        model = await conn.fetchrow(
            """
            SELECT m.id
            FROM models m
            JOIN model_cards mc ON mc.id = m.model_card_id
            WHERE mc.id = $1 AND mc.is_private = false
            LIMIT 1
            """,
            mc_id,
        )
        if not model:
            return json.dumps([])
        rows = await conn.fetch(
            """
            SELECT
                e.id AS experiment_id,
                e.edge_device_id AS device_id,
                COALESCE(e.executed_at, e.model_used_at, e.start_at) AS timestamp,
                CASE WHEN e.executed_at IS NULL THEN 'active' ELSE 'completed' END AS status,
                e.precision, e.recall, e.f1_score, e.map_50, e.map_50_95
            FROM experiments e
            WHERE e.model_id = $1
            ORDER BY COALESCE(e.executed_at, e.model_used_at, e.start_at) DESC NULLS LAST, e.id DESC
            LIMIT 50
            """,
            model["id"],
        )
    return json.dumps([_serialize_row(r) for r in rows])


@mcp.resource("datasheet://{ds_id}")
async def datasheet_resource(ds_id: int) -> str:
    """Full datasheet with nested DataCite fields."""
    pool = get_pool()
    async with pool.acquire() as conn:
        core = await conn.fetchrow(
            """
            SELECT d.identifier, d.publication_year, d.resource_type,
                   d.resource_type_general, d.size, d.format, d.version,
                   d.updated_at, d.dataset_schema_id,
                   p.name AS publisher_name, p.publisher_identifier,
                   p.publisher_identifier_scheme, p.scheme_uri AS publisher_scheme_uri,
                   p.lang AS publisher_lang
            FROM datasheets d
            LEFT JOIN publishers p ON p.id = d.publisher_id
            WHERE d.identifier = $1 AND d.is_private = false
            """,
            ds_id,
        )
    if not core:
        return json.dumps({"error": "Not found"})

    async with pool.acquire() as conn:
        creators = await conn.fetch(
            """SELECT creator_name, name_type, lang, given_name, family_name,
                      name_identifier, name_identifier_scheme, name_id_scheme_uri,
                      affiliation, affiliation_identifier,
                      affiliation_identifier_scheme, affiliation_scheme_uri
               FROM datasheet_creators WHERE datasheet_id = $1 ORDER BY id""",
            ds_id,
        )
        titles = await conn.fetch(
            "SELECT title, title_type, lang FROM datasheet_titles WHERE datasheet_id = $1 ORDER BY id",
            ds_id,
        )
        subjects = await conn.fetch(
            """SELECT subject, subject_scheme, scheme_uri, value_uri,
                      classification_code, lang
               FROM datasheet_subjects WHERE datasheet_id = $1 ORDER BY id""",
            ds_id,
        )
        contributors = await conn.fetch(
            """SELECT contributor_type, contributor_name, name_type,
                      given_name, family_name,
                      name_identifier, name_identifier_scheme, name_id_scheme_uri,
                      affiliation, affiliation_identifier,
                      affiliation_identifier_scheme, affiliation_scheme_uri
               FROM datasheet_contributors WHERE datasheet_id = $1 ORDER BY id""",
            ds_id,
        )
        descriptions = await conn.fetch(
            "SELECT description, description_type, lang FROM datasheet_descriptions WHERE datasheet_id = $1 ORDER BY id",
            ds_id,
        )

    result = _serialize_row(core)
    result["creators"] = [_serialize_row(r) for r in creators]
    result["titles"] = [_serialize_row(r) for r in titles]
    result["subjects"] = [_serialize_row(r) for r in subjects]
    result["contributors"] = [_serialize_row(r) for r in contributors]
    result["descriptions"] = [_serialize_row(r) for r in descriptions]
    return json.dumps(result)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_modelcards(skip: int = 0, limit: int = 50) -> str:
    """List public model cards (paginated)."""
    limit = min(limit, 100)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, category, author, version, short_description, is_gated
            FROM model_cards
            WHERE is_private = false
            ORDER BY id
            LIMIT $1 OFFSET $2
            """,
            limit, skip,
        )
    return json.dumps([_serialize_row(r) for r in rows])


@mcp.tool()
async def search_modelcards(query: str, skip: int = 0, limit: int = 50) -> str:
    """Search public model cards by name, description, keywords, or author."""
    limit = min(limit, 100)
    pattern = f"%{query}%"
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, category, author, version, short_description, is_gated
            FROM model_cards
            WHERE is_private = false
              AND (name ILIKE $1 OR short_description ILIKE $1
                   OR keywords ILIKE $1 OR author ILIKE $1)
            ORDER BY id
            LIMIT $2 OFFSET $3
            """,
            pattern, limit, skip,
        )
    return json.dumps([_serialize_row(r) for r in rows])


@mcp.tool()
async def get_modelcard(mc_id: int) -> str:
    """Get a single public model card by ID, including AI model detail."""
    pool = get_pool()
    async with pool.acquire() as conn:
        mc = await conn.fetchrow(
            """
            SELECT id, name, version, short_description, full_description,
                   keywords, author, input_data, output_data, input_type,
                   category, citation, foundational_model, is_gated
            FROM model_cards
            WHERE id = $1 AND is_private = false
            """,
            mc_id,
        )
        model = await conn.fetchrow(
            """
            SELECT id, name, version, description, owner, location,
                   license, framework, model_type, test_accuracy
            FROM models WHERE model_card_id = $1 LIMIT 1
            """,
            mc_id,
        ) if mc else None
    if not mc:
        return json.dumps({"error": "Not found"})
    result = _serialize_row(mc)
    result["ai_model"] = _serialize_row(model)
    return json.dumps(result)


@mcp.tool()
async def list_datasheets(skip: int = 0, limit: int = 50) -> str:
    """List public datasheets (paginated)."""
    limit = min(limit, 100)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                d.identifier,
                t.title,
                c.creator,
                s.subject AS category
            FROM datasheets d
            LEFT JOIN LATERAL (
                SELECT title FROM datasheet_titles
                WHERE datasheet_id = d.identifier ORDER BY id LIMIT 1
            ) AS t ON TRUE
            LEFT JOIN LATERAL (
                SELECT creator_name AS creator FROM datasheet_creators
                WHERE datasheet_id = d.identifier ORDER BY id LIMIT 1
            ) AS c ON TRUE
            LEFT JOIN LATERAL (
                SELECT subject FROM datasheet_subjects
                WHERE datasheet_id = d.identifier ORDER BY id LIMIT 1
            ) AS s ON TRUE
            WHERE d.is_private = false
            ORDER BY d.identifier
            LIMIT $1 OFFSET $2
            """,
            limit, skip,
        )
    return json.dumps([_serialize_row(r) for r in rows])


@mcp.tool()
async def get_datasheet(ds_id: int) -> str:
    """Get a single public datasheet by identifier, including nested DataCite fields."""
    pool = get_pool()
    async with pool.acquire() as conn:
        core = await conn.fetchrow(
            """
            SELECT d.identifier, d.publication_year, d.resource_type,
                   d.resource_type_general, d.size, d.format, d.version,
                   d.updated_at, d.dataset_schema_id,
                   p.name AS publisher_name, p.publisher_identifier,
                   p.publisher_identifier_scheme, p.scheme_uri AS publisher_scheme_uri,
                   p.lang AS publisher_lang
            FROM datasheets d
            LEFT JOIN publishers p ON p.id = d.publisher_id
            WHERE d.identifier = $1 AND d.is_private = false
            """,
            ds_id,
        )
    if not core:
        return json.dumps({"error": "Not found"})

    async with pool.acquire() as conn:
        creators = await conn.fetch(
            """SELECT creator_name, name_type, lang, given_name, family_name,
                      name_identifier, name_identifier_scheme, name_id_scheme_uri,
                      affiliation, affiliation_identifier,
                      affiliation_identifier_scheme, affiliation_scheme_uri
               FROM datasheet_creators WHERE datasheet_id = $1 ORDER BY id""",
            ds_id,
        )
        titles = await conn.fetch(
            "SELECT title, title_type, lang FROM datasheet_titles WHERE datasheet_id = $1 ORDER BY id",
            ds_id,
        )
        subjects = await conn.fetch(
            """SELECT subject, subject_scheme, scheme_uri, value_uri,
                      classification_code, lang
               FROM datasheet_subjects WHERE datasheet_id = $1 ORDER BY id""",
            ds_id,
        )
        contributors = await conn.fetch(
            """SELECT contributor_type, contributor_name, name_type,
                      given_name, family_name,
                      name_identifier, name_identifier_scheme, name_id_scheme_uri,
                      affiliation, affiliation_identifier,
                      affiliation_identifier_scheme, affiliation_scheme_uri
               FROM datasheet_contributors WHERE datasheet_id = $1 ORDER BY id""",
            ds_id,
        )
        dates = await conn.fetch(
            "SELECT date, date_type, date_information FROM datasheet_dates WHERE datasheet_id = $1 ORDER BY id",
            ds_id,
        )
        alt_ids = await conn.fetch(
            """SELECT alternate_identifier, alternate_identifier_type
               FROM datasheet_alternate_identifiers WHERE datasheet_id = $1 ORDER BY id""",
            ds_id,
        )
        rel_ids = await conn.fetch(
            """SELECT related_identifier, related_identifier_type, relation_type,
                      related_metadata_scheme, scheme_uri, scheme_type, resource_type_general
               FROM datasheet_related_identifiers WHERE datasheet_id = $1 ORDER BY id""",
            ds_id,
        )
        rights = await conn.fetch(
            """SELECT rights, rights_uri, rights_identifier,
                      rights_identifier_scheme, scheme_uri, lang
               FROM datasheet_rights WHERE datasheet_id = $1 ORDER BY id""",
            ds_id,
        )
        descriptions = await conn.fetch(
            "SELECT description, description_type, lang FROM datasheet_descriptions WHERE datasheet_id = $1 ORDER BY id",
            ds_id,
        )
        geo = await conn.fetch(
            """SELECT geo_location_place, point_longitude, point_latitude,
                      box_west, box_east, box_south, box_north, polygon
               FROM datasheet_geo_locations WHERE datasheet_id = $1 ORDER BY id""",
            ds_id,
        )
        funding = await conn.fetch(
            """SELECT funder_name, funder_identifier, funder_identifier_type,
                      scheme_uri, award_number, award_uri, award_title
               FROM datasheet_funding_references WHERE datasheet_id = $1 ORDER BY id""",
            ds_id,
        )

    result = _serialize_row(core)
    result["creators"] = [_serialize_row(r) for r in creators]
    result["titles"] = [_serialize_row(r) for r in titles]
    result["subjects"] = [_serialize_row(r) for r in subjects]
    result["contributors"] = [_serialize_row(r) for r in contributors]
    result["dates"] = [_serialize_row(r) for r in dates]
    result["alternate_identifiers"] = [_serialize_row(r) for r in alt_ids]
    result["related_identifiers"] = [_serialize_row(r) for r in rel_ids]
    result["rights_list"] = [_serialize_row(r) for r in rights]
    result["descriptions"] = [_serialize_row(r) for r in descriptions]
    result["geo_locations"] = [_serialize_row(r) for r in geo]
    result["funding_references"] = [_serialize_row(r) for r in funding]
    return json.dumps(result)


@mcp.tool()
async def list_experiment_users(domain: str) -> str:
    """List distinct users with experiment events in a domain."""
    domain = "digital-ag" if domain == "digital-agriculture" else domain
    tables = DOMAIN_TABLES.get(domain)
    if not tables:
        return json.dumps({"error": f"Unknown domain: {domain}", "valid_domains": list(DOMAIN_TABLES.keys())})
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT DISTINCT user_id, user_id AS username
            FROM {tables['events']}
            ORDER BY user_id
        """)
    return json.dumps([_serialize_row(r) for r in rows])


@mcp.tool()
async def get_experiment_summary(domain: str, user_id: str) -> str:
    """Experiment summary table for a given user in a domain."""
    domain = "digital-ag" if domain == "digital-agriculture" else domain
    tables = DOMAIN_TABLES.get(domain)
    if not tables:
        return json.dumps({"error": f"Unknown domain: {domain}", "valid_domains": list(DOMAIN_TABLES.keys())})
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT
                experiment_id, user_id, model_id, device_id,
                MIN(image_receiving_timestamp) AS start_at,
                MAX(total_images) AS total_images,
                SUM(CASE WHEN image_decision = 'Save' THEN 1 ELSE 0 END) AS saved_images,
                MAX(precision) AS precision,
                MAX(recall) AS recall,
                MAX(f1_score) AS f1_score
            FROM {tables['events']}
            WHERE user_id = $1
            GROUP BY experiment_id, user_id, model_id, device_id
            ORDER BY MIN(image_receiving_timestamp) DESC
        """, user_id)
    return json.dumps([_serialize_row(r) for r in rows])


@mcp.tool()
async def list_user_experiments(domain: str, user_id: str) -> str:
    """List experiments for a user in a domain (for experiment selector)."""
    domain = "digital-ag" if domain == "digital-agriculture" else domain
    tables = DOMAIN_TABLES.get(domain)
    if not tables:
        return json.dumps({"error": f"Unknown domain: {domain}", "valid_domains": list(DOMAIN_TABLES.keys())})
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT DISTINCT
                experiment_id,
                MIN(image_receiving_timestamp) AS start_at,
                device_id,
                model_id
            FROM {tables['events']}
            WHERE user_id = $1
            GROUP BY experiment_id, device_id, model_id
            ORDER BY MIN(image_receiving_timestamp) DESC
            """,
            user_id,
        )
    return json.dumps([_serialize_row(r) for r in rows])


@mcp.tool()
async def get_experiment_detail(domain: str, experiment_id: str) -> str:
    """Full experiment detail — latest metrics snapshot."""
    domain = "digital-ag" if domain == "digital-agriculture" else domain
    tables = DOMAIN_TABLES.get(domain)
    if not tables:
        return json.dumps({"error": f"Unknown domain: {domain}", "valid_domains": list(DOMAIN_TABLES.keys())})
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(f"""
            SELECT * FROM {tables['events']}
            WHERE experiment_id = $1
            ORDER BY image_count DESC
            LIMIT 1
        """, experiment_id)
    if not r:
        return json.dumps({"error": "Experiment not found"})
    return json.dumps(_serialize_row(r))


@mcp.tool()
async def get_experiment_images(domain: str, experiment_id: str, skip: int = 0, limit: int = 100) -> str:
    """Raw image data table for an experiment (paginated)."""
    domain = "digital-ag" if domain == "digital-agriculture" else domain
    tables = DOMAIN_TABLES.get(domain)
    if not tables:
        return json.dumps({"error": f"Unknown domain: {domain}", "valid_domains": list(DOMAIN_TABLES.keys())})
    limit = min(limit, 500)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT
                image_name, ground_truth, label, probability,
                image_decision, flattened_scores,
                image_receiving_timestamp, image_scoring_timestamp
            FROM {tables['events']}
            WHERE experiment_id = $1
            ORDER BY image_receiving_timestamp ASC
            LIMIT $2 OFFSET $3
        """, experiment_id, limit, skip)
    return json.dumps([_serialize_row(r) for r in rows])


@mcp.tool()
async def get_experiment_power(domain: str, experiment_id: str) -> str:
    """Power consumption breakdown for an experiment."""
    domain = "digital-ag" if domain == "digital-agriculture" else domain
    tables = DOMAIN_TABLES.get(domain)
    if not tables:
        return json.dumps({"error": f"Unknown domain: {domain}", "valid_domains": list(DOMAIN_TABLES.keys())})
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            f"SELECT * FROM {tables['power']} WHERE experiment_id = $1",
            experiment_id,
        )
    if not r:
        return json.dumps(None)
    return json.dumps(_serialize_row(r))


@mcp.tool()
async def list_stored_procedures(schema: str = "public", include_system: bool = False) -> str:
    """List PostgreSQL procedures/functions available in a schema."""
    if not _IDENT_RE.match(schema):
        return json.dumps({"error": f"Invalid schema identifier: {schema}"})

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                n.nspname AS schema_name,
                p.proname AS routine_name,
                p.prokind,
                pg_get_function_identity_arguments(p.oid) AS arg_signature,
                pg_get_function_result(p.oid) AS result_type
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE ($1::bool OR n.nspname NOT IN ('pg_catalog', 'information_schema'))
              AND n.nspname = $2
            ORDER BY n.nspname, p.proname, arg_signature
            """,
            include_system,
            schema,
        )

    routines = []
    for row in rows:
        kind = row["prokind"]
        routines.append(
            {
                "schema": row["schema_name"],
                "name": row["routine_name"],
                "kind": "procedure" if kind == "p" else "function",
                "arguments": row["arg_signature"],
                "returns": row["result_type"],
            }
        )
    return json.dumps(routines)


@mcp.tool()
async def call_stored_procedure(name: str, args_json: str = "[]", schema: str = "public") -> str:
    """Call a PostgreSQL stored function/procedure by name with positional args."""
    if not _IDENT_RE.match(schema):
        return json.dumps({"error": f"Invalid schema identifier: {schema}"})
    if not _IDENT_RE.match(name):
        return json.dumps({"error": f"Invalid routine identifier: {name}"})

    try:
        args = json.loads(args_json)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Invalid args_json: {exc}"})

    if not isinstance(args, list):
        return json.dumps({"error": "args_json must decode to a JSON array"})

    pool = get_pool()
    async with pool.acquire() as conn:
        routine = await conn.fetchrow(
            """
            SELECT p.prokind
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = $1 AND p.proname = $2
            ORDER BY p.oid
            LIMIT 1
            """,
            schema,
            name,
        )
        if not routine:
            return json.dumps({"error": f"Routine not found: {schema}.{name}"})

        placeholders = ", ".join(f"${idx}" for idx in range(1, len(args) + 1))
        qualified = f'"{schema}"."{name}"'

        if routine["prokind"] == "p":
            sql = f"CALL {qualified}({placeholders})"
            await conn.execute(sql, *args)
            return json.dumps({"status": "ok", "routine": f"{schema}.{name}", "kind": "procedure"})

        sql = f"SELECT * FROM {qualified}({placeholders})"
        rows = await conn.fetch(sql, *args)
        return json.dumps([_serialize_row(r) for r in rows])


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("MCP_PORT", "8050"))

    async def run():
        await init_pool()
        app = mcp.sse_app()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
        server = uvicorn.Server(config)
        try:
            await server.serve()
        finally:
            await close_pool()

    asyncio.run(run())
