import pytest

from src.core.enums import ErrorCategory
from src.services.usage.error_classifier import classify_error


@pytest.mark.parametrize(
    "status_code,error_message,status,expected",
    [
        (429, None, None, ErrorCategory.RATE_LIMIT),
        (401, None, None, ErrorCategory.AUTH),
        (404, None, None, ErrorCategory.NOT_FOUND),
        (None, "maximum context length exceeded", None, ErrorCategory.CONTEXT_LENGTH),
        (None, "content_filter triggered", None, ErrorCategory.CONTENT_FILTER),
        (None, "rate limit reached", None, ErrorCategory.RATE_LIMIT),
        (None, "request timeout", None, ErrorCategory.TIMEOUT),
        (None, "connection reset by peer", None, ErrorCategory.NETWORK),
        (500, None, None, ErrorCategory.SERVER_ERROR),
        (400, None, None, ErrorCategory.INVALID_REQUEST),
        (200, None, "cancelled", ErrorCategory.CANCELLED),
        (None, None, None, ErrorCategory.UNKNOWN),
    ],
)
def test_classify_error(
    status_code: int | None, error_message: str | None, status: str | None, expected: ErrorCategory
) -> None:
    assert classify_error(status_code, error_message, status) == expected
