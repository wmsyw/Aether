from __future__ import annotations

from itertools import count
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from src.api.admin import provider_oauth as oauthmod


@pytest.mark.asyncio
async def test_standard_batch_import_releases_db_connection_before_network_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_calls: list[str] = []

    monkeypatch.setattr(
        oauthmod,
        "_require_oauth_template",
        lambda _provider_type: SimpleNamespace(
            oauth=SimpleNamespace(
                token_url="https://example.com/oauth/token",
                client_id="client-id",
                client_secret=None,
                scopes=[],
            )
        ),
    )
    monkeypatch.setattr(
        oauthmod,
        "_parse_standard_oauth_import_entries",
        lambda _raw: [{"refresh_token": "r" * 120}],
    )
    monkeypatch.setattr(oauthmod, "_get_provider_api_formats", lambda _provider: [])
    monkeypatch.setattr(
        oauthmod,
        "_release_batch_import_db_connection_before_await",
        lambda _db: release_calls.append("release"),
    )

    async def _fake_post_oauth_token(**_kwargs: object) -> httpx.Response:
        raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(oauthmod, "post_oauth_token", _fake_post_oauth_token)

    db = MagicMock()

    result = await oauthmod._batch_import_standard_oauth_internal(
        provider_id="provider-1",
        provider_type="codex",
        provider=SimpleNamespace(endpoints=[]),  # type: ignore[arg-type]
        raw_credentials="ignored",
        db=db,
        concurrency=1,
    )

    assert result.total == 1
    assert result.success == 0
    assert result.failed == 1
    assert release_calls
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_standard_batch_import_commits_successes_in_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_ids = count(1)

    monkeypatch.setattr(
        oauthmod,
        "_PROVIDER_OAUTH_BATCH_IMPORT_COMMIT_BATCH_SIZE",
        2,
    )
    monkeypatch.setattr(
        oauthmod,
        "_require_oauth_template",
        lambda _provider_type: SimpleNamespace(
            oauth=SimpleNamespace(
                token_url="https://example.com/oauth/token",
                client_id="client-id",
                client_secret=None,
                scopes=[],
            )
        ),
    )
    monkeypatch.setattr(
        oauthmod,
        "_parse_standard_oauth_import_entries",
        lambda _raw: [{"refresh_token": f"r-{idx}" + ("x" * 120)} for idx in range(3)],
    )
    monkeypatch.setattr(
        oauthmod, "_get_provider_api_formats", lambda _provider: ["responses"]
    )
    monkeypatch.setattr(
        oauthmod,
        "_release_batch_import_db_connection_before_await",
        lambda _db: None,
    )

    async def _fake_post_oauth_token(**_kwargs: object) -> httpx.Response:
        idx = next(key_ids)
        return httpx.Response(
            200,
            json={
                "access_token": f"access-{idx}",
                "refresh_token": f"refresh-{idx}",
                "expires_in": 3600,
            },
            request=httpx.Request("POST", "https://example.com/oauth/token"),
        )

    async def _fake_enrich_auth_config(**kwargs: object) -> dict[str, object]:
        raw_auth_config = kwargs.get("auth_config")
        auth_config = (
            {str(k): v for k, v in raw_auth_config.items()}
            if isinstance(raw_auth_config, dict)
            else {}
        )
        auth_config["email"] = f"user-{next(key_ids)}@example.com"
        return auth_config

    created_ids = count(1)
    monkeypatch.setattr(oauthmod, "post_oauth_token", _fake_post_oauth_token)
    monkeypatch.setattr(oauthmod, "enrich_auth_config", _fake_enrich_auth_config)
    monkeypatch.setattr(
        oauthmod, "_check_duplicate_oauth_account", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        oauthmod,
        "_create_oauth_key",
        lambda *_args, **_kwargs: SimpleNamespace(id=f"key-{next(created_ids)}"),
    )

    db = MagicMock()

    result = await oauthmod._batch_import_standard_oauth_internal(
        provider_id="provider-1",
        provider_type="example",
        provider=SimpleNamespace(endpoints=[]),  # type: ignore[arg-type]
        raw_credentials="ignored",
        db=db,
        concurrency=1,
    )

    assert result.total == 3
    assert result.success == 3
    assert result.failed == 0
    assert db.commit.call_count == 2


@pytest.mark.asyncio
async def test_kiro_batch_import_releases_db_connection_before_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_calls: list[str] = []

    class FakeKiroAuthConfig:
        def __init__(self, data: dict[str, object]) -> None:
            self._data = dict(data)
            self.provider_type = str(data.get("provider_type") or "")
            self.email = (
                data.get("email") if isinstance(data.get("email"), str) else None
            )
            self.auth_method = (
                data.get("auth_method")
                if isinstance(data.get("auth_method"), str)
                else "social"
            )
            self.refresh_token = str(data.get("refresh_token") or "")

        @staticmethod
        def validate_required_fields(
            _cred: dict[str, object],
        ) -> tuple[bool, str | None]:
            return True, None

        @classmethod
        def from_dict(cls, data: dict[str, object]) -> "FakeKiroAuthConfig":
            return cls(data)

        def to_dict(self) -> dict[str, object]:
            return dict(self._data)

    monkeypatch.setattr(
        oauthmod,
        "_parse_kiro_import_input",
        lambda _raw: [{"refresh_token": "r" * 120, "auth_method": "social"}],
    )
    monkeypatch.setattr(oauthmod, "_get_provider_api_formats", lambda _provider: [])
    monkeypatch.setattr(
        oauthmod,
        "_release_batch_import_db_connection_before_await",
        lambda _db: release_calls.append("release"),
    )
    monkeypatch.setattr(
        "src.services.provider.adapters.kiro.models.credentials.KiroAuthConfig",
        FakeKiroAuthConfig,
    )

    async def _fake_refresh_access_token(
        *_args: object, **_kwargs: object
    ) -> tuple[str, object]:
        raise RuntimeError("refresh token reused")

    monkeypatch.setattr(
        "src.services.provider.adapters.kiro.token_manager.refresh_access_token",
        _fake_refresh_access_token,
    )

    db = MagicMock()

    result = await oauthmod._batch_import_kiro_internal(
        provider_id="provider-1",
        provider=SimpleNamespace(endpoints=[]),  # type: ignore[arg-type]
        raw_credentials="ignored",
        db=db,
        concurrency=1,
    )

    assert result.total == 1
    assert result.success == 0
    assert result.failed == 1
    assert release_calls
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_standard_batch_import_prefers_entry_api_formats_for_new_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        oauthmod,
        "_require_oauth_template",
        lambda _provider_type: SimpleNamespace(
            oauth=SimpleNamespace(
                token_url="https://example.com/oauth/token",
                client_id="client-id",
                client_secret=None,
                scopes=[],
            )
        ),
    )
    monkeypatch.setattr(
        oauthmod,
        "_parse_standard_oauth_import_entries",
        lambda _raw: [{"refresh_token": "r" * 120, "api_formats": ["openai:cli"]}],
    )
    monkeypatch.setattr(
        oauthmod, "_get_provider_api_formats", lambda _provider: ["claude:chat"]
    )
    monkeypatch.setattr(
        oauthmod,
        "_release_batch_import_db_connection_before_await",
        lambda _db: None,
    )

    async def _fake_post_oauth_token(**_kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
            },
            request=httpx.Request("POST", "https://example.com/oauth/token"),
        )

    async def _fake_enrich_auth_config(**kwargs: object) -> dict[str, object]:
        raw_auth_config = kwargs.get("auth_config")
        auth_config = (
            {str(k): v for k, v in raw_auth_config.items()}
            if isinstance(raw_auth_config, dict)
            else {}
        )
        auth_config["email"] = "user@example.com"
        return auth_config

    captured_api_formats: list[str] = []

    def _fake_create_oauth_key(*_args: object, **kwargs: object) -> SimpleNamespace:
        nonlocal captured_api_formats
        raw_api_formats = kwargs.get("api_formats")
        captured_api_formats = (
            [str(item) for item in raw_api_formats]
            if isinstance(raw_api_formats, list)
            else []
        )
        return SimpleNamespace(id="key-1")

    monkeypatch.setattr(oauthmod, "post_oauth_token", _fake_post_oauth_token)
    monkeypatch.setattr(oauthmod, "enrich_auth_config", _fake_enrich_auth_config)
    monkeypatch.setattr(
        oauthmod, "_check_duplicate_oauth_account", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(oauthmod, "_create_oauth_key", _fake_create_oauth_key)

    db = MagicMock()

    result = await oauthmod._batch_import_standard_oauth_internal(
        provider_id="provider-1",
        provider_type="example",
        provider=SimpleNamespace(endpoints=[]),  # type: ignore[arg-type]
        raw_credentials="ignored",
        db=db,
        concurrency=1,
    )

    assert result.total == 1
    assert result.success == 1
    assert result.failed == 0
    assert captured_api_formats == ["openai:cli"]


@pytest.mark.asyncio
async def test_standard_batch_import_prefers_entry_api_formats_for_existing_key_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        oauthmod,
        "_require_oauth_template",
        lambda _provider_type: SimpleNamespace(
            oauth=SimpleNamespace(
                token_url="https://example.com/oauth/token",
                client_id="client-id",
                client_secret=None,
                scopes=[],
            )
        ),
    )
    monkeypatch.setattr(
        oauthmod,
        "_parse_standard_oauth_import_entries",
        lambda _raw: [{"refresh_token": "r" * 120, "api_formats": ["openai:cli"]}],
    )
    monkeypatch.setattr(
        oauthmod, "_get_provider_api_formats", lambda _provider: ["claude:chat"]
    )
    monkeypatch.setattr(
        oauthmod,
        "_release_batch_import_db_connection_before_await",
        lambda _db: None,
    )

    async def _fake_post_oauth_token(**_kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
            },
            request=httpx.Request("POST", "https://example.com/oauth/token"),
        )

    async def _fake_enrich_auth_config(**kwargs: object) -> dict[str, object]:
        raw_auth_config = kwargs.get("auth_config")
        auth_config = (
            {str(k): v for k, v in raw_auth_config.items()}
            if isinstance(raw_auth_config, dict)
            else {}
        )
        auth_config["email"] = "user@example.com"
        return auth_config

    existing_key = SimpleNamespace(id="key-existing", name="existing-key")
    captured_api_formats: list[str] = []

    def _fake_update_existing_oauth_key(
        *_args: object, **kwargs: object
    ) -> SimpleNamespace:
        nonlocal captured_api_formats
        raw_api_formats = kwargs.get("api_formats")
        captured_api_formats = (
            [str(item) for item in raw_api_formats]
            if isinstance(raw_api_formats, list)
            else []
        )
        return existing_key

    monkeypatch.setattr(oauthmod, "post_oauth_token", _fake_post_oauth_token)
    monkeypatch.setattr(oauthmod, "enrich_auth_config", _fake_enrich_auth_config)
    monkeypatch.setattr(
        oauthmod,
        "_check_duplicate_oauth_account",
        lambda *_args, **_kwargs: existing_key,
    )
    monkeypatch.setattr(
        oauthmod, "_update_existing_oauth_key", _fake_update_existing_oauth_key
    )

    db = MagicMock()

    result = await oauthmod._batch_import_standard_oauth_internal(
        provider_id="provider-1",
        provider_type="example",
        provider=SimpleNamespace(endpoints=[]),  # type: ignore[arg-type]
        raw_credentials="ignored",
        db=db,
        concurrency=1,
    )

    assert result.total == 1
    assert result.success == 1
    assert result.failed == 0
    assert result.results[0].replaced is True
    assert captured_api_formats == ["openai:cli"]
