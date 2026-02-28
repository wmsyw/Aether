"""
模型相关数据库模型

包含: GlobalModel, Model, BillingRule, DimensionCollector
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from ._base import Base, ExportMixin


class GlobalModel(ExportMixin, Base):
    """全局统一模型定义 - 包含价格和能力配置

    设计原则:
    - 定义模型的基本信息和价格配置（价格为必填项）
    - Provider 级别的 Model 可以覆盖这些默认值
    - 如果 Model 的价格/能力字段为空，则使用 GlobalModel 的值
    """

    __tablename__ = "global_models"

    _export_exclude = frozenset(
        {
            "id",
            "usage_count",
            "created_at",
            "updated_at",
        }
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)  # 统一模型名（唯一）
    display_name = Column(String(100), nullable=False)

    # 按次计费配置（每次请求的固定费用，美元）- 可选，与按 token 计费叠加
    default_price_per_request = Column(Float, nullable=True, default=None)  # 每次请求固定费用

    # 统一阶梯计费配置（JSON格式）- 必填
    # 固定价格也用单阶梯表示: {"tiers": [{"up_to": null, "input_price_per_1m": X, ...}]}
    # 结构示例:
    # {
    #     "tiers": [
    #         {
    #             "up_to": 128000,  # 阶梯上限（tokens），null 表示无上限
    #             "input_price_per_1m": 2.50,
    #             "output_price_per_1m": 10.00,
    #             "cache_creation_price_per_1m": 3.75,  # 可选
    #             "cache_read_price_per_1m": 0.30,      # 可选
    #             "cache_ttl_pricing": [                 # 可选：按缓存时长分价格
    #                 {"ttl_minutes": 5, "cache_creation_price_per_1m": 3.75, "cache_read_price_per_1m": 0.30},
    #                 {"ttl_minutes": 60, "cache_creation_price_per_1m": 6.00, "cache_read_price_per_1m": 0.50}
    #             ]
    #         },
    #         {"up_to": null, "input_price_per_1m": 1.25, ...}
    #     ]
    # }
    default_tiered_pricing = Column(JSON, nullable=False)

    # Key 能力配置 - 模型支持的能力列表（如 ["cache_1h", "context_1m"]）
    # Key 只能启用模型支持的能力
    supported_capabilities = Column(JSON, nullable=True, default=list)

    # 模型配置（JSON格式）- 包含能力、规格、元信息等
    # 结构示例:
    # {
    #     # 能力配置
    #     "streaming": true,
    #     "vision": true,
    #     "function_calling": true,
    #     "extended_thinking": false,
    #     "image_generation": false,
    #     # 规格参数
    #     "context_limit": 200000,
    #     "output_limit": 8192,
    #     # 元信息
    #     "description": "...",
    #     "icon_url": "...",
    #     "official_url": "...",
    #     "knowledge_cutoff": "2024-04",
    #     "family": "claude-3.5",
    #     "release_date": "2024-10-22",
    #     "input_modalities": ["text", "image"],
    #     "output_modalities": ["text"],
    # }
    config = Column(JSONB, nullable=True, default=dict)

    # 状态
    is_active = Column(Boolean, default=True, nullable=False)

    # 统计计数器（优化性能，避免实时查询）
    usage_count = Column(Integer, default=0, nullable=False, index=True)

    # 时间戳
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # 关系
    models = relationship("Model", back_populates="global_model")


class Model(ExportMixin, Base):
    """Provider 模型配置表 - Provider 如何使用某个 GlobalModel

    设计原则:
    - Model 表示 Provider 对某个模型的具体实现
    - global_model_id 必填，必须关联到一个 GlobalModel
    - provider_model_name 是 Provider 侧的实际模型名称 (可能与 GlobalModel.name 不同)
    - 价格和能力配置可为空，为空时使用 GlobalModel 的默认值
    """

    __tablename__ = "models"

    _export_exclude = frozenset(
        {
            "id",
            "provider_id",
            "global_model_id",
            "is_available",
            "created_at",
            "updated_at",
        }
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    provider_id = Column(String(36), ForeignKey("providers.id"), nullable=False)
    # 必须关联一个 GlobalModel
    global_model_id = Column(String(36), ForeignKey("global_models.id"), nullable=False, index=True)

    # Provider 映射配置
    provider_model_name = Column(String(200), nullable=False)  # Provider 侧的主模型名称
    # 模型名称映射列表（带优先级），用于同一模型在 Provider 侧有多个名称变体的场景
    # 格式: [{"name": "Claude-Sonnet-4.5", "priority": 1}, {"name": "Claude-Sonnet-4-5", "priority": 2}]
    # 为空时只使用 provider_model_name
    provider_model_mappings = Column(JSON, nullable=True, default=None)

    # 按次计费配置（每次请求的固定费用，美元）- 可为空，为空时使用 GlobalModel 的默认值
    price_per_request = Column(Float, nullable=True)  # 每次请求固定费用

    # 阶梯计费配置（JSON格式）- 可为空，为空时使用 GlobalModel 的默认值
    tiered_pricing = Column(JSON, nullable=True, default=None)

    # Provider 能力配置 - 可为空，为空时使用 GlobalModel 的默认值
    supports_vision = Column(Boolean, nullable=True)
    supports_function_calling = Column(Boolean, nullable=True)
    supports_streaming = Column(Boolean, nullable=True)
    supports_extended_thinking = Column(Boolean, nullable=True)
    supports_image_generation = Column(Boolean, nullable=True)

    # 状态
    is_active = Column(Boolean, default=True, nullable=False)
    is_available = Column(Boolean, default=True)  # 是否当前可用

    # 扩展配置
    config = Column(JSON, nullable=True)

    # 时间戳
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # 关系
    provider = relationship("Provider", back_populates="models")
    global_model = relationship("GlobalModel", back_populates="models")

    # 唯一约束：同一个提供商下的 provider_model_name 不能重复
    __table_args__ = (
        UniqueConstraint("provider_id", "provider_model_name", name="uq_provider_model"),
    )

    # 辅助方法：获取有效的阶梯计费配置
    def get_effective_tiered_pricing(self) -> dict | None:
        """获取有效的阶梯计费配置"""
        if self.tiered_pricing is not None:
            return self.tiered_pricing
        if self.global_model:
            return self.global_model.default_tiered_pricing
        return None

    def _get_first_tier(self) -> dict | None:
        """获取第一个阶梯（用于获取默认价格）"""
        tiered = self.get_effective_tiered_pricing()
        if tiered and tiered.get("tiers"):
            return tiered["tiers"][0]
        return None

    def get_effective_input_price(self) -> float:
        """获取有效的输入价格（从第一个阶梯）"""
        tier = self._get_first_tier()
        if tier:
            return tier.get("input_price_per_1m", 0.0)
        return 0.0

    def get_effective_output_price(self) -> float:
        """获取有效的输出价格（从第一个阶梯）"""
        tier = self._get_first_tier()
        if tier:
            return tier.get("output_price_per_1m", 0.0)
        return 0.0

    def get_effective_cache_creation_price(self) -> float | None:
        """获取有效的缓存创建价格（从第一个阶梯）"""
        tier = self._get_first_tier()
        if tier:
            return tier.get("cache_creation_price_per_1m")
        return None

    def get_effective_cache_read_price(self) -> float | None:
        """获取有效的缓存读取价格（从第一个阶梯）"""
        tier = self._get_first_tier()
        if tier:
            return tier.get("cache_read_price_per_1m")
        return None

    def get_effective_1h_cache_creation_price(self) -> float | None:
        """获取有效的 1h 缓存创建价格（从第一个阶梯）"""
        tier = self._get_first_tier()
        if tier:
            cache_ttl_pricing = tier.get("cache_ttl_pricing") or []
            for ttl_entry in cache_ttl_pricing:
                if ttl_entry.get("ttl_minutes") == 60:
                    return ttl_entry.get("cache_creation_price_per_1m")
        return None

    def get_effective_price_per_request(self) -> float | None:
        """获取有效的按次计费价格"""
        if self.price_per_request is not None:
            return self.price_per_request
        if self.global_model:
            return self.global_model.default_price_per_request
        return None

    def _get_effective_capability(self, attr_name: str, default: bool = False) -> bool:
        """获取有效的能力配置（通用辅助方法）"""
        local_value = getattr(self, attr_name, None)
        if local_value is not None:
            return bool(local_value)
        if self.global_model:
            config_key_map = {
                "supports_vision": "vision",
                "supports_function_calling": "function_calling",
                "supports_streaming": "streaming",
                "supports_extended_thinking": "extended_thinking",
                "supports_image_generation": "image_generation",
            }
            config_key = config_key_map.get(attr_name)
            if config_key:
                global_config = getattr(self.global_model, "config", None)
                if isinstance(global_config, dict):
                    global_value = global_config.get(config_key)
                    if global_value is not None:
                        return bool(global_value)
        return default

    def get_effective_supports_vision(self) -> bool:
        return self._get_effective_capability("supports_vision", False)

    def get_effective_supports_function_calling(self) -> bool:
        return self._get_effective_capability("supports_function_calling", False)

    def get_effective_supports_streaming(self) -> bool:
        return self._get_effective_capability("supports_streaming", True)

    def get_effective_supports_extended_thinking(self) -> bool:
        return self._get_effective_capability("supports_extended_thinking", False)

    def get_effective_supports_image_generation(self) -> bool:
        return self._get_effective_capability("supports_image_generation", False)

    def get_effective_config(self) -> dict | None:
        """获取有效的 config（合并 Model 和 GlobalModel 的 config）

        合并策略：
        - GlobalModel.config 作为基础
        - Model.config 覆盖 GlobalModel.config
        - 深度合并 billing 子字段
        """
        global_config = {}
        if self.global_model and self.global_model.config:
            global_config = dict(self.global_model.config)

        if not self.config:
            return global_config if global_config else None

        # 深度合并 config
        result = dict(global_config)
        for key, value in self.config.items():
            if key == "billing" and isinstance(value, dict) and isinstance(result.get(key), dict):
                # 深度合并 billing
                result[key] = {**result[key], **value}
            else:
                result[key] = value

        return result if result else None

    def select_provider_model_name(
        self, affinity_key: str | None = None, api_format: str | None = None
    ) -> str:
        """按优先级选择要使用的 Provider 模型名称

        如果配置了 provider_model_mappings，按优先级选择（数字越小越优先）；
        相同优先级的映射通过哈希分散实现负载均衡（与 Key 调度策略一致）；
        否则返回 provider_model_name。

        Args:
            affinity_key: 用于哈希分散的亲和键（如用户 API Key 哈希），确保同一用户稳定选择同一映射
            api_format: 当前请求的 endpoint signature（如 "openai:chat"），用于过滤适用的映射
        """
        import hashlib

        if not self.provider_model_mappings:
            return self.provider_model_name

        raw_mappings = self.provider_model_mappings
        if not isinstance(raw_mappings, list) or len(raw_mappings) == 0:
            return self.provider_model_name

        mappings: list[dict] = []
        for raw in raw_mappings:
            if not isinstance(raw, dict):
                continue
            name = raw.get("name")
            if not isinstance(name, str) or not name.strip():
                continue

            # 检查 api_formats 作用域（如果配置了且当前有 api_format）
            mapping_api_formats = raw.get("api_formats")
            if api_format and mapping_api_formats:
                # 如果配置了作用域，只有匹配时才生效
                if isinstance(mapping_api_formats, list):
                    target = str(api_format).strip().lower()
                    allowed = {str(fmt).strip().lower() for fmt in mapping_api_formats if fmt}
                    if target not in allowed:
                        continue

            raw_priority = raw.get("priority", 1)
            try:
                priority = int(raw_priority)
            except Exception:
                priority = 1
            if priority < 1:
                priority = 1

            mappings.append({"name": name.strip(), "priority": priority})

        if not mappings:
            return self.provider_model_name

        # 按优先级排序（数字越小越优先）
        sorted_mappings = sorted(mappings, key=lambda x: x["priority"])

        # 获取最高优先级（最小数字）
        highest_priority = sorted_mappings[0]["priority"]

        # 获取所有最高优先级的映射
        top_priority_mappings = [
            mapping for mapping in sorted_mappings if mapping["priority"] == highest_priority
        ]

        # 如果有多个相同优先级的映射，通过哈希分散选择
        if len(top_priority_mappings) > 1 and affinity_key:
            # 为每个映射计算哈希得分，选择得分最小的
            def hash_score(mapping: dict) -> int:
                combined = f"{affinity_key}:{mapping['name']}"
                return int(hashlib.md5(combined.encode()).hexdigest(), 16)

            selected = min(top_priority_mappings, key=hash_score)
        elif len(top_priority_mappings) > 1:
            # 没有 affinity_key 时，使用确定性选择（按名称排序后取第一个）
            # 避免随机选择导致同一请求重试时选择不同的模型名称
            selected = min(top_priority_mappings, key=lambda x: x["name"])
        else:
            selected = top_priority_mappings[0]

        return selected["name"]

    def get_all_provider_model_names(self) -> list[str]:
        """获取所有可用的 Provider 模型名称（主名称 + 映射名称）"""
        names = [self.provider_model_name]
        if self.provider_model_mappings:
            for mapping in self.provider_model_mappings:
                if isinstance(mapping, dict) and mapping.get("name"):
                    names.append(mapping["name"])
        return names


class BillingRule(Base):
    """计费规则表（单条 formula 规则，支持 Model 覆盖 GlobalModel）。"""

    __tablename__ = "billing_rules"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 规则关联（两者必有其一）
    global_model_id = Column(
        String(36), ForeignKey("global_models.id", ondelete="CASCADE"), nullable=True, index=True
    )
    model_id = Column(
        String(36), ForeignKey("models.id", ondelete="CASCADE"), nullable=True, index=True
    )

    name = Column(String(100), nullable=False)
    # 注：CLI 在计费域里恒等于 chat，不单独存 "cli"
    task_type = Column(String(20), nullable=False, default="chat")

    # Formula 表达式及其配置
    expression = Column(Text, nullable=False)
    variables = Column(JSONB, nullable=False, default=dict)
    dimension_mappings = Column(JSONB, nullable=False, default=dict)

    is_enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    global_model = relationship("GlobalModel", foreign_keys=[global_model_id])
    model = relationship("Model", foreign_keys=[model_id])

    __table_args__ = (
        CheckConstraint(
            "(global_model_id IS NOT NULL AND model_id IS NULL) OR "
            "(global_model_id IS NULL AND model_id IS NOT NULL)",
            name="chk_billing_rules_model_ref",
        ),
        # 同级同 task_type 只允许一条启用规则（partial unique index）
        Index(
            "uq_billing_rules_global_model_task",
            "global_model_id",
            "task_type",
            unique=True,
            postgresql_where=text("is_enabled = TRUE AND global_model_id IS NOT NULL"),
        ),
        Index(
            "uq_billing_rules_model_task",
            "model_id",
            "task_type",
            unique=True,
            postgresql_where=text("is_enabled = TRUE AND model_id IS NOT NULL"),
        ),
    )


class DimensionCollector(Base):
    """维度收集器配置表（从请求/响应/元数据/派生计算收集维度）。"""

    __tablename__ = "dimension_collectors"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    api_format = Column(String(50), nullable=False)
    task_type = Column(String(20), nullable=False)
    dimension_name = Column(String(100), nullable=False)

    # 来源配置
    # - response / request / metadata / computed
    source_type = Column(String(20), nullable=False)
    source_path = Column(String(200), nullable=True)  # computed 允许为空

    # 值类型与转换
    value_type = Column(String(20), nullable=False, default="float")  # float/int/string
    transform_expression = Column(Text, nullable=True)  # computed 时为派生公式
    default_value = Column(String(100), nullable=True)

    priority = Column(Integer, nullable=False, default=0)
    is_enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "(source_type = 'computed' AND source_path IS NULL AND transform_expression IS NOT NULL) OR "
            "(source_type != 'computed' AND source_path IS NOT NULL)",
            name="chk_dimension_collectors_source_config",
        ),
        # 同维度 + 同优先级 + enabled 才唯一（允许禁用旧配置后重建）
        Index(
            "uq_dimension_collectors_enabled",
            "api_format",
            "task_type",
            "dimension_name",
            "priority",
            unique=True,
            postgresql_where=text("is_enabled = TRUE"),
        ),
    )
