from __future__ import annotations

from typing import Any

from .registry import PresetDimensionBase, register_preset_dimension


class RoundRobinDimension(PresetDimensionBase):
    @property
    def name(self) -> str:
        return "round_robin"

    @property
    def label(self) -> str:
        return "轮询调度"

    @property
    def description(self) -> str:
        return "基于 Redis 原子游标按固定顺序轮转 Key"

    @property
    def mutex_group(self) -> str | None:
        return "distribution_mode"

    @property
    def evidence_hint(self) -> str | None:
        return "依据 Redis 原子自增游标，在稳定顺序上做轮转偏移"

    def compute_metric(
        self,
        *,
        key_id: str,
        all_key_ids: list[str],
        keys_by_id: dict[str, Any],
        lru_scores: dict[str, Any],
        context: dict[str, Any],
        mode: str | None,
    ) -> float:
        del keys_by_id, lru_scores, mode

        total = len(all_key_ids)
        if total <= 1:
            return 0.0

        raw_positions = context.get("round_robin_positions")
        positions = raw_positions if isinstance(raw_positions, dict) else {}
        position_raw = positions.get(key_id)
        if not isinstance(position_raw, int) or position_raw < 0:
            try:
                position = all_key_ids.index(key_id)
            except ValueError:
                return 0.5
        else:
            position = position_raw

        try:
            cursor = int(context.get("round_robin_cursor", 0) or 0)
        except (TypeError, ValueError):
            cursor = 0

        start = cursor % total
        offset = (position - start) % total
        return offset / float(total - 1)


register_preset_dimension(RoundRobinDimension())
