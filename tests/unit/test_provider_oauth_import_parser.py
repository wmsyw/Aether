from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.api.admin import provider_oauth as module
from src.core.exceptions import InvalidRequestException


def test_parse_standard_oauth_import_entries_keeps_codex_hints() -> None:
    entries = module._parse_standard_oauth_import_entries(
        '[{"refresh_token":"rt_1","accountId":"acc-1","chatgptAccountUserId":"u-1__acc-1","planType":"TEAM","userId":"u-1","email":"u@example.com"}]'
    )

    assert entries == [
        {
            "refresh_token": "rt_1",
            "account_id": "acc-1",
            "account_user_id": "u-1__acc-1",
            "plan_type": "team",
            "user_id": "u-1",
            "email": "u@example.com",
        }
    ]


def test_parse_standard_oauth_import_entries_parses_api_formats() -> None:
    entries = module._parse_standard_oauth_import_entries(
        '[{"refresh_token":"rt_1","apiFormats":["OPENAI_CLI","openai:chat","openai:chat","invalid"]}]'
    )

    assert entries == [
        {
            "refresh_token": "rt_1",
            "api_formats": ["openai:cli", "openai:chat"],
        }
    ]


def test_parse_standard_oauth_import_entries_parses_allowed_api_formats_string() -> (
    None
):
    entries = module._parse_standard_oauth_import_entries(
        '{"refresh_token":"rt_2","allowed_api_formats":"openai:cli, claude:chat"}'
    )

    assert entries == [
        {
            "refresh_token": "rt_2",
            "api_formats": ["openai:cli", "claude:chat"],
        }
    ]


def test_parse_tokens_input_compatibility_wrapper() -> None:
    tokens = module._parse_tokens_input("token_a\ntoken_b")
    assert tokens == ["token_a", "token_b"]


def test_update_existing_oauth_key_updates_api_formats_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.crypto_service, "encrypt", lambda value: f"enc:{value}")

    existing_key = SimpleNamespace(
        api_key="old-api-key",
        auth_config="old-auth-config",
        api_formats=["claude:chat"],
        is_active=False,
        oauth_invalid_at=123,
        oauth_invalid_reason="invalid",
        health_by_format={"claude:chat": {"health_score": 0.1}},
        circuit_breaker_by_format={"claude:chat": {"open": True}},
        error_count=8,
        last_error_at=123,
        last_error_msg="boom",
        proxy=None,
    )
    db = MagicMock()
    existing_key_obj: Any = existing_key

    updated = module._update_existing_oauth_key(
        db,
        existing_key_obj,
        "new-access-token",
        {"refresh_token": "new-refresh-token"},
        api_formats=["openai:cli", "openai:chat"],
        flush_only=True,
    )

    assert updated is existing_key
    assert existing_key.api_formats == ["openai:cli", "openai:chat"]
    assert existing_key.is_active is True
    assert existing_key.oauth_invalid_at is None
    assert existing_key.oauth_invalid_reason is None
    db.flush.assert_called_once()
    db.commit.assert_not_called()


def test_apply_codex_import_hints_only_fills_missing_fields() -> None:
    auth_config = {
        "account_id": "existing-account",
        "plan_type": "",
    }
    module._apply_codex_import_hints(
        auth_config,
        {
            "account_user_id": "u-1__acc-1",
            "account_id": "acc-1",
            "plan_type": "plus",
            "user_id": "user-1",
            "email": "u@example.com",
        },
    )

    assert auth_config["account_id"] == "existing-account"
    assert auth_config["account_user_id"] == "u-1__acc-1"
    assert auth_config["plan_type"] == "plus"
    assert auth_config["user_id"] == "user-1"
    assert auth_config["email"] == "u@example.com"


class _DummyQuery:
    def __init__(self, keys: list[SimpleNamespace]) -> None:
        self._keys = keys

    def filter(self, *_args: object, **_kwargs: object) -> "_DummyQuery":
        return self

    def all(self) -> list[SimpleNamespace]:
        return self._keys


class _DummyDB:
    def __init__(self, keys: list[SimpleNamespace]) -> None:
        self._keys = keys

    def query(self, _model: object) -> _DummyQuery:
        return _DummyQuery(self._keys)


def _make_oauth_key(
    *, key_id: str, name: str, auth_config: dict[str, object]
) -> SimpleNamespace:
    return SimpleNamespace(
        id=key_id,
        name=name,
        provider_id="provider-1",
        auth_type="oauth",
        auth_config=json.dumps(auth_config),
        is_active=True,
    )


class _SingleKeyQuery:
    def __init__(self, key: SimpleNamespace | None) -> None:
        self._key = key

    def filter(self, *_args: object, **_kwargs: object) -> "_SingleKeyQuery":
        return self

    def first(self) -> SimpleNamespace | None:
        return self._key


class _SingleKeyDB:
    def __init__(self, key: SimpleNamespace | None) -> None:
        self._key = key

    def query(self, _model: object) -> _SingleKeyQuery:
        return _SingleKeyQuery(self._key)


@contextmanager
def _fake_db_context(db: _SingleKeyDB):
    yield db


def test_check_duplicate_oauth_account_codex_allows_same_user_different_account_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        module.crypto_service, "decrypt", lambda value, silent=True: value
    )

    existing_key = _make_oauth_key(
        key_id="key-1",
        name="existing",
        auth_config={
            "provider_type": "codex",
            "email": "u@example.com",
            "user_id": "user-1",
            "account_id": "acc-1",
            "account_user_id": "user-1__acc-1",
            "plan_type": "team",
        },
    )
    db = _DummyDB([existing_key])

    result = module._check_duplicate_oauth_account(
        db,  # type: ignore[arg-type]
        "provider-1",
        {
            "provider_type": "codex",
            "email": "u@example.com",
            "user_id": "user-1",
            "account_id": "acc-2",
            "account_user_id": "user-1__acc-2",
            "plan_type": "team",
        },
    )

    assert result is None


def test_check_duplicate_oauth_account_codex_rejects_same_account_user_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        module.crypto_service, "decrypt", lambda value, silent=True: value
    )

    existing_key = _make_oauth_key(
        key_id="key-1",
        name="existing",
        auth_config={
            "provider_type": "codex",
            "email": "u@example.com",
            "user_id": "user-1",
            "account_id": "acc-1",
            "account_user_id": "user-1__acc-1",
            "plan_type": "team",
        },
    )
    db = _DummyDB([existing_key])

    with pytest.raises(InvalidRequestException, match="已存在"):
        module._check_duplicate_oauth_account(
            db,  # type: ignore[arg-type]
            "provider-1",
            {
                "provider_type": "codex",
                "email": "u@example.com",
                "user_id": "user-1",
                "account_id": "acc-1",
                "account_user_id": "user-1__acc-1",
                "plan_type": "team",
            },
        )


def test_mark_refresh_failed_sync_appends_refresh_failure_for_account_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = SimpleNamespace(
        id="key-1",
        oauth_invalid_at="old-invalid-at",
        oauth_invalid_reason="[ACCOUNT_BLOCK] account has been deactivated",
    )
    db = _SingleKeyDB(key)
    monkeypatch.setattr(module, "get_db_context", lambda: _fake_db_context(db))

    module._mark_refresh_failed_sync(
        "key-1",
        "[REFRESH_FAILED] Token 续期失败 (400): refresh_token_reused",
    )

    assert key.oauth_invalid_at != "old-invalid-at"
    assert key.oauth_invalid_reason == (
        "[ACCOUNT_BLOCK] account has been deactivated\n"
        "[REFRESH_FAILED] Token 续期失败 (400): refresh_token_reused"
    )


@pytest.mark.asyncio
async def test_refresh_account_state_after_oauth_update_refreshes_supported_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = SimpleNamespace(close=MagicMock())
    captured: dict[str, object] = {}

    async def _fake_refresh_provider_quota_for_provider(
        **kwargs: object,
    ) -> dict[str, object]:
        captured.update(kwargs)
        return {"success": 1}

    monkeypatch.setattr(module, "create_session", lambda: fake_db)

    from src.services.provider_keys import key_quota_service as quota_module

    monkeypatch.setattr(
        quota_module,
        "refresh_provider_quota_for_provider",
        _fake_refresh_provider_quota_for_provider,
    )

    attempted, error = await module._refresh_account_state_after_oauth_update(
        provider_id="provider-1",
        provider_type="codex",
        key_ids=["key-1"],
    )

    assert attempted is True
    assert error is None
    assert captured["provider_id"] == "provider-1"
    assert captured["key_ids"] == ["key-1"]
    fake_db.close.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_account_state_after_oauth_update_returns_error_when_refresh_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = SimpleNamespace(close=MagicMock())

    async def _fake_refresh_provider_quota_for_provider(
        **_kwargs: object,
    ) -> dict[str, object]:
        raise RuntimeError("quota refresh failed")

    monkeypatch.setattr(module, "create_session", lambda: fake_db)

    from src.services.provider_keys import key_quota_service as quota_module

    monkeypatch.setattr(
        quota_module,
        "refresh_provider_quota_for_provider",
        _fake_refresh_provider_quota_for_provider,
    )

    attempted, error = await module._refresh_account_state_after_oauth_update(
        provider_id="provider-1",
        provider_type="codex",
        key_ids=["key-1"],
    )

    assert attempted is True
    assert error is not None
    assert "quota refresh failed" in error
    fake_db.close.assert_called_once()
