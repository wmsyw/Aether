"""
Codex upstream request compatibility helpers.

The Codex upstream (https://chatgpt.com/backend-api/codex) is largely compatible with the
OpenAI Responses (/responses, aka "openai:cli") schema, but enforces some extra constraints.

CLIProxyAPI's reference implementation applies a small set of mutations before forwarding.
We replicate the same mutations here to keep Aether's routing compatible when
Provider.provider_type == "codex".
"""

from __future__ import annotations

from typing import Any

_CODEX_REQUIRED_INCLUDE_ITEM = "reasoning.encrypted_content"


def patch_openai_cli_request_for_codex(request_body: dict[str, Any]) -> dict[str, Any]:
    """
    Mutate an OpenAI Responses (openai:cli) request into a Codex-compatible payload.

    Notes (based on CLIProxyAPI translators):
    - `store` must be explicitly set to false.
    - `instructions` field must exist (Codex rejects missing instructions).
    - Codex rejects several generation params, so strip them.
    - Codex does not accept `system` role inside the `input` array.
    - Enable `parallel_tool_calls` and request encrypted reasoning content.
    """
    if not isinstance(request_body, dict):
        return request_body

    result: dict[str, Any] = dict(request_body)

    # Required by Codex: explicitly disable storing.
    result["store"] = False

    # Required by Codex: ensure instructions exists (can be empty).
    instructions = result.get("instructions")
    if instructions is None:
        result["instructions"] = ""
    elif not isinstance(instructions, str):
        result["instructions"] = str(instructions)

    # Codex defaults/tooling expectations
    result["parallel_tool_calls"] = True

    include_value = result.get("include")
    include: list[str] = []
    if isinstance(include_value, list):
        include = [v for v in include_value if isinstance(v, str) and v]
    if _CODEX_REQUIRED_INCLUDE_ITEM not in include:
        include.append(_CODEX_REQUIRED_INCLUDE_ITEM)
    result["include"] = include

    # Codex Responses rejects token limit fields and some sampling params.
    for key in (
        "max_output_tokens",
        "max_completion_tokens",
        "max_tokens",
        "temperature",
        "top_p",
        "service_tier",
    ):
        result.pop(key, None)

    # Convert role "system" to "developer" in input array to comply with Codex API requirements.
    input_value = result.get("input")
    if isinstance(input_value, list):
        patched_input: list[Any] = []
        for item in input_value:
            if (
                isinstance(item, dict)
                and item.get("type") == "message"
                and item.get("role") == "system"
            ):
                item = dict(item)
                item["role"] = "developer"
            patched_input.append(item)
        result["input"] = patched_input

    return result


def maybe_patch_request_for_codex(
    *,
    provider_type: str | None,
    provider_api_format: str | None,
    request_body: dict[str, Any],
) -> dict[str, Any]:
    """
    Apply Codex compatibility patches only when the selected upstream is Codex and the
    endpoint uses the OpenAI Responses schema ("openai:cli").
    """
    if str(provider_type or "").strip().lower() != "codex":
        return request_body
    if str(provider_api_format or "").strip().lower() != "openai:cli":
        return request_body
    return patch_openai_cli_request_for_codex(request_body)


__all__ = [
    "maybe_patch_request_for_codex",
    "patch_openai_cli_request_for_codex",
]

