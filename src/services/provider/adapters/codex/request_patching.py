"""
Codex provider request patching helpers (passthrough path).

This is the **primary** Codex request transformation used by the normalizer's
``patch_for_variant("codex")`` fast path.  It applies minimal, non-destructive
patches directly on the original request dict -- no internal representation
round-trip, so every field the client sent is preserved as-is unless explicitly
modified here.

Transformations applied:
- Force ``store=false``.
- Force ``stream=true`` (except compact requests).
- Force ``parallel_tool_calls=true``.
- Ensure ``instructions`` exists (empty string when absent).
- Convert ``role=system`` messages to ``role=developer``.
- Drop request parameters known to be rejected by Codex gateways.
- Force ``include`` to ``["reasoning.encrypted_content"]``.
- Drop compatibility-problematic fields (``context_management`` / ``user``).
"""

from __future__ import annotations

from typing import Any

from src.core.provider_types import ProviderType

_REJECTED_PARAMS: frozenset[str] = frozenset(
    {
        "max_output_tokens",
        "max_completion_tokens",
        "temperature",
        "top_p",
        "service_tier",
        "previous_response_id",
        "truncation",
    }
)

_REQUIRED_INCLUDE_ITEM = "reasoning.encrypted_content"


def patch_openai_cli_request_for_codex(request_body: dict[str, Any]) -> dict[str, Any]:
    """
    Patch an OpenAI CLI (Responses API style) request body for Codex gateways.

    This function never mutates the input object.
    """
    out: dict[str, Any] = dict(request_body)

    for k in _REJECTED_PARAMS:
        out.pop(k, None)

    # Codex gateways often reject/ignore persistence; be explicit.
    out["store"] = False

    # Codex compact endpoint is non-streaming; normal responses requires stream=true.
    is_compact = bool(out.pop("_aether_compact", False))
    if is_compact:
        out.pop("stream", None)
    else:
        out["stream"] = True

    # Codex expects parallel tool calls enabled.
    out["parallel_tool_calls"] = True

    # Ensure instructions exists (some gateways require it even if empty).
    instructions = out.get("instructions")
    if not isinstance(instructions, str):
        out["instructions"] = ""

    # Convert "system" role to "developer" (Codex behavior).
    input_items = out.get("input")
    if isinstance(input_items, list):
        patched_items: list[Any] = []
        for item in input_items:
            if isinstance(item, dict):
                patched = dict(item)
                if patched.get("role") == "system":
                    patched["role"] = "developer"
                patched_items.append(patched)
            else:
                patched_items.append(item)
        out["input"] = patched_items

    # Keep codex behavior deterministic: force the exact include list.
    out["include"] = [_REQUIRED_INCLUDE_ITEM]

    # Codex upstream currently rejects these fields.
    out.pop("context_management", None)
    out.pop("user", None)

    return out


def maybe_patch_request_for_codex(
    *,
    provider_type: str | None,
    provider_api_format: str | None,
    request_body: Any,
) -> Any:
    """
    Conditionally patch request body for Codex gateways.

    No-op for:
    - Non-Codex providers
    - Non OpenAI CLI / Responses-style endpoints
    - Non-dict request bodies
    """
    if (provider_type or "").lower() != ProviderType.CODEX:
        return request_body
    if (provider_api_format or "").lower() != "openai:cli":
        return request_body
    if not isinstance(request_body, dict):
        return request_body
    return patch_openai_cli_request_for_codex(request_body)


__all__ = [
    "maybe_patch_request_for_codex",
    "patch_openai_cli_request_for_codex",
]
