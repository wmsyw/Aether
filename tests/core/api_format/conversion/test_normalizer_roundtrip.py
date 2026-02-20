"""
Layer 2: Normalizer roundtrip tests.

Verifies that converting A -> internal -> A preserves semantic equivalence.
"""

from __future__ import annotations

import copy

import pytest

from src.core.api_format.conversion.registry import (
    format_conversion_registry,
    register_default_normalizers,
)

from .fixtures.assertions import assert_internal_requests_equivalent
from .fixtures.format_fixtures import ALL_FORMATS, FORMAT_FIXTURES, get_format_fixture
from .fixtures.golden_internal import ALL_FIXTURE_IDS, KNOWN_LIMITATIONS


@pytest.fixture(autouse=True, scope="module")
def _ensure_normalizers_registered() -> None:
    register_default_normalizers()


def _available_combos() -> list[tuple[str, str]]:
    combos = []
    for fmt in ALL_FORMATS:
        for fid in ALL_FIXTURE_IDS:
            if fid in FORMAT_FIXTURES.get(fmt, {}):
                combos.append((fmt, fid))
    return combos


_COMBOS = _available_combos()


class TestRequestRoundtrip:
    """A.request -> internal -> A.request -> internal: two internals should match."""

    @pytest.mark.parametrize("format_id,fixture_id", _COMBOS)
    def test_request_roundtrip(self, format_id: str, fixture_id: str) -> None:
        limitation = KNOWN_LIMITATIONS.get((format_id, fixture_id, "roundtrip"))
        if limitation:
            pytest.skip(limitation)

        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None

        fixture = get_format_fixture(format_id, fixture_id)

        # First pass: native -> internal
        internal1 = normalizer.request_to_internal(fixture.request)

        # Reconstruct: internal -> native
        # Deep copy because some normalizers mutate the input (e.g. _coerce_claude_message_sequence)
        reconstructed = normalizer.request_from_internal(copy.deepcopy(internal1))

        # Second pass: native -> internal
        internal2 = normalizer.request_to_internal(reconstructed)

        # The two internal representations should be semantically equivalent
        assert_internal_requests_equivalent(internal1, internal2, lossy_fields=fixture.lossy_fields)


class TestResponseRoundtrip:
    """A.response -> internal -> A.response -> internal: two internals should match."""

    @pytest.mark.parametrize("format_id,fixture_id", _COMBOS)
    def test_response_roundtrip(self, format_id: str, fixture_id: str) -> None:
        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None

        fixture = get_format_fixture(format_id, fixture_id)

        # First pass
        internal1 = normalizer.response_to_internal(fixture.response)

        # Reconstruct
        reconstructed = normalizer.response_from_internal(internal1)

        # Second pass
        internal2 = normalizer.response_to_internal(reconstructed)

        # Compare content blocks (the core semantic payload)
        from .fixtures.assertions import assert_content_blocks_match

        assert_content_blocks_match(
            internal1.content, internal2.content, context="response roundtrip"
        )
        # Stop reason should be preserved
        assert (
            internal1.stop_reason == internal2.stop_reason
        ), f"stop_reason changed after roundtrip: {internal1.stop_reason} -> {internal2.stop_reason}"
