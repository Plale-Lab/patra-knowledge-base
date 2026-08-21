from rest_server.features.hf_import import llm_enrichment


def test_llm_disabled_when_api_base_unset(monkeypatch):
    monkeypatch.delenv("HF_IMPORT_LLM_API_BASE", raising=False)
    assert llm_enrichment._llm_enabled() is False


def test_llm_enabled_when_api_base_set(monkeypatch):
    monkeypatch.setenv("HF_IMPORT_LLM_API_BASE", "https://litellm.pods.tacc.tapis.io")
    assert llm_enrichment._llm_enabled() is True


def test_resolve_llm_auth_prefers_service_token_over_request_token(monkeypatch):
    monkeypatch.setenv("HF_IMPORT_TAPIS_TOKEN", "service-token")
    api_key, headers = llm_enrichment._resolve_llm_auth(
        "https://litellm.pods.tacc.tapis.io", "request-token"
    )
    assert api_key is None
    assert headers == {"X-Tapis-Token": "service-token"}


def test_resolve_llm_auth_falls_back_to_request_token(monkeypatch):
    monkeypatch.delenv("HF_IMPORT_TAPIS_TOKEN", raising=False)
    api_key, headers = llm_enrichment._resolve_llm_auth(
        "https://litellm.pods.tacc.tapis.io", "request-token"
    )
    assert api_key is None
    assert headers == {"X-Tapis-Token": "request-token"}


def test_resolve_llm_auth_no_token_falls_back_to_api_key(monkeypatch):
    monkeypatch.delenv("HF_IMPORT_TAPIS_TOKEN", raising=False)
    monkeypatch.setenv("HF_IMPORT_LLM_API_KEY", "sk-test")
    api_key, headers = llm_enrichment._resolve_llm_auth(
        "https://litellm.pods.tacc.tapis.io", None
    )
    assert api_key == "sk-test"
    assert headers == {}


def test_resolve_llm_auth_non_litellm_host_ignores_tapis_tokens(monkeypatch):
    monkeypatch.setenv("HF_IMPORT_TAPIS_TOKEN", "service-token")
    monkeypatch.setenv("HF_IMPORT_LLM_API_KEY", "sk-test")
    api_key, headers = llm_enrichment._resolve_llm_auth(
        "https://api.openai.com", "request-token"
    )
    assert api_key == "sk-test"
    assert headers == {}
