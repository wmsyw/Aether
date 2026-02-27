"""Tests for pool_cost_tracker.py — rolling window cost tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.services.provider.pool.config import PoolConfig
from src.services.provider.pool.cost_tracker import (
    get_window_usage,
    is_approaching_limit,
    is_at_limit,
    record_usage,
)

PID = "provider-test"
KID = "key-test"


@pytest.fixture()
def config() -> PoolConfig:
    return PoolConfig(
        cost_limit_per_key_tokens=10000,
        cost_soft_threshold_percent=80,
        cost_window_seconds=18000,
    )


@pytest.fixture()
def config_no_limit() -> PoolConfig:
    return PoolConfig(cost_limit_per_key_tokens=None)


# ---------------------------------------------------------------------------
# record_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_usage_calls_redis(config: PoolConfig) -> None:
    with patch(
        "src.services.provider.pool.redis_ops.add_cost_entry",
        new_callable=AsyncMock,
    ) as mock_add:
        await record_usage(PID, KID, 500, config)

    mock_add.assert_called_once_with(PID, KID, 500, 18000)


@pytest.mark.asyncio
async def test_record_usage_skips_zero_tokens(config: PoolConfig) -> None:
    with patch(
        "src.services.provider.pool.redis_ops.add_cost_entry",
        new_callable=AsyncMock,
    ) as mock_add:
        await record_usage(PID, KID, 0, config)

    mock_add.assert_not_called()


@pytest.mark.asyncio
async def test_record_usage_skips_when_no_limit(config_no_limit: PoolConfig) -> None:
    with patch(
        "src.services.provider.pool.redis_ops.add_cost_entry",
        new_callable=AsyncMock,
    ) as mock_add:
        await record_usage(PID, KID, 500, config_no_limit)

    mock_add.assert_not_called()


# ---------------------------------------------------------------------------
# is_at_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_at_limit_true(config: PoolConfig) -> None:
    with patch(
        "src.services.provider.pool.redis_ops.get_cost_window_total",
        new_callable=AsyncMock,
        return_value=10000,
    ):
        assert await is_at_limit(PID, KID, config) is True


@pytest.mark.asyncio
async def test_is_at_limit_false(config: PoolConfig) -> None:
    with patch(
        "src.services.provider.pool.redis_ops.get_cost_window_total",
        new_callable=AsyncMock,
        return_value=5000,
    ):
        assert await is_at_limit(PID, KID, config) is False


@pytest.mark.asyncio
async def test_is_at_limit_always_false_when_no_limit(config_no_limit: PoolConfig) -> None:
    assert await is_at_limit(PID, KID, config_no_limit) is False


# ---------------------------------------------------------------------------
# is_approaching_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_approaching_limit_true(config: PoolConfig) -> None:
    # 80% of 10000 = 8000
    with patch(
        "src.services.provider.pool.redis_ops.get_cost_window_total",
        new_callable=AsyncMock,
        return_value=8500,
    ):
        assert await is_approaching_limit(PID, KID, config) is True


@pytest.mark.asyncio
async def test_is_approaching_limit_false(config: PoolConfig) -> None:
    with patch(
        "src.services.provider.pool.redis_ops.get_cost_window_total",
        new_callable=AsyncMock,
        return_value=5000,
    ):
        assert await is_approaching_limit(PID, KID, config) is False


# ---------------------------------------------------------------------------
# get_window_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_window_usage(config: PoolConfig) -> None:
    with patch(
        "src.services.provider.pool.redis_ops.get_cost_window_total",
        new_callable=AsyncMock,
        return_value=4200,
    ):
        assert await get_window_usage(PID, KID, config) == 4200
