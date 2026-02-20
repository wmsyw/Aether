"""
Format-specific fixtures for each normalizer.

Each format has native request/response payloads that correspond to the
golden internal fixtures defined in golden_internal.py.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .golden_internal import _MODEL, _SYSTEM, _TOOL_DEF, _TOOL_ID


@dataclass
class FormatFixture:
    """A format-specific fixture (native request + response)."""

    request: dict[str, Any]
    response: dict[str, Any]
    # Fields that may be lost during roundtrip for this specific format
    lossy_fields: set[str] = field(default_factory=set)


_TOOL_PARAMS = {
    "type": "object",
    "properties": {
        "location": {"type": "string", "description": "City name"},
    },
    "required": ["location"],
}


# ===================================================================
# Claude Chat (claude:chat) - Messages API
# ===================================================================

_CLAUDE_CHAT: dict[str, FormatFixture] = {
    "simple_text": FormatFixture(
        request={
            "model": _MODEL,
            "system": _SYSTEM,
            "messages": [{"role": "user", "content": "Hello, how are you?"}],
            "max_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "resp_001",
            "type": "message",
            "role": "assistant",
            "model": _MODEL,
            "content": [{"type": "text", "text": "I'm doing well, thank you!"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 8},
        },
    ),
    "multi_turn": FormatFixture(
        request={
            "model": _MODEL,
            "system": _SYSTEM,
            "messages": [
                {"role": "user", "content": "What is 2+2?"},
                {"role": "assistant", "content": "4"},
                {"role": "user", "content": "And 3+3?"},
            ],
            "max_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "resp_002",
            "type": "message",
            "role": "assistant",
            "model": _MODEL,
            "content": [{"type": "text", "text": "6"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 20, "output_tokens": 1},
        },
    ),
    "tool_use": FormatFixture(
        request={
            "model": _MODEL,
            "system": _SYSTEM,
            "messages": [
                {"role": "user", "content": "What is the weather in Tokyo?"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Let me check the weather for you."},
                        {
                            "type": "tool_use",
                            "id": _TOOL_ID,
                            "name": "get_weather",
                            "input": {"location": "Tokyo"},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": _TOOL_ID,
                            "content": '{"temperature": 22, "condition": "sunny"}',
                        },
                    ],
                },
                {"role": "user", "content": "Thanks!"},
            ],
            "max_tokens": 1024,
            "stream": False,
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get the current weather for a location.",
                    "input_schema": _TOOL_PARAMS,
                },
            ],
        },
        response={
            "id": "resp_003",
            "type": "message",
            "role": "assistant",
            "model": _MODEL,
            "content": [{"type": "text", "text": "The weather in Tokyo is 22C and sunny."}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 50, "output_tokens": 12},
        },
    ),
    "empty_response": FormatFixture(
        request={
            "model": _MODEL,
            "system": _SYSTEM,
            "messages": [{"role": "user", "content": "Say nothing."}],
            "max_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "resp_008",
            "type": "message",
            "role": "assistant",
            "model": _MODEL,
            "content": [{"type": "text", "text": ""}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 0},
        },
    ),
    "tool_use_response": FormatFixture(
        request={
            "model": _MODEL,
            "system": _SYSTEM,
            "messages": [
                {"role": "user", "content": "What is the weather in Tokyo?"},
            ],
            "max_tokens": 1024,
            "stream": False,
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get the current weather for a location.",
                    "input_schema": _TOOL_PARAMS,
                },
            ],
        },
        response={
            "id": "resp_004",
            "type": "message",
            "role": "assistant",
            "model": _MODEL,
            "content": [
                {
                    "type": "tool_use",
                    "id": _TOOL_ID,
                    "name": "get_weather",
                    "input": {"location": "Tokyo"},
                },
            ],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 30, "output_tokens": 15},
        },
    ),
    "thinking": FormatFixture(
        request={
            "model": _MODEL,
            "system": _SYSTEM,
            "messages": [{"role": "user", "content": "Solve: 15 * 23"}],
            "max_tokens": 2048,
            "stream": False,
        },
        response={
            "id": "resp_005",
            "type": "message",
            "role": "assistant",
            "model": _MODEL,
            "content": [
                {
                    "type": "thinking",
                    "thinking": "15 * 23 = 15 * 20 + 15 * 3 = 300 + 45 = 345",
                },
                {"type": "text", "text": "345"},
            ],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 15, "output_tokens": 20},
        },
    ),
    "image_url": FormatFixture(
        request={
            "model": _MODEL,
            "system": _SYSTEM,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "url", "url": "https://example.com/image.png"},
                        },
                        {"type": "text", "text": "What is in this image?"},
                    ],
                }
            ],
            "max_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "resp_006",
            "type": "message",
            "role": "assistant",
            "model": _MODEL,
            "content": [{"type": "text", "text": "I see a cat."}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 5},
        },
    ),
    "image_base64": FormatFixture(
        request={
            "model": _MODEL,
            "system": _SYSTEM,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "iVBORw0KGgo=",
                            },
                        },
                        {"type": "text", "text": "Describe this image."},
                    ],
                }
            ],
            "max_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "resp_007",
            "type": "message",
            "role": "assistant",
            "model": _MODEL,
            "content": [{"type": "text", "text": "A small icon."}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 80, "output_tokens": 3},
        },
    ),
    "tool_choice_auto": FormatFixture(
        request={
            "model": _MODEL,
            "system": _SYSTEM,
            "messages": [{"role": "user", "content": "Help me."}],
            "max_tokens": 1024,
            "stream": False,
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get the current weather for a location.",
                    "input_schema": _TOOL_PARAMS,
                },
            ],
            "tool_choice": {"type": "auto"},
        },
        response={
            "id": "resp_009",
            "type": "message",
            "role": "assistant",
            "model": _MODEL,
            "content": [{"type": "text", "text": "Sure!"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 2},
        },
    ),
}

# Claude CLI (claude:cli) reuses the same body format as claude:chat
_CLAUDE_CLI: dict[str, FormatFixture] = {k: v for k, v in _CLAUDE_CHAT.items()}

# ===================================================================
# OpenAI Chat (openai:chat) - Chat Completions API
# ===================================================================

_OPENAI_CHAT: dict[str, FormatFixture] = {
    "simple_text": FormatFixture(
        request={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": "Hello, how are you?"},
            ],
            "max_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "chatcmpl-001",
            "object": "chat.completion",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "I'm doing well, thank you!",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        },
    ),
    "multi_turn": FormatFixture(
        request={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": "What is 2+2?"},
                {"role": "assistant", "content": "4"},
                {"role": "user", "content": "And 3+3?"},
            ],
            "max_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "chatcmpl-002",
            "object": "chat.completion",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "6"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 1, "total_tokens": 21},
        },
    ),
    "tool_use": FormatFixture(
        request={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": "What is the weather in Tokyo?"},
                {
                    "role": "assistant",
                    "content": "Let me check the weather for you.",
                    "tool_calls": [
                        {
                            "id": _TOOL_ID,
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"location": "Tokyo"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": _TOOL_ID,
                    "content": '{"temperature": 22, "condition": "sunny"}',
                },
                {"role": "user", "content": "Thanks!"},
            ],
            "max_tokens": 1024,
            "stream": False,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather for a location.",
                        "parameters": _TOOL_PARAMS,
                    },
                }
            ],
        },
        response={
            "id": "chatcmpl-003",
            "object": "chat.completion",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "The weather in Tokyo is 22C and sunny.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 50, "completion_tokens": 12, "total_tokens": 62},
        },
    ),
    "empty_response": FormatFixture(
        request={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": "Say nothing."},
            ],
            "max_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "chatcmpl-008",
            "object": "chat.completion",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": ""},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
        },
    ),
    "tool_use_response": FormatFixture(
        request={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": "What is the weather in Tokyo?"},
            ],
            "max_tokens": 1024,
            "stream": False,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather for a location.",
                        "parameters": _TOOL_PARAMS,
                    },
                }
            ],
        },
        response={
            "id": "chatcmpl-004",
            "object": "chat.completion",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": _TOOL_ID,
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "Tokyo"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 30, "completion_tokens": 15, "total_tokens": 45},
        },
    ),
    "thinking": FormatFixture(
        request={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": "Solve: 15 * 23"},
            ],
            "max_tokens": 2048,
            "stream": False,
        },
        response={
            "id": "chatcmpl-005",
            "object": "chat.completion",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "345",
                        "reasoning_content": "15 * 23 = 15 * 20 + 15 * 3 = 300 + 45 = 345",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 15, "completion_tokens": 20, "total_tokens": 35},
        },
    ),
    "image_url": FormatFixture(
        request={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.com/image.png"},
                        },
                        {"type": "text", "text": "What is in this image?"},
                    ],
                },
            ],
            "max_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "chatcmpl-006",
            "object": "chat.completion",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "I see a cat."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105},
        },
    ),
    "image_base64": FormatFixture(
        request={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
                        },
                        {"type": "text", "text": "Describe this image."},
                    ],
                },
            ],
            "max_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "chatcmpl-007",
            "object": "chat.completion",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "A small icon."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 80, "completion_tokens": 3, "total_tokens": 83},
        },
    ),
    "tool_choice_auto": FormatFixture(
        request={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": "Help me."},
            ],
            "max_tokens": 1024,
            "stream": False,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather for a location.",
                        "parameters": _TOOL_PARAMS,
                    },
                }
            ],
            "tool_choice": "auto",
        },
        response={
            "id": "chatcmpl-009",
            "object": "chat.completion",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Sure!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        },
    ),
}

# ===================================================================
# OpenAI CLI (openai:cli) - Responses API
# ===================================================================

_OPENAI_CLI: dict[str, FormatFixture] = {
    "simple_text": FormatFixture(
        request={
            "model": _MODEL,
            "instructions": _SYSTEM,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Hello, how are you?"}],
                },
            ],
            "max_output_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "resp_001",
            "object": "response",
            "model": _MODEL,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_001",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "I'm doing well, thank you!"}],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
        },
    ),
    "multi_turn": FormatFixture(
        request={
            "model": _MODEL,
            "instructions": _SYSTEM,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "What is 2+2?"}],
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "4"}],
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "And 3+3?"}],
                },
            ],
            "max_output_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "resp_002",
            "object": "response",
            "model": _MODEL,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_002",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "6"}],
                }
            ],
            "usage": {"input_tokens": 20, "output_tokens": 1, "total_tokens": 21},
        },
    ),
    "tool_use": FormatFixture(
        request={
            "model": _MODEL,
            "instructions": _SYSTEM,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "What is the weather in Tokyo?"}],
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "Let me check the weather for you."}
                    ],
                },
                {
                    "type": "function_call",
                    "call_id": _TOOL_ID,
                    "name": "get_weather",
                    "arguments": '{"location": "Tokyo"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": _TOOL_ID,
                    "output": '{"temperature": 22, "condition": "sunny"}',
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Thanks!"}],
                },
            ],
            "max_output_tokens": 1024,
            "stream": False,
            "tools": [
                {
                    "type": "function",
                    "name": "get_weather",
                    "description": "Get the current weather for a location.",
                    "parameters": _TOOL_PARAMS,
                },
            ],
        },
        # Responses API tool_use fixture has separate messages for text and function_call
        # so the message count differs from golden. Mark messages as lossy.
        response={
            "id": "resp_003",
            "object": "response",
            "model": _MODEL,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_003",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "The weather in Tokyo is 22C and sunny."}
                    ],
                }
            ],
            "usage": {"input_tokens": 50, "output_tokens": 12, "total_tokens": 62},
        },
        lossy_fields={"messages"},  # openai:cli splits text+tool into separate input items
    ),
    "empty_response": FormatFixture(
        request={
            "model": _MODEL,
            "instructions": _SYSTEM,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Say nothing."}],
                },
            ],
            "max_output_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "resp_008",
            "object": "response",
            "model": _MODEL,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_008",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": ""}],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 0, "total_tokens": 10},
        },
    ),
    "tool_use_response": FormatFixture(
        request={
            "model": _MODEL,
            "instructions": _SYSTEM,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "What is the weather in Tokyo?"}],
                },
            ],
            "max_output_tokens": 1024,
            "stream": False,
            "tools": [
                {
                    "type": "function",
                    "name": "get_weather",
                    "description": "Get the current weather for a location.",
                    "parameters": _TOOL_PARAMS,
                },
            ],
        },
        response={
            "id": "resp_004",
            "object": "response",
            "model": _MODEL,
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "call_id": _TOOL_ID,
                    "id": _TOOL_ID,
                    "name": "get_weather",
                    "arguments": '{"location": "Tokyo"}',
                    "status": "completed",
                }
            ],
            "usage": {"input_tokens": 30, "output_tokens": 15, "total_tokens": 45},
        },
    ),
    "image_url": FormatFixture(
        request={
            "model": _MODEL,
            "instructions": _SYSTEM,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": "https://example.com/image.png"},
                        {"type": "input_text", "text": "What is in this image?"},
                    ],
                },
            ],
            "max_output_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "resp_006",
            "object": "response",
            "model": _MODEL,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_006",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "I see a cat."}],
                }
            ],
            "usage": {"input_tokens": 100, "output_tokens": 5, "total_tokens": 105},
        },
    ),
    "image_base64": FormatFixture(
        request={
            "model": _MODEL,
            "instructions": _SYSTEM,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": "data:image/png;base64,iVBORw0KGgo="},
                        {"type": "input_text", "text": "Describe this image."},
                    ],
                },
            ],
            "max_output_tokens": 1024,
            "stream": False,
        },
        response={
            "id": "resp_007",
            "object": "response",
            "model": _MODEL,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_007",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "A small icon."}],
                }
            ],
            "usage": {"input_tokens": 80, "output_tokens": 3, "total_tokens": 83},
        },
    ),
    "tool_choice_auto": FormatFixture(
        request={
            "model": _MODEL,
            "instructions": _SYSTEM,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Help me."}],
                },
            ],
            "max_output_tokens": 1024,
            "stream": False,
            "tools": [
                {
                    "type": "function",
                    "name": "get_weather",
                    "description": "Get the current weather for a location.",
                    "parameters": _TOOL_PARAMS,
                },
            ],
            "tool_choice": "auto",
        },
        response={
            "id": "resp_009",
            "object": "response",
            "model": _MODEL,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_009",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "Sure!"}],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        },
    ),
}

# ===================================================================
# Gemini Chat (gemini:chat) - GenerateContent API
# ===================================================================

_GEMINI_CHAT: dict[str, FormatFixture] = {
    "simple_text": FormatFixture(
        request={
            "model": _MODEL,
            "contents": [
                {"role": "user", "parts": [{"text": "Hello, how are you?"}]},
            ],
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "generationConfig": {"maxOutputTokens": 1024},
        },
        response={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "I'm doing well, thank you!"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 8,
                "totalTokenCount": 18,
            },
            "modelVersion": _MODEL,
        },
    ),
    "multi_turn": FormatFixture(
        request={
            "model": _MODEL,
            "contents": [
                {"role": "user", "parts": [{"text": "What is 2+2?"}]},
                {"role": "model", "parts": [{"text": "4"}]},
                {"role": "user", "parts": [{"text": "And 3+3?"}]},
            ],
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "generationConfig": {"maxOutputTokens": 1024},
        },
        response={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "6"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 20,
                "candidatesTokenCount": 1,
                "totalTokenCount": 21,
            },
            "modelVersion": _MODEL,
        },
    ),
    "tool_use": FormatFixture(
        request={
            "model": _MODEL,
            "contents": [
                {"role": "user", "parts": [{"text": "What is the weather in Tokyo?"}]},
                {
                    "role": "model",
                    "parts": [
                        {"text": "Let me check the weather for you."},
                        {"functionCall": {"name": "get_weather", "args": {"location": "Tokyo"}}},
                    ],
                },
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": "get_weather",
                                "response": {"temperature": 22, "condition": "sunny"},
                            }
                        },
                    ],
                },
                {"role": "user", "parts": [{"text": "Thanks!"}]},
            ],
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "generationConfig": {"maxOutputTokens": 1024},
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "get_weather",
                            "description": "Get the current weather for a location.",
                            "parameters": _TOOL_PARAMS,
                        }
                    ]
                }
            ],
        },
        response={
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"text": "The weather in Tokyo is 22C and sunny."}],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 50,
                "candidatesTokenCount": 12,
                "totalTokenCount": 62,
            },
            "modelVersion": _MODEL,
        },
    ),
    "empty_response": FormatFixture(
        request={
            "model": _MODEL,
            "contents": [
                {"role": "user", "parts": [{"text": "Say nothing."}]},
            ],
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "generationConfig": {"maxOutputTokens": 1024},
        },
        response={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": ""}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 0,
                "totalTokenCount": 10,
            },
            "modelVersion": _MODEL,
        },
    ),
    "tool_use_response": FormatFixture(
        request={
            "model": _MODEL,
            "contents": [
                {"role": "user", "parts": [{"text": "What is the weather in Tokyo?"}]},
            ],
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "generationConfig": {"maxOutputTokens": 1024},
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "get_weather",
                            "description": "Get the current weather for a location.",
                            "parameters": _TOOL_PARAMS,
                        }
                    ]
                }
            ],
        },
        response={
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
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 30,
                "candidatesTokenCount": 15,
                "totalTokenCount": 45,
            },
            "modelVersion": _MODEL,
        },
    ),
    "thinking": FormatFixture(
        request={
            "model": _MODEL,
            "contents": [
                {"role": "user", "parts": [{"text": "Solve: 15 * 23"}]},
            ],
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "generationConfig": {"maxOutputTokens": 2048},
        },
        response={
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "text": "15 * 23 = 15 * 20 + 15 * 3 = 300 + 45 = 345",
                                "thought": True,
                            },
                            {"text": "345"},
                        ],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 15,
                "candidatesTokenCount": 20,
                "totalTokenCount": 35,
            },
            "modelVersion": _MODEL,
        },
    ),
    "image_url": FormatFixture(
        request={
            "model": _MODEL,
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "fileData": {
                                "fileUri": "https://example.com/image.png",
                                "mimeType": "image/png",
                            }
                        },
                        {"text": "What is in this image?"},
                    ],
                },
            ],
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "generationConfig": {"maxOutputTokens": 1024},
        },
        response={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "I see a cat."}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 100,
                "candidatesTokenCount": 5,
                "totalTokenCount": 105,
            },
            "modelVersion": _MODEL,
        },
    ),
    "image_base64": FormatFixture(
        request={
            "model": _MODEL,
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"inlineData": {"mimeType": "image/png", "data": "iVBORw0KGgo="}},
                        {"text": "Describe this image."},
                    ],
                },
            ],
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "generationConfig": {"maxOutputTokens": 1024},
        },
        response={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "A small icon."}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 80,
                "candidatesTokenCount": 3,
                "totalTokenCount": 83,
            },
            "modelVersion": _MODEL,
        },
    ),
    "tool_choice_auto": FormatFixture(
        request={
            "model": _MODEL,
            "contents": [
                {"role": "user", "parts": [{"text": "Help me."}]},
            ],
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "generationConfig": {"maxOutputTokens": 1024},
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "get_weather",
                            "description": "Get the current weather for a location.",
                            "parameters": _TOOL_PARAMS,
                        }
                    ]
                }
            ],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
        },
        response={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "Sure!"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 2,
                "totalTokenCount": 12,
            },
            "modelVersion": _MODEL,
        },
    ),
}

# Gemini CLI (gemini:cli) reuses the same body format as gemini:chat
_GEMINI_CLI: dict[str, FormatFixture] = {k: v for k, v in _GEMINI_CHAT.items()}


# ===================================================================
# Registry: format_id -> fixture_id -> FormatFixture
# ===================================================================

FORMAT_FIXTURES: dict[str, dict[str, FormatFixture]] = {
    "claude:chat": _CLAUDE_CHAT,
    "claude:cli": _CLAUDE_CLI,
    "openai:chat": _OPENAI_CHAT,
    "openai:cli": _OPENAI_CLI,
    "gemini:chat": _GEMINI_CHAT,
    "gemini:cli": _GEMINI_CLI,
}

ALL_FORMATS = list(FORMAT_FIXTURES.keys())


def get_format_fixture(format_id: str, fixture_id: str) -> FormatFixture:
    """Get a format-specific fixture, returning a deep copy to avoid mutation."""
    fmt = FORMAT_FIXTURES.get(format_id)
    if fmt is None:
        raise KeyError(f"Unknown format: {format_id}")
    fix = fmt.get(fixture_id)
    if fix is None:
        raise KeyError(f"No fixture '{fixture_id}' for format '{format_id}'")
    return FormatFixture(
        request=copy.deepcopy(fix.request),
        response=copy.deepcopy(fix.response),
        lossy_fields=set(fix.lossy_fields),
    )
