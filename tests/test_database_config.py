import ssl

import pytest

from rest_server import database


def test_build_connection_options_enables_direct_tls_for_tapis_pods():
    dsn, ssl_arg, direct_tls = database._build_connection_options(
        "postgresql://user:pass@patradb.pods.icicleai.tapis.io:5432/patradb?sslmode=require"
    )

    assert dsn == "postgresql://user:pass@patradb.pods.icicleai.tapis.io:443/patradb"
    assert isinstance(ssl_arg, ssl.SSLContext)
    assert direct_tls is True


def test_build_connection_options_uses_regular_tls_for_non_pod_hosts():
    dsn, ssl_arg, direct_tls = database._build_connection_options(
        "postgresql://user:pass@localhost:5432/patradb?sslmode=require"
    )

    assert dsn == "postgresql://user:pass@localhost:5432/patradb"
    assert isinstance(ssl_arg, ssl.SSLContext)
    assert direct_tls is False


@pytest.mark.asyncio
async def test_init_pool_passes_direct_tls_for_tapis_pods(monkeypatch):
    captured = {}

    async def fake_create_pool(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@patradb.pods.icicleai.tapis.io:5432/patradb?sslmode=require",
    )
    monkeypatch.setattr(database.asyncpg, "create_pool", fake_create_pool)
    database._pool = None

    pool = await database.init_pool()

    assert pool is not None
    assert captured["args"] == ("postgresql://user:pass@patradb.pods.icicleai.tapis.io:443/patradb",)
    assert captured["kwargs"]["direct_tls"] is True
    assert isinstance(captured["kwargs"]["ssl"], ssl.SSLContext)

    database._pool = None
