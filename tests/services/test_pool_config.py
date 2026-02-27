"""Tests for pool_config.py — configuration parsing and defaults."""

from __future__ import annotations

from src.services.provider.pool.config import (
    PoolConfig,
    UnschedulableRule,
    parse_pool_config,
)


def test_parse_pool_config_returns_none_when_no_advanced_section() -> None:
    assert parse_pool_config({}) is None
    assert parse_pool_config(None) is None
    assert parse_pool_config({"other_key": 1}) is None


def test_parse_pool_config_returns_defaults_for_empty_advanced() -> None:
    cfg = parse_pool_config({"pool_advanced": {}})
    assert cfg is not None
    assert cfg.sticky_session_ttl_seconds == 3600
    assert cfg.load_threshold_percent == 80
    assert cfg.lru_enabled is True
    assert cfg.cost_window_seconds == 18000
    assert cfg.cost_limit_per_key_tokens is None
    assert cfg.cost_soft_threshold_percent == 80
    assert cfg.rate_limit_cooldown_seconds == 300
    assert cfg.overload_cooldown_seconds == 30
    assert cfg.proactive_refresh_seconds == 180
    assert cfg.health_policy_enabled is True
    assert cfg.unschedulable_rules == []


def test_parse_pool_config_overrides_values() -> None:
    cfg = parse_pool_config(
        {
            "pool_advanced": {
                "sticky_session_ttl_seconds": 7200,
                "load_threshold_percent": 90,
                "lru_enabled": False,
                "cost_window_seconds": 36000,
                "cost_limit_per_key_tokens": 100000,
                "cost_soft_threshold_percent": 70,
                "rate_limit_cooldown_seconds": 600,
                "overload_cooldown_seconds": 60,
                "proactive_refresh_seconds": 300,
                "health_policy_enabled": False,
            }
        }
    )
    assert cfg is not None
    assert cfg.sticky_session_ttl_seconds == 7200
    assert cfg.load_threshold_percent == 90
    assert cfg.lru_enabled is False
    assert cfg.cost_window_seconds == 36000
    assert cfg.cost_limit_per_key_tokens == 100000
    assert cfg.cost_soft_threshold_percent == 70
    assert cfg.rate_limit_cooldown_seconds == 600
    assert cfg.overload_cooldown_seconds == 60
    assert cfg.proactive_refresh_seconds == 300
    assert cfg.health_policy_enabled is False


def test_parse_pool_config_parses_unschedulable_rules() -> None:
    cfg = parse_pool_config(
        {
            "pool_advanced": {
                "unschedulable_rules": [
                    {"keyword": "rate_limit", "duration_minutes": 10},
                    {"keyword": "overloaded"},
                    {"invalid": "entry"},  # should be skipped
                    "not_a_dict",  # should be skipped
                ]
            }
        }
    )
    assert cfg is not None
    assert len(cfg.unschedulable_rules) == 2
    assert cfg.unschedulable_rules[0] == UnschedulableRule(
        keyword="rate_limit", duration_minutes=10
    )
    assert cfg.unschedulable_rules[1] == UnschedulableRule(keyword="overloaded", duration_minutes=5)


def test_parse_pool_config_handles_invalid_types_gracefully() -> None:
    # Invalid int values should fall back to defaults
    cfg = parse_pool_config(
        {
            "pool_advanced": {
                "sticky_session_ttl_seconds": "not_a_number",
                "cost_limit_per_key_tokens": "bad",
            }
        }
    )
    assert cfg is not None
    assert cfg.sticky_session_ttl_seconds == 3600  # default
    assert cfg.cost_limit_per_key_tokens is None  # default for opt_int


def test_pool_config_is_frozen() -> None:
    cfg = PoolConfig()
    try:
        cfg.sticky_session_ttl_seconds = 999  # type: ignore[misc]
        assert False, "Should have raised FrozenInstanceError"
    except AttributeError:
        pass
