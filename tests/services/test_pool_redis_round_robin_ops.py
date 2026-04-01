from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.services.provider.pool import redis_ops


class _FakeRedis:
    def __init__(self, cursor: int) -> None:
        self.cursor = cursor
        self.keys: list[str] = []

    async def incr(self, key: str) -> int:
        self.keys.append(key)
        return self.cursor


@pytest.mark.asyncio
async def test_next_round_robin_cursor_returns_zero_based_counter() -> None:
    fake_redis = _FakeRedis(cursor=3)
    with patch(
        "src.services.provider.pool.redis_ops._get_redis",
        new_callable=AsyncMock,
        return_value=fake_redis,
    ):
        result = await redis_ops.next_round_robin_cursor("prov-1")

    assert result == 2
    assert fake_redis.keys == ["ap:prov-1:round_robin"]


@pytest.mark.asyncio
async def test_next_round_robin_cursor_gracefully_handles_missing_redis() -> None:
    with patch(
        "src.services.provider.pool.redis_ops._get_redis",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await redis_ops.next_round_robin_cursor("prov-1")

    assert result == 0
