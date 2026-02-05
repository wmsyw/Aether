from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from src.services.provider.stream_policy import (
    UpstreamStreamPolicy,
    enforce_stream_mode_for_upstream,
    get_upstream_stream_policy,
)


@dataclass
class _DummyEndpoint:
    api_format: str
    config: dict | None = None
    provider: object | None = None


def test_get_upstream_stream_policy_defaults_to_auto() -> None:
    ep = _DummyEndpoint(api_format="openai:chat", config=None, provider=SimpleNamespace(provider_type="custom"))
    assert get_upstream_stream_policy(ep) == UpstreamStreamPolicy.AUTO


def test_get_upstream_stream_policy_codex_openai_cli_forces_stream() -> None:
    ep = _DummyEndpoint(
        api_format="openai:cli",
        config=None,
        provider=SimpleNamespace(provider_type="codex"),
    )
    assert get_upstream_stream_policy(ep) == UpstreamStreamPolicy.FORCE_STREAM


def test_get_upstream_stream_policy_codex_ignores_force_non_stream_config() -> None:
    ep = _DummyEndpoint(
        api_format="openai:cli",
        config={"upstream_stream_policy": "force_non_stream"},
        provider=SimpleNamespace(provider_type="codex"),
    )
    assert get_upstream_stream_policy(ep) == UpstreamStreamPolicy.FORCE_STREAM


def test_enforce_stream_mode_for_upstream_openai_chat_sets_stream_options_usage() -> None:
    body = {"stream": False}
    out = enforce_stream_mode_for_upstream(
        body,
        provider_api_format="openai:chat",
        upstream_is_stream=True,
    )
    assert out["stream"] is True
    assert out["stream_options"]["include_usage"] is True


def test_enforce_stream_mode_for_upstream_gemini_drops_stream_field() -> None:
    body = {"stream": True, "foo": "bar"}
    out = enforce_stream_mode_for_upstream(
        body,
        provider_api_format="gemini:chat",
        upstream_is_stream=False,
    )
    assert "stream" not in out
    assert out["foo"] == "bar"

