"""
使用记录相关数据库模型

包含: Usage, RequestCandidate
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ._base import Base


class Usage(Base):
    """使用记录模型"""

    __tablename__ = "usage"
    __table_args__ = (
        # Composite indexes for common query patterns (analytics / list pages)
        Index("idx_usage_user_created", "user_id", "created_at"),
        Index("idx_usage_apikey_created", "api_key_id", "created_at"),
        Index("idx_usage_provider_model_created", "provider_name", "model", "created_at"),
        Index("idx_usage_provider_created", "provider_name", "created_at"),
        Index("idx_usage_model_created", "model", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    api_key_id = Column(String(36), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True)

    # 请求信息
    request_id = Column(String(100), unique=True, index=True, nullable=False)
    provider_name = Column(String(100), nullable=False)  # Provider 名称（非外键）
    model = Column(String(100), nullable=False)
    target_model = Column(
        String(100), nullable=True, comment="映射后的目标模型名（若无映射则为空）"
    )

    # Provider 侧追踪信息（记录最终成功的 Provider/Endpoint/Key）
    provider_id = Column(String(36), ForeignKey("providers.id", ondelete="SET NULL"), nullable=True)
    provider_endpoint_id = Column(
        String(36), ForeignKey("provider_endpoints.id", ondelete="SET NULL"), nullable=True
    )
    provider_api_key_id = Column(
        String(36), ForeignKey("provider_api_keys.id", ondelete="SET NULL"), nullable=True
    )

    # Token统计
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)

    # 缓存相关 tokens (for Claude models)
    cache_creation_input_tokens = Column(Integer, default=0)
    cache_read_input_tokens = Column(Integer, default=0)
    cache_creation_input_tokens_5m = Column(Integer, default=0)  # 5min TTL 缓存创建
    cache_creation_input_tokens_1h = Column(Integer, default=0)  # 1h TTL 缓存创建

    # 成本计算
    input_cost_usd = Column(Float, default=0.0)
    output_cost_usd = Column(Float, default=0.0)
    cache_cost_usd = Column(Float, default=0.0)  # 总缓存成本（兼容旧数据）
    cache_creation_cost_usd = Column(Float, default=0.0)  # 缓存创建成本
    cache_read_cost_usd = Column(Float, default=0.0)  # 缓存读取成本
    request_cost_usd = Column(Float, default=0.0)  # 按次计费成本
    total_cost_usd = Column(Float, default=0.0)

    # 真实成本计算（表面成本 x 倍率）
    actual_input_cost_usd = Column(Float, default=0.0)  # 真实输入成本
    actual_output_cost_usd = Column(Float, default=0.0)  # 真实输出成本
    actual_cache_creation_cost_usd = Column(Float, default=0.0)  # 真实缓存创建成本
    actual_cache_read_cost_usd = Column(Float, default=0.0)  # 真实缓存读取成本
    actual_request_cost_usd = Column(Float, default=0.0)  # 真实按次计费成本
    actual_total_cost_usd = Column(Float, default=0.0)  # 真实总成本
    rate_multiplier = Column(Float, default=1.0)  # 使用的倍率（来自 ProviderAPIKey）

    # 历史价格记录（每1M tokens的美元价格，记录请求时的实际价格）
    input_price_per_1m = Column(Float, nullable=True)  # 输入单价
    output_price_per_1m = Column(Float, nullable=True)  # 输出单价
    cache_creation_price_per_1m = Column(Float, nullable=True)  # 缓存创建单价
    cache_read_price_per_1m = Column(Float, nullable=True)  # 缓存读取单价
    price_per_request = Column(Float, nullable=True)  # 按次计费单价（历史记录）

    # 请求详情
    request_type = Column(String(50))  # chat, completion, embedding等
    api_format = Column(String(50), nullable=True)  # API 格式: CLAUDE, OPENAI 等（用户请求格式）
    api_family = Column(String(50), nullable=True)  # 协议族: claude, openai, gemini
    endpoint_kind = Column(String(50), nullable=True)  # 端点类型: chat, cli, video
    endpoint_api_format = Column(String(50), nullable=True)  # 端点原生 API 格式
    provider_api_family = Column(String(50), nullable=True)  # 提供商协议族
    provider_endpoint_kind = Column(String(50), nullable=True)  # 提供商端点类型
    has_format_conversion = Column(Boolean, nullable=True, default=False)  # 是否发生了格式转换
    is_stream = Column(Boolean, default=False)  # 是否为流式请求
    status_code = Column(Integer)
    error_message = Column(Text, nullable=True)
    error_category = Column(String(50), nullable=True, index=True)
    response_time_ms = Column(Integer)  # 总响应时间（毫秒）
    first_byte_time_ms = Column(Integer, nullable=True)  # 首字时间/TTFB（毫秒）

    # 请求状态追踪
    # pending: 请求开始处理中
    # streaming: 流式响应进行中
    # completed: 请求成功完成
    # failed: 请求失败
    # cancelled: 客户端主动断开连接
    status = Column(String(20), default="completed", nullable=False, index=True)

    # 结算状态（与 status 解耦）
    # - pending: 等待结算（任务未完成 / 流式未结束）
    # - settled: 已结算（cost 已写入，可能 > 0 或 = 0）
    # - void: 作废（不收费，如任务未开始就取消）
    billing_status = Column(String(20), default="settled", nullable=False, index=True)
    finalized_at = Column(DateTime(timezone=True), nullable=True)  # 结算完成时间（可选）

    # 完整请求和响应记录
    request_headers = Column(JSON, nullable=True)  # 客户端请求头
    request_body = Column(JSON, nullable=True)  # 客户端原始请求体（7天内未压缩）
    provider_request_headers = Column(JSON, nullable=True)  # 向提供商发送的请求头
    provider_request_body = Column(JSON, nullable=True)  # 发给提供商的请求体（格式转换后）
    response_headers = Column(JSON, nullable=True)  # 提供商响应头
    response_body = Column(JSON, nullable=True)  # 提供商原始响应体（7天内未压缩）
    client_response_headers = Column(JSON, nullable=True)  # 返回给客户端的响应头
    client_response_body = Column(JSON, nullable=True)  # 返回给客户端的响应体（格式转换后）

    # 压缩存储字段（7天后自动压缩到这里）
    request_body_compressed = Column(LargeBinary, nullable=True)  # gzip压缩的客户端请求体
    provider_request_body_compressed = Column(LargeBinary, nullable=True)  # gzip压缩的提供商请求体
    response_body_compressed = Column(LargeBinary, nullable=True)  # gzip压缩的提供商响应体
    client_response_body_compressed = Column(LargeBinary, nullable=True)  # gzip压缩的客户端响应体

    # 元数据
    request_metadata = Column(JSON, nullable=True)  # 存储额外信息

    # 时间戳
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # 关系
    user = relationship("User", back_populates="usage_records")
    api_key = relationship("ApiKey", back_populates="usage_records")
    provider_obj = relationship("Provider")  # 使用 provider_obj 避免与 provider 字段名冲突
    provider_endpoint = relationship("ProviderEndpoint")
    provider_api_key = relationship("ProviderAPIKey")

    def get_request_body(self) -> Any:
        """获取客户端原始请求体（自动解压）"""
        if self.request_body is not None:
            return self.request_body
        if self.request_body_compressed is not None:
            from src.utils.compression import decompress_json

            return decompress_json(self.request_body_compressed)
        return None

    def get_provider_request_body(self) -> Any:
        """获取发给提供商的请求体（自动解压）"""
        if self.provider_request_body is not None:
            return self.provider_request_body
        if self.provider_request_body_compressed is not None:
            from src.utils.compression import decompress_json

            return decompress_json(self.provider_request_body_compressed)
        return None

    def get_response_body(self) -> Any:
        """获取提供商原始响应体（自动解压）"""
        if self.response_body is not None:
            return self.response_body
        if self.response_body_compressed is not None:
            from src.utils.compression import decompress_json

            return decompress_json(self.response_body_compressed)
        return None

    def get_client_response_body(self) -> Any:
        """获取返回给客户端的响应体（自动解压）"""
        if self.client_response_body is not None:
            return self.client_response_body
        if self.client_response_body_compressed is not None:
            from src.utils.compression import decompress_json

            return decompress_json(self.client_response_body_compressed)
        return None


class RequestCandidate(Base):
    """请求候选记录 - 追踪所有候选（包括未使用的）"""

    __tablename__ = "request_candidates"

    # 主键
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 关联字段
    request_id = Column(String(100), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    api_key_id = Column(String(36), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=True)

    # 候选信息
    candidate_index = Column(Integer, nullable=False)  # 候选序号（从0开始）
    retry_index = Column(Integer, nullable=False, default=0)  # 重试序号（从0开始）
    provider_id = Column(String(36), ForeignKey("providers.id", ondelete="CASCADE"), nullable=True)
    endpoint_id = Column(
        String(36), ForeignKey("provider_endpoints.id", ondelete="CASCADE"), nullable=True
    )
    key_id = Column(
        String(36), ForeignKey("provider_api_keys.id", ondelete="CASCADE"), nullable=True
    )

    # 状态信息
    status = Column(
        String(20), nullable=False
    )  # 'pending', 'streaming', 'success', 'failed', 'cancelled', 'skipped'
    skip_reason = Column(Text, nullable=True)  # 跳过/失败原因
    is_cached = Column(Boolean, default=False)  # 是否为缓存亲和性候选

    # 执行结果信息（当 status = success/failed 时）
    status_code = Column(Integer, nullable=True)  # HTTP 状态码
    error_type = Column(String(50), nullable=True)  # 错误类型
    error_message = Column(Text, nullable=True)  # 错误消息
    latency_ms = Column(Integer, nullable=True)  # 延迟（毫秒）
    concurrent_requests = Column(Integer, nullable=True)  # 并发请求数

    # 元数据
    extra_data = Column(JSON, nullable=True)
    required_capabilities = Column(JSON, nullable=True)  # 请求实际需要的能力标签

    # 时间戳
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    started_at = Column(DateTime(timezone=True), nullable=True)  # 开始执行时间
    finished_at = Column(DateTime(timezone=True), nullable=True)  # 完成时间

    # 唯一约束和索引
    __table_args__ = (
        UniqueConstraint(
            "request_id", "candidate_index", "retry_index", name="uq_request_candidate_with_retry"
        ),
        Index("idx_request_candidates_request_id", "request_id"),
        Index("idx_request_candidates_status", "status"),
        Index("idx_request_candidates_provider_id", "provider_id"),
        Index("idx_request_candidates_created_at", "created_at"),
    )

    # 关系
    user = relationship("User")
    api_key = relationship("ApiKey")
    provider = relationship("Provider")
    endpoint = relationship("ProviderEndpoint")
    key = relationship("ProviderAPIKey")
