"""Account Pool health policy: error code classification and key state management.

Maps upstream HTTP status codes to pool-level actions:

| Code | Action                                                       |
|------|--------------------------------------------------------------|
| 401  | Invalidate OAuth token cache -> attempt refresh -> disable   |
| 402  | Auto-disable key (payment issue)                             |
| 403  | Auto-disable key (suspended/banned)                          |
| 400  | Check body for "organization has been disabled" -> disable   |
| 429  | Set cooldown (retry-after header or config default)          |
| 529  | Set cooldown (config default)                                |
| *    | Check unschedulable_rules keyword matching                   |
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.core.logger import logger
from src.services.provider.pool import redis_ops

if TYPE_CHECKING:
    from src.services.provider.pool.config import PoolConfig

# Patterns in 400 error body that indicate account-level issues.
_ACCOUNT_DISABLE_PATTERNS = (
    "organization has been disabled",
    "organization_disabled",
    "account has been disabled",
    "account_disabled",
)


def _parse_retry_after(headers: dict[str, str] | None) -> int | None:
    """Extract retry-after seconds from response headers."""
    if not headers:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    try:
        val = int(raw)
        return max(1, min(val, 3600))
    except (ValueError, TypeError):
        return None


def _extract_error_message(error_body: str | None) -> str:
    """Best-effort extraction of error message from JSON body."""
    if not error_body:
        return ""
    try:
        data = json.loads(error_body)
        if isinstance(data, dict):
            error_obj = data.get("error")
            if isinstance(error_obj, dict):
                return str(error_obj.get("message", ""))
            if isinstance(error_obj, str):
                return error_obj
            return str(data.get("message", ""))
    except (json.JSONDecodeError, TypeError):
        pass
    return error_body[:500]


async def apply_health_policy(
    *,
    provider_id: str,
    key_id: str,
    status_code: int,
    error_body: str | None,
    response_headers: dict[str, str] | None,
    config: PoolConfig,
) -> None:
    """Apply health policy for an upstream error.

    This is fire-and-forget; exceptions are caught and logged.
    """
    if not config.health_policy_enabled:
        return

    try:
        await _apply(
            provider_id=provider_id,
            key_id=key_id,
            status_code=status_code,
            error_body=error_body,
            response_headers=response_headers,
            config=config,
        )
    except Exception as exc:
        logger.warning(
            "Pool health policy failed for key {}: {}",
            key_id[:8],
            str(exc),
        )


async def _apply(
    *,
    provider_id: str,
    key_id: str,
    status_code: int,
    error_body: str | None,
    response_headers: dict[str, str] | None,
    config: PoolConfig,
) -> None:
    error_msg = _extract_error_message(error_body)

    # --- 401 Unauthorized ---------------------------------------------------
    if status_code == 401:
        await redis_ops.invalidate_oauth_token_cache(key_id)
        # Set a short cooldown to avoid hammering while refresh happens.
        await redis_ops.set_cooldown(provider_id, key_id, "auth_failed_401", ttl=60)
        logger.info(
            "Pool[{}]: key {} got 401, token cache invalidated + 60s cooldown",
            provider_id[:8],
            key_id[:8],
        )
        return

    # --- 402 Payment Required ------------------------------------------------
    if status_code == 402:
        await redis_ops.set_cooldown(provider_id, key_id, "payment_required_402", ttl=3600)
        logger.warning(
            "Pool[{}]: key {} got 402 (payment required), cooldown 1h",
            provider_id[:8],
            key_id[:8],
        )
        return

    # --- 403 Forbidden -------------------------------------------------------
    if status_code == 403:
        await redis_ops.set_cooldown(provider_id, key_id, "forbidden_403", ttl=3600)
        logger.warning(
            "Pool[{}]: key {} got 403 (forbidden/suspended), cooldown 1h",
            provider_id[:8],
            key_id[:8],
        )
        return

    # --- 400 with account-disable pattern ------------------------------------
    if status_code == 400:
        error_lower = error_msg.lower()
        for pattern in _ACCOUNT_DISABLE_PATTERNS:
            if pattern in error_lower:
                await redis_ops.set_cooldown(
                    provider_id, key_id, f"account_disabled_400:{pattern}", ttl=3600
                )
                logger.warning(
                    "Pool[{}]: key {} got 400 with '{}', cooldown 1h",
                    provider_id[:8],
                    key_id[:8],
                    pattern,
                )
                return

    # --- 429 Rate Limited ----------------------------------------------------
    if status_code == 429:
        retry_after = _parse_retry_after(response_headers)
        ttl = retry_after or config.rate_limit_cooldown_seconds
        await redis_ops.set_cooldown(provider_id, key_id, "rate_limited_429", ttl=ttl)
        logger.info(
            "Pool[{}]: key {} got 429, cooldown {}s",
            provider_id[:8],
            key_id[:8],
            ttl,
        )
        return

    # --- 529 Overloaded ------------------------------------------------------
    if status_code == 529:
        ttl = config.overload_cooldown_seconds
        await redis_ops.set_cooldown(provider_id, key_id, "overloaded_529", ttl=ttl)
        logger.info(
            "Pool[{}]: key {} got 529, cooldown {}s",
            provider_id[:8],
            key_id[:8],
            ttl,
        )
        return

    # --- Keyword-based unschedulable rules -----------------------------------
    if config.unschedulable_rules and error_msg:
        error_lower = error_msg.lower()
        for rule in config.unschedulable_rules:
            if rule.keyword.lower() in error_lower:
                ttl = max(60, rule.duration_minutes * 60)
                await redis_ops.set_cooldown(
                    provider_id,
                    key_id,
                    f"rule:{rule.keyword}",
                    ttl=ttl,
                )
                logger.info(
                    "Pool[{}]: key {} matched rule '{}', cooldown {}m",
                    provider_id[:8],
                    key_id[:8],
                    rule.keyword,
                    rule.duration_minutes,
                )
                return


async def apply_stream_timeout_policy(
    *,
    provider_id: str,
    key_id: str,
    config: PoolConfig,
) -> None:
    """Record a stream timeout event and apply cooldown if threshold is reached.

    Called when an upstream stream response times out (no data within the
    configured interval). Increments a per-key counter in Redis and sets
    a cooldown if the count reaches the configured threshold.
    """
    if not config.health_policy_enabled:
        return

    try:
        count = await redis_ops.incr_stream_timeout_count(
            provider_id,
            key_id,
            config.stream_timeout_window_seconds,
        )
        if count >= config.stream_timeout_threshold:
            ttl = config.stream_timeout_cooldown_seconds
            await redis_ops.set_cooldown(
                provider_id,
                key_id,
                f"stream_timeout_x{count}",
                ttl=ttl,
            )
            logger.warning(
                "Pool[{}]: key {} stream timeout count {} >= threshold {}, cooldown {}s",
                provider_id[:8],
                key_id[:8],
                count,
                config.stream_timeout_threshold,
                ttl,
            )
        else:
            logger.info(
                "Pool[{}]: key {} stream timeout count {}/{}",
                provider_id[:8],
                key_id[:8],
                count,
                config.stream_timeout_threshold,
            )
    except Exception as exc:
        logger.warning(
            "Pool stream timeout policy failed for key {}: {}",
            key_id[:8],
            str(exc),
        )
