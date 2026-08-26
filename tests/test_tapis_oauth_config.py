"""shared.config Tapis OAuth2 getters."""

from shared.config import (
    get_tapis_oauth_client_id,
    get_tapis_oauth_client_key,
    get_tapis_tenant_base_url,
)


def test_tapis_tenant_base_url_defaults_to_icicleai(monkeypatch):
    monkeypatch.delenv("TAPIS_TENANT_BASE_URL", raising=False)
    assert get_tapis_tenant_base_url() == "https://icicleai.tapis.io"


def test_tapis_tenant_base_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("TAPIS_TENANT_BASE_URL", "https://example.tapis.io/")
    assert get_tapis_tenant_base_url() == "https://example.tapis.io"


def test_tapis_oauth_client_id_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("TAPIS_OAUTH_CLIENT_ID", raising=False)
    assert get_tapis_oauth_client_id() == ""


def test_tapis_oauth_client_id_strips_whitespace(monkeypatch):
    monkeypatch.setenv("TAPIS_OAUTH_CLIENT_ID", "  my-client-id  ")
    assert get_tapis_oauth_client_id() == "my-client-id"


def test_tapis_oauth_client_key_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("TAPIS_OAUTH_CLIENT_KEY", raising=False)
    assert get_tapis_oauth_client_key() == ""


def test_tapis_oauth_client_key_strips_whitespace(monkeypatch):
    monkeypatch.setenv("TAPIS_OAUTH_CLIENT_KEY", "  my-secret  ")
    assert get_tapis_oauth_client_key() == "my-secret"
