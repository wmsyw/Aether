"""
缓存感知调度器 (Cache-Aware Scheduler)

职责:
1. 统一管理Provider/Endpoint/Key的选择逻辑
2. 集成缓存亲和性管理，优先使用有缓存的Provider+Key
3. 协调并发控制和缓存优先级
4. 实现故障转移机制（同Endpoint内优先，跨Provider按优先级）

核心设计思想:
===============
1. 用户首次请求: 按 provider_priority 选择最优 Provider+Endpoint+Key
2. 用户后续请求:
   - 优先使用缓存的Endpoint+Key (利用Prompt Caching)
   - 如果缓存的Key并发满，尝试同Endpoint其他Key
   - 如果Endpoint不可用，按 provider_priority 切换到其他Provider

3. 并发控制（动态预留机制）:
   - 探测阶段：使用低预留（10%），让系统快速学习真实并发限制
   - 稳定阶段：根据置信度和负载动态调整预留比例（10%-35%）
   - 置信度因素：连续成功次数、429冷却时间、调整历史稳定性
   - 缓存用户可使用全部槽位，新用户只能用 (1-预留比例) 的槽位

4. 故障转移:
   - Key故障: 同Endpoint内切换其他Key（检查模型支持）
   - Endpoint故障: 按 provider_priority 切换到其他Provider
   - 注意：不同Endpoint的协议完全不兼容，不能在同Provider内切换Endpoint
   - 失效缓存亲和性，避免重复选择故障资源
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.core.exceptions import ModelNotSupportedException, ProviderNotAvailableException
from src.core.logger import logger
from src.core.model_permissions import (
    check_model_allowed,
    get_allowed_models_preview,
    merge_allowed_models,
)
from src.models.database import (
    ApiKey,
    Provider,
    ProviderAPIKey,
    ProviderEndpoint,
)
from src.services.cache._candidate_builder import (
    CandidateBuilder,
)
from src.services.cache._candidate_builder import (
    _sort_endpoints_by_family_priority as _sort_endpoints_by_family_priority,
)
from src.services.cache._candidate_sorter import CandidateSorter
from src.services.cache.affinity_manager import (
    CacheAffinityManager,
    get_affinity_manager,
)
from src.services.cache.model_cache import ModelCacheService
from src.services.provider.format import normalize_endpoint_signature
from src.services.rate_limit.adaptive_reservation import (
    AdaptiveReservationManager,
    get_adaptive_reservation_manager,
)
from src.services.rate_limit.adaptive_rpm import get_adaptive_rpm_manager
from src.services.rate_limit.concurrency_manager import get_concurrency_manager
from src.services.system.config import SystemConfigService


@dataclass
class ProviderCandidate:
    """候选 provider 组合及是否命中缓存"""

    provider: Provider
    endpoint: ProviderEndpoint
    key: ProviderAPIKey
    is_cached: bool = False
    is_skipped: bool = False  # 是否被跳过
    skip_reason: str | None = None  # 跳过原因
    mapping_matched_model: str | None = None  # 通过映射匹配到的模型名（用于实际请求）
    needs_conversion: bool = False  # 是否需要格式转换
    provider_api_format: str = ""  # Provider 端点实际格式（用于健康度/熔断 bucket）

    def _stable_order_key(self) -> tuple[int, int, str, str, str]:
        """
        为排序/优先队列提供稳定的比较键。

        说明：
        - 运行时偶发会出现对 ProviderCandidate 做 tuple 排序/heap 排序的场景；
          当主键相同需要比较候选本身时，若候选不可比较会触发：
          TypeError: '<' not supported between instances of 'ProviderCandidate' and 'ProviderCandidate'
        - 这里提供一个与调度逻辑无关、但足够稳定且可比的兜底顺序。
        """
        provider_priority_raw = getattr(self.provider, "provider_priority", None)
        internal_priority_raw = getattr(self.key, "internal_priority", None)

        try:
            provider_priority = (
                int(provider_priority_raw) if provider_priority_raw is not None else 999999
            )
        except Exception:
            provider_priority = 999999

        try:
            internal_priority = (
                int(internal_priority_raw) if internal_priority_raw is not None else 999999
            )
        except Exception:
            internal_priority = 999999

        provider_id = str(getattr(self.provider, "id", "") or "")
        endpoint_id = str(getattr(self.endpoint, "id", "") or "")
        key_id = str(getattr(self.key, "id", "") or "")
        return (provider_priority, internal_priority, provider_id, endpoint_id, key_id)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ProviderCandidate):
            return NotImplemented
        return self._stable_order_key() < other._stable_order_key()


@dataclass
class ConcurrencySnapshot:
    key_current: int
    key_limit: int | None
    is_cached_user: bool = False
    # 动态预留信息
    reservation_ratio: float = 0.0
    reservation_phase: str = "unknown"
    reservation_confidence: float = 0.0

    def describe(self) -> str:
        key_limit_text = str(self.key_limit) if self.key_limit is not None else "inf"
        reservation_text = f"{self.reservation_ratio:.0%}" if self.reservation_ratio > 0 else "N/A"
        return (
            f"key={self.key_current}/{key_limit_text}, "
            f"cached={self.is_cached_user}, "
            f"reserve={reservation_text}({self.reservation_phase})"
        )


class CacheAwareScheduler:
    """
    缓存感知调度器

    这是Provider选择的核心组件，整合了:
    - Provider/Endpoint/Key三层架构
    - 缓存亲和性管理
    - 并发控制（动态预留机制）
    - 健康度监控
    """

    # 优先级模式常量
    PRIORITY_MODE_PROVIDER = "provider"  # 提供商优先模式
    PRIORITY_MODE_GLOBAL_KEY = "global_key"  # 全局 Key 优先模式
    ALLOWED_PRIORITY_MODES = {
        PRIORITY_MODE_PROVIDER,
        PRIORITY_MODE_GLOBAL_KEY,
    }
    # 调度模式常量
    SCHEDULING_MODE_FIXED_ORDER = "fixed_order"  # 固定顺序模式：严格按优先级，忽略缓存
    SCHEDULING_MODE_CACHE_AFFINITY = "cache_affinity"  # 缓存亲和模式：优先缓存，同优先级哈希分散
    SCHEDULING_MODE_LOAD_BALANCE = "load_balance"  # 负载均衡模式：忽略缓存，同优先级随机轮换
    ALLOWED_SCHEDULING_MODES = {
        SCHEDULING_MODE_FIXED_ORDER,
        SCHEDULING_MODE_CACHE_AFFINITY,
        SCHEDULING_MODE_LOAD_BALANCE,
    }

    def __init__(
        self,
        redis_client: Any | None = None,
        priority_mode: str | None = None,
        scheduling_mode: str | None = None,
    ) -> None:
        """
        初始化调度器

        注意: 不再持久化 db Session,避免跨请求使用已关闭的会话
        每个方法调用时需要传入当前请求的 db Session

        Args:
            redis_client: Redis客户端（可选）
            priority_mode: 候选排序策略（provider | global_key）
            scheduling_mode: 调度模式（fixed_order | cache_affinity）
        """
        self.redis = redis_client
        self.priority_mode = self._normalize_priority_mode(
            priority_mode or self.PRIORITY_MODE_PROVIDER
        )
        self.scheduling_mode = self._normalize_scheduling_mode(
            scheduling_mode or self.SCHEDULING_MODE_CACHE_AFFINITY
        )
        logger.debug(
            f"[CacheAwareScheduler] 初始化优先级模式: {self.priority_mode}, 调度模式: {self.scheduling_mode}"
        )

        # 初始化子组件（将在第一次使用时异步初始化）
        self._affinity_manager: CacheAffinityManager | None = None
        self._concurrency_manager = None
        # 动态预留管理器（同步初始化）
        self._reservation_manager: AdaptiveReservationManager = get_adaptive_reservation_manager()
        self._metrics = {
            "total_batches": 0,
            "last_batch_size": 0,
            "total_candidates": 0,
            "last_candidate_count": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "concurrency_denied": 0,
            "last_api_format": None,
            "last_model_name": None,
            "last_updated_at": None,
            # 动态预留相关指标
            "reservation_probe_count": 0,
            "reservation_stable_count": 0,
            "avg_reservation_ratio": 0.0,
            "last_reservation_result": None,
        }

        # 初始化拆分出的子模块
        self._candidate_builder = CandidateBuilder(self)
        self._candidate_sorter = CandidateSorter(self)

    @staticmethod
    def _release_db_connection_before_await(db: Session) -> None:
        """
        Best-effort: end a read-only transaction before awaiting async I/O.

        This scheduler does a lot of async work (cache/Redis) mixed with sync SQLAlchemy reads.
        If a SELECT has already started a transaction, the pooled connection can remain checked
        out while we await, causing pool pressure under concurrency.

        Safety:
        - Only commits when the Session has no ORM pending changes.
        - Temporarily disables expire_on_commit to keep already-loaded ORM objects usable.
        """
        try:
            if db is None:
                return
            has_pending_changes = bool(db.new) or bool(db.dirty) or bool(db.deleted)
            if has_pending_changes:
                return
            if not db.in_transaction():
                return

            original_expire_on_commit = getattr(db, "expire_on_commit", True)
            db.expire_on_commit = False
            try:
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
            finally:
                db.expire_on_commit = original_expire_on_commit
        except Exception:
            # Never let this optimization break scheduling
            return

    async def _ensure_initialized(self) -> None:
        """确保所有异步组件已初始化"""
        if self._affinity_manager is None:
            self._affinity_manager = await get_affinity_manager(self.redis)

        if self._concurrency_manager is None:
            self._concurrency_manager = await get_concurrency_manager()

    async def select_with_cache_affinity(
        self,
        db: Session,
        affinity_key: str,
        api_format: str,
        model_name: str,
        excluded_endpoints: list[str] | None = None,
        excluded_keys: list[str] | None = None,
        provider_batch_size: int = 20,
        max_candidates_per_batch: int | None = None,
    ) -> tuple[Provider, ProviderEndpoint, ProviderAPIKey]:
        """
        缓存感知选择 - 核心方法

        逻辑：一次性获取所有候选（缓存命中优先），按顺序检查
        排除列表和并发限制，返回首个可用组合，并在需要时刷新缓存亲和性。

        Args:
            db: 数据库会话
            affinity_key: 亲和性标识符（通常为API Key ID）
            api_format: API格式
            model_name: 模型名称
            excluded_endpoints: 排除的Endpoint ID列表
            excluded_keys: 排除的Provider Key ID列表
            provider_batch_size: Provider批量大小
            max_candidates_per_batch: 每批最大候选数
        """
        await self._ensure_initialized()

        excluded_endpoints_set = set(excluded_endpoints or [])
        excluded_keys_set = set(excluded_keys or [])

        normalized_format = normalize_endpoint_signature(api_format)

        logger.debug(
            f"[CacheAwareScheduler] select_with_cache_affinity: "
            f"affinity_key={affinity_key[:8]}..., api_format={normalized_format}, model={model_name}"
        )

        self._metrics["last_api_format"] = normalized_format
        self._metrics["last_model_name"] = model_name

        provider_offset = 0

        global_model_id = None  # 用于缓存亲和性

        while True:
            candidates, resolved_global_model_id, provider_batch_count = (
                await self.list_all_candidates(
                    db=db,
                    api_format=normalized_format,
                    model_name=model_name,
                    affinity_key=affinity_key,
                    provider_offset=provider_offset,
                    provider_limit=provider_batch_size,
                    max_candidates=max_candidates_per_batch,
                )
            )

            if resolved_global_model_id and global_model_id is None:
                global_model_id = resolved_global_model_id

            if provider_batch_count == 0:
                if provider_offset == 0:
                    # 没有找到任何候选，提供友好的错误提示（不暴露内部信息）
                    raise ProviderNotAvailableException("请求的模型当前不可用")
                break

            self._metrics["total_batches"] += 1
            self._metrics["last_batch_size"] = len(candidates)
            self._metrics["last_updated_at"] = int(time.time())

            for candidate in candidates:
                provider = candidate.provider
                endpoint = candidate.endpoint
                key = candidate.key

                if endpoint.id in excluded_endpoints_set:
                    logger.debug(f"  └─ Endpoint {endpoint.id[:8]}... 在排除列表，跳过")
                    continue

                if key.id in excluded_keys_set:
                    logger.debug(f"  └─ Key {key.id[:8]}... 在排除列表，跳过")
                    continue

                is_cached_user = bool(candidate.is_cached)
                can_use, snapshot = await self._check_concurrent_available(
                    key,
                    is_cached_user=is_cached_user,
                )

                if not can_use:
                    logger.debug(f"  └─ Key {key.id[:8]}... 并发已满 ({snapshot.describe()})")
                    self._metrics["concurrency_denied"] += 1
                    continue

                logger.debug(
                    f"  └─ 选择 Provider={provider.name}, Endpoint={endpoint.id[:8]}..., "
                    f"Key=***{key.api_key[-4:]}, 缓存命中={is_cached_user}, "
                    f"并发状态[{snapshot.describe()}]"
                )

                if key.cache_ttl_minutes > 0 and global_model_id:
                    ttl = key.cache_ttl_minutes * 60
                    await self.set_cache_affinity(
                        affinity_key=affinity_key,
                        provider_id=str(provider.id),
                        endpoint_id=str(endpoint.id),
                        key_id=str(key.id),
                        api_format=normalized_format,
                        global_model_id=global_model_id,
                        ttl=ttl,
                    )

                if is_cached_user:
                    self._metrics["cache_hits"] += 1
                else:
                    self._metrics["cache_misses"] += 1

                return provider, endpoint, key

            provider_offset += provider_batch_size
            if provider_batch_count < provider_batch_size:
                break

        raise ProviderNotAvailableException("服务暂时繁忙，请稍后重试")

    def _get_effective_rpm_limit(self, key: ProviderAPIKey) -> int | None:
        """获取有效的 RPM 限制（委托给 AdaptiveRPMManager 统一逻辑）"""
        return get_adaptive_rpm_manager().get_effective_limit(key)

    async def _check_concurrent_available(
        self,
        key: ProviderAPIKey,
        is_cached_user: bool = False,
    ) -> tuple[bool, ConcurrencySnapshot]:
        """
        检查 RPM 限制是否可用（使用动态预留机制）

        核心逻辑 - 动态缓存预留机制:
        - 总槽位: 有效 RPM 限制（固定值或学习到的值）
        - 预留比例: 由 AdaptiveReservationManager 根据置信度和负载动态计算
        - 缓存用户可用: 全部槽位
        - 新用户可用: 总槽位 x (1 - 动态预留比例)

        Args:
            key: ProviderAPIKey对象
            is_cached_user: 是否是缓存用户

        Returns:
            (是否可用, 并发快照)
        """
        # 获取有效的并发限制
        effective_key_limit = self._get_effective_rpm_limit(key)

        logger.debug(
            f"            -> 并发检查: _concurrency_manager={self._concurrency_manager is not None}, "
            f"is_cached_user={is_cached_user}, effective_limit={effective_key_limit}"
        )

        if not self._concurrency_manager:
            # 并发管理器不可用，直接返回True
            logger.debug(f"            -> 无并发管理器，直接通过")
            snapshot = ConcurrencySnapshot(
                key_current=0,
                key_limit=effective_key_limit,
                is_cached_user=is_cached_user,
            )
            return True, snapshot

        # 获取当前 RPM 计数
        key_count = await self._concurrency_manager.get_key_rpm_count(
            key_id=str(key.id),
        )

        can_use = True

        # 计算动态预留比例
        reservation_result = self._reservation_manager.calculate_reservation(
            key=key,
            current_usage=key_count,
            effective_limit=effective_key_limit,
        )

        # 更新指标
        if reservation_result.phase == "probe":
            self._metrics["reservation_probe_count"] += 1
        else:
            self._metrics["reservation_stable_count"] += 1

        # 计算移动平均预留比例
        total_reservations = (
            self._metrics["reservation_probe_count"] + self._metrics["reservation_stable_count"]
        )
        if total_reservations > 0:
            # 指数移动平均
            alpha = 0.1
            self._metrics["avg_reservation_ratio"] = (
                alpha * reservation_result.ratio
                + (1 - alpha) * self._metrics["avg_reservation_ratio"]
            )

        self._metrics["last_reservation_result"] = {
            "ratio": reservation_result.ratio,
            "phase": reservation_result.phase,
            "confidence": reservation_result.confidence,
            "load_factor": reservation_result.load_factor,
        }

        available_for_new = None
        reservation_ratio = reservation_result.ratio

        # 检查Key级别限制（使用动态预留比例）
        if effective_key_limit is not None:
            if is_cached_user:
                # 缓存用户: 可以使用全部槽位
                if key_count >= effective_key_limit:
                    can_use = False
            else:
                # 新用户: 只能使用 (1 - 动态预留比例) 的槽位
                # 使用 max 确保至少有 1 个槽位可用

                # 与 ConcurrencyManager 的 Lua 脚本保持一致：使用 floor 计算新用户可用槽位
                available_for_new = max(
                    1, math.floor(effective_key_limit * (1 - reservation_ratio))
                )
                if key_count >= available_for_new:
                    logger.debug(
                        f"Key {key.id[:8]}... 新用户配额已满 "
                        f"({key_count}/{available_for_new}, 总{effective_key_limit}, "
                        f"预留{reservation_ratio:.0%}[{reservation_result.phase}])"
                    )
                    can_use = False

        key_limit_for_snapshot: int | None
        if is_cached_user:
            key_limit_for_snapshot = effective_key_limit
        elif effective_key_limit is not None:
            key_limit_for_snapshot = (
                available_for_new if available_for_new is not None else effective_key_limit
            )
        else:
            key_limit_for_snapshot = None

        snapshot = ConcurrencySnapshot(
            key_current=key_count,
            key_limit=key_limit_for_snapshot,
            is_cached_user=is_cached_user,
            reservation_ratio=reservation_ratio,
            reservation_phase=reservation_result.phase,
            reservation_confidence=reservation_result.confidence,
        )

        return can_use, snapshot

    def _get_effective_restrictions(
        self,
        user_api_key: ApiKey | None,
    ) -> dict[str, Any]:
        """
        获取有效的访问限制（合并 ApiKey 和 User 的限制）

        逻辑：
        - 如果 ApiKey 和 User 都有限制，取交集
        - 如果只有一方有限制，使用该方的限制
        - 如果都没有限制，返回 None（表示不限制）

        Args:
            user_api_key: 用户 API Key 对象（可能包含 user relationship）

        Returns:
            包含 allowed_providers, allowed_models, allowed_api_formats 的字典
        """
        result = {
            "allowed_providers": None,
            "allowed_models": None,
            "allowed_api_formats": None,
        }

        if not user_api_key:
            return result

        # 获取 User 的限制
        # 注意：这里可能触发 lazy loading，需要确保 session 仍然有效
        try:
            user = user_api_key.user if hasattr(user_api_key, "user") else None
        except Exception as e:
            logger.warning(f"无法加载 ApiKey 关联的 User: {e}，仅使用 ApiKey 级别的限制")
            user = None

        # 调试日志
        logger.debug(
            f"[_get_effective_restrictions] ApiKey={user_api_key.id[:8]}..., "
            f"User={user.id[:8] if user else 'None'}..., "
            f"ApiKey.allowed_models={user_api_key.allowed_models}, "
            f"User.allowed_models={user.allowed_models if user else 'N/A'}"
        )

        # 合并 allowed_providers
        result["allowed_providers"] = self._merge_restriction_sets(
            user_api_key.allowed_providers, user.allowed_providers if user else None
        )

        # 合并 allowed_models（取交集）
        result["allowed_models"] = merge_allowed_models(
            user_api_key.allowed_models, user.allowed_models if user else None
        )

        # 合并 allowed_api_formats
        result["allowed_api_formats"] = self._merge_restriction_sets(
            user_api_key.allowed_api_formats, user.allowed_api_formats if user else None
        )

        return result

    async def list_all_candidates(
        self,
        db: Session,
        api_format: str,
        model_name: str,
        affinity_key: str | None = None,
        user_api_key: ApiKey | None = None,
        provider_offset: int = 0,
        provider_limit: int | None = None,
        max_candidates: int | None = None,
        is_stream: bool = False,
        capability_requirements: dict[str, bool] | None = None,
    ) -> tuple[list[ProviderCandidate], str, int]:
        """
        预先获取所有可用的 Provider/Endpoint/Key 组合

        重构后的方法将逻辑拆分为：
        1. _query_providers: 数据库查询逻辑（委托给 CandidateBuilder）
        2. _build_candidates: 候选构建逻辑（委托给 CandidateBuilder）
        3. _apply_cache_affinity: 缓存亲和性处理

        Args:
            db: 数据库会话
            api_format: API 格式
            model_name: 模型名称
            affinity_key: 亲和性标识符（通常为API Key ID，用于缓存亲和性）
            user_api_key: 用户 API Key（用于访问限制过滤，同时考虑 User 级别限制）
            provider_offset: Provider 分页偏移
            provider_limit: Provider 分页限制
            max_candidates: 最大候选数量
            is_stream: 是否是流式请求，如果为 True 则过滤不支持流式的 Provider
            capability_requirements: 能力需求（用于过滤不满足能力要求的 Key）

        Returns:
            (候选列表, global_model_id, provider_batch_count)
            - global_model_id 用于缓存亲和性
            - provider_batch_count 表示本次查询到的 Provider 数量（未应用 allowed_providers 过滤前）
        """
        # If the caller already touched the DB, release the connection before we do async work.
        self._release_db_connection_before_await(db)
        await self._ensure_initialized()

        target_format = normalize_endpoint_signature(api_format)

        logger.debug(
            "[Scheduler] list_all_candidates: model={}, api_format={}",
            model_name,
            target_format,
        )

        # 0. 解析 model_name 到 GlobalModel（仅接受 GlobalModel.name）
        normalized_name = model_name.strip() if isinstance(model_name, str) else ""
        if not normalized_name:
            logger.warning("GlobalModel not found: <empty model name>")
            raise ModelNotSupportedException(model=model_name)

        global_model = await ModelCacheService.get_global_model_by_name(db, normalized_name)
        if not global_model or not global_model.is_active:
            logger.warning(f"GlobalModel not found or inactive: {normalized_name}")
            raise ModelNotSupportedException(model=model_name)

        logger.debug(
            "[Scheduler] GlobalModel resolved: id={}, name={}",
            global_model.id,
            global_model.name,
        )

        # 使用 GlobalModel.id 作为缓存亲和性的模型标识，确保映射名和规范名都能命中同一个缓存
        global_model_id: str = str(global_model.id)

        queried_provider_count = 0

        # 提取模型映射（用于 Provider Key 的 allowed_models 匹配）
        model_mappings: list[str] = (global_model.config or {}).get("model_mappings", [])
        if model_mappings:
            logger.debug(
                f"[Scheduler] GlobalModel={global_model.name} 配置了映射规则: {model_mappings}"
            )

        # 获取合并后的访问限制（ApiKey + User）
        restrictions = self._get_effective_restrictions(user_api_key)
        allowed_api_formats = restrictions["allowed_api_formats"]
        allowed_providers = restrictions["allowed_providers"]
        allowed_models = restrictions["allowed_models"]

        # 0.1 检查 API 格式是否被允许
        if allowed_api_formats is not None:
            allowed_norm = {normalize_endpoint_signature(f) for f in allowed_api_formats if f}
            if target_format not in allowed_norm:
                logger.debug(
                    f"API Key {user_api_key.id[:8] if user_api_key else 'N/A'}... 不允许使用 API 格式 {target_format}, "
                    f"允许的格式: {allowed_api_formats}"
                )
                return [], global_model_id, queried_provider_count

        # 0.2 检查模型是否被允许
        if not check_model_allowed(
            model_name=model_name,
            allowed_models=allowed_models,
        ):
            logger.debug(
                f"用户/API Key 不允许使用模型 {model_name}, "
                f"允许的模型: {get_allowed_models_preview(allowed_models)}"
            )
            return [], global_model_id, queried_provider_count

        # 1. 查询 Providers（委托给 CandidateBuilder）
        providers = self._candidate_builder._query_providers(
            db=db,
            provider_offset=provider_offset,
            provider_limit=provider_limit,
        )
        queried_provider_count = len(providers)

        # Provider query starts a transaction; release connection before entering async candidate build.
        self._release_db_connection_before_await(db)

        logger.debug(
            "[Scheduler] Found {} active providers",
            len(providers),
        )
        for p in providers:
            logger.debug(
                "[Scheduler] Provider: id={}, name={}, is_active={}, endpoints={}, models={}",
                p.id[:8] if p.id else "N/A",
                p.name,
                p.is_active,
                len(p.endpoints) if p.endpoints else 0,
                len(p.models) if p.models else 0,
            )

        if not providers:
            return [], global_model_id, queried_provider_count

        # 1.5 根据 allowed_providers 过滤（合并 ApiKey 和 User 的限制）
        if allowed_providers is not None:
            original_count = len(providers)
            # 同时支持 provider id 和 name 匹配
            providers = [
                p for p in providers if p.id in allowed_providers or p.name in allowed_providers
            ]
            if original_count != len(providers):
                logger.debug(f"用户/API Key 过滤 Provider: {original_count} -> {len(providers)}")

        if not providers:
            return [], global_model_id, queried_provider_count

        # 2. 构建候选列表（委托给 CandidateBuilder）

        # 格式转换总开关（数据库配置）：关闭时禁止任何跨格式候选进入队列
        global_conversion_enabled = SystemConfigService.is_format_conversion_enabled(db)

        candidates = await self._candidate_builder._build_candidates(
            db=db,
            providers=providers,
            client_format=target_format,
            model_name=model_name,
            model_mappings=model_mappings,
            affinity_key=affinity_key,
            max_candidates=max_candidates,
            is_stream=is_stream,
            capability_requirements=capability_requirements,
            global_conversion_enabled=global_conversion_enabled,
        )

        # 3. 应用优先级模式排序 + 调度模式排序
        candidates = await self.reorder_candidates(
            candidates=candidates,
            db=db,
            affinity_key=affinity_key,
            api_format=target_format,
            global_model_id=global_model_id,
        )

        # 更新指标
        self._metrics["total_candidates"] += len(candidates)
        self._metrics["last_candidate_count"] = len(candidates)

        logger.debug(
            f"预先获取到 {len(candidates)} 个可用组合 "
            f"(api_format={target_format}, model={model_name})"
        )

        return candidates, global_model_id, queried_provider_count

    async def reorder_candidates(
        self,
        candidates: list[ProviderCandidate],
        db: Session,
        affinity_key: str | None = None,
        api_format: str | None = None,
        global_model_id: str | None = None,
    ) -> list[ProviderCandidate]:
        """对候选列表应用优先级模式排序和调度模式排序。

        在分页汇总后调用此方法可修正跨页排序失真。

        Args:
            candidates: 候选列表
            db: 数据库会话
            affinity_key: 亲和性标识符
            api_format: API 格式
            global_model_id: GlobalModel ID（缓存亲和模式需要）

        Returns:
            重排序后的候选列表
        """
        if not candidates:
            return candidates

        # 1. 优先级模式排序（委托给 CandidateSorter）
        candidates = self._candidate_sorter._apply_priority_mode_sort(
            candidates, db, affinity_key, api_format
        )

        # 2. 调度模式排序
        if self.scheduling_mode == self.SCHEDULING_MODE_CACHE_AFFINITY:
            if affinity_key and candidates and global_model_id:
                candidates = await self._apply_cache_affinity(
                    candidates=candidates,
                    db=db,
                    affinity_key=affinity_key,
                    api_format=api_format or "",
                    global_model_id=global_model_id,
                )
        elif self.scheduling_mode == self.SCHEDULING_MODE_LOAD_BALANCE:
            candidates = self._candidate_sorter._apply_load_balance(candidates, api_format)
            for candidate in candidates:
                candidate.is_cached = False
        else:
            for candidate in candidates:
                candidate.is_cached = False

        return candidates

    async def _apply_cache_affinity(
        self,
        candidates: list[ProviderCandidate],
        db: Session,
        affinity_key: str,
        api_format: str,
        global_model_id: str,
    ) -> list[ProviderCandidate]:
        """
        应用缓存亲和性排序

        缓存命中的候选会被提升到列表前面

        Args:
            candidates: 候选列表
            affinity_key: 亲和性标识符（通常为API Key ID）
            api_format: API 格式
            global_model_id: GlobalModel ID（规范化的模型标识）

        Returns:
            重排序后的候选列表
        """
        try:
            # 查询该亲和性标识符在当前 API 格式和模型下的缓存亲和性
            api_format_str = str(api_format)
            affinity = await self._affinity_manager.get_affinity(
                affinity_key, api_format_str, global_model_id
            )

            if not affinity:
                # 没有缓存亲和性，所有候选都标记为非缓存
                for candidate in candidates:
                    candidate.is_cached = False
                return candidates

            # 判断候选是否应该被降级（用于分组）
            global_keep_priority = SystemConfigService.is_keep_priority_on_conversion(db)

            def should_demote(c: ProviderCandidate) -> bool:
                """判断候选是否应该被降级"""
                if global_keep_priority:
                    return False  # 全局开启时，所有候选都不降级
                if not c.needs_conversion:
                    return False  # exact 候选不降级
                if getattr(c.provider, "keep_priority_on_conversion", False):
                    return False  # 提供商配置了保持优先级
                return True  # 需要降级

            # 按是否匹配缓存亲和性分类候选，同时记录是否降级
            matched_candidate: ProviderCandidate | None = None
            matched = False

            for candidate in candidates:
                provider = candidate.provider
                endpoint = candidate.endpoint
                key = candidate.key

                if (
                    provider.id == affinity.provider_id
                    and endpoint.id == affinity.endpoint_id
                    and key.id == affinity.key_id
                ):
                    candidate.is_cached = True
                    matched_candidate = candidate
                    matched = True
                    logger.debug(
                        f"检测到缓存亲和性: affinity_key={affinity_key[:8]}..., "
                        f"api_format={api_format_str}, global_model_id={global_model_id[:8]}..., "
                        f"provider={provider.name}, endpoint={endpoint.id[:8]}..., "
                        f"provider_key=***{key.api_key[-4:]}, "
                        f"使用次数={affinity.request_count}"
                    )
                else:
                    candidate.is_cached = False

            if not matched:
                logger.debug(f"API格式 {api_format_str} 的缓存亲和性存在但组合不可用")
                return candidates

            # 缓存亲和性命中且该候选可用（未被跳过）时，无条件优先使用
            # 理由：1) 它之前成功过；2) 它有 prompt cache 优势
            # 只有当缓存亲和性的候选被跳过（健康度太低/熔断）时，才按 exact 优先排序
            assert matched_candidate is not None  # guaranteed by matched=True

            if not matched_candidate.is_skipped:
                # 缓存命中且健康，无条件提升到最前面
                other_candidates = [c for c in candidates if c is not matched_candidate]
                result = [matched_candidate] + other_candidates
                logger.debug(
                    f"缓存亲和性命中且健康，无条件优先使用 "
                    f"(needs_conversion={matched_candidate.needs_conversion})"
                )
                return result

            # 缓存命中但被跳过（不健康），按 exact 优先排序
            # 缓存候选在其所属类别内提升到最前面
            logger.debug(
                f"缓存亲和性命中但不健康 (skip_reason={matched_candidate.skip_reason})，"
                f"按 exact 优先排序"
            )
            matched_should_demote = should_demote(matched_candidate)

            # 分组：非降级类 和 降级类
            keep_priority_candidates: list[ProviderCandidate] = []
            demote_candidates: list[ProviderCandidate] = []

            for c in candidates:
                if c is matched_candidate:
                    continue  # 先跳过缓存命中的候选
                if should_demote(c):
                    demote_candidates.append(c)
                else:
                    keep_priority_candidates.append(c)

            # 将缓存命中的候选插入到其所属类别的最前面
            if matched_should_demote:
                # 缓存命中的是降级类，插入到降级类最前面
                demote_candidates.insert(0, matched_candidate)
            else:
                # 缓存命中的是非降级类，插入到非降级类最前面
                keep_priority_candidates.insert(0, matched_candidate)

            result = keep_priority_candidates + demote_candidates
            logger.debug(f"缓存组合已提升至其类别内优先级 (demote={matched_should_demote})")
            return result

        except Exception as e:
            logger.warning(f"检查缓存亲和性失败: {e}，继续使用默认排序")
            return candidates

    @staticmethod
    def _affinity_hash(affinity_key: str, identifier: str) -> int:
        """基于 affinity_key 和标识符的确定性哈希（用于同优先级内分散负载均衡）"""
        return int(hashlib.sha256(f"{affinity_key}:{identifier}".encode()).hexdigest()[:16], 16)

    @staticmethod
    def _merge_restriction_sets(key_restriction: Any, user_restriction: Any) -> set[Any] | None:
        """合并两个限制列表，取交集；任一方为空则使用另一方；均空返回 None"""
        key_set = set(key_restriction) if key_restriction else None
        user_set = set(user_restriction) if user_restriction else None
        if key_set and user_set:
            return key_set & user_set
        return key_set or user_set

    def _normalize_priority_mode(self, mode: str | None) -> str:
        normalized = (mode or "").strip().lower()
        if normalized not in self.ALLOWED_PRIORITY_MODES:
            if normalized:
                logger.warning(f"[CacheAwareScheduler] 无效的优先级模式 '{mode}'，回退为 provider")
            return self.PRIORITY_MODE_PROVIDER
        return normalized

    def set_priority_mode(self, mode: str | None) -> None:
        """运行时更新候选排序策略"""
        normalized = self._normalize_priority_mode(mode)
        if normalized == self.priority_mode:
            return
        self.priority_mode = normalized
        logger.debug(f"[CacheAwareScheduler] 切换优先级模式为: {self.priority_mode}")

    def _normalize_scheduling_mode(self, mode: str | None) -> str:
        normalized = (mode or "").strip().lower()
        if normalized not in self.ALLOWED_SCHEDULING_MODES:
            if normalized:
                logger.warning(
                    f"[CacheAwareScheduler] 无效的调度模式 '{mode}'，回退为 cache_affinity"
                )
            return self.SCHEDULING_MODE_CACHE_AFFINITY
        return normalized

    def set_scheduling_mode(self, mode: str | None) -> None:
        """运行时更新调度模式"""
        normalized = self._normalize_scheduling_mode(mode)
        if normalized == self.scheduling_mode:
            return
        self.scheduling_mode = normalized
        logger.debug(f"[CacheAwareScheduler] 切换调度模式为: {self.scheduling_mode}")

    async def invalidate_cache(
        self,
        affinity_key: str,
        api_format: str,
        global_model_id: str,
        endpoint_id: str | None = None,
        key_id: str | None = None,
        provider_id: str | None = None,
    ) -> Any:
        """
        失效指定亲和性标识符对特定API格式和模型的缓存亲和性

        Args:
            affinity_key: 亲和性标识符（通常为API Key ID）
            api_format: API格式 (claude/openai)
            global_model_id: GlobalModel ID（规范化的模型标识）
            endpoint_id: 端点ID（可选，如果提供则只在Endpoint匹配时失效）
            key_id: Provider Key ID（可选）
            provider_id: Provider ID（可选）
        """
        await self._ensure_initialized()
        await self._affinity_manager.invalidate_affinity(
            affinity_key=affinity_key,
            api_format=api_format,
            model_name=global_model_id,
            endpoint_id=endpoint_id,
            key_id=key_id,
            provider_id=provider_id,
        )

    async def set_cache_affinity(
        self,
        affinity_key: str,
        provider_id: str,
        endpoint_id: str,
        key_id: str,
        api_format: str,
        global_model_id: str,
        ttl: int | None = None,
    ) -> Any:
        """
        记录缓存亲和性（供编排器调用）

        Args:
            affinity_key: 亲和性标识符（通常为API Key ID）
            provider_id: Provider ID
            endpoint_id: Endpoint ID
            key_id: Provider Key ID
            api_format: API格式
            global_model_id: GlobalModel ID（规范化的模型标识）
            ttl: 缓存TTL（秒）

        注意：每次调用都会刷新过期时间，实现滑动窗口机制
        """
        await self._ensure_initialized()

        await self._affinity_manager.set_affinity(
            affinity_key=affinity_key,
            provider_id=provider_id,
            endpoint_id=endpoint_id,
            key_id=key_id,
            api_format=api_format,
            model_name=global_model_id,
            supports_caching=True,
            ttl=ttl,
        )

    async def get_stats(self) -> dict:
        """获取调度器统计信息"""
        await self._ensure_initialized()

        affinity_stats = self._affinity_manager.get_stats()
        metrics = dict(self._metrics)

        cache_total = metrics["cache_hits"] + metrics["cache_misses"]
        metrics["cache_hit_rate"] = metrics["cache_hits"] / cache_total if cache_total else 0.0
        metrics["avg_candidates_per_batch"] = (
            metrics["total_candidates"] / metrics["total_batches"]
            if metrics["total_batches"]
            else 0.0
        )

        # 动态预留统计
        reservation_stats = self._reservation_manager.get_stats()
        total_reservation_checks = (
            metrics["reservation_probe_count"] + metrics["reservation_stable_count"]
        )
        if total_reservation_checks > 0:
            probe_ratio = metrics["reservation_probe_count"] / total_reservation_checks
        else:
            probe_ratio = 0.0

        return {
            "scheduler": "cache_aware",
            "dynamic_reservation": {
                "enabled": True,
                "config": reservation_stats["config"],
                "current_avg_ratio": round(metrics["avg_reservation_ratio"], 3),
                "probe_phase_ratio": round(probe_ratio, 3),
                "total_checks": total_reservation_checks,
                "last_result": metrics["last_reservation_result"],
            },
            "affinity_stats": affinity_stats,
            "scheduler_metrics": metrics,
        }


# 全局单例
_scheduler: CacheAwareScheduler | None = None


async def get_cache_aware_scheduler(
    redis_client: Any | None = None,
    priority_mode: str | None = None,
    scheduling_mode: str | None = None,
) -> CacheAwareScheduler:
    """
    获取全局CacheAwareScheduler实例

    注意: 不再接受 db 参数,避免持久化请求级别的 Session
    每次调用 scheduler 方法时需要传入当前请求的 db Session

    Args:
        redis_client: Redis客户端（可选）
        priority_mode: 外部覆盖的优先级模式（provider | global_key）
        scheduling_mode: 外部覆盖的调度模式（fixed_order | cache_affinity）

    Returns:
        CacheAwareScheduler实例
    """
    global _scheduler

    if _scheduler is None:
        _scheduler = CacheAwareScheduler(
            redis_client, priority_mode=priority_mode, scheduling_mode=scheduling_mode
        )
    else:
        if priority_mode:
            _scheduler.set_priority_mode(priority_mode)
        if scheduling_mode:
            _scheduler.set_scheduling_mode(scheduling_mode)

    return _scheduler
