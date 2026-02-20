"""
Error fixtures for each format.

Each fixture defines a format-specific error response and the expected
InternalError it should produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.api_format.conversion.internal import ErrorType


@dataclass
class ErrorFixture:
    """A format-specific error fixture."""

    error_response: dict[str, Any]
    expected_type: ErrorType
    expected_message: str


# ===================================================================
# Claude error responses
# ===================================================================

_CLAUDE_ERRORS: dict[str, ErrorFixture] = {
    "invalid_request": ErrorFixture(
        error_response={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "max_tokens must be a positive integer",
            },
        },
        expected_type=ErrorType.INVALID_REQUEST,
        expected_message="max_tokens must be a positive integer",
    ),
    "rate_limit": ErrorFixture(
        error_response={
            "type": "error",
            "error": {
                "type": "rate_limit_error",
                "message": "Rate limit exceeded",
            },
        },
        expected_type=ErrorType.RATE_LIMIT,
        expected_message="Rate limit exceeded",
    ),
    "auth_error": ErrorFixture(
        error_response={
            "type": "error",
            "error": {
                "type": "authentication_error",
                "message": "Invalid API key",
            },
        },
        expected_type=ErrorType.AUTHENTICATION,
        expected_message="Invalid API key",
    ),
    "overloaded": ErrorFixture(
        error_response={
            "type": "error",
            "error": {
                "type": "overloaded_error",
                "message": "Overloaded",
            },
        },
        expected_type=ErrorType.OVERLOADED,
        expected_message="Overloaded",
    ),
    "server_error": ErrorFixture(
        error_response={
            "type": "error",
            "error": {
                "type": "api_error",
                "message": "Internal server error",
            },
        },
        expected_type=ErrorType.SERVER_ERROR,
        expected_message="Internal server error",
    ),
    "not_found": ErrorFixture(
        error_response={
            "type": "error",
            "error": {
                "type": "not_found_error",
                "message": "Model not found",
            },
        },
        expected_type=ErrorType.NOT_FOUND,
        expected_message="Model not found",
    ),
}

# ===================================================================
# OpenAI Chat error responses
# ===================================================================

_OPENAI_CHAT_ERRORS: dict[str, ErrorFixture] = {
    "invalid_request": ErrorFixture(
        error_response={
            "error": {
                "message": "Invalid value for max_tokens",
                "type": "invalid_request_error",
                "param": "max_tokens",
                "code": None,
            }
        },
        expected_type=ErrorType.INVALID_REQUEST,
        expected_message="Invalid value for max_tokens",
    ),
    "rate_limit": ErrorFixture(
        error_response={
            "error": {
                "message": "Rate limit reached",
                "type": "rate_limit_exceeded",
                "param": None,
                "code": "rate_limit_exceeded",
            }
        },
        expected_type=ErrorType.RATE_LIMIT,
        expected_message="Rate limit reached",
    ),
    "auth_error": ErrorFixture(
        error_response={
            "error": {
                "message": "Incorrect API key provided",
                "type": "invalid_api_key",
                "param": None,
                "code": "invalid_api_key",
            }
        },
        expected_type=ErrorType.AUTHENTICATION,
        expected_message="Incorrect API key provided",
    ),
    "server_error": ErrorFixture(
        error_response={
            "error": {
                "message": "The server had an error",
                "type": "server_error",
                "param": None,
                "code": "server_error",
            }
        },
        expected_type=ErrorType.SERVER_ERROR,
        expected_message="The server had an error",
    ),
}

# ===================================================================
# OpenAI CLI (Responses API) error responses
# ===================================================================

_OPENAI_CLI_ERRORS: dict[str, ErrorFixture] = {
    "invalid_request": ErrorFixture(
        error_response={
            "error": {
                "message": "Invalid input",
                "type": "invalid_request_error",
                "code": None,
            }
        },
        expected_type=ErrorType.INVALID_REQUEST,
        expected_message="Invalid input",
    ),
    "rate_limit": ErrorFixture(
        error_response={
            "error": {
                "message": "Rate limit reached",
                "type": "rate_limit_exceeded",
                "code": "rate_limit_exceeded",
            }
        },
        expected_type=ErrorType.RATE_LIMIT,
        expected_message="Rate limit reached",
    ),
    "server_error": ErrorFixture(
        error_response={
            "error": {
                "message": "Internal server error",
                "type": "server_error",
                "code": "server_error",
            }
        },
        expected_type=ErrorType.SERVER_ERROR,
        expected_message="Internal server error",
    ),
}

# ===================================================================
# Gemini error responses
# ===================================================================

_GEMINI_ERRORS: dict[str, ErrorFixture] = {
    "invalid_request": ErrorFixture(
        error_response={
            "error": {
                "code": 400,
                "message": "Invalid value for field",
                "status": "INVALID_ARGUMENT",
            }
        },
        expected_type=ErrorType.INVALID_REQUEST,
        expected_message="Invalid value for field",
    ),
    "rate_limit": ErrorFixture(
        error_response={
            "error": {
                "code": 429,
                "message": "Resource exhausted",
                "status": "RESOURCE_EXHAUSTED",
            }
        },
        expected_type=ErrorType.RATE_LIMIT,
        expected_message="Resource exhausted",
    ),
    "auth_error": ErrorFixture(
        error_response={
            "error": {
                "code": 401,
                "message": "API key not valid",
                "status": "UNAUTHENTICATED",
            }
        },
        expected_type=ErrorType.AUTHENTICATION,
        expected_message="API key not valid",
    ),
    "server_error": ErrorFixture(
        error_response={
            "error": {
                "code": 500,
                "message": "Internal error encountered",
                "status": "INTERNAL",
            }
        },
        expected_type=ErrorType.SERVER_ERROR,
        expected_message="Internal error encountered",
    ),
}


# ===================================================================
# Registry
# ===================================================================

ERROR_FIXTURES: dict[str, dict[str, ErrorFixture]] = {
    "claude:chat": _CLAUDE_ERRORS,
    "claude:cli": _CLAUDE_ERRORS,
    "openai:chat": _OPENAI_CHAT_ERRORS,
    "openai:cli": _OPENAI_CLI_ERRORS,
    "gemini:chat": _GEMINI_ERRORS,
    "gemini:cli": _GEMINI_ERRORS,
}

ERROR_ALL_FORMATS = list(ERROR_FIXTURES.keys())
