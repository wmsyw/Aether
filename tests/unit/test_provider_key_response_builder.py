from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.services.provider_keys import response_builder as module
from src.services.provider_keys.response_builder import build_key_response


def _make_key(**overrides: Any) -> Any:
    now = datetime.now(timezone.utc)
    data = {
        "id": "key-1",
        "provider_id": "provider-1",
        "api_formats": ["openai:chat"],
        "auth_type": "api_key",
        "api_key": "enc-access-token",
        "auth_config": None,
        "name": "test-key",
        "status_snapshot": None,
        "success_count": 0,
        "request_count": 0,
        "error_count": 0,
        "total_response_time_ms": 0,
        "rpm_limit": None,
        "global_priority_by_format": None,
        "allowed_models": None,
        "capabilities": None,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "cache_ttl_minutes": 5,
        "max_probe_interval_minutes": 32,
        "health_by_format": None,
        "circuit_breaker_by_format": None,
        "oauth_invalid_at": None,
        "oauth_invalid_reason": None,
        "note": None,
        "last_used_at": None,
        "provider": None,
    }
    data.update(overrides)
    return cast(Any, SimpleNamespace(**data))


def test_build_key_response_includes_codex_identity_metadata(
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    key = _make_key(
        auth_type="oauth",
        auth_config='{"email":"u@example.com","plan_type":"team","account_id":"acc-1","account_name":"Workspace Alpha","account_user_id":"user-1__acc-1","organizations":[{"id":"org-1","title":"Personal","is_default":true,"role":"owner"}],"expires_at":2100000000}',
        name="codex-user",
    )

    monkeypatch.setattr(module.crypto_service, "decrypt", lambda value: value)

    result = build_key_response(key)

    assert result.oauth_email == "u@example.com"
    assert result.oauth_plan_type == "team"
    assert result.oauth_account_id == "acc-1"
    assert result.oauth_account_name == "Workspace Alpha"
    assert result.oauth_account_user_id == "user-1__acc-1"
    assert len(result.oauth_organizations) == 1
    assert result.oauth_organizations[0].title == "Personal"
    assert result.oauth_organizations[0].is_default is True
    assert result.status_snapshot.oauth.code == "valid"
    assert result.status_snapshot.oauth.expires_at == 2100000000
    assert result.status_snapshot.account.code == "ok"


def test_build_key_response_prefers_persisted_status_snapshot_layers(
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    key = _make_key(
        id="key-2",
        auth_type="oauth",
        auth_config='{"expires_at":100}',
        name="codex-user",
        status_snapshot={
            "oauth": {"code": "valid", "label": "有效", "expires_at": 100},
            "account": {
                "code": "workspace_deactivated",
                "label": "工作区停用",
                "reason": "persisted",
                "blocked": True,
            },
            "quota": {
                "code": "exhausted",
                "label": "额度耗尽",
                "reason": "persisted quota",
                "exhausted": True,
            },
        },
    )

    monkeypatch.setattr(module.crypto_service, "decrypt", lambda value: value)

    result = build_key_response(key)

    assert result.status_snapshot.oauth.code == "expired"
    assert result.status_snapshot.account.code == "workspace_deactivated"
    assert result.status_snapshot.quota.code == "exhausted"


def test_build_key_response_normalizes_api_formats_and_format_dicts(
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    key = _make_key(
        id="key-3",
        api_formats=["OPENAI:CLI", " openai:chat "],
        api_key="enc-sk-test-1234567890",
        name="legacy-key",
        rate_multipliers={"OPENAI:CLI": 1.5},
        global_priority_by_format={"OPENAI:CHAT": 3},
        health_by_format={"OPENAI:CLI": {"health_score": 0.8}},
        circuit_breaker_by_format={"OPENAI:CLI": {"open": True}},
        success_count=1,
        request_count=1,
        total_response_time_ms=10,
    )

    monkeypatch.setattr(
        module.crypto_service, "decrypt", lambda value: value.removeprefix("enc-")
    )

    result = build_key_response(key)

    assert result.api_formats == ["openai:cli", "openai:chat"]
    assert result.rate_multipliers == {"openai:cli": 1.5}
    assert result.global_priority_by_format == {"openai:chat": 3}
    assert result.health_by_format == {"openai:cli": {"health_score": 0.8}}
    assert result.circuit_breaker_by_format == {"openai:cli": {"open": True}}
