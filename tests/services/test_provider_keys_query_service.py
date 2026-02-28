from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.core.exceptions import NotFoundException
from src.services.provider_keys import key_query_service as query_service_module
from src.services.provider_keys.key_query_service import (
    get_keys_grouped_by_format,
    list_provider_keys_responses,
)


class _FakeQuery:
    def __init__(
        self,
        *,
        first_result: Any = None,
        all_result: list[Any] | None = None,
    ) -> None:
        self._first_result = first_result
        self._all_result = all_result or []

    def join(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def filter(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def order_by(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def offset(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def limit(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def first(self) -> Any:
        return self._first_result

    def all(self) -> list[Any]:
        return self._all_result


class _FakeGroupedDB:
    def __init__(
        self,
        *,
        key_provider_rows: list[tuple[Any, Any]],
        endpoint_rows: list[tuple[str, str, str]],
    ) -> None:
        self._key_provider_rows = key_provider_rows
        self._endpoint_rows = endpoint_rows

    def query(self, *models: Any) -> _FakeQuery:
        if len(models) == 2:
            return _FakeQuery(all_result=self._key_provider_rows)
        if len(models) == 3:
            return _FakeQuery(all_result=self._endpoint_rows)
        raise AssertionError(f"unexpected query models: {models}")


class _FakeListDB:
    def __init__(self, *, provider: Any, keys: list[SimpleNamespace]) -> None:
        self._provider = provider
        self._keys = keys

    def query(self, model: Any) -> _FakeQuery:
        model_name = getattr(model, "__name__", "")
        if model_name == "Provider":
            return _FakeQuery(first_result=self._provider)
        if model_name == "ProviderAPIKey":
            return _FakeQuery(all_result=self._keys)
        raise AssertionError(f"unexpected query model: {model}")


def test_get_keys_grouped_by_format_builds_expected_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SimpleNamespace(id="p1", is_active=True, name="Provider-1")
    key = SimpleNamespace(
        id="k1",
        name="Key-1",
        api_formats=["openai:chat", "openai:cli"],
        auth_type="api_key",
        api_key="enc-key",
        internal_priority=3,
        global_priority_by_format={"openai:chat": 8},
        rate_multipliers={"openai:chat": 1.1},
        is_active=True,
        capabilities={"cache_1h": True, "ctx_1m": False},
        success_count=8,
        request_count=10,
        total_response_time_ms=800,
        health_by_format={"openai:chat": {"health_score": 0.7}},
        circuit_breaker_by_format={"openai:chat": {"open": True}},
    )
    db = _FakeGroupedDB(
        key_provider_rows=[(key, provider)],
        endpoint_rows=[
            ("p1", "openai:chat", "https://chat.example"),
            ("p1", "openai:cli", "https://cli.example"),
        ],
    )

    monkeypatch.setattr(
        query_service_module.crypto_service, "decrypt", lambda _v: "sk-1234567890abcd"
    )
    monkeypatch.setattr(
        query_service_module,
        "get_capability",
        lambda name: SimpleNamespace(short_name="缓存1h") if name == "cache_1h" else None,
    )

    result = get_keys_grouped_by_format(cast(Any, db))

    assert set(result.keys()) == {"openai:chat", "openai:cli"}
    chat_item = result["openai:chat"][0]
    assert chat_item["id"] == "k1"
    assert chat_item["provider_name"] == "Provider-1"
    assert chat_item["endpoint_base_url"] == "https://chat.example"
    assert chat_item["format_priority"] == 8
    assert chat_item["circuit_breaker_open"] is True
    assert chat_item["health_score"] == 0.7
    assert chat_item["capabilities"] == ["缓存1h"]
    assert chat_item["api_key_masked"].startswith("sk-12345")
    assert chat_item["api_key_masked"].endswith("abcd")

    cli_item = result["openai:cli"][0]
    assert cli_item["endpoint_base_url"] == "https://cli.example"
    assert cli_item["format_priority"] is None
    assert cli_item["circuit_breaker_open"] is False
    assert cli_item["health_score"] == 1.0


def test_list_provider_keys_responses_provider_not_found_raises() -> None:
    db = _FakeListDB(provider=None, keys=[])
    with pytest.raises(NotFoundException, match="Provider p1 不存在"):
        list_provider_keys_responses(cast(Any, db), provider_id="p1", skip=0, limit=10)


def test_list_provider_keys_responses_uses_response_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SimpleNamespace(id="p1")
    keys = [SimpleNamespace(id="k1"), SimpleNamespace(id="k2")]
    db = _FakeListDB(provider=provider, keys=keys)

    monkeypatch.setattr(query_service_module, "build_key_response", lambda key: {"id": key.id})

    result = list_provider_keys_responses(cast(Any, db), provider_id="p1", skip=0, limit=10)
    assert result == [{"id": "k1"}, {"id": "k2"}]
