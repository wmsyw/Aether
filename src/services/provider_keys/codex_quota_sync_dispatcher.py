"""
Codex 配额实时同步调度器（异步去重版）。

目标：
- 请求主路径只投递事件，不阻塞在解析/查询/提交上
- 同一 provider_api_key_id 在短窗口内仅保留最后一份响应头
- 后台批量 flush 到数据库，降低请求路径抖动
"""

from __future__ import annotations

import asyncio
from threading import Lock
from typing import Any

from sqlalchemy.orm import Session

from src.core.logger import logger
from src.database.database import create_session
from src.services.provider_keys.codex_realtime_quota import sync_codex_quota_from_response_headers


class CodexQuotaSyncDispatcher:
    """Codex 配额同步异步调度器。"""

    def __init__(self, flush_interval_seconds: float = 0.5) -> None:
        self.flush_interval_seconds = flush_interval_seconds
        self._pending: dict[str, dict[str, Any]] = {}
        self._pending_lock = Lock()
        self._event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._loop = asyncio.get_running_loop()
        self._event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="codex-quota-sync-dispatcher")
        self._running = True
        logger.info(
            "Codex 配额异步同步器已启动，flush_interval={}s",
            self.flush_interval_seconds,
        )

    async def stop(self) -> None:
        if not self._running:
            return

        task = self._task
        self._running = False
        self._task = None
        self._loop = None
        self._event = None

        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info("Codex 配额异步同步器已停止")

    def enqueue(
        self,
        *,
        provider_api_key_id: str | None,
        response_headers: dict[str, Any] | None,
    ) -> bool:
        """
        投递配额同步事件。

        返回:
        - True: 已进入异步队列
        - False: 调度器未运行或参数无效（调用方可回退同步路径）
        """
        loop = self._loop
        event = self._event
        if (
            not self._running
            or loop is None
            or event is None
            or not provider_api_key_id
            or not isinstance(response_headers, dict)
        ):
            return False

        payload = dict(response_headers)
        with self._pending_lock:
            # 同一 key 仅保留最新响应头，天然去重
            self._pending[provider_api_key_id] = payload

        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError as exc:
            # 事件循环关闭/切换时回退同步路径，避免请求路径抛异常。
            with self._pending_lock:
                if self._pending.get(provider_api_key_id) is payload:
                    self._pending.pop(provider_api_key_id, None)
            logger.warning("Codex 配额异步同步器投递失败，已回退同步路径: {}", exc)
            return False
        return True

    async def _run(self) -> None:
        assert self._event is not None
        event = self._event

        try:
            while True:
                await event.wait()
                await asyncio.sleep(self.flush_interval_seconds)
                batch = self._drain_pending()
                if batch:
                    try:
                        await asyncio.to_thread(self._flush_batch_sync, batch)
                    except Exception as exc:
                        logger.warning("Codex 配额异步同步器 flush 失败，将在下一轮重试: {}", exc)
                        self._merge_back_pending(batch)
                with self._pending_lock:
                    if not self._pending:
                        event.clear()
        except asyncio.CancelledError:
            batch = self._drain_pending()
            if batch:
                try:
                    await asyncio.to_thread(self._flush_batch_sync, batch)
                except Exception as exc:
                    logger.warning("Codex 配额异步同步器停止时 flush 失败: {}", exc)
            raise

    def _drain_pending(self) -> dict[str, dict[str, Any]]:
        with self._pending_lock:
            if not self._pending:
                return {}
            batch = dict(self._pending)
            self._pending.clear()
            return batch

    def _merge_back_pending(self, batch: dict[str, dict[str, Any]]) -> None:
        if not batch:
            return
        with self._pending_lock:
            self._pending.update(batch)

    def _flush_batch_sync(self, batch: dict[str, dict[str, Any]]) -> None:
        if not batch:
            return

        db: Session = create_session()
        updated_count = 0
        try:
            for provider_api_key_id, response_headers in batch.items():
                try:
                    updated = sync_codex_quota_from_response_headers(
                        db=db,
                        provider_api_key_id=provider_api_key_id,
                        response_headers=response_headers,
                    )
                    if updated:
                        db.commit()
                        updated_count += 1
                    else:
                        db.rollback()
                except Exception as exc:
                    db.rollback()
                    logger.warning(
                        "异步同步 Codex 配额失败，已跳过: provider_api_key_id={}, error={}",
                        provider_api_key_id,
                        exc,
                    )
            if updated_count > 0:
                logger.debug(
                    "异步同步 Codex 配额完成: queued_keys={}, updated_keys={}",
                    len(batch),
                    updated_count,
                )
        finally:
            db.close()


_dispatcher_instance: CodexQuotaSyncDispatcher | None = None


def get_codex_quota_sync_dispatcher() -> CodexQuotaSyncDispatcher:
    global _dispatcher_instance
    if _dispatcher_instance is None:
        _dispatcher_instance = CodexQuotaSyncDispatcher()
    return _dispatcher_instance


async def init_codex_quota_sync_dispatcher() -> CodexQuotaSyncDispatcher:
    dispatcher = get_codex_quota_sync_dispatcher()
    await dispatcher.start()
    return dispatcher


async def shutdown_codex_quota_sync_dispatcher() -> None:
    global _dispatcher_instance
    if _dispatcher_instance is None:
        return
    await _dispatcher_instance.stop()
    _dispatcher_instance = None


def dispatch_codex_quota_sync_from_response_headers(
    *,
    provider_api_key_id: str | None,
    response_headers: dict[str, Any] | None,
    db: Session | None = None,
) -> None:
    """
    投递 Codex 配额同步事件。

    正常路径:
    - 调度器已启动：异步去重后后台落库

    回退路径:
    - 调度器未启动且提供了 db：退回同步执行，避免数据丢失
    """
    dispatcher = get_codex_quota_sync_dispatcher()
    queued = dispatcher.enqueue(
        provider_api_key_id=provider_api_key_id,
        response_headers=response_headers,
    )
    if queued:
        return
    if db is not None:
        sync_codex_quota_from_response_headers(
            db=db,
            provider_api_key_id=provider_api_key_id,
            response_headers=response_headers,
        )
