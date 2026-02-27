from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.database import Provider, ProviderAPIKey, ProviderEndpoint
from src.services.orchestration.candidate_resolver import CandidateResolver
from src.services.scheduling.aware_scheduler import CacheAwareScheduler, ProviderCandidate


class _FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[int] = []
        self.scheduling_mode = CacheAwareScheduler.SCHEDULING_MODE_FIXED_ORDER
        self.priority_mode = CacheAwareScheduler.PRIORITY_MODE_PROVIDER

    async def list_all_candidates(
        self,
        *,
        db: Any,
        api_format: str,
        model_name: str,
        affinity_key: str | None = None,
        user_api_key: Any | None = None,
        provider_offset: int = 0,
        provider_limit: int | None = None,
        max_candidates: int | None = None,
        is_stream: bool = False,
        capability_requirements: dict[str, bool] | None = None,
        request_body: dict | None = None,
    ) -> tuple[list[Any], str, int]:
        _ = (
            db,
            api_format,
            model_name,
            affinity_key,
            user_api_key,
            max_candidates,
            is_stream,
            capability_requirements,
        )
        assert provider_limit is not None

        self.calls.append(int(provider_offset))

        if provider_offset == 0:
            # Simulate a provider page that has providers but no eligible candidates.
            return [], "gm1", int(provider_limit)

        if provider_offset == int(provider_limit):
            # Next page yields one eligible candidate and is also the last provider page.
            cand = SimpleNamespace(
                provider=SimpleNamespace(id="p1", name="prov"),
                endpoint=SimpleNamespace(id="e1"),
                key=SimpleNamespace(id="k1"),
                is_skipped=False,
                skip_reason=None,
                is_cached=False,
                needs_conversion=False,
                provider_api_format=str(api_format),
                mapping_matched_model=None,
            )
            return [cand], "gm1", 5

        return [], "gm1", 0

    async def reorder_candidates(
        self,
        candidates: list[Any],
        db: Any = None,
        affinity_key: str | None = None,
        api_format: str | None = None,
        global_model_id: str | None = None,
    ) -> list[Any]:
        return candidates


def _make_global_key_candidate(*, key_id: str, priority: int) -> ProviderCandidate:
    provider = SimpleNamespace(
        id=f"p_{key_id}",
        name=f"prov_{key_id}",
        provider_priority=1,
    )
    endpoint = SimpleNamespace(id=f"e_{key_id}")
    key = SimpleNamespace(
        id=key_id,
        internal_priority=1,
        global_priority_by_format={"openai:chat": priority},
    )
    return ProviderCandidate(
        provider=cast(Provider, provider),
        endpoint=cast(ProviderEndpoint, endpoint),
        key=cast(ProviderAPIKey, key),
        needs_conversion=False,
        provider_api_format="openai:chat",
    )


@pytest.mark.asyncio
async def test_candidate_resolver_pagination_continues_on_empty_candidate_batch() -> None:
    db = MagicMock()
    scheduler = _FakeScheduler()
    resolver = CandidateResolver(db=db, cache_scheduler=cast(CacheAwareScheduler, scheduler))

    candidates, global_model_id = await resolver.fetch_candidates(
        api_format="openai:chat",
        model_name="gpt-4o",
        affinity_key="a1",
        user_api_key=None,
        request_id="r1",
        is_stream=False,
        capability_requirements=None,
    )

    assert global_model_id == "gm1"
    assert len(candidates) == 1
    assert scheduler.calls == [0, 20]


@pytest.mark.asyncio
async def test_candidate_resolver_applies_global_reorder_after_pagination() -> None:
    db = MagicMock()

    scheduler = CacheAwareScheduler()
    scheduler.scheduling_mode = CacheAwareScheduler.SCHEDULING_MODE_FIXED_ORDER
    scheduler.priority_mode = CacheAwareScheduler.PRIORITY_MODE_GLOBAL_KEY

    c10 = _make_global_key_candidate(key_id="k10", priority=10)
    c1 = _make_global_key_candidate(key_id="k1", priority=1)

    async def _list_all_candidates(**kwargs: Any) -> tuple[list[Any], str, int]:
        provider_offset = int(kwargs.get("provider_offset", 0))
        provider_limit = kwargs.get("provider_limit")
        assert provider_limit is not None

        if provider_offset == 0:
            # First provider page returns a worse candidate first.
            return [c10], "gm1", int(provider_limit)

        if provider_offset == int(provider_limit):
            # Second page returns a better candidate and is also the last provider page.
            return [c1], "gm1", 5

        return [], "gm1", 0

    scheduler.list_all_candidates = AsyncMock(side_effect=_list_all_candidates)  # type: ignore[method-assign]

    resolver = CandidateResolver(db=db, cache_scheduler=scheduler)

    candidates, global_model_id = await resolver.fetch_candidates(
        api_format="openai:chat",
        model_name="gpt-4o",
        affinity_key="a1",
        user_api_key=None,
        request_id="r1",
        is_stream=False,
        capability_requirements=None,
    )

    assert global_model_id == "gm1"
    assert [c.key.id for c in candidates] == ["k1", "k10"]
