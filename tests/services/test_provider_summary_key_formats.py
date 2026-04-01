from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

from src.api.admin.providers.summary import _compose_provider_summary


def test_compose_provider_summary_matches_uppercase_key_formats() -> None:
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    provider = SimpleNamespace(
        id="provider-1",
        name="Provider-1",
        provider_type="custom",
        description=None,
        website=None,
        provider_priority=1,
        keep_priority_on_conversion=False,
        enable_format_conversion=False,
        is_active=True,
        billing_type=None,
        monthly_quota_usd=None,
        monthly_used_usd=None,
        quota_reset_day=30,
        quota_last_reset_at=None,
        quota_expires_at=None,
        max_retries=2,
        proxy=None,
        stream_first_byte_timeout=None,
        request_timeout=None,
        config={},
        created_at=now,
        updated_at=now,
    )
    endpoint = SimpleNamespace(
        id="endpoint-1",
        provider_id="provider-1",
        api_format="openai:chat",
        is_active=True,
    )
    key = SimpleNamespace(
        id="key-1",
        provider_id="provider-1",
        is_active=True,
        api_formats=["OPENAI:CHAT"],
        health_by_format={},
    )

    summary = _compose_provider_summary(
        provider=cast(Any, provider),
        endpoints=cast(Any, [endpoint]),
        all_keys=cast(Any, [key]),
        total_keys=1,
        active_keys=1,
        total_models=0,
        active_models=0,
        global_model_ids=[],
    )

    assert summary.active_endpoints == 1
    assert summary.endpoint_health_details[0]["active_keys"] == 1
    assert summary.endpoint_health_details[0]["total_keys"] == 1
