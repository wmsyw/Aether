"""Provider request/response envelope hooks.

Some upstreams expose an API that is *almost* compatible with an existing
endpoint signature (family:kind), but wrap the wire format in an extra envelope
or require small transport-level behaviors.

This module provides a small hook mechanism so handlers can stay generic while
provider-specific envelopes live in their own service modules.
"""

from __future__ import annotations

from typing import Any, Protocol


class ProviderEnvelope(Protocol):
    """Provider-specific envelope transformation and side-effects."""

    name: str

    def extra_headers(self) -> dict[str, str] | None:
        """Extra upstream request headers to merge into the RequestBuilder."""

    def wrap_request(
        self,
        request_body: dict[str, Any],
        *,
        model: str,
        url_model: str | None,
        decrypted_auth_config: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], str | None]:
        """Wrap request payload and optionally override url_model (e.g. move model into body)."""

    def unwrap_response(self, data: Any) -> Any:
        """Unwrap upstream response payload (streaming chunk or full JSON)."""

    def postprocess_unwrapped_response(self, *, model: str, data: Any) -> None:
        """Best-effort post processing after unwrap (e.g. cache signatures)."""

    def capture_selected_base_url(self) -> str | None:
        """Capture the base_url selected by transport layer (if any)."""

    def on_http_status(self, *, base_url: str | None, status_code: int) -> None:
        """Called after receiving upstream HTTP status code."""

    def on_connection_error(self, *, base_url: str | None, exc: Exception) -> None:
        """Called when a connection-type exception happens."""

    def force_stream_rewrite(self) -> bool:
        """Whether streaming should always go through the rewrite/conversion path."""


def get_provider_envelope(
    *,
    provider_type: str | None,
    endpoint_sig: str | None,
) -> ProviderEnvelope | None:
    """Return envelope hooks for the given provider_type + endpoint signature."""

    pt = str(provider_type or "").strip().lower()
    sig = str(endpoint_sig or "").strip().lower()

    if not pt:
        return None

    # Antigravity wraps Gemini CLI responses in a v1internal envelope.
    if pt == "antigravity" and (sig == "gemini:cli" or not sig):
        from src.services.antigravity.envelope import antigravity_v1internal_envelope

        return antigravity_v1internal_envelope

    # Codex OAuth upstream requires a few fixed headers (SSE, session id, etc.).
    if pt == "codex" and (sig == "openai:cli" or not sig):
        from src.services.codex.envelope import codex_oauth_envelope

        return codex_oauth_envelope

    return None


__all__ = ["ProviderEnvelope", "get_provider_envelope"]
