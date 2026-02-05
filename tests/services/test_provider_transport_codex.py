from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from src.services.provider.transport import build_provider_url


@dataclass
class _DummyEndpoint:
    base_url: str
    api_format: str
    custom_path: str | None = None
    provider: object | None = None


def test_codex_openai_cli_uses_responses_path_without_v1_prefix() -> None:
    endpoint = _DummyEndpoint(
        base_url="https://chatgpt.com/backend-api/codex",
        api_format="openai:cli",
        provider=SimpleNamespace(provider_type="codex"),
    )

    url = build_provider_url(
        endpoint,  # type: ignore[arg-type] - test stub
        path_params={"model": "ignored"},
        is_stream=True,
    )

    assert url == "https://chatgpt.com/backend-api/codex/responses"


def test_codex_openai_cli_does_not_duplicate_responses_suffix() -> None:
    endpoint = _DummyEndpoint(
        base_url="https://chatgpt.com/backend-api/codex/responses",
        api_format="openai:cli",
        provider=SimpleNamespace(provider_type="codex"),
    )

    url = build_provider_url(
        endpoint,  # type: ignore[arg-type] - test stub
        path_params={"model": "ignored"},
        is_stream=False,
    )

    assert url == "https://chatgpt.com/backend-api/codex/responses"

