"""
候选排序器 (CandidateSorter)

从 CacheAwareScheduler 拆分出的候选排序逻辑，负责:
- 优先级模式排序（provider / global_key）
- 负载均衡模式排序
- Key 内部按优先级分组打乱
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import TYPE_CHECKING

from src.core.logger import logger
from src.services.system.config import SystemConfigService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.models.database import ProviderAPIKey
    from src.services.cache.aware_scheduler import CacheAwareScheduler, ProviderCandidate


class CandidateSorter:
    """候选排序器，负责优先级模式排序、负载均衡排序和 Key 内部打乱。"""

    def __init__(self, scheduler: CacheAwareScheduler) -> None:
        self._scheduler = scheduler

    def _apply_priority_mode_sort(
        self,
        candidates: list[ProviderCandidate],
        db: Session,
        affinity_key: str | None = None,
        api_format: str | None = None,
    ) -> list[ProviderCandidate]:
        """
        根据优先级模式对候选列表排序（数字越小越优先）

        排序规则（受 keep_priority_on_conversion 配置影响）：
        1. 如果全局配置 keep_priority_on_conversion=True，所有候选保持原优先级
        2. 否则，按 needs_conversion 和 provider.keep_priority_on_conversion 分组：
           - 保持优先级的候选（exact 或 provider.keep_priority_on_conversion=True）按原优先级排序
           - 需要降级的候选（convertible 且 provider.keep_priority_on_conversion=False）整体排在后面
        3. 在同一组内，按优先级模式排序：
           - provider: 按 Provider.provider_priority -> Key.internal_priority 排序
           - global_key: 按 Key.global_priority_by_format 排序
        """
        if not candidates:
            return candidates

        s = self._scheduler

        # 全局配置：如果开启，所有候选保持原优先级
        global_keep_priority = SystemConfigService.is_keep_priority_on_conversion(db)

        if global_keep_priority:
            # 全局开启：不分组，直接按优先级模式排序
            if s.priority_mode == s.PRIORITY_MODE_GLOBAL_KEY:
                return self._sort_by_global_priority_with_hash(candidates, affinity_key, api_format)
            # 提供商优先模式：保持构建时的顺序（已按 provider_priority 排序）
            return candidates

        # 全局未开启：按是否需要降级分组
        # - 不需要降级：exact 候选 或 provider.keep_priority_on_conversion=True 的 convertible 候选
        # - 需要降级：convertible 且 provider.keep_priority_on_conversion=False
        keep_priority_candidates: list[ProviderCandidate] = []
        demote_candidates: list[ProviderCandidate] = []

        for c in candidates:
            if not c.needs_conversion:
                # exact 候选：不需要降级
                keep_priority_candidates.append(c)
            elif getattr(c.provider, "keep_priority_on_conversion", False):
                # convertible 但提供商配置了保持优先级
                keep_priority_candidates.append(c)
            else:
                # convertible 且未配置保持优先级：降级
                demote_candidates.append(c)

        if s.priority_mode == s.PRIORITY_MODE_GLOBAL_KEY:
            # 全局 Key 优先模式：分别对两组排序后合并
            sorted_keep = self._sort_by_global_priority_with_hash(
                keep_priority_candidates, affinity_key, api_format
            )
            sorted_demote = self._sort_by_global_priority_with_hash(
                demote_candidates, affinity_key, api_format
            )
            return sorted_keep + sorted_demote

        # 提供商优先模式：保持优先级的在前，降级的在后（各组内部顺序已由构建时保证）
        return keep_priority_candidates + demote_candidates

    def _sort_by_global_priority_with_hash(
        self,
        candidates: list[ProviderCandidate],
        affinity_key: str | None = None,
        api_format: str | None = None,
    ) -> list[ProviderCandidate]:
        """
        按 global_priority_by_format 分组排序，同优先级内通过哈希分散实现负载均衡

        排序逻辑：
        1. 按 global_priority_by_format[api_format] 分组（数字小的优先，NULL 排后面）
        2. 同优先级组内，使用 affinity_key 哈希分散
        3. 确保同一用户请求稳定选择同一个 Key（缓存亲和性）
        """

        def get_priority(candidate: ProviderCandidate) -> int:
            """获取候选的优先级"""
            if not candidate.key:
                return 999999
            priority_by_format = candidate.key.global_priority_by_format or {}
            if api_format and api_format in priority_by_format:
                return priority_by_format[api_format]
            return 999999  # NULL 排在后面

        # 按优先级分组
        priority_groups: dict[int, list[ProviderCandidate]] = defaultdict(list)
        for candidate in candidates:
            priority = get_priority(candidate)
            priority_groups[priority].append(candidate)

        result = []
        for priority in sorted(priority_groups.keys()):  # 数字小的优先级高
            group = priority_groups[priority]

            if len(group) > 1 and affinity_key:
                # 同优先级内哈希分散负载均衡
                scored_candidates = []
                for candidate in group:
                    key_id = candidate.key.id if candidate.key else ""
                    hash_value = self._scheduler._affinity_hash(affinity_key, key_id)
                    scored_candidates.append((hash_value, candidate))

                # 按哈希值排序
                sorted_group = [c for _, c in sorted(scored_candidates, key=lambda x: x[0])]
                result.extend(sorted_group)
            else:
                # 单个候选或没有 affinity_key，按次要排序条件排序
                def secondary_sort(c: ProviderCandidate) -> tuple[int, int, str]:
                    pp = c.provider.provider_priority
                    ip = c.key.internal_priority if c.key else None
                    return (
                        pp if pp is not None else 999999,
                        ip if ip is not None else 999999,
                        c.key.id if c.key else "",
                    )

                result.extend(sorted(group, key=secondary_sort))

        return result

    def _apply_load_balance(
        self, candidates: list[ProviderCandidate], api_format: str | None = None
    ) -> list[ProviderCandidate]:
        """
        负载均衡模式：同优先级内随机轮换

        排序逻辑：
        1. 按优先级分组（provider_priority, internal_priority 或 global_priority_by_format）
        2. 同优先级组内随机打乱
        3. 不考虑缓存亲和性
        """
        if not candidates:
            return candidates

        s = self._scheduler
        priority_groups: dict[tuple, list[ProviderCandidate]] = defaultdict(list)

        # 根据优先级模式选择分组方式
        if s.priority_mode == s.PRIORITY_MODE_GLOBAL_KEY:
            # 全局 Key 优先模式：按格式特定优先级分组
            for candidate in candidates:
                priority = 999999
                if candidate.key:
                    priority_by_format = candidate.key.global_priority_by_format or {}
                    if api_format and api_format in priority_by_format:
                        priority = priority_by_format[api_format]
                priority_groups[(priority,)].append(candidate)
        else:
            # 提供商优先模式：按 (provider_priority, internal_priority) 分组
            for candidate in candidates:
                pp = candidate.provider.provider_priority
                ip = candidate.key.internal_priority if candidate.key else None
                key = (
                    pp if pp is not None else 999999,
                    ip if ip is not None else 999999,
                )
                priority_groups[key].append(candidate)

        result: list[ProviderCandidate] = []
        for priority in sorted(priority_groups.keys()):
            group = priority_groups[priority]
            if len(group) > 1:
                # 同优先级内随机打乱
                shuffled = list(group)
                random.shuffle(shuffled)
                result.extend(shuffled)
            else:
                result.extend(group)

        return result

    def _shuffle_keys_by_internal_priority(
        self,
        keys: list[ProviderAPIKey],
        affinity_key: str | None = None,
        use_random: bool = False,
    ) -> list[ProviderAPIKey]:
        """
        对 API Key 按 internal_priority 分组，同优先级内部基于 affinity_key 进行确定性打乱

        目的：
        - 数字越小越优先使用
        - 同优先级 Key 之间实现负载均衡
        - 使用 affinity_key 哈希确保同一请求 Key 的请求稳定（避免破坏缓存亲和性）
        - 当 use_random=True 时，使用随机排序实现轮换（用于 TTL=0 的场景）

        Args:
            keys: API Key 列表
            affinity_key: 亲和性标识符（通常为 API Key ID，用于确定性打乱）
            use_random: 是否使用随机排序（TTL=0 时为 True）

        Returns:
            排序后的 Key 列表
        """
        if not keys:
            return []

        # 按 internal_priority 分组
        priority_groups: dict[int, list[ProviderAPIKey]] = defaultdict(list)

        for key in keys:
            priority = key.internal_priority if key.internal_priority is not None else 999999
            priority_groups[priority].append(key)

        # 对每个优先级组内的 Key 进行打乱
        result = []
        for priority in sorted(priority_groups.keys()):  # 数字小的优先级高，排前面
            group_keys = priority_groups[priority]

            if len(group_keys) > 1:
                if use_random:
                    # TTL=0 模式：使用随机排序实现 Key 轮换
                    shuffled = list(group_keys)
                    random.shuffle(shuffled)
                    result.extend(shuffled)
                elif affinity_key:
                    # 正常模式：使用哈希确定性打乱（保持缓存亲和性）
                    key_scores = []
                    for key in group_keys:
                        hash_value = self._scheduler._affinity_hash(affinity_key, key.id)
                        key_scores.append((hash_value, key))

                    # 按哈希值排序
                    sorted_group = [key for _, key in sorted(key_scores, key=lambda x: x[0])]
                    result.extend(sorted_group)
                else:
                    # 没有 affinity_key 时按 ID 排序保持稳定性
                    result.extend(sorted(group_keys, key=lambda k: k.id))
            else:
                # 单个 Key 直接添加
                result.extend(group_keys)

        return result
