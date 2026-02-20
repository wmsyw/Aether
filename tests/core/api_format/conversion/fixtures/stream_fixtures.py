"""
Stream fixtures for each format.

Each fixture defines a sequence of format-specific SSE chunks and the
expected internal stream events / final text they should produce.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.api_format.conversion.internal import StopReason

from .golden_internal import _MODEL


@dataclass
class StreamFixture:
    """A stream fixture for a specific format and scenario."""

    chunks: list[dict[str, Any]]
    expected_text: str
    expected_stop_reason: StopReason
    # Fields that may differ across formats
    lossy_fields: set[str] = field(default_factory=set)


# ===================================================================
# Claude Chat / CLI stream chunks
# ===================================================================

_CLAUDE_STREAM_TEXT_CHUNKS: list[dict[str, Any]] = [
    {
        "type": "message_start",
        "message": {
            "id": "msg_stream_001",
            "type": "message",
            "role": "assistant",
            "model": _MODEL,
            "content": [],
            "stop_reason": None,
            "usage": {"input_tokens": 10, "output_tokens": 0},
        },
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    },
    # PLACEHOLDER_DELTAS
]

# Add text deltas
_CLAUDE_STREAM_TEXT_CHUNKS.extend(
    [
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello, "},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "world!"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]
)


_CLAUDE_STREAM_TEXT = StreamFixture(
    chunks=_CLAUDE_STREAM_TEXT_CHUNKS,
    expected_text="Hello, world!",
    expected_stop_reason=StopReason.END_TURN,
)


# Claude stream tool call
_CLAUDE_STREAM_TOOL_CALL = StreamFixture(
    chunks=[
        {
            "type": "message_start",
            "message": {
                "id": "msg_stream_tc_001",
                "type": "message",
                "role": "assistant",
                "model": _MODEL,
                "content": [],
                "stop_reason": None,
                "usage": {"input_tokens": 20, "output_tokens": 0},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "tool_call_s01", "name": "get_weather"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"location":'},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": ' "Tokyo"}'},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 10},
        },
        {"type": "message_stop"},
    ],
    expected_text="",
    expected_stop_reason=StopReason.TOOL_USE,
)


# ===================================================================
# OpenAI Chat stream chunks
# ===================================================================

_OPENAI_CHAT_STREAM_TEXT = StreamFixture(
    chunks=[
        {
            "id": "chatcmpl-stream-001",
            "object": "chat.completion.chunk",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": ""},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-stream-001",
            "object": "chat.completion.chunk",
            "model": _MODEL,
            "choices": [{"index": 0, "delta": {"content": "Hello, "}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-stream-001",
            "object": "chat.completion.chunk",
            "model": _MODEL,
            "choices": [{"index": 0, "delta": {"content": "world!"}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-stream-001",
            "object": "chat.completion.chunk",
            "model": _MODEL,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ],
    expected_text="Hello, world!",
    expected_stop_reason=StopReason.END_TURN,
)


# OpenAI Chat stream tool call
_OPENAI_CHAT_STREAM_TOOL_CALL = StreamFixture(
    chunks=[
        {
            "id": "chatcmpl-stream-tc-001",
            "object": "chat.completion.chunk",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_tc_001",
                                "type": "function",
                                "function": {"name": "get_weather", "arguments": ""},
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-stream-tc-001",
            "object": "chat.completion.chunk",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [{"index": 0, "function": {"arguments": '{"location":'}}]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-stream-tc-001",
            "object": "chat.completion.chunk",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": ' "Tokyo"}'}}]},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-stream-tc-001",
            "object": "chat.completion.chunk",
            "model": _MODEL,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        },
    ],
    expected_text="",
    expected_stop_reason=StopReason.TOOL_USE,
)


# ===================================================================
# OpenAI CLI (Responses API) stream chunks
# ===================================================================

_OPENAI_CLI_STREAM_TEXT = StreamFixture(
    chunks=[
        {
            "type": "response.created",
            "response": {
                "id": "resp_stream_001",
                "object": "response",
                "model": _MODEL,
                "status": "in_progress",
                "output": [],
            },
        },
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "type": "message",
                "id": "msg_stream_001",
                "role": "assistant",
                "status": "in_progress",
                "content": [],
            },
        },
        {
            "type": "response.content_part.added",
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": ""},
        },
        {
            "type": "response.output_text.delta",
            "output_index": 0,
            "content_index": 0,
            "delta": "Hello, ",
        },
        {
            "type": "response.output_text.delta",
            "output_index": 0,
            "content_index": 0,
            "delta": "world!",
        },
        {
            "type": "response.output_text.done",
            "output_index": 0,
            "content_index": 0,
            "text": "Hello, world!",
        },
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {
                "type": "message",
                "id": "msg_stream_001",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Hello, world!"}],
            },
        },
        {
            "type": "response.completed",
            "response": {
                "id": "resp_stream_001",
                "object": "response",
                "model": _MODEL,
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_stream_001",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "Hello, world!"}],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            },
        },
    ],
    expected_text="Hello, world!",
    expected_stop_reason=StopReason.END_TURN,
)


# OpenAI CLI stream tool call
_OPENAI_CLI_STREAM_TOOL_CALL = StreamFixture(
    chunks=[
        {
            "type": "response.created",
            "response": {
                "id": "resp_stream_tc_001",
                "object": "response",
                "model": _MODEL,
                "status": "in_progress",
                "output": [],
            },
        },
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "call_id": "fc_001",
                "id": "fc_001",
                "name": "get_weather",
                "status": "in_progress",
                "arguments": "",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 0,
            "item_id": "fc_001",
            "delta": '{"location":',
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 0,
            "item_id": "fc_001",
            "delta": ' "Tokyo"}',
        },
        {
            "type": "response.function_call_arguments.done",
            "output_index": 0,
            "item_id": "fc_001",
            "arguments": '{"location": "Tokyo"}',
        },
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "call_id": "fc_001",
                "id": "fc_001",
                "name": "get_weather",
                "status": "completed",
                "arguments": '{"location": "Tokyo"}',
            },
        },
        {
            "type": "response.completed",
            "response": {
                "id": "resp_stream_tc_001",
                "object": "response",
                "model": _MODEL,
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "fc_001",
                        "id": "fc_001",
                        "name": "get_weather",
                        "status": "completed",
                        "arguments": '{"location": "Tokyo"}',
                    }
                ],
                "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            },
        },
    ],
    expected_text="",
    expected_stop_reason=StopReason.TOOL_USE,
)


# ===================================================================
# Gemini Chat / CLI stream chunks
# ===================================================================

_GEMINI_STREAM_TEXT = StreamFixture(
    chunks=[
        {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "Hello, "}]},
                    "index": 0,
                }
            ],
            "modelVersion": _MODEL,
        },
        {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "world!"}]},
                    "index": 0,
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 5,
                "totalTokenCount": 15,
            },
            "modelVersion": _MODEL,
        },
    ],
    expected_text="Hello, world!",
    expected_stop_reason=StopReason.END_TURN,
)


# Gemini stream tool call (Gemini emits complete tool calls atomically)
_GEMINI_STREAM_TOOL_CALL = StreamFixture(
    chunks=[
        {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "get_weather",
                                    "args": {"location": "Tokyo"},
                                }
                            },
                        ],
                    },
                    "index": 0,
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 20,
                "candidatesTokenCount": 10,
                "totalTokenCount": 30,
            },
            "modelVersion": _MODEL,
        },
    ],
    expected_text="",
    expected_stop_reason=StopReason.END_TURN,
)


# ===================================================================
# Registry
# ===================================================================

STREAM_FIXTURES: dict[str, dict[str, StreamFixture]] = {
    "claude:chat": {
        "stream_text": _CLAUDE_STREAM_TEXT,
        "stream_tool_call": _CLAUDE_STREAM_TOOL_CALL,
    },
    "claude:cli": {
        "stream_text": _CLAUDE_STREAM_TEXT,
        "stream_tool_call": _CLAUDE_STREAM_TOOL_CALL,
    },
    "openai:chat": {
        "stream_text": _OPENAI_CHAT_STREAM_TEXT,
        "stream_tool_call": _OPENAI_CHAT_STREAM_TOOL_CALL,
    },
    "openai:cli": {
        "stream_text": _OPENAI_CLI_STREAM_TEXT,
        "stream_tool_call": _OPENAI_CLI_STREAM_TOOL_CALL,
    },
    "gemini:chat": {
        "stream_text": _GEMINI_STREAM_TEXT,
        "stream_tool_call": _GEMINI_STREAM_TOOL_CALL,
    },
    "gemini:cli": {
        "stream_text": _GEMINI_STREAM_TEXT,
        "stream_tool_call": _GEMINI_STREAM_TOOL_CALL,
    },
}

STREAM_FIXTURE_IDS = ["stream_text", "stream_tool_call"]
STREAM_ALL_FORMATS = list(STREAM_FIXTURES.keys())
