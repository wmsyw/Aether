from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.api.admin.monitoring.trace import AdminGetRequestTraceAdapter
from src.services.request.candidate import RequestCandidateService


def _candidate(*, status: str, latency_ms: int | None = None) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=f"cand-{status}",
        request_id="req-1",
        candidate_index=0,
        retry_index=0,
        provider_id=None,
        endpoint_id=None,
        key_id=None,
        required_capabilities=None,
        status=status,
        skip_reason=None,
        is_cached=False,
        status_code=None,
        error_type=None,
        error_message=None,
        latency_ms=latency_ms,
        concurrent_requests=None,
        extra_data=None,
        created_at=now,
        started_at=None,
        finished_at=None,
    )


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        db=MagicMock(),
        add_audit_metadata=lambda **_: None,
    )


def test_trace_returns_all_candidates_including_unused(monkeypatch: object) -> None:
    candidates = [
        _candidate(status="available"),
        _candidate(status="unused"),
        _candidate(status="failed", latency_ms=123),
    ]
    monkeypatch.setattr(
        RequestCandidateService,
        "get_candidates_by_request_id",
        lambda _db, _request_id: candidates,
    )

    adapter = AdminGetRequestTraceAdapter(request_id="req-1")
    response = asyncio.run(adapter.handle(_context()))

    assert response.total_candidates == 3
    assert len(response.candidates) == 3
    assert {c.status for c in response.candidates} == {"available", "unused", "failed"}
    assert response.total_latency_ms == 123


def test_trace_returns_unattempted_candidates(monkeypatch: object) -> None:
    candidates = [
        _candidate(status="available"),
        _candidate(status="unused"),
    ]
    monkeypatch.setattr(
        RequestCandidateService,
        "get_candidates_by_request_id",
        lambda _db, _request_id: candidates,
    )

    adapter = AdminGetRequestTraceAdapter(request_id="req-1")
    response = asyncio.run(adapter.handle(_context()))

    assert response.total_candidates == 2
    assert len(response.candidates) == 2
    assert {c.status for c in response.candidates} == {"available", "unused"}
