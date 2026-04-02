from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.api.oauth.admin import GetSupportedTypesAdapter
from src.services.auth.oauth import registry as registry_module


@pytest.mark.asyncio
async def test_get_supported_types_adapter_discovers_builtin_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry_module, "_registry", None)

    adapter = GetSupportedTypesAdapter()
    result = await adapter.handle(SimpleNamespace())

    provider_types = {item["provider_type"] for item in result}
    assert {"github", "linuxdo"}.issubset(provider_types)

    github = next(item for item in result if item["provider_type"] == "github")
    assert github["display_name"] == "GitHub"
    assert github["default_authorization_url"] == "https://github.com/login/oauth/authorize"
    assert github["default_token_url"] == "https://github.com/login/oauth/access_token"
    assert github["default_userinfo_url"] == "https://api.github.com/user"
    assert github["default_scopes"] == ["read:user", "user:email"]
