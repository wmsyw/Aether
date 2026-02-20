"""
Layer 5: Error conversion tests (fixture-driven).

Verifies that each normalizer correctly converts format-specific error
responses to/from InternalError, and that error type mapping is correct.
"""

from __future__ import annotations

import pytest

from src.core.api_format.conversion.registry import (
    format_conversion_registry,
    register_default_normalizers,
)

from .fixtures.error_fixtures import ERROR_ALL_FORMATS, ERROR_FIXTURES
from .fixtures.schema_validators import get_error_validator


@pytest.fixture(autouse=True, scope="module")
def _ensure_normalizers_registered() -> None:
    register_default_normalizers()


def _error_combos() -> list[tuple[str, str]]:
    combos = []
    for fmt in ERROR_ALL_FORMATS:
        for eid in ERROR_FIXTURES.get(fmt, {}):
            combos.append((fmt, eid))
    return combos


_COMBOS = _error_combos()


class TestErrorToInternal:
    """Verify format-specific error -> InternalError."""

    @pytest.mark.parametrize("format_id,error_id", _COMBOS)
    def test_error_to_internal(self, format_id: str, error_id: str) -> None:
        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None

        fixture = ERROR_FIXTURES[format_id][error_id]
        internal = normalizer.error_to_internal(fixture.error_response)

        assert (
            internal.type == fixture.expected_type
        ), f"error type mismatch: {internal.type} != {fixture.expected_type}"
        assert (
            internal.message == fixture.expected_message
        ), f"error message mismatch: {internal.message!r} != {fixture.expected_message!r}"


class TestErrorRoundtrip:
    """Verify error -> internal -> error -> internal preserves type and message."""

    @pytest.mark.parametrize("format_id,error_id", _COMBOS)
    def test_error_roundtrip(self, format_id: str, error_id: str) -> None:
        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None

        fixture = ERROR_FIXTURES[format_id][error_id]

        # First pass
        internal1 = normalizer.error_to_internal(fixture.error_response)

        # Reconstruct
        reconstructed = normalizer.error_from_internal(internal1)

        # Second pass
        internal2 = normalizer.error_to_internal(reconstructed)

        assert (
            internal1.type == internal2.type
        ), f"error type changed after roundtrip: {internal1.type} -> {internal2.type}"
        assert (
            internal1.message == internal2.message
        ), f"error message changed after roundtrip: {internal1.message!r} -> {internal2.message!r}"


class TestErrorFromInternalSchema:
    """Verify InternalError -> format-specific error conforms to API schema."""

    @pytest.mark.parametrize("format_id,error_id", _COMBOS)
    def test_error_from_internal_schema(self, format_id: str, error_id: str) -> None:
        validator = get_error_validator(format_id)
        if validator is None:
            pytest.skip(f"No error schema validator for {format_id}")

        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None

        fixture = ERROR_FIXTURES[format_id][error_id]
        internal = normalizer.error_to_internal(fixture.error_response)
        reconstructed = normalizer.error_from_internal(internal)

        errors = validator(reconstructed)
        assert (
            not errors
        ), f"Error schema validation failed for {format_id} ({error_id}):\n" + "\n".join(
            f"  - {e}" for e in errors
        )
