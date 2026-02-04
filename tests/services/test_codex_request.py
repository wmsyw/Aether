from __future__ import annotations

from src.services.provider.codex import maybe_patch_request_for_codex, patch_openai_cli_request_for_codex


def test_patch_openai_cli_request_for_codex_sets_store_and_instructions() -> None:
    req = {"model": "gpt-test", "input": []}
    out = patch_openai_cli_request_for_codex(req)

    assert out is not req
    assert out["store"] is False
    assert "instructions" in out
    assert isinstance(out["instructions"], str)


def test_patch_openai_cli_request_for_codex_strips_rejected_params() -> None:
    req = {
        "model": "gpt-test",
        "input": [],
        "max_output_tokens": 123,
        "max_completion_tokens": 456,
        "max_tokens": 789,
        "temperature": 0.5,
        "top_p": 0.9,
        "service_tier": "default",
    }
    out = patch_openai_cli_request_for_codex(req)

    for key in (
        "max_output_tokens",
        "max_completion_tokens",
        "max_tokens",
        "temperature",
        "top_p",
        "service_tier",
    ):
        assert key not in out


def test_patch_openai_cli_request_for_codex_converts_system_role_to_developer() -> None:
    req = {
        "model": "gpt-test",
        "instructions": "ignored",
        "input": [
            {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": "You are a pirate."}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Hello"}],
            },
        ],
    }
    out = patch_openai_cli_request_for_codex(req)

    assert isinstance(out.get("input"), list)
    assert out["input"][0]["role"] == "developer"
    assert out["input"][1]["role"] == "user"


def test_patch_openai_cli_request_for_codex_adds_required_include_item() -> None:
    req = {"model": "gpt-test", "input": []}
    out = patch_openai_cli_request_for_codex(req)

    assert "include" in out
    assert "reasoning.encrypted_content" in out["include"]


def test_maybe_patch_request_for_codex_is_noop_for_non_codex() -> None:
    req = {"model": "gpt-test", "input": []}
    out = maybe_patch_request_for_codex(
        provider_type="custom",
        provider_api_format="openai:cli",
        request_body=req,
    )
    assert out is req


def test_maybe_patch_request_for_codex_is_noop_for_non_openai_cli() -> None:
    req = {"model": "gpt-test", "input": []}
    out = maybe_patch_request_for_codex(
        provider_type="codex",
        provider_api_format="openai:chat",
        request_body=req,
    )
    assert out is req


def test_maybe_patch_request_for_codex_patches_for_codex_openai_cli() -> None:
    req = {"model": "gpt-test", "input": []}
    out = maybe_patch_request_for_codex(
        provider_type="codex",
        provider_api_format="openai:cli",
        request_body=req,
    )

    assert out is not req
    assert out["store"] is False
    assert "instructions" in out

