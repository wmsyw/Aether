from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from src.services.provider_keys import codex_quota_sync_dispatcher as dispatcher_module


def _flush_ok(batch: dict[str, dict[str, Any]]) -> dispatcher_module.FlushResult:
    return dispatcher_module.FlushResult(
        queued_count=len(batch),
        updated_count=len(batch),
        retry_batch={},
    )


class _FakeNestedTxn:
    def __enter__(self) -> "_FakeNestedTxn":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        _ = exc_type, exc, tb
        return None


class _FakeSession:
    def __init__(self, *, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    def begin_nested(self) -> _FakeNestedTxn:
        return _FakeNestedTxn()

    def commit(self) -> None:
        self.commit_calls += 1
        if self.fail_commit and self.commit_calls == 1:
            raise RuntimeError("commit failed once")

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.closed = True


def test_dispatch_falls_back_to_sync_when_dispatcher_not_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = dispatcher_module.CodexQuotaSyncDispatcher(flush_interval_seconds=0.01)
    monkeypatch.setattr(dispatcher_module, "_dispatcher_instance", dispatcher)

    captured: dict[str, Any] = {}

    def _fake_sync(
        *,
        db: Any,
        provider_api_key_id: str | None,
        response_headers: dict[str, Any] | None,
    ) -> bool:
        captured["db"] = db
        captured["provider_api_key_id"] = provider_api_key_id
        captured["response_headers"] = response_headers
        return False

    monkeypatch.setattr(dispatcher_module, "sync_codex_quota_from_response_headers", _fake_sync)

    fake_db = cast(Any, object())
    dispatcher_module.dispatch_codex_quota_sync_from_response_headers(
        provider_api_key_id="fallback-key",
        response_headers={"x-codex-primary-used-percent": "12"},
        db=fake_db,
    )

    assert captured["db"] is fake_db
    assert captured["provider_api_key_id"] == "fallback-key"
    assert captured["response_headers"] == {"x-codex-primary-used-percent": "12"}


@pytest.mark.asyncio
async def test_dispatcher_deduplicates_headers_by_provider_api_key_id() -> None:
    dispatcher = dispatcher_module.CodexQuotaSyncDispatcher(flush_interval_seconds=0.01)
    flushed_batches: list[dict[str, dict[str, Any]]] = []

    def _fake_flush(batch: dict[str, dict[str, Any]]) -> dispatcher_module.FlushResult:
        flushed_batches.append(batch)
        return _flush_ok(batch)

    dispatcher._flush_batch_sync = _fake_flush  # type: ignore[method-assign]

    await dispatcher.start()
    try:
        assert dispatcher.enqueue(
            provider_api_key_id="key-a",
            response_headers={"x-codex-primary-used-percent": "1"},
        )
        assert dispatcher.enqueue(
            provider_api_key_id="key-a",
            response_headers={"x-codex-primary-used-percent": "2"},
        )
        assert dispatcher.enqueue(
            provider_api_key_id="key-b",
            response_headers={"x-codex-secondary-used-percent": "8"},
        )
        await asyncio.sleep(0.06)
    finally:
        await dispatcher.stop()

    merged: dict[str, dict[str, Any]] = {}
    for batch in flushed_batches:
        merged.update(batch)

    assert merged["key-a"] == {"x-codex-primary-used-percent": "2"}
    assert merged["key-b"] == {"x-codex-secondary-used-percent": "8"}


@pytest.mark.asyncio
async def test_dispatcher_retries_batch_after_flush_error() -> None:
    dispatcher = dispatcher_module.CodexQuotaSyncDispatcher(flush_interval_seconds=0.01)
    flushed_batches: list[dict[str, dict[str, Any]]] = []
    flush_attempts = 0

    def _flaky_flush(batch: dict[str, dict[str, Any]]) -> dispatcher_module.FlushResult:
        nonlocal flush_attempts
        flush_attempts += 1
        if flush_attempts == 1:
            raise RuntimeError("temporary flush error")
        flushed_batches.append(batch)
        return _flush_ok(batch)

    dispatcher._flush_batch_sync = _flaky_flush  # type: ignore[method-assign]

    await dispatcher.start()
    try:
        assert dispatcher.enqueue(
            provider_api_key_id="retry-key",
            response_headers={"x-codex-primary-used-percent": "7"},
        )
        await asyncio.sleep(0.12)
    finally:
        await dispatcher.stop()

    merged: dict[str, dict[str, Any]] = {}
    for batch in flushed_batches:
        merged.update(batch)

    assert flush_attempts >= 2
    assert merged["retry-key"] == {"x-codex-primary-used-percent": "7"}


def test_flush_batch_falls_back_to_single_item_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = dispatcher_module.CodexQuotaSyncDispatcher(flush_interval_seconds=0.01)
    main_session = _FakeSession(fail_commit=True)
    fallback_session_a = _FakeSession()
    fallback_session_b = _FakeSession()
    sessions: list[_FakeSession] = [main_session, fallback_session_a, fallback_session_b]

    def _fake_create_session() -> _FakeSession:
        return sessions.pop(0)

    def _fake_sync(
        *,
        db: Any,
        provider_api_key_id: str | None,
        response_headers: dict[str, Any] | None,
    ) -> bool:
        _ = db, provider_api_key_id, response_headers
        return True

    monkeypatch.setattr(dispatcher_module, "create_session", _fake_create_session)
    monkeypatch.setattr(dispatcher_module, "sync_codex_quota_from_response_headers", _fake_sync)

    result = dispatcher._flush_batch_sync(
        {
            "key-a": {"x-codex-primary-used-percent": "1"},
            "key-b": {"x-codex-primary-used-percent": "2"},
        }
    )

    assert result.updated_count == 2
    assert result.retry_batch == {}
    assert main_session.rollback_calls == 1
    assert fallback_session_a.commit_calls == 1
    assert fallback_session_b.commit_calls == 1
    assert main_session.closed is True
    assert fallback_session_a.closed is True
    assert fallback_session_b.closed is True


@pytest.mark.asyncio
async def test_dispatch_uses_async_queue_when_dispatcher_running() -> None:
    dispatcher = dispatcher_module.CodexQuotaSyncDispatcher(flush_interval_seconds=0.01)
    flushed_batches: list[dict[str, dict[str, Any]]] = []
    dispatcher_module._dispatcher_instance = dispatcher

    def _fake_flush(batch: dict[str, dict[str, Any]]) -> dispatcher_module.FlushResult:
        flushed_batches.append(batch)
        return _flush_ok(batch)

    dispatcher._flush_batch_sync = _fake_flush  # type: ignore[method-assign]

    await dispatcher.start()
    try:
        dispatcher_module.dispatch_codex_quota_sync_from_response_headers(
            provider_api_key_id="async-key",
            response_headers={"x-codex-plan-type": "team"},
            db=None,
        )
        await asyncio.sleep(0.06)
    finally:
        await dispatcher.stop()
        dispatcher_module._dispatcher_instance = None

    merged: dict[str, dict[str, Any]] = {}
    for batch in flushed_batches:
        merged.update(batch)
    assert merged["async-key"] == {"x-codex-plan-type": "team"}
