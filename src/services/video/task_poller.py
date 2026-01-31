"""
视频任务后台轮询服务
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from src.api.handlers.base.request_builder import ProviderAuthInfo, get_provider_auth
from src.api.handlers.base.video_handler_base import (
    normalize_gemini_operation_id,
    sanitize_error_message,
)
from src.clients.http_client import HTTPClientPool
from src.clients.redis_client import get_redis_client
from src.config.settings import config
from src.core.api_format import APIFormat, build_upstream_headers, get_extra_headers_from_endpoint
from src.core.api_format.conversion.internal_video import InternalVideoPollResult, VideoStatus
from src.core.api_format.conversion.normalizers.gemini import GeminiNormalizer
from src.core.api_format.conversion.normalizers.openai import OpenAINormalizer
from src.core.crypto import crypto_service
from src.core.logger import logger
from src.database import create_session
from src.models.database import ApiKey, Provider, ProviderAPIKey, ProviderEndpoint, User, VideoTask
from src.services.billing.dimension_collector_service import DimensionCollectorService
from src.services.billing.formula_engine import BillingIncompleteError, FormulaEngine
from src.services.billing.rule_service import BillingRuleService
from src.services.system.scheduler import get_scheduler
from src.services.usage.service import UsageService

# 永久性错误指示词（用于降级判断，不应重试）
_PERMANENT_ERROR_INDICATORS = frozenset(
    {
        "not found",
        "404",
        "unauthorized",
        "401",
        "forbidden",
        "403",
        "invalid request",
        "invalid api key",
        "does not exist",
    }
)


class PollHTTPError(RuntimeError):
    """HTTP 轮询错误，携带状态码便于区分临时/永久错误"""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class VideoTaskPollerService:
    """后台轮询视频生成任务状态"""

    LOCK_KEY = "video_task_poller:lock"
    LOCK_TTL = 60
    MAX_BACKOFF_SECONDS = 300
    # 连续失败告警阈值
    CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 5

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.redis = None
        self._openai_normalizer = OpenAINormalizer()
        self._gemini_normalizer = GeminiNormalizer()
        self._formula_engine = FormulaEngine()
        # 追踪连续失败次数（用于告警）
        self._consecutive_failures = 0
        # 从配置读取参数
        self._batch_size = config.video_poll_batch_size
        self._concurrency = config.video_poll_concurrency
        # Semaphore 延迟初始化，避免在事件循环外创建
        self._semaphore: asyncio.Semaphore | None = None

    async def start(self) -> None:
        # 在事件循环内初始化 Semaphore
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._concurrency)
        if self.redis is None:
            self.redis = await get_redis_client(require_redis=False)

        scheduler = get_scheduler()
        scheduler.add_interval_job(
            self.poll_pending_tasks,
            seconds=config.video_poll_interval_seconds,
            job_id="video_task_poller",
            name="视频任务轮询",
        )

    async def stop(self) -> None:
        """停止轮询服务"""
        scheduler = get_scheduler()
        scheduler.remove_job("video_task_poller")

    async def poll_pending_tasks(self) -> None:
        async with self._lock:
            token = await self._acquire_redis_lock()
            if token is None:
                return

            try:
                with create_session() as db:
                    now = datetime.now(timezone.utc)
                    tasks = (
                        db.query(VideoTask)
                        .filter(
                            VideoTask.status.in_(
                                [
                                    VideoStatus.SUBMITTED.value,
                                    VideoStatus.QUEUED.value,
                                    VideoStatus.PROCESSING.value,
                                ]
                            ),
                            VideoTask.next_poll_at <= now,
                            VideoTask.poll_count < VideoTask.max_poll_count,
                        )
                        .order_by(VideoTask.next_poll_at.asc())
                        .limit(self._batch_size)
                        .all()
                    )

                    if not tasks:
                        # 无任务时重置连续失败计数
                        self._consecutive_failures = 0
                        return

                    # 提取任务 ID 列表，释放查询 session 后逐个轮询
                    task_ids = [t.id for t in tasks]

                # 并发轮询：每个任务使用独立 session，避免共享 session 的并发风险
                poll_results: list[bool] = []

                # 确保 semaphore 已初始化（在 start 中初始化，此处防御性检查）
                if self._semaphore is None:
                    self._semaphore = asyncio.Semaphore(self._concurrency)
                semaphore = self._semaphore

                async def poll_with_semaphore(task_id: str) -> None:
                    """带信号量的轮询，结果写入 poll_results"""
                    async with semaphore:
                        try:
                            with create_session() as task_db:
                                task_obj = task_db.query(VideoTask).get(task_id)
                                if not task_obj:
                                    logger.warning("Task %s disappeared during poll", task_id)
                                    poll_results.append(True)
                                    return
                                await self._poll_single_task(task_db, task_obj)
                                task_db.commit()
                            poll_results.append(True)
                        except Exception as exc:
                            logger.exception(
                                "Unexpected error polling task %s: %s",
                                task_id,
                                sanitize_error_message(str(exc)),
                            )
                            poll_results.append(False)

                async with asyncio.TaskGroup() as tg:
                    for tid in task_ids:
                        tg.create_task(poll_with_semaphore(tid))

                batch_failures = sum(1 for r in poll_results if r is False)

                # 更新连续失败计数并检查告警阈值
                if batch_failures == len(task_ids):
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= self.CONSECUTIVE_FAILURE_ALERT_THRESHOLD:
                        logger.error(
                            "[ALERT] Video task poller: %d consecutive batches failed. "
                            "Provider connectivity or configuration issue suspected.",
                            self._consecutive_failures,
                        )
                else:
                    self._consecutive_failures = 0
            finally:
                await self._release_redis_lock(token)

    async def _poll_single_task(self, db: Session, task: VideoTask) -> None:
        try:
            result = await self._poll_task_status(db, task)
            if result.status == VideoStatus.COMPLETED:
                task.status = VideoStatus.COMPLETED.value
                task.video_url = result.video_url
                task.video_expires_at = result.expires_at
                task.completed_at = datetime.now(timezone.utc)
                task.progress_percent = 100
                # 存储多视频 URL（Gemini sampleCount > 1 时）
                if result.video_urls:
                    task.video_urls = result.video_urls
                # 保存上游原始响应（用于审计/重算）
                self._attach_poll_raw_response(task, result)
            elif result.status == VideoStatus.FAILED:
                task.status = VideoStatus.FAILED.value
                task.error_code = result.error_code
                task.error_message = result.error_message
                task.completed_at = datetime.now(timezone.utc)
                self._attach_poll_raw_response(task, result)
            else:
                task.poll_count += 1
                task.progress_percent = result.progress_percent
                task.next_poll_at = datetime.now(timezone.utc) + timedelta(
                    seconds=task.poll_interval_seconds
                )
        except Exception as exc:
            task.poll_count += 1
            error_msg = sanitize_error_message(str(exc))
            logger.warning("Poll error for task %s: %s", task.id, error_msg)
            task.progress_message = f"Poll error: {error_msg}"

            # 区分临时性错误和永久性错误
            status_code = exc.status_code if isinstance(exc, PollHTTPError) else None
            is_permanent = self._is_permanent_error(exc, status_code=status_code)
            if is_permanent:
                task.status = VideoStatus.FAILED.value
                task.error_code = "poll_permanent_error"
                task.error_message = error_msg
                task.completed_at = datetime.now(timezone.utc)
            else:
                # 临时性错误：指数退避重试
                backoff = min(
                    task.poll_interval_seconds * (2 ** min(task.retry_count, 5)),
                    self.MAX_BACKOFF_SECONDS,
                )
                task.retry_count += 1
                task.next_poll_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)

        # 检查是否超过最大轮询次数（超时）
        task.updated_at = datetime.now(timezone.utc)
        if task.poll_count >= task.max_poll_count and task.status not in [
            VideoStatus.COMPLETED.value,
            VideoStatus.FAILED.value,
            VideoStatus.CANCELLED.value,
        ]:
            task.status = VideoStatus.FAILED.value
            task.error_code = "poll_timeout"
            task.error_message = f"Task timed out after {task.poll_count} polls"
            task.completed_at = datetime.now(timezone.utc)

        # 终态写入 Usage（复用外层 per-task session）
        if task.status in (VideoStatus.COMPLETED.value, VideoStatus.FAILED.value):
            try:
                await self._record_terminal_usage(db, task)
            except Exception as exc:
                logger.exception(
                    "Failed to record video usage for task=%s: %s",
                    task.id,
                    sanitize_error_message(str(exc)),
                )

    def _attach_poll_raw_response(self, task: VideoTask, result: InternalVideoPollResult) -> None:
        if not result.raw_response:
            return
        if task.request_metadata is None:
            task.request_metadata = {}
        # 仅在终态写一次，避免污染 request_metadata
        task.request_metadata["poll_raw_response"] = result.raw_response

    async def _record_terminal_usage(self, db: Session, task: VideoTask) -> None:
        """
        为视频任务终态写入 Usage：
        - COMPLETED: 使用 FormulaEngine 计算 cost（或 no_rule / incomplete -> cost=0）
        - FAILED: cost=0
        """
        request_id = None
        if isinstance(task.request_metadata, dict):
            request_id = task.request_metadata.get("request_id")
        request_id = request_id or task.id

        # 计算异步任务总耗时（ms）
        response_time_ms = None
        if task.submitted_at and task.completed_at:
            delta = task.completed_at - task.submitted_at
            response_time_ms = int(delta.total_seconds() * 1000)

        # 基础维度（无需 collectors 也可计费）
        base_dimensions: dict[str, Any] = {
            "duration_seconds": task.duration_seconds,
            "resolution": task.resolution,
            "aspect_ratio": task.aspect_ratio,
            "size": task.size or "",
            "retry_count": task.retry_count,
        }

        # collectors 可用的 metadata（结构稳定，便于配置 path）
        collector_metadata: dict[str, Any] = {
            "task": {
                "id": task.id,
                "external_task_id": task.external_task_id,
                "model": task.model,
                "duration_seconds": task.duration_seconds,
                "resolution": task.resolution,
                "aspect_ratio": task.aspect_ratio,
                "size": task.size,
                "retry_count": task.retry_count,
                "video_size_bytes": task.video_size_bytes,
            },
            "result": {
                "video_url": task.video_url,
                "video_urls": task.video_urls or [],
            },
        }

        # 维度采集：base + collectors 覆盖/补全
        dims = DimensionCollectorService(db).collect_dimensions(
            api_format=task.provider_api_format,
            task_type="video",
            request=task.original_request_body or {},
            response=(
                (task.request_metadata or {}).get("poll_raw_response")
                if isinstance(task.request_metadata, dict)
                else None
            ),
            metadata=collector_metadata,
            base_dimensions=base_dimensions,
        )

        # 取冻结的 rule_snapshot；若缺失则回退 DB 查找（兼容旧任务）
        rule_snapshot = None
        if isinstance(task.request_metadata, dict):
            rule_snapshot = task.request_metadata.get("billing_rule_snapshot")

        # 构建 billing_snapshot（写入 Usage.request_metadata）
        billing_snapshot: dict[str, Any] = {
            "status": "complete",
            "missing_required": [],
            "strict_mode": config.billing_strict_mode,
        }
        cost = 0.0

        if task.status == VideoStatus.FAILED.value:
            billing_snapshot["billed_reason"] = "task_failed"
        else:
            # COMPLETED：计算成本
            expression = None
            variables = None
            dimension_mappings = None
            rule_id = None
            rule_name = None
            rule_scope = None

            if isinstance(rule_snapshot, dict) and rule_snapshot.get("status") == "ok":
                rule_id = rule_snapshot.get("rule_id")
                rule_name = rule_snapshot.get("rule_name")
                rule_scope = rule_snapshot.get("scope")
                expression = rule_snapshot.get("expression")
                variables = rule_snapshot.get("variables")
                dimension_mappings = rule_snapshot.get("dimension_mappings")
            else:
                lookup = BillingRuleService.find_rule(
                    db,
                    provider_id=task.provider_id,
                    model_name=task.model,
                    task_type="video",
                )
                if lookup:
                    rule = lookup.rule
                    rule_id = rule.id
                    rule_name = rule.name
                    rule_scope = lookup.scope
                    expression = rule.expression
                    variables = rule.variables
                    dimension_mappings = rule.dimension_mappings

            if not expression:
                billing_snapshot["status"] = "no_rule"
                billing_snapshot["cost_breakdown"] = {"total": 0.0}
                logger.warning(
                    "No billing rule for video task (request_id=%s, model=%s, provider_id=%s)",
                    request_id,
                    task.model,
                    task.provider_id,
                )
            else:
                billing_snapshot.update(
                    {
                        "rule_id": rule_id,
                        "rule_name": rule_name,
                        "rule_scope": rule_scope,
                        "expression": expression,
                        "variables": variables or {},
                    }
                )
                try:
                    result = self._formula_engine.evaluate(
                        expression=expression,
                        variables=variables or {},
                        dimensions=dims,
                        dimension_mappings=dimension_mappings or {},
                        strict_mode=config.billing_strict_mode,
                    )
                    billing_snapshot["status"] = result.status
                    billing_snapshot["missing_required"] = result.missing_required
                    billing_snapshot["resolved_values"] = result.resolved_values
                    if result.status == "complete":
                        cost = result.cost
                    else:
                        logger.error(
                            "Billing incomplete due to missing required dimensions "
                            "(request_id=%s, model=%s, missing=%s)",
                            request_id,
                            task.model,
                            result.missing_required,
                        )
                        cost = 0.0
                        await self._maybe_alert_missing_required(
                            model=task.model,
                            missing_required=result.missing_required,
                        )
                    if result.error:
                        billing_snapshot["error"] = result.error
                except BillingIncompleteError as exc:
                    logger.error(
                        "Billing strict mode triggered (request_id=%s, model=%s, missing=%s)",
                        request_id,
                        task.model,
                        exc.missing_required,
                    )
                    billing_snapshot["status"] = "incomplete"
                    billing_snapshot["missing_required"] = exc.missing_required
                    billing_snapshot["resolved_values"] = {}
                    billing_snapshot["error"] = "strict_mode_missing_required"
                    cost = 0.0

                    # strict_mode=true：标记任务失败并隐藏产物，避免"免费放行"
                    task.status = VideoStatus.FAILED.value
                    task.error_code = "billing_incomplete"
                    task.error_message = f"Missing required dimensions: {exc.missing_required}"
                    task.video_url = None
                    task.video_urls = None

                    await self._maybe_alert_missing_required(
                        model=task.model,
                        missing_required=exc.missing_required,
                    )

                billing_snapshot["cost_breakdown"] = {"total": cost}

        # Usage 元数据（包含 snapshot + dimensions + raw_response_ref）
        usage_metadata: dict[str, Any] = {
            "billing_snapshot": billing_snapshot,
            "dimensions": dims,
            "raw_response_ref": {
                "video_task_id": task.id,
                "field": "video_tasks.request_metadata.poll_raw_response",
            },
        }

        # 查询关联对象（用于写入 usage.user_id/api_key_id 等）
        user_obj = db.query(User).filter(User.id == task.user_id).first()
        api_key_obj = (
            db.query(ApiKey).filter(ApiKey.id == task.api_key_id).first()
            if task.api_key_id
            else None
        )
        provider_obj = (
            db.query(Provider).filter(Provider.id == task.provider_id).first()
            if task.provider_id
            else None
        )
        provider_name = provider_obj.name if provider_obj else "unknown"

        await UsageService.record_usage_with_custom_cost(
            db=db,
            user=user_obj,
            api_key=api_key_obj,
            provider=provider_name,
            model=task.model,
            request_type="video",
            total_cost_usd=cost,
            request_cost_usd=cost,
            input_tokens=0,
            output_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            api_format=task.client_api_format,
            endpoint_api_format=task.provider_api_format,
            has_format_conversion=bool(task.format_converted),
            is_stream=False,
            response_time_ms=response_time_ms,
            first_byte_time_ms=None,
            status_code=200 if task.status == VideoStatus.COMPLETED.value else 500,
            error_message=(
                None
                if task.status == VideoStatus.COMPLETED.value
                else (task.error_message or task.error_code or "video_task_failed")
            ),
            metadata=usage_metadata,
            request_headers=(
                (task.request_metadata or {}).get("request_headers")
                if isinstance(task.request_metadata, dict)
                else None
            ),
            request_body=task.original_request_body,
            provider_request_headers=None,
            response_headers=None,
            client_response_headers=None,
            response_body=None,
            request_id=request_id,
            provider_id=task.provider_id,
            provider_endpoint_id=task.endpoint_id,
            provider_api_key_id=task.key_id,
            status="completed" if task.status == VideoStatus.COMPLETED.value else "failed",
            target_model=None,
        )

    async def _maybe_alert_missing_required(
        self, *, model: str, missing_required: list[str]
    ) -> None:
        """required 维度缺失告警：同一 (model, dimension) 1 小时内 >= 10 次触发升级告警。"""
        if not missing_required:
            return
        if not self.redis:
            # Redis 不可用：降级为日志
            logger.error(
                "Missing required billing dimensions (model=%s): %s", model, missing_required
            )
            return

        # 按小时 bucket 聚合
        now = datetime.now(timezone.utc)
        hour_bucket = now.strftime("%Y%m%d%H")
        for dim in missing_required:
            key = f"billing:missing_required:{model}:{dim}:{hour_bucket}"
            try:
                count = await self.redis.incr(key)
                # TTL 略大于 1h，避免边界抖动
                if count == 1:
                    await self.redis.expire(key, 3700)
                if count >= 10:
                    logger.warning(
                        "Billing required dimension missing frequently (model=%s, dim=%s, count=%s/hour)",
                        model,
                        dim,
                        count,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to record billing alert counter: %s", sanitize_error_message(str(exc))
                )

    def _is_permanent_error(self, exc: Exception, status_code: int | None = None) -> bool:
        """判断是否为永久性错误（不应重试）"""
        # 优先使用 HTTP 状态码判断
        if status_code is not None:
            # 4xx 客户端错误（除 429 限流）通常是永久性错误
            return 400 <= status_code < 500 and status_code != 429

        # 降级到字符串匹配
        error_msg = str(exc).lower()
        return any(indicator in error_msg for indicator in _PERMANENT_ERROR_INDICATORS)

    async def _poll_task_status(self, db: Session, task: VideoTask) -> InternalVideoPollResult:
        if not task.endpoint_id or not task.key_id:
            return InternalVideoPollResult(
                status=VideoStatus.FAILED,
                error_code="missing_provider_info",
                error_message="Task missing endpoint_id or key_id",
            )
        endpoint = self._get_endpoint(db, task.endpoint_id)
        key = self._get_key(db, task.key_id)
        if not key.api_key:
            return InternalVideoPollResult(
                status=VideoStatus.FAILED,
                error_code="provider_config_error",
                error_message="Provider key not properly configured",
            )
        try:
            upstream_key = crypto_service.decrypt(key.api_key)
        except Exception:
            logger.warning("Failed to decrypt provider key for task %s", task.id)
            return InternalVideoPollResult(
                status=VideoStatus.FAILED,
                error_code="decryption_error",
                error_message="Failed to decrypt provider key",
            )

        if (task.provider_api_format or "").upper() == "GEMINI":
            auth_info = await get_provider_auth(endpoint, key)
            return await self._poll_gemini(task, endpoint, upstream_key, auth_info)
        return await self._poll_openai(task, endpoint, upstream_key)

    async def _poll_openai(
        self,
        task: VideoTask,
        endpoint: ProviderEndpoint,
        upstream_key: str,
    ) -> InternalVideoPollResult:
        if not task.external_task_id:
            return InternalVideoPollResult(
                status=VideoStatus.FAILED,
                error_code="missing_external_task_id",
                error_message="Task missing external_task_id",
            )
        url = self._build_openai_url(endpoint.base_url, task.external_task_id)
        headers = self._build_headers(APIFormat.OPENAI, upstream_key, endpoint)

        client = await HTTPClientPool.get_default_client_async()
        response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            raise PollHTTPError(
                response.status_code,
                sanitize_error_message(response.text or "Poll error"),
            )

        payload = response.json()
        return self._openai_normalizer.video_poll_to_internal(payload)

    async def _poll_gemini(
        self,
        task: VideoTask,
        endpoint: ProviderEndpoint,
        upstream_key: str,
        auth_info: ProviderAuthInfo | None,
    ) -> InternalVideoPollResult:
        if not task.external_task_id:
            return InternalVideoPollResult(
                status=VideoStatus.FAILED,
                error_code="missing_external_task_id",
                error_message="Task missing external_task_id",
            )
        operation_name = normalize_gemini_operation_id(task.external_task_id)
        url = self._build_gemini_url(endpoint.base_url, operation_name)
        headers = self._build_headers(APIFormat.GEMINI, upstream_key, endpoint, auth_info)

        client = await HTTPClientPool.get_default_client_async()
        response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            raise PollHTTPError(
                response.status_code,
                sanitize_error_message(response.text or "Poll error"),
            )

        payload = response.json()
        return self._gemini_normalizer.video_poll_to_internal(payload)

    def _build_openai_url(self, base_url: str | None, task_id: str) -> str:
        base = (base_url or "https://api.openai.com").rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/videos/{task_id}"
        return f"{base}/v1/videos/{task_id}"

    def _build_gemini_url(self, base_url: str | None, operation_name: str) -> str:
        base = (base_url or "https://generativelanguage.googleapis.com").rstrip("/")
        if base.endswith("/v1beta"):
            base = base[: -len("/v1beta")]
        return f"{base}/v1beta/{operation_name}"

    def _build_headers(
        self,
        api_format: APIFormat,
        upstream_key: str,
        endpoint: ProviderEndpoint,
        auth_info: ProviderAuthInfo | None = None,
    ) -> dict[str, str]:
        extra_headers = get_extra_headers_from_endpoint(endpoint)
        headers = build_upstream_headers(
            {},
            api_format,
            upstream_key,
            endpoint_headers=extra_headers,
        )
        if auth_info:
            headers.pop("x-goog-api-key", None)
            headers[auth_info.auth_header] = auth_info.auth_value
        return headers

    def _get_endpoint(self, db: Session, endpoint_id: str) -> ProviderEndpoint:
        endpoint = db.query(ProviderEndpoint).filter(ProviderEndpoint.id == endpoint_id).first()
        if not endpoint:
            raise RuntimeError("Provider endpoint not found")
        return endpoint

    def _get_key(self, db: Session, key_id: str) -> ProviderAPIKey:
        key = db.query(ProviderAPIKey).filter(ProviderAPIKey.id == key_id).first()
        if not key:
            raise RuntimeError("Provider key not found")
        return key

    async def _acquire_redis_lock(self) -> str | None:
        if not self.redis:
            return "no_redis"
        token = str(uuid4())
        acquired = await self.redis.set(self.LOCK_KEY, token, nx=True, ex=self.LOCK_TTL)
        return token if acquired else None

    async def _release_redis_lock(self, token: str) -> None:
        if not self.redis or token == "no_redis":
            return
        script = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('DEL', KEYS[1])
        end
        return 0
        """
        await self.redis.eval(script, 1, self.LOCK_KEY, token)


_video_task_poller: VideoTaskPollerService | None = None


def get_video_task_poller() -> VideoTaskPollerService:
    global _video_task_poller
    if _video_task_poller is None:
        _video_task_poller = VideoTaskPollerService()
    return _video_task_poller
