from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from src.services.provider_keys import key_query_service as module


class _DummyQuery:
    def __init__(self, key: SimpleNamespace | None) -> None:
        self._key = key

    def filter(self, *_args: object, **_kwargs: object) -> "_DummyQuery":
        return self

    def first(self) -> SimpleNamespace | None:
        return self._key


class _DummyDB:
    def __init__(self, key: SimpleNamespace | None) -> None:
        self._key = key

    def query(self, _model: object) -> _DummyQuery:
        return _DummyQuery(self._key)


def test_export_oauth_key_data_includes_api_formats(monkeypatch) -> None:
    key = SimpleNamespace(
        id="key-1",
        auth_type="oauth",
        auth_config=json.dumps({"provider_type": "codex", "refresh_token": "rt-1"}),
        name="oauth-key",
        upstream_metadata=None,
        api_formats=["openai:cli", " openai:chat ", ""],
    )
    db: Any = _DummyDB(key)

    monkeypatch.setattr(module.crypto_service, "decrypt", lambda value: value)
    monkeypatch.setattr(
        "src.services.provider.export.build_export_data",
        lambda provider_type, auth_config, upstream: {
            "provider_type": provider_type,
            "refresh_token": auth_config.get("refresh_token"),
        },
    )

    export_data = module.export_oauth_key_data(db, "key-1")

    assert export_data["api_formats"] == ["openai:cli", "openai:chat"]
    assert export_data["name"] == "oauth-key"
    assert export_data["provider_type"] == "codex"
    assert export_data["refresh_token"] == "rt-1"
    assert "exported_at" in export_data


def test_export_oauth_key_data_defaults_empty_api_formats(monkeypatch) -> None:
    key = SimpleNamespace(
        id="key-2",
        auth_type="oauth",
        auth_config=json.dumps({"provider_type": "codex", "refresh_token": "rt-2"}),
        name="oauth-key-2",
        upstream_metadata=None,
        api_formats=None,
    )
    db: Any = _DummyDB(key)

    monkeypatch.setattr(module.crypto_service, "decrypt", lambda value: value)
    monkeypatch.setattr(
        "src.services.provider.export.build_export_data",
        lambda provider_type, auth_config, upstream: {
            "provider_type": provider_type,
            "refresh_token": auth_config.get("refresh_token"),
        },
    )

    export_data = module.export_oauth_key_data(db, "key-2")

    assert export_data["api_formats"] == []
