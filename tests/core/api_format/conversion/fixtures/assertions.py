"""
Assertion helpers for format conversion tests.

Provides semantic comparison functions that check meaningful equivalence
while tolerating format-specific differences (extra fields, id regeneration, etc.).
"""

from __future__ import annotations

from collections.abc import Sequence

from src.core.api_format.conversion.internal import (
    ContentBlock,
    ImageBlock,
    InternalMessage,
    InternalRequest,
    InternalResponse,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
)
from src.core.api_format.conversion.stream_events import (
    ContentBlockStartEvent,
    ContentDeltaEvent,
    InternalStreamEvent,
    MessageStopEvent,
    ToolCallDeltaEvent,
)


def assert_internal_request_matches(
    actual: InternalRequest,
    expected: InternalRequest,
    required_fields: set[str],
) -> None:
    """Verify that actual InternalRequest matches expected on required fields."""
    if "model" in required_fields:
        assert (
            actual.model == expected.model
        ), f"model mismatch: {actual.model!r} != {expected.model!r}"

    if "messages" in required_fields:
        # Merge consecutive same-role messages before comparison,
        # since normalizers may merge/split them during conversion.
        actual_msgs = _merge_consecutive_same_role(actual.messages)
        expected_msgs = _merge_consecutive_same_role(expected.messages)
        assert len(actual_msgs) == len(
            expected_msgs
        ), f"message count mismatch: {len(actual_msgs)} != {len(expected_msgs)}"
        for i, (a, e) in enumerate(zip(actual_msgs, expected_msgs)):
            assert a.role == e.role, f"message[{i}] role mismatch: {a.role} != {e.role}"
            assert_content_blocks_match_unordered(a.content, e.content, context=f"message[{i}]")

    if "system" in required_fields:
        # Allow either system or instructions to carry the system prompt
        actual_sys = actual.system or _join_instructions(actual.instructions)
        expected_sys = expected.system or _join_instructions(expected.instructions)
        assert actual_sys == expected_sys, f"system mismatch: {actual_sys!r} != {expected_sys!r}"

    if "max_tokens" in required_fields:
        assert (
            actual.max_tokens == expected.max_tokens
        ), f"max_tokens mismatch: {actual.max_tokens} != {expected.max_tokens}"

    if "stream" in required_fields:
        assert actual.stream == expected.stream

    if "tools" in required_fields:
        assert_tools_match(actual.tools, expected.tools)

    if "tool_choice" in required_fields:
        if expected.tool_choice is not None:
            assert actual.tool_choice is not None, "tool_choice is None but expected non-None"
            assert (
                actual.tool_choice.type == expected.tool_choice.type
            ), f"tool_choice.type mismatch: {actual.tool_choice.type} != {expected.tool_choice.type}"


def assert_internal_response_matches(
    actual: InternalResponse,
    expected: InternalResponse,
    required_fields: set[str],
) -> None:
    """Verify that actual InternalResponse matches expected on required fields."""
    if "content" in required_fields:
        assert_content_blocks_match(actual.content, expected.content, context="response")

    if "stop_reason" in required_fields:
        assert (
            actual.stop_reason == expected.stop_reason
        ), f"stop_reason mismatch: {actual.stop_reason} != {expected.stop_reason}"

    if "usage" in required_fields and expected.usage is not None:
        assert actual.usage is not None, "usage is None but expected non-None"
        assert actual.usage.input_tokens == expected.usage.input_tokens
        assert actual.usage.output_tokens == expected.usage.output_tokens


def assert_content_blocks_match(
    actual_blocks: list[ContentBlock],
    expected_blocks: list[ContentBlock],
    *,
    context: str = "",
) -> None:
    """Verify content block lists are semantically equivalent (ignoring extra)."""
    # Filter out UnknownBlock (allowed to be lost)
    actual_meaningful = [b for b in actual_blocks if not isinstance(b, UnknownBlock)]
    expected_meaningful = [b for b in expected_blocks if not isinstance(b, UnknownBlock)]

    assert len(actual_meaningful) == len(expected_meaningful), (
        f"{context} block count mismatch: {len(actual_meaningful)} != {len(expected_meaningful)}"
        f"\n  actual types: {[type(b).__name__ for b in actual_meaningful]}"
        f"\n  expected types: {[type(b).__name__ for b in expected_meaningful]}"
    )

    for i, (a, e) in enumerate(zip(actual_meaningful, expected_meaningful)):
        prefix = f"{context}.block[{i}]" if context else f"block[{i}]"
        assert type(a) is type(
            e
        ), f"{prefix} type mismatch: {type(a).__name__} != {type(e).__name__}"

        if isinstance(a, TextBlock) and isinstance(e, TextBlock):
            assert a.text == e.text, f"{prefix} text mismatch: {a.text!r} != {e.text!r}"

        elif isinstance(a, ToolUseBlock) and isinstance(e, ToolUseBlock):
            assert (
                a.tool_name == e.tool_name
            ), f"{prefix} tool_name mismatch: {a.tool_name!r} != {e.tool_name!r}"
            assert (
                a.tool_input == e.tool_input
            ), f"{prefix} tool_input mismatch: {a.tool_input} != {e.tool_input}"
            # tool_id may be regenerated, just verify non-empty
            assert bool(a.tool_id), f"{prefix} tool_id is empty"

        elif isinstance(a, ToolResultBlock) and isinstance(e, ToolResultBlock):
            assert bool(a.tool_use_id), f"{prefix} tool_use_id is empty"
            # content_text or output should be semantically equivalent
            # Normalizers may parse JSON strings into dicts, so compare semantically
            a_val = _normalize_tool_output(a)
            e_val = _normalize_tool_output(e)
            assert a_val == e_val, f"{prefix} tool result mismatch: {a_val!r} != {e_val!r}"

        elif isinstance(a, ThinkingBlock) and isinstance(e, ThinkingBlock):
            assert (
                a.thinking == e.thinking
            ), f"{prefix} thinking mismatch: {a.thinking!r} != {e.thinking!r}"

        elif isinstance(a, ImageBlock) and isinstance(e, ImageBlock):
            if e.url:
                assert a.url == e.url, f"{prefix} image url mismatch"
            if e.data:
                assert a.data == e.data, f"{prefix} image data mismatch"
            if e.media_type:
                assert a.media_type == e.media_type, f"{prefix} media_type mismatch"


def assert_tools_match(
    actual: list[ToolDefinition] | None,
    expected: list[ToolDefinition] | None,
) -> None:
    """Verify tool definitions match."""
    if expected is None:
        return
    assert actual is not None, "tools is None but expected non-None"
    assert len(actual) == len(expected), f"tools count mismatch: {len(actual)} != {len(expected)}"
    for i, (a, e) in enumerate(zip(actual, expected)):
        assert a.name == e.name, f"tool[{i}].name mismatch: {a.name!r} != {e.name!r}"
        if e.description is not None:
            assert a.description == e.description, f"tool[{i}].description mismatch"
        if e.parameters is not None:
            assert a.parameters == e.parameters, f"tool[{i}].parameters mismatch"


def assert_content_blocks_match_unordered(
    actual_blocks: list[ContentBlock],
    expected_blocks: list[ContentBlock],
    *,
    context: str = "",
) -> None:
    """Verify content blocks are semantically equivalent regardless of order.

    Groups blocks by type and compares within each group. This tolerates
    reordering that normalizers may introduce during roundtrip (e.g. placing
    tool_result before or after text within the same message).
    """
    actual_meaningful = [b for b in actual_blocks if not isinstance(b, UnknownBlock)]
    expected_meaningful = [b for b in expected_blocks if not isinstance(b, UnknownBlock)]

    assert len(actual_meaningful) == len(expected_meaningful), (
        f"{context} block count mismatch: {len(actual_meaningful)} != {len(expected_meaningful)}"
        f"\n  actual types: {[type(b).__name__ for b in actual_meaningful]}"
        f"\n  expected types: {[type(b).__name__ for b in expected_meaningful]}"
    )

    def _group_by_type(blocks: Sequence[ContentBlock]) -> dict[type, list[ContentBlock]]:
        groups: dict[type, list[ContentBlock]] = {}
        for b in blocks:
            groups.setdefault(type(b), []).append(b)
        return groups

    actual_groups = _group_by_type(actual_meaningful)
    expected_groups = _group_by_type(expected_meaningful)

    assert set(actual_groups.keys()) == set(expected_groups.keys()), (
        f"{context} block type sets differ: "
        f"{[t.__name__ for t in actual_groups]} != {[t.__name__ for t in expected_groups]}"
    )

    for btype in expected_groups:
        a_list = actual_groups[btype]
        e_list = expected_groups[btype]
        assert len(a_list) == len(
            e_list
        ), f"{context} {btype.__name__} count mismatch: {len(a_list)} != {len(e_list)}"
        for i, (a, e) in enumerate(zip(a_list, e_list)):
            prefix = f"{context}.{btype.__name__}[{i}]" if context else f"{btype.__name__}[{i}]"
            if isinstance(a, TextBlock) and isinstance(e, TextBlock):
                assert a.text == e.text, f"{prefix} text mismatch: {a.text!r} != {e.text!r}"
            elif isinstance(a, ToolUseBlock) and isinstance(e, ToolUseBlock):
                assert a.tool_name == e.tool_name, f"{prefix} tool_name mismatch"
                assert a.tool_input == e.tool_input, f"{prefix} tool_input mismatch"
            elif isinstance(a, ToolResultBlock) and isinstance(e, ToolResultBlock):
                a_val = _normalize_tool_output(a)
                e_val = _normalize_tool_output(e)
                assert a_val == e_val, f"{prefix} tool result mismatch: {a_val!r} != {e_val!r}"
            elif isinstance(a, ThinkingBlock) and isinstance(e, ThinkingBlock):
                assert a.thinking == e.thinking, f"{prefix} thinking mismatch"
            elif isinstance(a, ImageBlock) and isinstance(e, ImageBlock):
                if e.url:
                    assert a.url == e.url, f"{prefix} image url mismatch"
                if e.data:
                    assert a.data == e.data, f"{prefix} image data mismatch"


def _merge_consecutive_same_role(
    messages: list[InternalMessage],
) -> list[InternalMessage]:
    """Merge consecutive messages with the same role into one (for semantic comparison)."""
    if not messages:
        return []
    merged: list[InternalMessage] = []
    for msg in messages:
        if merged and merged[-1].role == msg.role:
            merged[-1] = InternalMessage(
                role=msg.role,
                content=list(merged[-1].content) + list(msg.content),
            )
        else:
            merged.append(InternalMessage(role=msg.role, content=list(msg.content)))
    return merged


def assert_internal_requests_equivalent(
    a: InternalRequest,
    b: InternalRequest,
    lossy_fields: set[str] | None = None,
) -> None:
    """Verify two InternalRequests are semantically equivalent after roundtrip."""
    lossy = lossy_fields or set()

    assert a.model == b.model
    if "messages" not in lossy:
        # Merge consecutive same-role messages before comparison,
        # since normalizers may merge/split them during roundtrip.
        a_msgs = _merge_consecutive_same_role(a.messages)
        b_msgs = _merge_consecutive_same_role(b.messages)
        assert len(a_msgs) == len(
            b_msgs
        ), f"message count mismatch after merge: {len(a_msgs)} != {len(b_msgs)}"
        for i, (am, bm) in enumerate(zip(a_msgs, b_msgs)):
            assert am.role == bm.role, f"message[{i}] role mismatch after roundtrip"
            # Use order-insensitive comparison: normalizers may reorder blocks
            # within a message during roundtrip (e.g. tool_result before/after text).
            assert_content_blocks_match_unordered(
                am.content, bm.content, context=f"roundtrip.message[{i}]"
            )
    if "system" not in lossy:
        a_sys = a.system or _join_instructions(a.instructions)
        b_sys = b.system or _join_instructions(b.instructions)
        assert a_sys == b_sys
    if "max_tokens" not in lossy:
        assert a.max_tokens == b.max_tokens
    if "tools" not in lossy:
        assert_tools_match(a.tools, b.tools)


def assert_stream_text_matches(
    events: list[InternalStreamEvent],
    expected_text: str,
) -> None:
    """Verify that stream events produce the expected text when concatenated."""
    parts: list[str] = []
    for evt in events:
        if isinstance(evt, ContentDeltaEvent) and evt.text_delta:
            parts.append(evt.text_delta)
    actual = "".join(parts)
    assert actual == expected_text, f"stream text mismatch: {actual!r} != {expected_text!r}"


def assert_stream_stop_reason_matches(
    events: list[InternalStreamEvent],
    expected: StopReason,
) -> None:
    """Verify that the stream ends with the expected stop reason."""
    stop_events = [e for e in events if isinstance(e, MessageStopEvent)]
    assert stop_events, "no MessageStopEvent found in stream events"
    last = stop_events[-1]
    assert (
        last.stop_reason == expected
    ), f"stream stop_reason mismatch: {last.stop_reason} != {expected}"


def _join_instructions(instructions: list) -> str | None:
    if not instructions:
        return None
    parts = [seg.text for seg in instructions if seg.text]
    return "\n\n".join(parts) or None


def _normalize_tool_output(block: ToolResultBlock) -> object:
    """Normalize tool output for comparison (parse JSON strings to dicts)."""
    import json

    val = block.content_text if block.content_text is not None else block.output
    if val is None:
        return ""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    return val


def assert_stream_has_tool_call(
    events: list[InternalStreamEvent],
    expected_tool_name: str,
) -> None:
    """Verify that stream events contain a tool call with the expected name."""
    from src.core.api_format.conversion.internal import ContentType

    tool_starts = [
        e
        for e in events
        if isinstance(e, ContentBlockStartEvent) and e.block_type == ContentType.TOOL_USE
    ]
    assert tool_starts, "no tool call ContentBlockStartEvent found in stream events"
    names = [e.tool_name for e in tool_starts]
    assert (
        expected_tool_name in names
    ), f"tool name {expected_tool_name!r} not found in stream tool starts: {names}"

    # Verify there are ToolCallDeltaEvents with non-empty input
    tool_deltas = [e for e in events if isinstance(e, ToolCallDeltaEvent)]
    assert tool_deltas, "no ToolCallDeltaEvent found in stream events"
    combined = "".join(d.input_delta for d in tool_deltas)
    assert combined, "tool call input_delta is empty after concatenation"
