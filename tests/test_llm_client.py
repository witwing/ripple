import os

from ripple.core.config import load
from ripple.llm.client import AnthropicClient, DryRunClient, get_client


def test_no_api_key_returns_dry_run(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("RIPPLE_NO_LLM", raising=False)
    cfg = load()
    client = get_client(cfg)
    assert isinstance(client, DryRunClient)


def test_env_no_llm_forces_dry_run(monkeypatch):
    monkeypatch.setenv("RIPPLE_NO_LLM", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-xxx")  # 即便有 key 也应该走 dry-run
    cfg = load()
    client = get_client(cfg)
    assert isinstance(client, DryRunClient)


def test_force_dry_run(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-xxx")
    cfg = load()
    client = get_client(cfg, force_dry_run=True)
    assert isinstance(client, DryRunClient)


def test_auth_token_env_returns_http_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
    monkeypatch.delenv("RIPPLE_NO_LLM", raising=False)
    cfg = load()
    client = get_client(cfg)
    from ripple.llm.client import AnthropicHTTPClient
    assert isinstance(client, AnthropicHTTPClient)
    assert client._settings.api_key == "test-token"
    assert client._settings.base_url == "https://example.com"


def test_dry_run_complete():
    c = DryRunClient()
    out = c.complete("sys", "hello world")
    assert "[DRY-RUN]" in out
