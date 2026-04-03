from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import httpx

from src.core.exceptions import ProviderNotAvailableException
from src.utils.ssl_utils import get_ssl_context_for_profile
from src.utils.url_utils import is_websocket_url


_RESPONSES_WEBSOCKET_FORMATS: frozenset[str] = frozenset(
    {"openai:cli", "openai:compact"}
)
_RESPONSES_WS_COMPLETION_EVENTS: frozenset[str] = frozenset({"response.completed"})
_RESPONSES_WS_FAILURE_EVENTS: frozenset[str] = frozenset(
    {"response.failed", "response.incomplete", "error"}
)


def should_use_responses_websocket(
    url: str | None, provider_api_format: str | None
) -> bool:
    normalized_format = str(provider_api_format or "").strip().lower()
    return normalized_format in _RESPONSES_WEBSOCKET_FORMATS and is_websocket_url(url)


def _build_http_request(method: str, url: str) -> httpx.Request:
    return httpx.Request(method, url)


def _convert_ws_handshake_error(
    url: str, exc: aiohttp.WSServerHandshakeError
) -> httpx.HTTPStatusError:
    request = _build_http_request("GET", url)
    response = httpx.Response(status_code=int(exc.status), request=request)
    return httpx.HTTPStatusError(str(exc), request=request, response=response)


def _serialize_payload(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _format_sse_message(
    payload: dict[str, object], *, event_type: str | None = None
) -> bytes:
    lines: list[str] = []
    if event_type:
        lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(payload, ensure_ascii=False)}")
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def _parse_json_text(raw_text: str) -> dict[str, object] | None:
    try:
        decoded_obj: object = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded_obj, dict):
        return None
    return {str(key): value for key, value in decoded_obj.items()}


def _extract_event_type_from_sse_text(
    raw_text: str,
) -> tuple[str | None, dict[str, object] | None]:
    event_type: str | None = None
    payload: dict[str, object] | None = None
    for line in raw_text.splitlines():
        normalized_line = line.strip()
        if normalized_line.startswith("event:"):
            raw_event = normalized_line[6:].strip()
            event_type = raw_event or None
            continue
        if normalized_line.startswith("data:"):
            raw_data = normalized_line[5:].strip()
            if not raw_data or raw_data == "[DONE]":
                continue
            payload = _parse_json_text(raw_data)
    if event_type is None and payload is not None:
        raw_event = payload.get("type") or payload.get("event")
        event_type = str(raw_event).strip() or None if raw_event is not None else None
    return event_type, payload


def _resolve_terminal_error_message(
    payload: dict[str, object] | None,
    event_type: str | None,
) -> str | None:
    normalized_event = str(event_type or "").strip().lower()
    if normalized_event not in _RESPONSES_WS_FAILURE_EVENTS:
        return None

    if payload is None:
        return f"Responses websocket reported {normalized_event or 'an error'}"

    error_obj = payload.get("error")
    if isinstance(error_obj, dict):
        message = error_obj.get("message") or error_obj.get("type")
        if message is not None:
            return str(message)

    if normalized_event == "response.incomplete":
        response_obj = payload.get("response")
        if isinstance(response_obj, dict):
            details = response_obj.get("incomplete_details")
            if isinstance(details, dict):
                reason = details.get("reason") or details.get("type")
                if reason is not None:
                    return f"Responses websocket reported response.incomplete: {reason}"

    return f"Responses websocket reported {normalized_event}"


def _coerce_ws_message_to_sse(
    message: str | bytes,
) -> tuple[bytes, str | None, str | None]:
    raw_text = message.decode("utf-8") if isinstance(message, bytes) else str(message)
    if not raw_text:
        return b"", None, None

    stripped = raw_text.strip()
    if not stripped:
        return b"", None, None

    if stripped == "[DONE]":
        return b"data: [DONE]\n\n", None, None

    if stripped.startswith(("data:", "event:")):
        normalized = (
            raw_text if raw_text.endswith("\n\n") else raw_text.rstrip("\n") + "\n\n"
        )
        event_type, payload = _extract_event_type_from_sse_text(normalized)
        terminal_error = _resolve_terminal_error_message(payload, event_type)
        return normalized.encode("utf-8"), event_type, terminal_error

    payload = _parse_json_text(raw_text)
    if payload is None:
        raise httpx.ReadError("Unsupported websocket message for Responses API")

    raw_event = payload.get("type") or payload.get("event")
    event_type = str(raw_event).strip() or None if raw_event is not None else None
    terminal_error = _resolve_terminal_error_message(payload, event_type)
    return (
        _format_sse_message(payload, event_type=event_type),
        event_type,
        terminal_error,
    )


@dataclass(slots=True)
class ResponsesWebSocketStreamResponse:
    websocket: aiohttp.ClientWebSocketResponse
    tls_profile: str | None = None
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    _saw_completion: bool = field(default=False, init=False, repr=False)
    _pending_terminal_error: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        raw_response = getattr(self.websocket, "_response", None)
        raw_status = int(getattr(raw_response, "status", 200) or 200)
        self.status_code = 200 if raw_status == 101 else raw_status
        raw_headers = dict(getattr(raw_response, "headers", {}) or {})
        self.headers = {str(name): str(value) for name, value in raw_headers.items()}

    def raise_for_status(self) -> None:
        return None

    def _record_event_state(
        self, event_type: str | None, terminal_error: str | None
    ) -> None:
        if event_type in _RESPONSES_WS_COMPLETION_EVENTS:
            self._saw_completion = True
        if terminal_error:
            self._pending_terminal_error = terminal_error

    def _finalize_close(self) -> None:
        if self._pending_terminal_error:
            raise httpx.ReadError(self._pending_terminal_error)
        if not self._saw_completion:
            raise httpx.ReadError(
                "Responses websocket closed before response.completed"
            )

    async def aiter_bytes(self) -> AsyncGenerator[bytes, None]:
        async for msg in self.websocket:
            if msg.type == aiohttp.WSMsgType.TEXT:
                chunk, event_type, terminal_error = _coerce_ws_message_to_sse(
                    str(msg.data)
                )
                self._record_event_state(event_type, terminal_error)
                if chunk:
                    yield chunk
                continue

            if msg.type == aiohttp.WSMsgType.BINARY:
                chunk, event_type, terminal_error = _coerce_ws_message_to_sse(
                    bytes(msg.data)
                )
                self._record_event_state(event_type, terminal_error)
                if chunk:
                    yield chunk
                continue

            if msg.type in {
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
            }:
                self._finalize_close()

            if msg.type == aiohttp.WSMsgType.ERROR:
                error = self.websocket.exception() or msg.data
                if isinstance(error, BaseException):
                    raise httpx.ReadError("Responses websocket read failed") from error
                raise httpx.ReadError(f"Responses websocket read failed: {error}")

        self._finalize_close()


class ResponsesWebSocketRequestContext:
    def __init__(
        self,
        *,
        url: str,
        headers: Mapping[str, str] | None,
        payload: object,
        provider_name: str,
        proxy_config: dict[str, Any] | None,
        tls_profile: str | None,
        connect_timeout: float | None,
        receive_timeout: float | None,
        total_timeout: float | None,
    ) -> None:
        self._url = url
        self._headers = dict(headers or {})
        self._payload = payload
        self._provider_name = provider_name
        self._proxy_config = proxy_config
        self._tls_profile = tls_profile
        self._connect_timeout = connect_timeout
        self._receive_timeout = receive_timeout
        self._total_timeout = total_timeout
        self._session: aiohttp.ClientSession | None = None
        self._websocket: aiohttp.ClientWebSocketResponse | None = None

    async def __aenter__(self) -> ResponsesWebSocketStreamResponse:
        from src.services.proxy_node.resolver import (
            build_proxy_url_async,
            get_system_proxy_config_async,
            resolve_delegate_config_async,
        )

        effective_proxy = self._proxy_config
        if effective_proxy is None:
            try:
                effective_proxy = await get_system_proxy_config_async()
            except Exception:
                effective_proxy = None

        delegate_cfg = (
            await resolve_delegate_config_async(effective_proxy)
            if effective_proxy is not None
            else None
        )
        if delegate_cfg and delegate_cfg.get("tunnel"):
            raise ProviderNotAvailableException(
                "当前代理节点的 tunnel 传输暂不支持 Responses WebSocket 上游",
                provider_name=self._provider_name,
            )

        proxy_url = (
            await build_proxy_url_async(effective_proxy) if effective_proxy else None
        )

        timeout = aiohttp.ClientTimeout(
            total=self._total_timeout,
            connect=self._connect_timeout,
            sock_connect=self._connect_timeout,
            sock_read=self._receive_timeout,
        )
        ws_timeout_factory = getattr(aiohttp, "ClientWSTimeout")
        ws_timeout = ws_timeout_factory(ws_receive=self._receive_timeout)
        self._session = aiohttp.ClientSession(timeout=timeout)
        try:
            self._websocket = await self._session.ws_connect(
                self._url,
                headers=self._headers,
                proxy=proxy_url,
                ssl=get_ssl_context_for_profile(self._tls_profile),
                timeout=ws_timeout,
                heartbeat=30.0,
                autoping=True,
                autoclose=True,
                max_msg_size=0,
            )
        except aiohttp.WSServerHandshakeError as exc:
            await self._session.close()
            self._session = None
            raise _convert_ws_handshake_error(self._url, exc) from exc
        except asyncio.TimeoutError as exc:
            await self._session.close()
            self._session = None
            raise httpx.ConnectTimeout(
                "Responses websocket connection timed out",
                request=_build_http_request("GET", self._url),
            ) from exc
        except aiohttp.ClientError as exc:
            await self._session.close()
            self._session = None
            raise httpx.ConnectError(
                f"Responses websocket connection failed: {exc}",
                request=_build_http_request("GET", self._url),
            ) from exc

        try:
            if isinstance(self._payload, bytes):
                await self._websocket.send_bytes(self._payload)
            elif isinstance(self._payload, str):
                await self._websocket.send_str(self._payload)
            else:
                await self._websocket.send_str(_serialize_payload(self._payload))
        except Exception:
            _ = await self.__aexit__(None, None, None)
            raise

        return ResponsesWebSocketStreamResponse(
            websocket=self._websocket,
            tls_profile=self._tls_profile,
        )

    async def __aexit__(
        self,
        exc_type: object | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> bool:
        _ = exc_type, exc, tb
        if self._websocket is not None and not self._websocket.closed:
            _ = await self._websocket.close()
        self._websocket = None

        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
        return False


__all__ = [
    "ResponsesWebSocketRequestContext",
    "ResponsesWebSocketStreamResponse",
    "should_use_responses_websocket",
]
