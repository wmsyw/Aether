"""
Layer 1: Normalizer to_internal / from_internal tests.

Verifies that each normalizer correctly converts format-specific
requests/responses to/from the canonical internal representation.
"""

from __future__ import annotations

import pytest

from src.core.api_format.conversion.registry import (
    format_conversion_registry,
    register_default_normalizers,
)

from .fixtures.assertions import (
    assert_internal_request_matches,
    assert_internal_response_matches,
)
from .fixtures.format_fixtures import ALL_FORMATS, FORMAT_FIXTURES, get_format_fixture
from .fixtures.golden_internal import ALL_FIXTURE_IDS, ALL_GOLDEN_FIXTURES, KNOWN_LIMITATIONS
from .fixtures.schema_validators import (
    get_request_validator,
    get_response_validator,
)


@pytest.fixture(autouse=True, scope="module")
def _ensure_normalizers_registered() -> None:
    """Ensure all normalizers are registered before tests run."""
    register_default_normalizers()


def _available_combos() -> list[tuple[str, str]]:
    """Generate (format_id, fixture_id) pairs where fixture exists for format."""
    combos = []
    for fmt in ALL_FORMATS:
        for fid in ALL_FIXTURE_IDS:
            if fid in FORMAT_FIXTURES.get(fmt, {}):
                combos.append((fmt, fid))
    return combos


_COMBOS = _available_combos()


class TestRequestToInternal:
    """Verify format-specific request -> InternalRequest."""

    @pytest.mark.parametrize("format_id,fixture_id", _COMBOS)
    def test_request_to_internal(self, format_id: str, fixture_id: str) -> None:
        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None, f"No normalizer for {format_id}"

        fixture = get_format_fixture(format_id, fixture_id)
        golden = ALL_GOLDEN_FIXTURES[fixture_id]

        internal = normalizer.request_to_internal(fixture.request)

        # Exclude lossy fields from comparison
        effective_required = golden.required_fields - fixture.lossy_fields
        assert_internal_request_matches(internal, golden.internal_request, effective_required)


class TestResponseToInternal:
    """Verify format-specific response -> InternalResponse."""

    @pytest.mark.parametrize("format_id,fixture_id", _COMBOS)
    def test_response_to_internal(self, format_id: str, fixture_id: str) -> None:
        limitation = KNOWN_LIMITATIONS.get((format_id, fixture_id, "to_internal_response"))
        if limitation:
            pytest.skip(limitation)

        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None, f"No normalizer for {format_id}"

        fixture = get_format_fixture(format_id, fixture_id)
        golden = ALL_GOLDEN_FIXTURES[fixture_id]

        internal = normalizer.response_to_internal(fixture.response)

        assert_internal_response_matches(internal, golden.internal_response, golden.required_fields)


class TestRequestFromInternal:
    """Verify InternalRequest -> format-specific request produces valid output."""

    @pytest.mark.parametrize("format_id,fixture_id", _COMBOS)
    def test_request_from_internal(self, format_id: str, fixture_id: str) -> None:
        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None, f"No normalizer for {format_id}"

        golden = ALL_GOLDEN_FIXTURES[fixture_id]

        result = normalizer.request_from_internal(golden.internal_request)

        # The result should be a valid dict that can be parsed back
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        # Model should be preserved
        model_key = "model"
        if format_id.startswith("gemini"):
            # Gemini doesn't put model in request body
            pass
        else:
            assert result.get(model_key) == golden.internal_request.model

    @pytest.mark.parametrize("format_id,fixture_id", _COMBOS)
    def test_request_from_internal_schema(self, format_id: str, fixture_id: str) -> None:
        """Validate output structure conforms to the target API schema."""
        validator = get_request_validator(format_id)
        if validator is None:
            pytest.skip(f"No request schema validator for {format_id}")

        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None

        golden = ALL_GOLDEN_FIXTURES[fixture_id]
        result = normalizer.request_from_internal(golden.internal_request)
        errors = validator(result)
        assert (
            not errors
        ), f"Schema validation failed for {format_id} request ({fixture_id}):\n" + "\n".join(
            f"  - {e}" for e in errors
        )


class TestResponseFromInternal:
    """Verify InternalResponse -> format-specific response produces valid output."""

    @pytest.mark.parametrize("format_id,fixture_id", _COMBOS)
    def test_response_from_internal(self, format_id: str, fixture_id: str) -> None:
        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None, f"No normalizer for {format_id}"

        golden = ALL_GOLDEN_FIXTURES[fixture_id]

        result = normalizer.response_from_internal(golden.internal_response)

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    @pytest.mark.parametrize("format_id,fixture_id", _COMBOS)
    def test_response_from_internal_schema(self, format_id: str, fixture_id: str) -> None:
        """Validate output structure conforms to the target API schema."""
        validator = get_response_validator(format_id)
        if validator is None:
            pytest.skip(f"No response schema validator for {format_id}")

        normalizer = format_conversion_registry.get_normalizer(format_id)
        assert normalizer is not None

        golden = ALL_GOLDEN_FIXTURES[fixture_id]
        result = normalizer.response_from_internal(golden.internal_response)
        errors = validator(result)
        assert (
            not errors
        ), f"Schema validation failed for {format_id} response ({fixture_id}):\n" + "\n".join(
            f"  - {e}" for e in errors
        )
