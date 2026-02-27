"""Tests for pool scheduling strategy registry."""

from __future__ import annotations

from src.services.provider.pool.strategy import (
    _strategy_registry,
    get_active_strategies,
    get_pool_strategy,
    register_pool_strategy,
)


class _DummyStrategy:
    name = "dummy"

    def compute_score(self, *, key_id, config, context):
        return 42.0


class _AnotherStrategy:
    name = "another"

    def on_before_select(self, *, provider_id, key_ids, config, context):
        return key_ids[:1]


def setup_function():
    _strategy_registry.clear()


def teardown_function():
    _strategy_registry.clear()


def test_register_and_get() -> None:
    s = _DummyStrategy()
    register_pool_strategy("dummy", s)
    assert get_pool_strategy("dummy") is s


def test_get_nonexistent() -> None:
    assert get_pool_strategy("nonexistent") is None


def test_get_active_strategies_filters_by_name() -> None:
    s1 = _DummyStrategy()
    s2 = _AnotherStrategy()
    register_pool_strategy("dummy", s1)
    register_pool_strategy("another", s2)

    active = get_active_strategies(["dummy"])
    assert len(active) == 1
    assert active[0] is s1

    active_both = get_active_strategies(["dummy", "another"])
    assert len(active_both) == 2

    active_none = get_active_strategies(["missing"])
    assert len(active_none) == 0


def test_get_active_strategies_empty_names() -> None:
    register_pool_strategy("dummy", _DummyStrategy())
    assert get_active_strategies([]) == []
    assert get_active_strategies(()) == []
