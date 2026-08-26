"""POST /auth/tapis/exchange: server-side half of the Tapis OAuth2 redirect login."""

import httpx
import pytest

from rest_server.features.tapis_oauth.service import (
    TapisLoginResult,
    TapisOAuthNotConfiguredError,
    TapisTokenExchangeError,
    TapisUserinfoError,
    complete_tapis_login,
    exchange_code_for_token,
    fetch_tapis_userinfo,
)

REDIRECT_URI = "https://patra.example/auth/callback"


# ---------------------------------------------------------------------------
# Route-level tests (mock complete_tapis_login at the route's import site)
# ---------------------------------------------------------------------------

def test_exchange_success(client, monkeypatch):
    monkeypatch.setattr(
        "rest_server.routes.auth.complete_tapis_login",
        lambda **kwargs: TapisLoginResult(access_token="tapis-jwt", username="alice", expires_at=None),
    )
    resp = client.post("/auth/tapis/exchange", json={"code": "abc123", "redirect_uri": REDIRECT_URI})
    assert resp.status_code == 200
    assert resp.json() == {"access_token": "tapis-jwt", "username": "alice", "expires_at": None}


def test_exchange_rejects_missing_body(client):
    resp = client.post("/auth/tapis/exchange")
    assert resp.status_code == 422


def test_exchange_rejects_empty_code(client):
    resp = client.post("/auth/tapis/exchange", json={"code": "  ", "redirect_uri": REDIRECT_URI})
    assert resp.status_code == 400


def test_exchange_rejects_empty_redirect_uri(client):
    resp = client.post("/auth/tapis/exchange", json={"code": "abc123", "redirect_uri": ""})
    assert resp.status_code == 400


def test_exchange_returns_503_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("TAPIS_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TAPIS_OAUTH_CLIENT_KEY", raising=False)
    resp = client.post("/auth/tapis/exchange", json={"code": "abc123", "redirect_uri": REDIRECT_URI})
    assert resp.status_code == 503


def test_exchange_returns_401_on_token_exchange_failure(client, monkeypatch):
    def _raise(**kwargs):
        raise TapisTokenExchangeError("bad code")

    monkeypatch.setattr("rest_server.routes.auth.complete_tapis_login", _raise)
    resp = client.post("/auth/tapis/exchange", json={"code": "abc123", "redirect_uri": REDIRECT_URI})
    assert resp.status_code == 401


def test_exchange_returns_502_on_userinfo_failure(client, monkeypatch):
    def _raise(**kwargs):
        raise TapisUserinfoError("userinfo unreachable")

    monkeypatch.setattr("rest_server.routes.auth.complete_tapis_login", _raise)
    resp = client.post("/auth/tapis/exchange", json={"code": "abc123", "redirect_uri": REDIRECT_URI})
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Unit tests of the service functions -- mocked httpx.Client, asserting the
# exact outbound request shape against the confirmed Tapis contract.
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


class _FakeClient:
    def __init__(self, get_response=None, post_response=None):
        self._get_response = get_response
        self._post_response = post_response
        self.get_calls = []
        self.post_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, headers=None):
        self.get_calls.append((url, headers))
        return self._get_response

    def post(self, url, data=None, auth=None):
        self.post_calls.append((url, data, auth))
        return self._post_response


def _configure_client_credentials(monkeypatch):
    monkeypatch.setenv("TAPIS_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("TAPIS_OAUTH_CLIENT_KEY", "test-client-key")
    monkeypatch.setenv("TAPIS_TENANT_BASE_URL", "https://icicleai.tapis.io")


def test_exchange_code_for_token_sends_basic_auth_and_form_body(monkeypatch):
    _configure_client_credentials(monkeypatch)
    fake_client = _FakeClient(post_response=_FakeResponse({"access_token": "tapis-jwt"}))
    monkeypatch.setattr(
        "rest_server.features.tapis_oauth.service.httpx.Client",
        lambda timeout: fake_client,
    )

    result = exchange_code_for_token(code="abc123", redirect_uri=REDIRECT_URI)

    assert result == {"access_token": "tapis-jwt"}
    url, data, auth = fake_client.post_calls[0]
    assert url == "https://icicleai.tapis.io/v3/oauth2/tokens"
    assert data == {"grant_type": "authorization_code", "code": "abc123", "redirect_uri": REDIRECT_URI}
    assert auth == ("test-client-id", "test-client-key")


def test_exchange_code_for_token_raises_on_http_error(monkeypatch):
    _configure_client_credentials(monkeypatch)
    fake_client = _FakeClient(post_response=_FakeResponse({"error": "invalid_grant"}, status_code=400))
    monkeypatch.setattr(
        "rest_server.features.tapis_oauth.service.httpx.Client",
        lambda timeout: fake_client,
    )

    with pytest.raises(TapisTokenExchangeError):
        exchange_code_for_token(code="bad", redirect_uri=REDIRECT_URI)


def test_fetch_tapis_userinfo_sends_tapis_token_header(monkeypatch):
    _configure_client_credentials(monkeypatch)
    fake_client = _FakeClient(get_response=_FakeResponse({"username": "alice"}))
    monkeypatch.setattr(
        "rest_server.features.tapis_oauth.service.httpx.Client",
        lambda timeout: fake_client,
    )

    result = fetch_tapis_userinfo(access_token="tapis-jwt")

    assert result == {"username": "alice"}
    url, headers = fake_client.get_calls[0]
    assert url == "https://icicleai.tapis.io/v3/oauth2/userinfo"
    assert headers == {"X-Tapis-Token": "tapis-jwt"}


def test_fetch_tapis_userinfo_raises_on_http_error(monkeypatch):
    _configure_client_credentials(monkeypatch)
    fake_client = _FakeClient(get_response=_FakeResponse({}, status_code=401))
    monkeypatch.setattr(
        "rest_server.features.tapis_oauth.service.httpx.Client",
        lambda timeout: fake_client,
    )

    with pytest.raises(TapisUserinfoError):
        fetch_tapis_userinfo(access_token="bad-token")


def test_complete_tapis_login_missing_client_credentials_raises(monkeypatch):
    monkeypatch.delenv("TAPIS_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TAPIS_OAUTH_CLIENT_KEY", raising=False)

    with pytest.raises(TapisOAuthNotConfiguredError):
        complete_tapis_login(code="abc123", redirect_uri=REDIRECT_URI)


def test_complete_tapis_login_full_flow_flat_response_shape(monkeypatch):
    _configure_client_credentials(monkeypatch)
    fake_client = _FakeClient(
        post_response=_FakeResponse({"access_token": "tapis-jwt"}),
        get_response=_FakeResponse({"username": "alice"}),
    )
    monkeypatch.setattr(
        "rest_server.features.tapis_oauth.service.httpx.Client",
        lambda timeout: fake_client,
    )

    result = complete_tapis_login(code="abc123", redirect_uri=REDIRECT_URI)

    assert result.access_token == "tapis-jwt"
    assert result.username == "alice"


def test_complete_tapis_login_full_flow_nested_response_shape(monkeypatch):
    """Matches the nested {result: {...}} shape auth.js already handles for ROPC."""
    _configure_client_credentials(monkeypatch)
    fake_client = _FakeClient(
        post_response=_FakeResponse({"result": {"access_token": {"access_token": "nested-jwt"}}}),
        get_response=_FakeResponse({"result": {"username": "bob"}}),
    )
    monkeypatch.setattr(
        "rest_server.features.tapis_oauth.service.httpx.Client",
        lambda timeout: fake_client,
    )

    result = complete_tapis_login(code="abc123", redirect_uri=REDIRECT_URI)

    assert result.access_token == "nested-jwt"
    assert result.username == "bob"
