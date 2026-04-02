from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from src.api.oauth.admin import GetSupportedTypesAdapter
from src.services.auth.oauth.providers.github import GitHubOAuthProvider
from src.services.auth.oauth.registry import OAuthProviderRegistry


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        client_id="github-client-id",
        redirect_uri="https://api.example.com/api/oauth/github/callback",
        authorization_url_override=None,
        token_url_override=None,
        userinfo_url_override=None,
        scopes=None,
        get_client_secret=lambda: "github-client-secret",
    )


def test_registry_discovers_github_provider() -> None:
    registry = OAuthProviderRegistry()

    registry.discover_providers()

    provider = registry.get_provider("github")
    assert provider is not None
    assert provider.display_name == "GitHub"


@pytest.mark.asyncio
async def test_supported_types_adapter_triggers_provider_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = OAuthProviderRegistry()
    adapter = GetSupportedTypesAdapter()

    monkeypatch.setattr("src.api.oauth.admin.get_oauth_provider_registry", lambda: registry)

    payload = await adapter.handle(SimpleNamespace())

    assert any(item["provider_type"] == "github" for item in payload)


def test_github_authorization_url_includes_default_scopes() -> None:
    provider = GitHubOAuthProvider()
    url = provider.get_authorization_url(_make_config(), "state-1")

    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    assert parsed.netloc == "github.com"
    assert params["scope"] == ["read:user user:email"]
    assert params["state"] == ["state-1"]


@pytest.mark.asyncio
async def test_github_exchange_code_posts_json_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GitHubOAuthProvider()
    config = _make_config()
    captured: dict[str, object] = {}

    async def _fake_post_form(
        url: str,
        data: dict[str, str],
        *,
        timeout_seconds: float = 5.0,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers or {}
        captured["timeout_seconds"] = timeout_seconds
        return httpx.Response(
            200,
            json={"access_token": "access-1", "token_type": "bearer", "scope": "read:user,user:email"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(provider, "_http_post_form", _fake_post_form)

    token = await provider.exchange_code(config, "code-1")

    assert token.access_token == "access-1"
    assert captured["url"] == provider.token_url
    assert captured["data"] == {
        "code": "code-1",
        "redirect_uri": config.redirect_uri,
        "client_id": config.client_id,
        "client_secret": "github-client-secret",
    }
    assert captured["headers"] == {
        "Accept": "application/json",
        "User-Agent": "Aether",
    }


@pytest.mark.asyncio
async def test_github_userinfo_fetches_primary_email_from_email_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = GitHubOAuthProvider()
    config = _make_config()
    calls: list[str] = []

    async def _fake_get(
        url: str,
        *,
        timeout_seconds: float = 5.0,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        calls.append(url)
        if url.endswith("/user"):
            return httpx.Response(
                200,
                json={"id": 42, "login": "octocat", "email": None},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(
            200,
            json=[
                {"email": "secondary@example.com", "primary": False, "verified": True},
                {"email": "primary@example.com", "primary": True, "verified": True},
            ],
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(provider, "_http_get", _fake_get)

    user = await provider.get_user_info(config, "access-token")

    assert user.id == "42"
    assert user.username == "octocat"
    assert user.email == "primary@example.com"
    assert user.email_verified is True
    assert calls == [provider.userinfo_url, provider.emails_url]


@pytest.mark.asyncio
async def test_github_userinfo_falls_back_to_profile_email_when_email_api_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = GitHubOAuthProvider()
    config = _make_config()

    async def _fake_get(
        url: str,
        *,
        timeout_seconds: float = 5.0,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        if url.endswith("/user"):
            return httpx.Response(
                200,
                json={"id": 7, "login": "hubot", "email": "Hubot@Example.com"},
                request=httpx.Request("GET", url),
            )
        raise httpx.ConnectError("network down", request=httpx.Request("GET", url))

    monkeypatch.setattr(provider, "_http_get", _fake_get)

    user = await provider.get_user_info(config, "access-token")

    assert user.id == "7"
    assert user.username == "hubot"
    assert user.email == "hubot@example.com"
    assert user.email_verified is None
