from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.candidate.schema import CandidateKey
from src.services.candidate.submit import SubmitOutcome
from src.services.task.context import TaskMode
from src.services.task.protocol import AttemptKind
from src.services.task.service import TaskService


@pytest.mark.asyncio
async def test_task_service_execute_async_requires_extract_external_task_id() -> None:
    svc = TaskService(MagicMock())
    with pytest.raises(ValueError):
        await svc.execute(
            task_type="video",
            task_mode=TaskMode.ASYNC,
            api_format="openai:video",
            model_name="m",
            user_api_key=MagicMock(id="u", user_id="user"),
            request_func=AsyncMock(),
            request_id="rid",
        )


@pytest.mark.asyncio
async def test_task_service_execute_async_returns_execution_result() -> None:
    db = MagicMock()
    svc = TaskService(db)

    candidate = SimpleNamespace(
        provider=SimpleNamespace(id="p1", name="prov"),
        endpoint=SimpleNamespace(id="e1"),
        key=SimpleNamespace(id="k1"),
    )
    outcome = SubmitOutcome(
        candidate=candidate,  # type: ignore[arg-type]
        candidate_keys=[{"index": 0, "provider_id": "p1"}],
        external_task_id="task_123",
        rule_lookup=None,
        upstream_payload={"id": "x"},
        upstream_headers={"x-test": "1"},
        upstream_status_code=200,
    )

    svc.submit_with_failover = AsyncMock(return_value=outcome)  # type: ignore[method-assign]
    svc._recorder.get_candidate_keys = MagicMock(  # type: ignore[attr-defined, method-assign]
        return_value=[
            CandidateKey(candidate_index=0, retry_index=0, status="success", provider_id="p1")
        ]
    )

    result = await svc.execute(
        task_type="video",
        task_mode=TaskMode.ASYNC,
        api_format="openai:video",
        model_name="m",
        user_api_key=MagicMock(id="u", user_id="user"),
        request_func=AsyncMock(),
        request_id="rid",
        extract_external_task_id=MagicMock(),
        allow_format_conversion=True,
    )

    assert result.success is True
    assert result.attempt_result is not None
    assert result.attempt_result.kind == AttemptKind.ASYNC_SUBMIT
    assert result.provider_task_id == "task_123"
    assert result.provider_id == "p1"
    assert result.candidate_index == 0


@pytest.mark.asyncio
async def test_task_service_execute_sync_passes_request_headers_and_body() -> None:
    db = MagicMock()
    svc = TaskService(db)
    sentinel_result = object()
    svc._execute_sync_unified = AsyncMock(  # type: ignore[method-assign]
        return_value=sentinel_result
    )

    request_headers = {"authorization": "Bearer test", "x-trace-id": "abc123"}
    request_body = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}
    request_body_ref = {"body": request_body}

    result = await svc.execute(
        task_type="chat",
        task_mode=TaskMode.SYNC,
        api_format="openai:chat",
        model_name="gpt-4o-mini",
        user_api_key=MagicMock(id="u", user_id="user"),
        request_func=AsyncMock(),
        request_id="rid-sync",
        is_stream=True,
        request_headers=request_headers,
        request_body=request_body,
        request_body_ref=request_body_ref,
    )

    assert result is sentinel_result
    svc._execute_sync_unified.assert_awaited_once()  # type: ignore[attr-defined]
    kwargs = svc._execute_sync_unified.await_args.kwargs  # type: ignore[attr-defined, union-attr]
    assert kwargs["request_headers"] == request_headers
    assert kwargs["request_body"] == request_body
    assert kwargs["request_body_ref"] == request_body_ref
