import pytest
from types import SimpleNamespace
from typing import Mapping, cast
from unittest.mock import MagicMock
from sqlalchemy.orm import Session
from starlette.requests import Request

from src.api.admin.system import (
    CONFIG_EXPORT_VERSION,
    CONFIG_SUPPORTED_VERSIONS,
    AdminExportConfigAdapter,
    AdminImportConfigAdapter,
)
from src.api.base.context import ApiRequestContext
from src.core.exceptions import InvalidRequestException
from src.models.database import ApiKey
from src.services.provider_ops.types import SENSITIVE_CREDENTIAL_FIELDS


def test_export_key_api_formats_falls_back_to_provider_endpoints_when_none() -> None:
    adapter = AdminExportConfigAdapter()

    result = adapter._resolve_export_key_api_formats(
        None,
        ["claude:chat", "openai:cli"],
    )

    assert result == ["claude:chat", "openai:cli"]


def test_export_key_api_formats_keeps_explicit_empty_list() -> None:
    adapter = AdminExportConfigAdapter()

    result = adapter._resolve_export_key_api_formats(
        [],
        ["openai:chat"],
    )

    assert result == []


def test_export_key_api_formats_normalizes_and_deduplicates() -> None:
    adapter = AdminExportConfigAdapter()

    result = adapter._resolve_export_key_api_formats(
        [" OPENAI:CHAT ", "openai:chat", "openai:cli", "bad-format"],
        ["claude:chat"],
    )

    assert result == ["openai:chat", "openai:cli"]


def test_import_key_api_formats_uses_supported_endpoints_alias() -> None:
    result = AdminImportConfigAdapter._extract_import_key_api_formats(
        {"supported_endpoints": ["openai:chat"]},
        {"openai:chat", "openai:cli"},
    )

    assert result == ["openai:chat"]


def test_import_key_api_formats_falls_back_to_provider_endpoints_when_none() -> None:
    result = AdminImportConfigAdapter._extract_import_key_api_formats(
        {"api_formats": None},
        {"openai:chat", "claude:cli"},
    )

    assert result == ["claude:cli", "openai:chat"]


def test_import_key_api_formats_keeps_explicit_empty_list() -> None:
    result = AdminImportConfigAdapter._extract_import_key_api_formats(
        {"api_formats": []},
        {"openai:chat"},
    )

    assert result == []


class _FakeCrypto:
    def encrypt(self, value: str) -> str:
        return f"enc:{value}"

    def decrypt(self, value: str) -> str:
        return value.removeprefix("enc:")


def test_provider_ops_sensitive_fields_include_refresh_token() -> None:
    assert "refresh_token" in SENSITIVE_CREDENTIAL_FIELDS


def test_export_provider_config_decrypts_refresh_token() -> None:
    adapter = AdminExportConfigAdapter()

    config = {
        "provider_ops": {
            "connector": {
                "credentials": {
                    "refresh_token": "enc:rt-1",
                    "api_key": "enc:key-1",
                }
            }
        }
    }

    result = adapter._decrypt_provider_config(config, _FakeCrypto())

    assert result["provider_ops"]["connector"]["credentials"]["refresh_token"] == "rt-1"
    assert result["provider_ops"]["connector"]["credentials"]["api_key"] == "key-1"
    assert (
        config["provider_ops"]["connector"]["credentials"]["refresh_token"]
        == "enc:rt-1"
    )


def test_import_provider_config_encrypts_refresh_token() -> None:
    adapter = AdminImportConfigAdapter()

    config = {
        "provider_ops": {
            "connector": {
                "credentials": {
                    "refresh_token": "rt-1",
                    "api_key": "key-1",
                }
            }
        }
    }

    result = adapter._encrypt_provider_config(config, _FakeCrypto())

    assert (
        result["provider_ops"]["connector"]["credentials"]["refresh_token"]
        == "enc:rt-1"
    )
    assert result["provider_ops"]["connector"]["credentials"]["api_key"] == "enc:key-1"
    assert config["provider_ops"]["connector"]["credentials"]["refresh_token"] == "rt-1"


def test_import_endpoint_payload_rejects_dict_base_url() -> None:
    with pytest.raises(InvalidRequestException, match="导入 Endpoint 失败"):
        AdminImportConfigAdapter._normalize_import_endpoint_payload(
            "provider-1",
            {
                "api_format": "claude:chat",
                "base_url": {"url": "https://api.anthropic.com"},
            },
        )


def test_import_endpoint_payload_normalizes_base_url() -> None:
    result = AdminImportConfigAdapter._normalize_import_endpoint_payload(
        "provider-1",
        {
            "api_format": "claude:chat",
            "base_url": "https://api.anthropic.com/",
        },
    )

    assert result["base_url"] == "https://api.anthropic.com"
    assert result["api_format"] == "claude:chat"


def test_config_export_version_supports_api_key_sync() -> None:
    assert CONFIG_EXPORT_VERSION == "2.3"
    assert "2.3" in CONFIG_SUPPORTED_VERSIONS


def test_import_config_resolve_api_key_material_prefers_plaintext_key() -> None:
    key_hash, key_encrypted = AdminImportConfigAdapter._resolve_api_key_material(
        {"key": " sk-12345678901 "}
    )

    assert key_hash == ApiKey.hash_key("sk-12345678901")
    assert isinstance(key_encrypted, str)
    assert len(key_encrypted) > 0


def test_import_config_api_key_rate_limit_defaults() -> None:
    assert (
        AdminImportConfigAdapter._normalize_imported_api_key_rate_limit(
            {}, is_standalone=False
        )
        == 0
    )
    assert (
        AdminImportConfigAdapter._normalize_imported_api_key_rate_limit(
            {}, is_standalone=True
        )
        is None
    )


class _QueryStub:
    def __init__(self, first_result: object | None) -> None:
        self._first_result = first_result

    def filter(self, *_args: object, **_kwargs: object) -> "_QueryStub":
        return self

    def first(self) -> object | None:
        return self._first_result


class _DbStub:
    def __init__(
        self, *, user_first: object | None, api_key_first: object | None
    ) -> None:
        self._user_query = _QueryStub(user_first)
        self._api_key_query = _QueryStub(api_key_first)
        self._generic_query = _QueryStub(None)
        self.add = MagicMock()
        self.flush = MagicMock()
        self.commit = MagicMock()
        self.rollback = MagicMock()

    def query(self, model: type[object]) -> _QueryStub:
        from src.models.database import ApiKey as ApiKeyModel
        from src.models.database import User as UserModel

        if model is UserModel:
            return self._user_query
        if model is ApiKeyModel:
            return self._api_key_query
        return self._generic_query


def _make_context(db: object, payload: Mapping[str, object]) -> ApiRequestContext:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "path": "/api/admin/config/import",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )
    return ApiRequestContext(
        request=request,
        db=cast(Session, db),
        user=None,
        api_key=None,
        request_id="test-req",
        start_time=0.0,
        client_ip="127.0.0.1",
        user_agent="pytest",
        original_headers={},
        query_params={},
        raw_body=b"{}",
        json_body=dict(payload),
    )


def _patch_cache_invalidation(monkeypatch: pytest.MonkeyPatch) -> None:
    cache_service = SimpleNamespace(clear_all_caches=lambda: None)
    monkeypatch.setattr(
        "src.services.cache.invalidation.get_cache_invalidation_service",
        lambda: cache_service,
    )


@pytest.mark.asyncio
async def test_import_config_user_api_key_skips_when_owner_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_invalidation(monkeypatch)

    db = _DbStub(user_first=None, api_key_first=None)
    payload = {
        "version": "2.3",
        "user_api_keys": [
            {
                "owner_email": "missing@example.com",
                "name": "Missing Owner Key",
                "key": "sk-missing-owner-12345",
            }
        ],
    }

    result = await AdminImportConfigAdapter().handle(_make_context(db, payload))

    assert result["stats"]["user_api_keys"] == {
        "created": 0,
        "updated": 0,
        "skipped": 1,
    }
    assert any(
        "未找到用户 'missing@example.com'" in err for err in result["stats"]["errors"]
    )
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_import_config_standalone_api_key_overwrite_restores_wallet_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_invalidation(monkeypatch)

    admin_user = SimpleNamespace(id="admin-1")
    existing_key = SimpleNamespace(
        id="key-existing",
        user_id="old-owner",
        key_encrypted="old-encrypted",
        name="old-name",
        is_standalone=False,
        is_locked=True,
        allowed_providers=["old-provider"],
        allowed_api_formats=["openai:chat"],
        allowed_models=["old-model"],
        rate_limit=99,
        concurrent_limit=1,
        force_capabilities=None,
        is_active=False,
        expires_at=None,
        auto_delete_on_expiry=False,
        total_requests=1,
        total_cost_usd=1.0,
        updated_at=None,
    )
    db = _DbStub(user_first=admin_user, api_key_first=existing_key)

    wallet = SimpleNamespace(
        limit_mode="finite",
        balance=0,
        gift_balance=0,
        total_recharged=0,
        total_consumed=0,
        total_refunded=0,
        total_adjusted=0,
        status="active",
        updated_at=None,
    )
    wallet_service = SimpleNamespace(
        get_or_create_wallet=lambda *_args, **_kwargs: wallet
    )
    monkeypatch.setattr("src.api.admin.system._wallet_service", lambda: wallet_service)

    payload = {
        "version": "2.3",
        "merge_mode": "overwrite",
        "standalone_api_keys": [
            {
                "name": "Imported Standalone",
                "key": "sk-standalone-import-12345",
                "allowed_providers": ["openai"],
                "allowed_api_formats": ["openai:chat"],
                "allowed_models": ["gpt-4o"],
                "rate_limit": None,
                "concurrent_limit": 7,
                "force_capabilities": ["chat"],
                "is_active": True,
                "auto_delete_on_expiry": True,
                "total_requests": 10,
                "total_cost_usd": 2.5,
                "wallet": {
                    "limit_mode": "finite",
                    "recharge_balance": 12.5,
                    "gift_balance": 1.5,
                    "total_recharged": 20,
                    "total_consumed": 8,
                    "total_refunded": 2,
                    "total_adjusted": -1,
                    "status": "active",
                },
            }
        ],
    }

    result = await AdminImportConfigAdapter().handle(_make_context(db, payload))

    assert result["stats"]["standalone_api_keys"] == {
        "created": 0,
        "updated": 1,
        "skipped": 0,
    }
    assert existing_key.user_id == "admin-1"
    assert existing_key.is_standalone is True
    assert existing_key.is_locked is False
    assert existing_key.name == "Imported Standalone"
    assert existing_key.concurrent_limit == 7
    assert existing_key.total_requests == 10
    assert existing_key.total_cost_usd == 2.5
    assert wallet.limit_mode == "finite"
    assert wallet.balance == 12.5
    assert wallet.gift_balance == 1.5
    assert wallet.total_recharged == 20
    assert wallet.total_consumed == 8
    assert wallet.total_refunded == 2
    assert wallet.total_adjusted == -1
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_import_config_standalone_api_key_merge_mode_error_on_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_invalidation(monkeypatch)

    admin_user = SimpleNamespace(id="admin-1")
    existing_key = SimpleNamespace(key_hash=ApiKey.hash_key("sk-existing-key-12345"))
    db = _DbStub(user_first=admin_user, api_key_first=existing_key)

    payload = {
        "version": "2.3",
        "merge_mode": "error",
        "standalone_api_keys": [
            {
                "name": "Colliding Key",
                "key": "sk-existing-key-12345",
            }
        ],
    }

    with pytest.raises(InvalidRequestException, match="API Key 'Colliding Key' 已存在"):
        await AdminImportConfigAdapter().handle(_make_context(db, payload))

    db.rollback.assert_called_once()
    db.commit.assert_not_called()
