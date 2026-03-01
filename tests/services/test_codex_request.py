from __future__ import annotations

from src.services.provider.adapters.codex.request_patching import (
    maybe_patch_request_for_codex,
    patch_openai_cli_request_for_codex,
)


def test_patch_openai_cli_request_for_codex_sets_store_and_instructions() -> None:
    req = {"model": "gpt-test", "input": []}
    out = patch_openai_cli_request_for_codex(req)

    assert out is not req
    assert out["store"] is False
    assert out["stream"] is True
    assert out["instructions"] == ""


def test_patch_openai_cli_request_for_codex_strips_rejected_params() -> None:
    req = {
        "model": "gpt-test",
        "input": [],
        "max_output_tokens": 123,
        "max_completion_tokens": 456,
        "temperature": 0.5,
        "top_p": 0.9,
        "service_tier": "default",
        "truncation": "auto",
        "context_management": {"compaction": {"type": "summary"}},
        "user": "u_123",
    }
    out = patch_openai_cli_request_for_codex(req)

    for key in (
        "max_output_tokens",
        "max_completion_tokens",
        "temperature",
        "top_p",
        "service_tier",
        "truncation",
        "context_management",
        "user",
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

    assert out["include"] == ["reasoning.encrypted_content"]


def test_patch_openai_cli_request_for_codex_overrides_include() -> None:
    req = {
        "model": "gpt-test",
        "input": [],
        "include": ["foo", "bar"],
    }
    out = patch_openai_cli_request_for_codex(req)
    assert out["include"] == ["reasoning.encrypted_content"]


def test_patch_openai_cli_request_for_codex_compact_drops_stream() -> None:
    req = {
        "model": "gpt-test",
        "input": [],
        "_aether_compact": True,
        "stream": True,
    }
    out = patch_openai_cli_request_for_codex(req)
    assert "stream" not in out


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


def test_codex_envelope_extra_headers_includes_sse_accept_and_session() -> None:
    from src.services.provider.adapters.codex.envelope import codex_oauth_envelope

    headers = codex_oauth_envelope.extra_headers() or {}
    assert headers.get("Accept") == "text/event-stream"
    assert headers.get("Originator") == "codex_cli_rs"
    assert headers.get("Version") == "0.101.0"
    assert headers.get("Connection") == "Keep-Alive"
    assert isinstance(headers.get("Session_id"), str)
    assert headers.get("Session_id")


def test_codex_envelope_extra_headers_compact_uses_json_accept() -> None:
    from src.services.provider.adapters.codex.context import (
        CodexRequestContext,
        set_codex_request_context,
    )
    from src.services.provider.adapters.codex.envelope import codex_oauth_envelope

    set_codex_request_context(CodexRequestContext(is_compact=True))
    headers = codex_oauth_envelope.extra_headers() or {}
    assert headers.get("Accept") == "application/json"
    set_codex_request_context(None)


def test_codex_envelope_extra_headers_uses_account_id_header() -> None:
    from src.services.provider.adapters.codex.context import (
        CodexRequestContext,
        set_codex_request_context,
    )
    from src.services.provider.adapters.codex.envelope import codex_oauth_envelope

    set_codex_request_context(CodexRequestContext(account_id="acc_123"))
    headers = codex_oauth_envelope.extra_headers() or {}
    assert headers.get("Chatgpt-Account-Id") == "acc_123"
    set_codex_request_context(None)
