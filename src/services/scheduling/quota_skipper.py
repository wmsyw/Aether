from __future__ import annotations

from src.core.provider_types import ProviderType, normalize_provider_type
from src.models.database import ProviderAPIKey


def _pct_is_exhausted(value: object) -> bool:
    """Return True when used_percent indicates 0% remaining."""
    try:
        pct = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    # Some upstreams may return values slightly above 100 due to rounding.
    return pct >= 100.0 - 1e-6


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def is_key_quota_exhausted(
    provider_type: str | None,
    key: ProviderAPIKey,
    *,
    model_name: str,
) -> tuple[bool, str | None]:
    """Check ProviderAPIKey.upstream_metadata quota and decide whether to skip.

    Requirements:
    - Kiro: account-level quota. When remaining == 0, skip this key; allow again when remaining > 0.
    - Codex: only consider weekly quota + 5H quota.
             If either remaining is 0%, skip this key.
    - Antigravity: quota is per-model; do not disable the account.
                   When the requested model's quota is 0%, skip this key.
    """

    pt = normalize_provider_type(provider_type)

    upstream = getattr(key, "upstream_metadata", None) or {}
    if not isinstance(upstream, dict):
        return False, None

    if pt == ProviderType.KIRO:
        kiro_meta = upstream.get("kiro")
        if not isinstance(kiro_meta, dict):
            return False, None

        remaining = _float_or_none(kiro_meta.get("remaining"))

        if remaining is not None and remaining <= 0.0:
            return True, "Kiro 账号配额剩余 0"

        return False, None

    if pt == ProviderType.CODEX:
        codex_meta = upstream.get("codex")
        if not isinstance(codex_meta, dict):
            return False, None

        weekly_used = codex_meta.get("primary_used_percent")
        five_hour_used = codex_meta.get("secondary_used_percent")

        exhausted_parts: list[str] = []
        if _pct_is_exhausted(weekly_used):
            exhausted_parts.append("周限额剩余 0%")
        if _pct_is_exhausted(five_hour_used):
            exhausted_parts.append("5H 限额剩余 0%")

        if exhausted_parts:
            return True, "Codex " + "，".join(exhausted_parts)

        return False, None

    if pt == ProviderType.ANTIGRAVITY:
        ag_meta = upstream.get("antigravity")
        if not isinstance(ag_meta, dict):
            return False, None

        quota_by_model = ag_meta.get("quota_by_model")
        if not isinstance(quota_by_model, dict):
            return False, None

        model_quota = quota_by_model.get(model_name)
        if not isinstance(model_quota, dict):
            return False, None

        remaining_fraction = _float_or_none(model_quota.get("remaining_fraction"))
        if remaining_fraction is not None and remaining_fraction <= 0.0:
            return True, f"Antigravity 模型 {model_name} 配额剩余 0%"
        if _pct_is_exhausted(model_quota.get("used_percent")):
            return True, f"Antigravity 模型 {model_name} 配额剩余 0%"

        return False, None

    return False, None
