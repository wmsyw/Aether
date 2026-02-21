from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.core.logger import logger
from src.models.database import ApiKey, Usage, User
from src.services.system.config import SystemConfigService


class UsageLifecycleMixin:
    """使用记录生命周期管理方法"""

    @classmethod
    def begin_pending_usage(
        cls,
        db: Session,
        request_id: str,
        user: User | None,
        api_key: ApiKey | None,
        model: str,
        *,
        is_stream: bool = False,
        request_type: str = "chat",
        api_format: str | None = None,
        request_headers: dict[str, Any] | None = None,
        request_body: Any | None = None,
    ) -> Usage:
        """
        创建（或返回已有）pending Usage 记录，但**不提交事务**。

        适用场景：
        - ApplicationService 在同一事务内创建 pending usage + task + candidates
        - submit 幂等：重复调用同一 request_id 时返回已有记录
        """
        existing = db.query(Usage).filter(Usage.request_id == request_id).first()
        if existing:
            return existing

        # 根据配置决定是否记录请求详情
        should_log_headers = SystemConfigService.should_log_headers(db)
        should_log_body = SystemConfigService.should_log_body(db)

        # 处理请求头
        processed_request_headers = None
        if should_log_headers and request_headers is not None:
            processed_request_headers = SystemConfigService.mask_sensitive_headers(
                db, request_headers
            )

        # 处理请求体
        processed_request_body = None
        if should_log_body and request_body is not None:
            processed_request_body = SystemConfigService.truncate_body(
                db, request_body, is_request=True
            )

        usage = Usage(
            user_id=user.id if user else None,
            api_key_id=api_key.id if api_key else None,
            request_id=request_id,
            provider_name="pending",  # 尚未确定 provider
            model=model,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            total_cost_usd=0.0,
            request_type=request_type,
            api_format=api_format,
            is_stream=is_stream,
            status="pending",
            billing_status="pending",
            request_headers=processed_request_headers,
            request_body=processed_request_body,
        )

        db.add(usage)
        db.flush()
        return usage

    @classmethod
    def create_pending_usage(
        cls,
        db: Session,
        request_id: str,
        user: User | None,
        api_key: ApiKey | None,
        model: str,
        is_stream: bool = False,
        request_type: str = "chat",
        api_format: str | None = None,
        request_headers: dict[str, Any] | None = None,
        request_body: Any | None = None,
    ) -> Usage:
        """
        创建 pending 状态的使用记录（在请求开始时调用）

        Args:
            db: 数据库会话
            request_id: 请求ID
            user: 用户对象
            api_key: API Key 对象
            model: 模型名称
            is_stream: 是否流式请求
            api_format: API 格式
            request_headers: 请求头
            request_body: 请求体

        Returns:
            创建的 Usage 记录
        """
        usage = cls.begin_pending_usage(
            db,
            request_id=request_id,
            user=user,
            api_key=api_key,
            model=model,
            is_stream=is_stream,
            request_type=request_type,
            api_format=api_format,
            request_headers=request_headers,
            request_body=request_body,
        )
        db.commit()

        logger.debug("创建 pending 使用记录: request_id={}, model={}", request_id, model)

        return usage

    # ========== billing_status 并发幂等 finalize ==========

    @classmethod
    def finalize_settled(
        cls,
        db: Session,
        request_id: str,
        *,
        total_cost_usd: float,
        request_cost_usd: float | None = None,
        status: str = "completed",
        status_code: int = 200,
        error_message: str | None = None,
        response_time_ms: int | None = None,
        billing_snapshot: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        并发安全的幂等 finalize（settled）。

        约定：
        - 仅当 billing_status='pending' 时才会生效（rowcount==1）
        - 不在本方法内 commit，由调用方决定事务提交时机
        """
        from sqlalchemy import update

        now = datetime.now(timezone.utc)
        cost = float(total_cost_usd)
        request_cost = float(request_cost_usd) if request_cost_usd is not None else cost

        result = db.execute(
            update(Usage)
            .where(
                Usage.request_id == request_id,
                Usage.billing_status == "pending",
            )
            .values(
                billing_status="settled",
                finalized_at=now,
                total_cost_usd=cost,
                request_cost_usd=request_cost,
                status=status,
                status_code=status_code,
                error_message=error_message,
                response_time_ms=response_time_ms,
            )
        )
        if result.rowcount != 1:
            return False

        # 写入审计快照（只在本次 finalize 生效时执行）
        usage = db.query(Usage).filter(Usage.request_id == request_id).first()
        if usage:
            metadata = usage.request_metadata or {}
            if billing_snapshot is not None:
                metadata["billing_snapshot"] = billing_snapshot
            if extra_metadata:
                metadata.update(extra_metadata)
            usage.request_metadata = cls._sanitize_request_metadata(metadata)

        return True

    @classmethod
    def finalize_void(
        cls,
        db: Session,
        request_id: str,
        *,
        reason: str | None = None,
        status_code: int = 499,
    ) -> bool:
        """
        并发安全的幂等 finalize（void，不收费）。

        约定：
        - 仅当 billing_status='pending' 时才会生效（rowcount==1）
        - 不在本方法内 commit，由调用方决定事务提交时机
        """
        from sqlalchemy import update

        now = datetime.now(timezone.utc)
        result = db.execute(
            update(Usage)
            .where(
                Usage.request_id == request_id,
                Usage.billing_status == "pending",
            )
            .values(
                billing_status="void",
                finalized_at=now,
                total_cost_usd=0.0,
                request_cost_usd=0.0,
                status="cancelled",
                status_code=status_code,
                error_message=reason,
                response_time_ms=None,
            )
        )
        return result.rowcount == 1

    @classmethod
    def finalize_submitted(
        cls,
        db: Session,
        request_id: str,
        *,
        provider_name: str,
        provider_id: str | None = None,
        provider_endpoint_id: str | None = None,
        provider_api_key_id: str | None = None,
        response_time_ms: int | None = None,
        status_code: int = 200,
        endpoint_api_format: str | None = None,
        provider_request_headers: dict[str, Any] | None = None,
        response_headers: dict[str, Any] | None = None,
        response_body: Any | None = None,
    ) -> bool:
        """
        异步任务提交成功时的幂等结算。

        将 pending 使用记录标记为 settled，费用暂时为 0。
        后续轮询完成后通过 update_settled_billing 更新实际费用。

        约定：
        - 仅当 billing_status='pending' 时才会生效（rowcount==1）
        - 不在本方法内 commit，由调用方决定事务提交时机
        """
        from sqlalchemy import update

        now = datetime.now(timezone.utc)

        # 处理响应头和响应体
        should_log_headers = SystemConfigService.should_log_headers(db)
        should_log_body = SystemConfigService.should_log_body(db)

        processed_provider_headers = None
        if should_log_headers and provider_request_headers is not None:
            processed_provider_headers = SystemConfigService.mask_sensitive_headers(
                db, provider_request_headers
            )

        processed_response_headers = None
        if should_log_headers and response_headers is not None:
            processed_response_headers = dict(response_headers)

        processed_response_body = None
        if should_log_body and response_body is not None:
            processed_response_body = SystemConfigService.truncate_body(
                db, response_body, is_request=False
            )

        values: dict[str, Any] = {
            "billing_status": "settled",
            "finalized_at": now,
            "total_cost_usd": 0.0,
            "request_cost_usd": 0.0,
            "status": "completed",
            "status_code": status_code,
            "response_time_ms": response_time_ms,
            "provider_name": provider_name,
            "provider_id": provider_id,
            "provider_endpoint_id": provider_endpoint_id,
            "provider_api_key_id": provider_api_key_id,
            "endpoint_api_format": endpoint_api_format,
        }

        if processed_provider_headers is not None:
            values["provider_request_headers"] = processed_provider_headers
        if processed_response_headers is not None:
            values["response_headers"] = processed_response_headers
        if processed_response_body is not None:
            values["response_body"] = processed_response_body

        result = db.execute(
            update(Usage)
            .where(
                Usage.request_id == request_id,
                Usage.billing_status == "pending",
            )
            .values(**values)
        )
        return result.rowcount == 1

    @classmethod
    def update_settled_billing(
        cls,
        db: Session,
        request_id: str,
        *,
        total_cost_usd: float,
        request_cost_usd: float | None = None,
        status: str = "completed",
        status_code: int = 200,
        error_message: str | None = None,
        response_time_ms: int | None = None,
        billing_snapshot: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        更新已结算记录的计费信息（用于异步任务轮询完成后）。

        与 finalize_settled 不同：
        - finalize_settled: pending -> settled（首次结算）
        - update_settled_billing: settled -> settled（更新费用）

        约定：
        - 仅当 billing_status='settled' 时才会生效
        - 不在本方法内 commit，由调用方决定事务提交时机
        """
        from sqlalchemy import update

        now = datetime.now(timezone.utc)
        cost = float(total_cost_usd)
        request_cost = float(request_cost_usd) if request_cost_usd is not None else cost

        values: dict[str, Any] = {
            "total_cost_usd": cost,
            "request_cost_usd": request_cost,
            "status": status,
            "status_code": status_code,
        }
        if error_message is not None:
            values["error_message"] = error_message
        if response_time_ms is not None:
            values["response_time_ms"] = response_time_ms

        result = db.execute(
            update(Usage)
            .where(
                Usage.request_id == request_id,
                Usage.billing_status == "settled",
            )
            .values(**values)
        )
        if result.rowcount != 1:
            return False

        # 写入审计快照
        usage = db.query(Usage).filter(Usage.request_id == request_id).first()
        if usage:
            metadata = usage.request_metadata or {}
            if billing_snapshot is not None:
                metadata["billing_snapshot"] = billing_snapshot
            if extra_metadata:
                metadata.update(extra_metadata)
            metadata["billing_updated_at"] = now.isoformat()
            usage.request_metadata = cls._sanitize_request_metadata(metadata)

        return True

    @classmethod
    def void_settled(
        cls,
        db: Session,
        request_id: str,
        *,
        reason: str | None = None,
        status_code: int = 499,
    ) -> bool:
        """
        将已结算的记录作废（用于异步任务取消）。

        与 finalize_void 不同：
        - finalize_void: pending -> void（未结算时作废）
        - void_settled: settled -> void（已结算后取消，费用归零）

        约定：
        - 仅当 billing_status='settled' 时才会生效
        - 不在本方法内 commit，由调用方决定事务提交时机
        """
        from sqlalchemy import update

        now = datetime.now(timezone.utc)
        result = db.execute(
            update(Usage)
            .where(
                Usage.request_id == request_id,
                Usage.billing_status == "settled",
            )
            .values(
                billing_status="void",
                finalized_at=now,
                total_cost_usd=0.0,
                request_cost_usd=0.0,
                status="cancelled",
                status_code=status_code,
                error_message=reason,
            )
        )
        return result.rowcount == 1

    @classmethod
    def update_usage_status(
        cls,
        db: Session,
        request_id: str,
        status: str,
        error_message: str | None = None,
        provider: str | None = None,
        target_model: str | None = None,
        first_byte_time_ms: int | None = None,
        provider_id: str | None = None,
        provider_endpoint_id: str | None = None,
        provider_api_key_id: str | None = None,
        api_format: str | None = None,
        endpoint_api_format: str | None = None,
        has_format_conversion: bool | None = None,
        status_code: int | None = None,
    ) -> Usage | None:
        """
        快速更新使用记录状态

        Args:
            db: 数据库会话
            request_id: 请求ID
            status: 新状态 (pending, streaming, completed, failed)
            error_message: 错误消息（仅在 failed 状态时使用）
            provider: 提供商名称（可选，streaming 状态时更新）
            target_model: 映射后的目标模型名（可选）
            first_byte_time_ms: 首字时间/TTFB（可选，streaming 状态时更新）
            provider_id: Provider ID（可选，streaming 状态时更新）
            provider_endpoint_id: Endpoint ID（可选，streaming 状态时更新）
            provider_api_key_id: Provider API Key ID（可选，streaming 状态时更新）
            api_format: API 格式（可选，用于获取按格式配置的倍率）
            endpoint_api_format: 端点原生 API 格式（可选）
            has_format_conversion: 是否发生了格式转换（可选）
            status_code: HTTP 状态码（可选）

        Returns:
            更新后的 Usage 记录，如果未找到则返回 None
        """
        usage = db.query(Usage).filter(Usage.request_id == request_id).first()
        if not usage:
            logger.warning("未找到 request_id={} 的使用记录，无法更新状态", request_id)
            return None

        # 避免状态回退：streaming 只能从 pending/streaming 进入
        if status == "streaming" and usage.status not in ("pending", "streaming"):
            logger.debug(
                f"跳过 streaming 状态更新（避免回退）: request_id={request_id}, "
                f"{usage.status} -> {status}"
            )
            return usage

        old_status = usage.status
        usage.status = status
        if error_message:
            usage.error_message = error_message
        if provider:
            usage.provider_name = provider
        elif status == "streaming" and usage.provider_name == "pending":
            # 状态变为 streaming 但 provider_name 仍为 pending，记录警告
            logger.warning(
                f"状态更新为 streaming 但 provider_name 为空: request_id={request_id}, "
                f"当前 provider_name={usage.provider_name}"
            )
        if target_model:
            usage.target_model = target_model
        if first_byte_time_ms is not None:
            usage.first_byte_time_ms = first_byte_time_ms
        if provider_id is not None:
            usage.provider_id = provider_id
        if provider_endpoint_id is not None:
            usage.provider_endpoint_id = provider_endpoint_id
        if provider_api_key_id is not None:
            usage.provider_api_key_id = provider_api_key_id
            # 当设置 provider_api_key_id 时，同步获取并更新 rate_multiplier
            # 这样前端在 streaming 状态就能显示倍率
            rate_multiplier = cls._get_rate_multiplier_sync(
                db, provider_api_key_id, api_format or usage.api_format
            )
            if rate_multiplier is not None:
                usage.rate_multiplier = rate_multiplier
        if endpoint_api_format is not None:
            usage.endpoint_api_format = endpoint_api_format
        if has_format_conversion is not None:
            usage.has_format_conversion = has_format_conversion
        if status_code is not None:
            usage.status_code = status_code

        # 结算状态：当请求进入终态时，将 billing_status 标记为 settled
        # 注意：取消是否应 VOID/部分结算由更高层策略决定；这里默认终态均视为已结算。
        if status in ("completed", "failed", "cancelled"):
            if getattr(usage, "billing_status", None) == "pending":
                usage.billing_status = "settled"
            if getattr(usage, "finalized_at", None) is None:
                usage.finalized_at = datetime.now(timezone.utc)

        db.commit()

        logger.debug("更新使用记录状态: request_id={}, {} -> {}", request_id, old_status, status)

        return usage
