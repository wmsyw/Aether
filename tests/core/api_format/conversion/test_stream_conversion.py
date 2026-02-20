"""
Layer 4: Stream conversion tests.

Verifies that each normalizer correctly converts format-specific stream
chunks to/from internal stream events.
"""

from __future__ import annotations

import pytest

from src.core.api_format.conversion.registry import (
    format_conversion_registry,
    register_default_normalizers,
)
from src.core.api_format.conversion.stream_state import StreamState

from .fixtures.assertions import (
    assert_stream_has_tool_call,
    assert_stream_stop_reason_matches,
    assert_stream_text_matches,
)
from .fixtures.schema_validators import get_stream_chunk_validator
from .fixtures.stream_fixtures import (
    STREAM_ALL_FORMATS,
    STREAM_FIXTURE_IDS,
    STREAM_FIXTURES,
)


@pytest.fixture(autouse=True, scope="module")
def _ensure_normalizers_registered() -> None:
    register_default_normalizers()


def _stream_combos() -> list[tuple[str, str]]:
    combos = []
    for fmt in STREAM_ALL_FORMATS:
        for fid in STREAM_FIXTURE_IDS:
            if fid in STREAM_FIXTURES.get(fmt, {}):
                combos.append((fmt, fid))
    return combos


_COMBOS = _stream_combos()


class TestStreamToInternal:
    """Verify format-specific stream chunks -> InternalStreamEvent sequence."""

    @pytest.mark.parametrize("format_id,fixture_id", _COMBOS)
    def test_stream_to_internal(self, format_id: str, fixture_id: str) -> None:
        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None

        fixture = STREAM_FIXTURES[format_id][fixture_id]
        state = StreamState(model=fixture.chunks[0].get("model", ""))

        all_events = []
        for chunk in fixture.chunks:
            events = normalizer.stream_chunk_to_internal(chunk, state)
            all_events.extend(events)

        assert_stream_text_matches(all_events, fixture.expected_text)
        assert_stream_stop_reason_matches(all_events, fixture.expected_stop_reason)

        if fixture_id == "stream_tool_call":
            assert_stream_has_tool_call(all_events, "get_weather")


class TestStreamFromInternalSchema:
    """Verify internal events -> format-specific chunks conform to API schema."""

    @pytest.mark.parametrize("format_id,fixture_id", _COMBOS)
    def test_stream_roundtrip_schema(self, format_id: str, fixture_id: str) -> None:
        """Parse chunks -> internal events -> reconstruct chunks, validate schema."""
        validator = get_stream_chunk_validator(format_id)
        if validator is None:
            pytest.skip(f"No stream chunk schema validator for {format_id}")

        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None

        fixture = STREAM_FIXTURES[format_id][fixture_id]

        # Phase 1: chunks -> internal events
        in_state = StreamState(model=fixture.chunks[0].get("model", ""))
        all_events = []
        for chunk in fixture.chunks:
            events = normalizer.stream_chunk_to_internal(chunk, in_state)
            all_events.extend(events)

        # Phase 2: internal events -> output chunks, validate each
        out_state = StreamState(
            message_id=in_state.message_id or "chatcmpl-test",
            model=in_state.model or "test-model",
        )
        all_errors: list[str] = []
        for event in all_events:
            output_chunks = normalizer.stream_event_from_internal(event, out_state)
            for out_chunk in output_chunks:
                errors = validator(out_chunk)
                if errors:
                    all_errors.extend(f"[{type(event).__name__}] {e}" for e in errors)

        assert (
            not all_errors
        ), f"Stream schema validation failed for {format_id} ({fixture_id}):\n" + "\n".join(
            f"  - {e}" for e in all_errors
        )
