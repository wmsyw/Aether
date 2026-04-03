from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from src.core.provider_types import ProviderType
from src.services.provider.provider_context import resolve_provider_type
from src.utils.url_utils import is_websocket_url


_RESPONSES_WEBSOCKET_CONFIG_KEYS: tuple[str, ...] = (
    "responses_websocket_enabled",
    "responsesWebsocketEnabled",
)


def _normalize_endpoint_signature(
    endpoint: object, endpoint_sig: str | None = None
) -> str:
    raw = (
        endpoint_sig
        if isinstance(endpoint_sig, str) and endpoint_sig
        else getattr(endpoint, "api_format", "")
    )
    return str(raw or "").strip().lower()


def _parse_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in {"true", "1", "yes", "on", "enabled"}:
        return True
    if raw in {"false", "0", "no", "off", "disabled"}:
        return False
    return None


def _replace_scheme(url: str, scheme: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme:
        return url
    return urlunsplit(
        (scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )


def is_openai_cli_websocket_enabled(
    endpoint: object, *, endpoint_sig: str | None = None
) -> bool:
    sig = _normalize_endpoint_signature(endpoint, endpoint_sig)
    if sig != "openai:cli":
        return False

    provider_type = (
        resolve_provider_type(endpoint=endpoint, explicit_provider_type=None) or ""
    )
    if provider_type == ProviderType.CODEX.value:
        return False

    raw_config = getattr(endpoint, "config", None)
    if isinstance(raw_config, dict):
        normalized_config = {str(key): value for key, value in raw_config.items()}
        for key in _RESPONSES_WEBSOCKET_CONFIG_KEYS:
            if key in normalized_config:
                parsed = _parse_bool(normalized_config.get(key))
                if parsed is not None:
                    return parsed

    return is_websocket_url(getattr(endpoint, "base_url", None))


def resolve_responses_transport_base_url(
    endpoint: object, *, endpoint_sig: str | None = None
) -> str:
    base_url = str(getattr(endpoint, "base_url", "") or "").strip()
    if not base_url:
        return base_url

    if not is_openai_cli_websocket_enabled(endpoint, endpoint_sig=endpoint_sig):
        if base_url.startswith("wss://"):
            return _replace_scheme(base_url, "https")
        if base_url.startswith("ws://"):
            return _replace_scheme(base_url, "http")
        return base_url

    if base_url.startswith("https://"):
        return _replace_scheme(base_url, "wss")
    if base_url.startswith("http://"):
        return _replace_scheme(base_url, "ws")
    return base_url


__all__ = [
    "is_openai_cli_websocket_enabled",
    "resolve_responses_transport_base_url",
]
