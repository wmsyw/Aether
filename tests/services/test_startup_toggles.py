from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import src.services.system.maintenance_scheduler as maintenance_scheduler_module
from src.config.settings import config
from src.services.system.maintenance_scheduler import MaintenanceScheduler


@pytest.mark.asyncio
async def test_maintenance_scheduler_start_skips_startup_task_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "maintenance_startup_tasks_enabled", False)

    scheduler = MaintenanceScheduler()

    created = False

    def fake_create_task(coro):  # type: ignore[no-untyped-def]
        nonlocal created
        created = True
        if inspect.iscoroutine(coro):
            coro.close()
        return object()

    monkeypatch.setattr(maintenance_scheduler_module.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(scheduler, "_get_checkin_time", lambda: (1, 5))
    monkeypatch.setattr(
        maintenance_scheduler_module,
        "get_scheduler",
        lambda: SimpleNamespace(
            add_cron_job=lambda *args, **kwargs: None,
            add_interval_job=lambda *args, **kwargs: None,
        ),
    )

    await scheduler.start()

    assert created is False


def test_http_client_idle_cleanup_interval_env_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_CLIENT_IDLE_CLEANUP_INTERVAL_MINUTES", "bad")
    assert MaintenanceScheduler._get_http_client_idle_cleanup_interval_minutes() == 5


@pytest.mark.asyncio
async def test_candidate_cleanup_uses_dedicated_retention_and_batch_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduler = MaintenanceScheduler()

    class _FakeLoop:
        async def run_in_executor(self, _executor, func):  # type: ignore[no-untyped-def]
            return func()

    class _ConfigSession:
        def close(self) -> None:
            return None

    class _BatchSession:
        def __init__(self, ids: list[str]) -> None:
            self.ids = ids
            self.closed = False
            self.committed = False
            self.query_obj = MagicMock()
            filtered = self.query_obj.filter.return_value
            filtered.order_by.return_value.limit.return_value.all.return_value = [
                SimpleNamespace(id=value) for value in ids
            ]

        def query(self, _model):  # type: ignore[no-untyped-def]
            return self.query_obj

        def execute(self, _statement):  # type: ignore[no-untyped-def]
            return SimpleNamespace(rowcount=len(self.ids))

        def commit(self) -> None:
            self.committed = True

        def rollback(self) -> None:
            raise AssertionError("rollback should not be called")

        def close(self) -> None:
            self.closed = True

    config_session = _ConfigSession()
    batch_one = _BatchSession(["candidate-1", "candidate-2"])
    batch_two = _BatchSession([])
    sessions = iter([config_session, batch_one, batch_two])

    def fake_create_session():  # type: ignore[no-untyped-def]
        return next(sessions)

    config_values = {
        "enable_auto_cleanup": True,
        "request_candidates_retention_days": 21,
        "request_candidates_cleanup_batch_size": 2,
    }

    monkeypatch.setattr(maintenance_scheduler_module, "create_session", fake_create_session)
    monkeypatch.setattr(
        maintenance_scheduler_module.SystemConfigService,
        "get_config",
        lambda _db, key, default=None: config_values.get(key, default),
    )
    monkeypatch.setattr(
        maintenance_scheduler_module.asyncio, "get_running_loop", lambda: _FakeLoop()
    )

    await scheduler._perform_candidate_cleanup()

    batch_one.query_obj.filter.return_value.order_by.return_value.limit.return_value.all.assert_called_once()
    batch_one.query_obj.filter.return_value.order_by.return_value.limit.assert_called_once_with(2)
    assert batch_one.committed is True
    assert batch_one.closed is True
    assert batch_two.closed is True


def test_cleanup_body_fields_loads_ids_then_processes_records_individually(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduler = MaintenanceScheduler()

    class _IdBatchSession:
        def __init__(self, ids: list[str]) -> None:
            self.ids = ids
            self.closed = False
            self.query_obj = MagicMock()
            filtered = self.query_obj.filter.return_value
            filtered.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
                SimpleNamespace(id=value) for value in ids
            ]

        def query(self, *args):  # type: ignore[no-untyped-def]
            self.query_args = args
            return self.query_obj

        def rollback(self) -> None:
            raise AssertionError("rollback should not be called")

        def close(self) -> None:
            self.closed = True

    class _RecordSession:
        def __init__(self, record: SimpleNamespace) -> None:
            self.record = record
            self.closed = False
            self.committed = False
            self.query_obj = MagicMock()
            self.query_obj.filter.return_value.first.return_value = record

        def query(self, *args):  # type: ignore[no-untyped-def]
            self.query_args = args
            return self.query_obj

        def execute(self, _statement):  # type: ignore[no-untyped-def]
            return SimpleNamespace(rowcount=1)

        def commit(self) -> None:
            self.committed = True

        def rollback(self) -> None:
            raise AssertionError("rollback should not be called")

        def close(self) -> None:
            self.closed = True

    batch_one = _IdBatchSession(["usage-1", "usage-2"])
    record_one = _RecordSession(
        SimpleNamespace(
            id="usage-1",
            request_body={"hello": "world"},
            response_body=None,
            provider_request_body=None,
            client_response_body=None,
        )
    )
    record_two = _RecordSession(
        SimpleNamespace(
            id="usage-2",
            request_body=None,
            response_body={"ok": True},
            provider_request_body=None,
            client_response_body=None,
        )
    )
    batch_two = _IdBatchSession([])
    sessions = iter([batch_one, record_one, record_two, batch_two])

    monkeypatch.setattr(
        maintenance_scheduler_module,
        "create_session",
        lambda: next(sessions),
    )
    monkeypatch.setattr(
        maintenance_scheduler_module,
        "compress_json",
        lambda payload: f"compressed:{payload}".encode(),
    )

    compressed = scheduler._cleanup_body_fields(
        cutoff_time=SimpleNamespace(),  # type: ignore[arg-type]
        batch_size=1000,
    )

    assert compressed == 2
    assert batch_one.query_args == (maintenance_scheduler_module.Usage.id,)
    assert len(record_one.query_args) == 5
    assert len(record_two.query_args) == 5
    assert batch_one.closed is True
    assert batch_two.closed is True
    assert record_one.committed is True
    assert record_two.committed is True
    assert record_one.closed is True
    assert record_two.closed is True
