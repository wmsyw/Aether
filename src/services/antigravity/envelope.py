"""Antigravity v1internal request/response envelope helpers.

Antigravity reuses the `gemini:cli` endpoint signature but wraps the actual
wire format:
- Request: V1InternalRequest (top-level metadata + nested GeminiRequest)
- Response: V1InternalResponse (top-level responseId + nested GeminiResponse)

We keep this logic isolated so other providers can reuse the same envelope hook
pattern.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.services.antigravity.constants import HTTP_USER_AGENT as ANTIGRAVITY_HTTP_USER_AGENT
from src.services.antigravity.constants import REQUEST_USER_AGENT as ANTIGRAVITY_REQUEST_USER_AGENT
from src.services.antigravity.url_availability import url_availability
from src.services.provider.request_context import get_selected_base_url


def wrap_v1internal_request(
    gemini_request: dict[str, Any],
    *,
    project_id: str,
    model: str,
) -> dict[str, Any]:
    """Wrap a GeminiRequest into Antigravity V1InternalRequest.

    Note: Antigravity expects `model` at top-level; the nested request must not
    include `model` again.
    """

    inner_request = dict(gemini_request)
    inner_request.pop("model", None)

    return {
        "project": project_id,
        "requestId": str(uuid.uuid4()),
        "userAgent": ANTIGRAVITY_REQUEST_USER_AGENT,
        "requestType": "agent",
        "model": model,
        "request": inner_request,
    }


def unwrap_v1internal_response(response: dict[str, Any]) -> dict[str, Any]:
    """Unwrap Antigravity V1InternalResponse into a GeminiResponse-like dict."""

    inner = response.get("response")
    if isinstance(inner, dict):
        unwrapped = dict(inner)
        resp_id = response.get("responseId")
        if resp_id is not None:
            unwrapped["_v1internal_response_id"] = resp_id
        return unwrapped
    return response


def cache_thought_signatures(model: str, response: dict[str, Any]) -> None:
    """Best-effort cache for Antigravity thought signatures."""

    try:
        from src.services.antigravity.signature_cache import signature_cache
    except Exception:
        return

    try:
        candidates = response.get("candidates")
        if not isinstance(candidates, list):
            return

        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            content = cand.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue

            for part in parts:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if not isinstance(text, str) or not text:
                    continue
                sig = (
                    part.get("thoughtSignature")
                    or part.get("thought_signature")
                    or part.get("signature")
                )
                if not isinstance(sig, str) or not sig:
                    continue
                signature_cache.cache(model, text, sig)
    except Exception:
        # Never fail request path due to cache issues.
        return


class AntigravityV1InternalEnvelope:
    """Provider envelope hooks for Antigravity v1internal wrapper."""

    name = "antigravity:v1internal"

    def extra_headers(self) -> dict[str, str] | None:
        return {"User-Agent": ANTIGRAVITY_HTTP_USER_AGENT}

    def wrap_request(
        self,
        request_body: dict[str, Any],
        *,
        model: str,
        url_model: str | None,
        decrypted_auth_config: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], str | None]:
        project_id = (decrypted_auth_config or {}).get("project_id")
        if not isinstance(project_id, str) or not project_id:
            from src.core.exceptions import ProviderNotAvailableException

            raise ProviderNotAvailableException(
                "Antigravity OAuth 配置缺少 project_id，请重新授权",
                provider_name="antigravity",
                upstream_response="missing auth_config.project_id",
            )

        wrapped = wrap_v1internal_request(
            request_body,
            project_id=project_id,
            model=model,
        )

        # Antigravity's model lives in the request body, not the URL path.
        return wrapped, None

    def unwrap_response(self, data: Any) -> Any:
        if isinstance(data, dict):
            return unwrap_v1internal_response(data)
        return data

    def postprocess_unwrapped_response(self, *, model: str, data: Any) -> None:
        if isinstance(data, dict):
            cache_thought_signatures(model, data)

    def capture_selected_base_url(self) -> str | None:
        return get_selected_base_url()

    def on_http_status(self, *, base_url: str | None, status_code: int) -> None:
        if not base_url:
            return
        if status_code == 200:
            url_availability.mark_success(base_url)
        elif status_code in (429, 500, 502, 503, 504):
            url_availability.mark_unavailable(base_url)

    def on_connection_error(self, *, base_url: str | None, exc: Exception) -> None:  # noqa: ARG002
        if not base_url:
            return
        url_availability.mark_unavailable(base_url)

    def force_stream_rewrite(self) -> bool:
        # Streaming must be rewritten even when endpoint signature matches, because
        # Antigravity wraps chunks in v1internal envelope.
        return True


antigravity_v1internal_envelope = AntigravityV1InternalEnvelope()

__all__ = [
    "AntigravityV1InternalEnvelope",
    "antigravity_v1internal_envelope",
    "cache_thought_signatures",
    "unwrap_v1internal_response",
    "wrap_v1internal_request",
]
