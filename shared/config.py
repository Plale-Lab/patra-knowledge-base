"""Centralised environment configuration for the Patra backend.

All functions read ``os.getenv`` at call time (not import time) so that
``monkeypatch.setenv`` in tests works transparently.
"""

import os


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_database_url() -> str | None:
    return os.getenv("DATABASE_URL")


# ---------------------------------------------------------------------------
# REST server startup
# ---------------------------------------------------------------------------

def get_db_startup_timeout_seconds() -> int:
    return int(os.getenv("DB_STARTUP_TIMEOUT_SECONDS", "12") or "12")


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() == "true"


def is_ask_patra_enabled() -> bool:
    return _env_flag("ENABLE_ASK_PATRA", default=False)


def is_domain_experiments_enabled() -> bool:
    return _env_flag("ENABLE_DOMAIN_EXPERIMENTS", default=False)


def is_hf_import_enabled() -> bool:
    return _env_flag("ENABLE_HF_IMPORT", default=False)


# ---------------------------------------------------------------------------
# Auth / admin
# ---------------------------------------------------------------------------

_DEFAULT_ADMIN_USERS = frozenset({"williamq96"})


def get_admin_users_csv() -> str:
    return os.getenv("PATRA_ADMIN_USERS", "").strip()


def get_default_admin_users() -> frozenset[str]:
    return _DEFAULT_ADMIN_USERS


def get_asset_ingest_keys_json() -> str:
    return os.getenv("PATRA_ASSET_INGEST_KEYS_JSON", "").strip()


# ---------------------------------------------------------------------------
# Tapis OAuth2 (authorization-code redirect login)
# ---------------------------------------------------------------------------

def get_tapis_tenant_base_url() -> str:
    return os.getenv("TAPIS_TENANT_BASE_URL", "https://icicleai.tapis.io").rstrip("/")


def get_tapis_oauth_client_id() -> str:
    return os.getenv("TAPIS_OAUTH_CLIENT_ID", "").strip()


def get_tapis_oauth_client_key() -> str:
    return os.getenv("TAPIS_OAUTH_CLIENT_KEY", "").strip()


# ---------------------------------------------------------------------------
# LLM / Agent defaults  (shared across agent-tools and ingestion)
# ---------------------------------------------------------------------------

def get_llm_api_base() -> str:
    return os.getenv("PATRA_AGENT_LLM_API_BASE", "http://127.0.0.1:1234/v1")


def get_llm_model() -> str:
    return os.getenv("PATRA_AGENT_LLM_MODEL", "qwen/qwen3.5-9b")


def get_llm_api_key() -> str:
    return os.getenv("PATRA_AGENT_LLM_API_KEY", "lm-studio")


def get_llm_timeout_seconds() -> int:
    return int(os.getenv("PATRA_AGENT_LLM_TIMEOUT_SECONDS", "60") or "60")


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

def get_mcp_port() -> int:
    return int(os.getenv("MCP_PORT", "8050"))
