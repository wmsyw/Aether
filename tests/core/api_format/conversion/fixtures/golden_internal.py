"""
Internal golden fixtures.

Each fixture defines the canonical InternalRequest / InternalResponse
that all normalizers must produce (or consume) for a given scenario.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.api_format.conversion.internal import (
    ImageBlock,
    InstructionSegment,
    InternalMessage,
    InternalRequest,
    InternalResponse,
    Role,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolChoice,
    ToolChoiceType,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
    UsageInfo,
)


@dataclass
class GoldenFixture:
    """A golden internal fixture for a specific scenario."""

    fixture_id: str
    description: str
    internal_request: InternalRequest
    internal_response: InternalResponse
    # Fields that MUST be correctly converted by every normalizer
    required_fields: set[str] = field(default_factory=set)
    # Fields that may be lost during conversion (format-specific extras)
    lossy_fields: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
_MODEL = "test-model"
_SYSTEM = "You are a helpful assistant."
_TOOL_DEF = ToolDefinition(
    name="get_weather",
    description="Get the current weather for a location.",
    parameters={
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City name"},
        },
        "required": ["location"],
    },
)

_TOOL_ID = "tool_call_001"

_REQUIRED_REQUEST = {"model", "messages", "system"}
_REQUIRED_RESPONSE = {"content", "stop_reason"}


# ---------------------------------------------------------------------------
# simple_text: single-turn text conversation
# ---------------------------------------------------------------------------
SIMPLE_TEXT = GoldenFixture(
    fixture_id="simple_text",
    description="Single-turn text conversation with system prompt",
    internal_request=InternalRequest(
        model=_MODEL,
        messages=[
            InternalMessage(role=Role.USER, content=[TextBlock(text="Hello, how are you?")]),
        ],
        instructions=[InstructionSegment(role=Role.SYSTEM, text=_SYSTEM)],
        system=_SYSTEM,
        max_tokens=1024,
        stream=False,
    ),
    internal_response=InternalResponse(
        id="resp_001",
        model=_MODEL,
        content=[TextBlock(text="I'm doing well, thank you!")],
        stop_reason=StopReason.END_TURN,
        usage=UsageInfo(input_tokens=10, output_tokens=8, total_tokens=18),
    ),
    required_fields={"model", "messages", "system", "max_tokens", "content", "stop_reason"},
)


# ---------------------------------------------------------------------------
# multi_turn: multi-turn conversation
# ---------------------------------------------------------------------------
MULTI_TURN = GoldenFixture(
    fixture_id="multi_turn",
    description="Multi-turn conversation with user/assistant alternation",
    internal_request=InternalRequest(
        model=_MODEL,
        messages=[
            InternalMessage(role=Role.USER, content=[TextBlock(text="What is 2+2?")]),
            InternalMessage(role=Role.ASSISTANT, content=[TextBlock(text="4")]),
            InternalMessage(role=Role.USER, content=[TextBlock(text="And 3+3?")]),
        ],
        instructions=[InstructionSegment(role=Role.SYSTEM, text=_SYSTEM)],
        system=_SYSTEM,
        max_tokens=1024,
        stream=False,
    ),
    internal_response=InternalResponse(
        id="resp_002",
        model=_MODEL,
        content=[TextBlock(text="6")],
        stop_reason=StopReason.END_TURN,
        usage=UsageInfo(input_tokens=20, output_tokens=1, total_tokens=21),
    ),
    required_fields={"model", "messages", "system", "content", "stop_reason"},
)

# ---------------------------------------------------------------------------
# tool_use: tool call + tool result
# ---------------------------------------------------------------------------
TOOL_USE = GoldenFixture(
    fixture_id="tool_use",
    description="Single tool call with result in conversation history",
    internal_request=InternalRequest(
        model=_MODEL,
        messages=[
            InternalMessage(
                role=Role.USER, content=[TextBlock(text="What is the weather in Tokyo?")]
            ),
            InternalMessage(
                role=Role.ASSISTANT,
                content=[
                    TextBlock(text="Let me check the weather for you."),
                    ToolUseBlock(
                        tool_id=_TOOL_ID,
                        tool_name="get_weather",
                        tool_input={"location": "Tokyo"},
                    ),
                ],
            ),
            InternalMessage(
                role=Role.USER,
                content=[
                    ToolResultBlock(
                        tool_use_id=_TOOL_ID,
                        content_text='{"temperature": 22, "condition": "sunny"}',
                    ),
                ],
            ),
            InternalMessage(role=Role.USER, content=[TextBlock(text="Thanks!")]),
        ],
        instructions=[InstructionSegment(role=Role.SYSTEM, text=_SYSTEM)],
        system=_SYSTEM,
        max_tokens=1024,
        stream=False,
        tools=[_TOOL_DEF],
    ),
    internal_response=InternalResponse(
        id="resp_003",
        model=_MODEL,
        content=[TextBlock(text="The weather in Tokyo is 22C and sunny.")],
        stop_reason=StopReason.END_TURN,
        usage=UsageInfo(input_tokens=50, output_tokens=12, total_tokens=62),
    ),
    required_fields={"model", "messages", "system", "tools", "content", "stop_reason"},
)


# ---------------------------------------------------------------------------
# tool_use_response: response that contains a tool call (not end_turn)
# ---------------------------------------------------------------------------
TOOL_USE_RESPONSE = GoldenFixture(
    fixture_id="tool_use_response",
    description="Response that is a tool call (stop_reason=tool_use)",
    internal_request=InternalRequest(
        model=_MODEL,
        messages=[
            InternalMessage(
                role=Role.USER, content=[TextBlock(text="What is the weather in Tokyo?")]
            ),
        ],
        instructions=[InstructionSegment(role=Role.SYSTEM, text=_SYSTEM)],
        system=_SYSTEM,
        max_tokens=1024,
        stream=False,
        tools=[_TOOL_DEF],
    ),
    internal_response=InternalResponse(
        id="resp_004",
        model=_MODEL,
        content=[
            ToolUseBlock(
                tool_id=_TOOL_ID,
                tool_name="get_weather",
                tool_input={"location": "Tokyo"},
            ),
        ],
        stop_reason=StopReason.TOOL_USE,
        usage=UsageInfo(input_tokens=30, output_tokens=15, total_tokens=45),
    ),
    required_fields={"model", "messages", "tools", "content", "stop_reason"},
)


# ---------------------------------------------------------------------------
# thinking: response with thinking block
# ---------------------------------------------------------------------------
THINKING = GoldenFixture(
    fixture_id="thinking",
    description="Response with thinking/reasoning content",
    internal_request=InternalRequest(
        model=_MODEL,
        messages=[
            InternalMessage(role=Role.USER, content=[TextBlock(text="Solve: 15 * 23")]),
        ],
        instructions=[InstructionSegment(role=Role.SYSTEM, text=_SYSTEM)],
        system=_SYSTEM,
        max_tokens=2048,
        stream=False,
    ),
    internal_response=InternalResponse(
        id="resp_005",
        model=_MODEL,
        content=[
            ThinkingBlock(thinking="15 * 23 = 15 * 20 + 15 * 3 = 300 + 45 = 345"),
            TextBlock(text="345"),
        ],
        stop_reason=StopReason.END_TURN,
        usage=UsageInfo(input_tokens=15, output_tokens=20, total_tokens=35),
    ),
    required_fields={"model", "messages", "content", "stop_reason"},
)


# ---------------------------------------------------------------------------
# image_url: image input via URL
# ---------------------------------------------------------------------------
IMAGE_URL = GoldenFixture(
    fixture_id="image_url",
    description="Image input via URL",
    internal_request=InternalRequest(
        model=_MODEL,
        messages=[
            InternalMessage(
                role=Role.USER,
                content=[
                    ImageBlock(url="https://example.com/image.png", media_type="image/png"),
                    TextBlock(text="What is in this image?"),
                ],
            ),
        ],
        instructions=[InstructionSegment(role=Role.SYSTEM, text=_SYSTEM)],
        system=_SYSTEM,
        max_tokens=1024,
        stream=False,
    ),
    internal_response=InternalResponse(
        id="resp_006",
        model=_MODEL,
        content=[TextBlock(text="I see a cat.")],
        stop_reason=StopReason.END_TURN,
        usage=UsageInfo(input_tokens=100, output_tokens=5, total_tokens=105),
    ),
    required_fields={"model", "messages", "content", "stop_reason"},
)


# ---------------------------------------------------------------------------
# image_base64: image input via base64
# ---------------------------------------------------------------------------
IMAGE_BASE64 = GoldenFixture(
    fixture_id="image_base64",
    description="Image input via base64 data",
    internal_request=InternalRequest(
        model=_MODEL,
        messages=[
            InternalMessage(
                role=Role.USER,
                content=[
                    ImageBlock(data="iVBORw0KGgo=", media_type="image/png"),
                    TextBlock(text="Describe this image."),
                ],
            ),
        ],
        instructions=[InstructionSegment(role=Role.SYSTEM, text=_SYSTEM)],
        system=_SYSTEM,
        max_tokens=1024,
        stream=False,
    ),
    internal_response=InternalResponse(
        id="resp_007",
        model=_MODEL,
        content=[TextBlock(text="A small icon.")],
        stop_reason=StopReason.END_TURN,
        usage=UsageInfo(input_tokens=80, output_tokens=3, total_tokens=83),
    ),
    required_fields={"model", "messages", "content", "stop_reason"},
)


# ---------------------------------------------------------------------------
# empty_response: response with no content
# ---------------------------------------------------------------------------
EMPTY_RESPONSE = GoldenFixture(
    fixture_id="empty_response",
    description="Empty response (no content blocks)",
    internal_request=InternalRequest(
        model=_MODEL,
        messages=[
            InternalMessage(role=Role.USER, content=[TextBlock(text="Say nothing.")]),
        ],
        instructions=[InstructionSegment(role=Role.SYSTEM, text=_SYSTEM)],
        system=_SYSTEM,
        max_tokens=1024,
        stream=False,
    ),
    internal_response=InternalResponse(
        id="resp_008",
        model=_MODEL,
        content=[],  # Normalizers typically drop empty text blocks
        stop_reason=StopReason.END_TURN,
        usage=UsageInfo(input_tokens=10, output_tokens=0, total_tokens=10),
    ),
    required_fields={"model", "stop_reason"},
)


# ---------------------------------------------------------------------------
# tool_choice_auto: tool_choice=auto
# ---------------------------------------------------------------------------
TOOL_CHOICE_AUTO = GoldenFixture(
    fixture_id="tool_choice_auto",
    description="Request with tool_choice=auto",
    internal_request=InternalRequest(
        model=_MODEL,
        messages=[
            InternalMessage(role=Role.USER, content=[TextBlock(text="Help me.")]),
        ],
        system=_SYSTEM,
        max_tokens=1024,
        stream=False,
        tools=[_TOOL_DEF],
        tool_choice=ToolChoice(type=ToolChoiceType.AUTO),
    ),
    internal_response=InternalResponse(
        id="resp_009",
        model=_MODEL,
        content=[TextBlock(text="Sure!")],
        stop_reason=StopReason.END_TURN,
    ),
    required_fields={"model", "messages", "tools", "tool_choice"},
)


# ---------------------------------------------------------------------------
# Registry of all golden fixtures
# ---------------------------------------------------------------------------
ALL_GOLDEN_FIXTURES: dict[str, GoldenFixture] = {
    f.fixture_id: f
    for f in [
        SIMPLE_TEXT,
        MULTI_TURN,
        TOOL_USE,
        TOOL_USE_RESPONSE,
        THINKING,
        IMAGE_URL,
        IMAGE_BASE64,
        EMPTY_RESPONSE,
        TOOL_CHOICE_AUTO,
    ]
}

# Fixture IDs that all formats must support (core scenarios)
CORE_FIXTURE_IDS = ["simple_text", "multi_turn", "tool_use", "empty_response"]

# Fixture IDs for extended scenarios (some formats may not support)
EXTENDED_FIXTURE_IDS = [
    "tool_use_response",
    "thinking",
    "image_url",
    "image_base64",
    "tool_choice_auto",
]

ALL_FIXTURE_IDS = CORE_FIXTURE_IDS + EXTENDED_FIXTURE_IDS

# ---------------------------------------------------------------------------
# Known normalizer limitations for extended fixtures.
#
# Maps (format_id, fixture_id, test_layer) -> reason string.
# test_layer: "to_internal", "from_internal", "roundtrip", "cross_request", "cross_response"
#
# These are documented limitations of the current normalizer implementations,
# NOT bugs to fix. Tests will skip these combinations.
# ---------------------------------------------------------------------------
KNOWN_LIMITATIONS: dict[tuple[str, str, str], str] = {}

# Formats where response_to_internal loses ThinkingBlock (source limitation)
_THINKING_RESPONSE_LOSSY_SOURCES = {"openai:cli"}

# Fixtures where the response's thinking block is lost when target format
# doesn't support ThinkingBlock in non-streaming responses.
_THINKING_RESPONSE_LOSSY_TARGETS = {"openai:cli"}


def is_cross_format_limited(
    source: str,
    target: str,
    fixture_id: str,
    layer: str,
) -> str | None:
    """Return a reason string if this cross-format combo is a known limitation, else None."""
    # thinking response: openai:cli doesn't support ThinkingBlock in non-streaming
    if fixture_id == "thinking" and layer == "cross_response":
        if source in _THINKING_RESPONSE_LOSSY_SOURCES:
            return f"{source} does not parse thinking content into ThinkingBlock"
        if target in _THINKING_RESPONSE_LOSSY_TARGETS:
            return f"{target} does not preserve ThinkingBlock in non-streaming responses"

    return None
