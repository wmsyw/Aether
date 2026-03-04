from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from src.models.database import ProviderAPIKey
from src.services.scheduling.candidate_sorter import CandidateSorter
from src.services.scheduling.scheduling_config import SchedulingConfig
from src.services.scheduling.utils import affinity_hash


def _make_key(key_id: str, internal_priority: int = 1) -> ProviderAPIKey:
    return cast(
        ProviderAPIKey,
        SimpleNamespace(
            id=key_id,
            internal_priority=internal_priority,
        ),
    )


def _reverse_in_place(items: list[object]) -> None:
    items.reverse()


def test_shuffle_keys_random_in_load_balance_mode_even_with_affinity_key() -> None:
    config = SchedulingConfig(
        priority_mode=SchedulingConfig.PRIORITY_MODE_PROVIDER,
        scheduling_mode=SchedulingConfig.SCHEDULING_MODE_LOAD_BALANCE,
    )
    sorter = CandidateSorter(config)

    keys = [_make_key("k1"), _make_key("k2"), _make_key("k3")]

    with patch(
        "src.services.scheduling.candidate_sorter.random.shuffle",
        side_effect=_reverse_in_place,
    ) as shuffle_mock:
        result = sorter.shuffle_keys_by_internal_priority(
            keys,
            affinity_key="affinity-1",
            use_random=False,
        )

    assert [k.id for k in result] == ["k3", "k2", "k1"]
    assert shuffle_mock.call_count == 1


def test_shuffle_keys_random_when_affinity_key_absent() -> None:
    config = SchedulingConfig(
        priority_mode=SchedulingConfig.PRIORITY_MODE_PROVIDER,
        scheduling_mode=SchedulingConfig.SCHEDULING_MODE_CACHE_AFFINITY,
    )
    sorter = CandidateSorter(config)

    keys = [_make_key("k1"), _make_key("k2"), _make_key("k3")]

    with patch(
        "src.services.scheduling.candidate_sorter.random.shuffle",
        side_effect=_reverse_in_place,
    ) as shuffle_mock:
        result = sorter.shuffle_keys_by_internal_priority(
            keys,
            affinity_key=None,
            use_random=False,
        )

    assert [k.id for k in result] == ["k3", "k2", "k1"]
    assert shuffle_mock.call_count == 1


def test_shuffle_keys_still_hashes_with_affinity_in_non_load_balance_mode() -> None:
    config = SchedulingConfig(
        priority_mode=SchedulingConfig.PRIORITY_MODE_PROVIDER,
        scheduling_mode=SchedulingConfig.SCHEDULING_MODE_CACHE_AFFINITY,
    )
    sorter = CandidateSorter(config)

    keys = [_make_key("k1"), _make_key("k2"), _make_key("k3")]
    affinity_key = "affinity-1"

    expected = sorted(keys, key=lambda k: affinity_hash(affinity_key, k.id))

    with patch("src.services.scheduling.candidate_sorter.random.shuffle") as shuffle_mock:
        result = sorter.shuffle_keys_by_internal_priority(
            keys,
            affinity_key=affinity_key,
            use_random=False,
        )

    assert [k.id for k in result] == [k.id for k in expected]
    shuffle_mock.assert_not_called()
