"""
Layer 3: Cross-format roundtrip tests.

Verifies that converting A -> internal -> B -> internal preserves
semantic equivalence across all format pairs.
"""

from __future__ import annotations

import itertools

import pytest

from src.core.api_format.conversion.registry import (
    format_conversion_registry,
    register_default_normalizers,
)

from .fixtures.assertions import assert_internal_request_matches, assert_internal_response_matches
from .fixtures.format_fixtures import ALL_FORMATS, FORMAT_FIXTURES, get_format_fixture
from .fixtures.golden_internal import ALL_FIXTURE_IDS, ALL_GOLDEN_FIXTURES, is_cross_format_limited


@pytest.fixture(autouse=True, scope="module")
def _ensure_normalizers_registered() -> None:
    register_default_normalizers()


def _cross_format_combos() -> list[tuple[str, str, str]]:
    """Generate (source, target, fixture_id) where fixture exists for source."""
    combos = []
    for source, target in itertools.permutations(ALL_FORMATS, 2):
        for fid in ALL_FIXTURE_IDS:
            if fid in FORMAT_FIXTURES.get(source, {}):
                combos.append((source, target, fid))
    return combos


_COMBOS = _cross_format_combos()


def _combo_id(combo: tuple[str, str, str]) -> str:
    return f"{combo[0]}->{combo[1]}:{combo[2]}"


class TestCrossFormatRequest:
    """source.request -> internal -> target.request -> internal: matches golden."""

    @pytest.mark.parametrize("source,target,fixture_id", _COMBOS, ids=_combo_id)
    def test_cross_format_request(self, source: str, target: str, fixture_id: str) -> None:
        limitation = is_cross_format_limited(source, target, fixture_id, "cross_request")
        if limitation:
            pytest.skip(limitation)

        src_norm = format_conversion_registry.get_normalizer(source)
        tgt_norm = format_conversion_registry.get_normalizer(target)
        assert src_norm is not None and tgt_norm is not None

        fixture = get_format_fixture(source, fixture_id)
        golden = ALL_GOLDEN_FIXTURES[fixture_id]

        # source -> internal
        internal = src_norm.request_to_internal(fixture.request)

        # internal -> target native
        target_native = tgt_norm.request_from_internal(internal)

        # target native -> internal (should still match golden)
        internal2 = tgt_norm.request_to_internal(target_native)

        assert_internal_request_matches(internal2, golden.internal_request, golden.required_fields)


class TestCrossFormatResponse:
    """source.response -> internal -> target.response -> internal: matches golden."""

    @pytest.mark.parametrize("source,target,fixture_id", _COMBOS, ids=_combo_id)
    def test_cross_format_response(self, source: str, target: str, fixture_id: str) -> None:
        limitation = is_cross_format_limited(source, target, fixture_id, "cross_response")
        if limitation:
            pytest.skip(limitation)

        src_norm = format_conversion_registry.get_normalizer(source)
        tgt_norm = format_conversion_registry.get_normalizer(target)
        assert src_norm is not None and tgt_norm is not None

        fixture = get_format_fixture(source, fixture_id)
        golden = ALL_GOLDEN_FIXTURES[fixture_id]

        # source -> internal
        internal = src_norm.response_to_internal(fixture.response)

        # internal -> target native
        target_native = tgt_norm.response_from_internal(internal)

        # target native -> internal
        internal2 = tgt_norm.response_to_internal(target_native)

        assert_internal_response_matches(
            internal2, golden.internal_response, golden.required_fields
        )
