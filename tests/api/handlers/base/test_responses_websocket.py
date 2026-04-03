from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Callable

import httpx
from aiohttp import web
import pytest

from src.api.handlers.base.responses_websocket import (
    ResponsesWebSocketRequestContext,
    should_use_responses_websocket,
)
from src.api.handlers.base.upstream_stream_bridge import (
    aggregate_upstream_stream_to_internal_response,
)
from src.core.api_format.conversion import register_default_normalizers
from src.core.api_format.conversion.internal import InternalResponse, TextBlock


@asynccontextmanager
async def _responses_websocket_server(
    unused_tcp_port_factory: Callable[[], int],
    received_payloads: list[dict[str, object]],
) -> AsyncIterator[str]:
    async def _handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        _ = await ws.prepare(request)

        received_json = await ws.receive_json()
        assert isinstance(received_json, dict)
        received_payloads.append(
            {str(key): value for key, value in received_json.items()}
        )
        await ws.send_json(
            {
                "type": "response.created",
                "response": {
                    "id": "resp_ws_1",
                    "model": "gpt-test",
                    "output": [],
                },
            }
        )
        await ws.send_json({"type": "response.output_text.delta", "delta": "hello"})
        await ws.send_json(
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_ws_1",
                    "model": "gpt-test",
                    "status": "completed",
                    "output": [
                        {
                            "id": "msg_1",
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "hello",
                                }
                            ],
                        }
                    ],
                    "usage": {
                        "input_tokens": 11,
                        "output_tokens": 7,
                        "total_tokens": 18,
                    },
                },
            }
        )
        _ = await ws.close()
        return ws

    app = web.Application()
    _ = app.router.add_get("/responses", _handler)

    runner = web.AppRunner(app)
    await runner.setup()
    port = unused_tcp_port_factory()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        yield f"ws://127.0.0.1:{port}/responses"
    finally:
        await runner.cleanup()


@asynccontextmanager
async def _incomplete_responses_websocket_server(
    unused_tcp_port_factory: Callable[[], int],
) -> AsyncIterator[str]:
    async def _handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        _ = await ws.prepare(request)
        _ = await ws.receive_json()
        await ws.send_json(
            {
                "type": "response.created",
                "response": {
                    "id": "resp_incomplete",
                    "model": "gpt-test",
                    "output": [],
                },
            }
        )
        await ws.send_json({"type": "response.output_text.delta", "delta": "partial"})
        _ = await ws.close()
        return ws

    app = web.Application()
    _ = app.router.add_get("/responses", _handler)

    runner = web.AppRunner(app)
    await runner.setup()
    port = unused_tcp_port_factory()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        yield f"ws://127.0.0.1:{port}/responses"
    finally:
        await runner.cleanup()


@asynccontextmanager
async def _failed_responses_websocket_server(
    unused_tcp_port_factory: Callable[[], int],
) -> AsyncIterator[str]:
    async def _handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        _ = await ws.prepare(request)
        _ = await ws.receive_json()
        await ws.send_json(
            {
                "type": "response.failed",
                "error": {"message": "upstream failed"},
                "response": {"id": "resp_failed", "model": "gpt-test"},
            }
        )
        _ = await ws.close()
        return ws

    app = web.Application()
    _ = app.router.add_get("/responses", _handler)

    runner = web.AppRunner(app)
    await runner.setup()
    port = unused_tcp_port_factory()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        yield f"ws://127.0.0.1:{port}/responses"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_should_use_responses_websocket_only_for_responses_formats() -> None:
    assert should_use_responses_websocket(
        "wss://example.com/v1/responses", "openai:cli"
    )
    assert should_use_responses_websocket(
        "ws://example.com/v1/responses", "openai:compact"
    )
    assert not should_use_responses_websocket(
        "https://example.com/v1/responses", "openai:cli"
    )
    assert not should_use_responses_websocket(
        "wss://example.com/v1/chat/completions", "openai:chat"
    )


@pytest.mark.asyncio
async def test_responses_websocket_request_context_formats_messages_as_sse(
    unused_tcp_port_factory: Callable[[], int],
) -> None:
    received_payloads: list[dict[str, object]] = []
    stream_response: object | None = None
    collected_chunks: list[bytes] = []

    async with _responses_websocket_server(
        unused_tcp_port_factory, received_payloads
    ) as url:
        async with ResponsesWebSocketRequestContext(
            url=url,
            headers={"Authorization": "Bearer test-token"},
            payload={"model": "gpt-test", "input": []},
            provider_name="responses-ws-test",
            proxy_config=None,
            tls_profile=None,
            connect_timeout=5.0,
            receive_timeout=5.0,
            total_timeout=5.0,
        ) as ws_response:
            stream_response = ws_response
            async for chunk in ws_response.aiter_bytes():
                collected_chunks.append(chunk)

    assert stream_response is not None
    combined = b"".join(collected_chunks).decode("utf-8")

    assert stream_response.status_code == 200
    assert received_payloads == [{"model": "gpt-test", "input": []}]
    assert "event: response.created" in combined
    assert "event: response.output_text.delta" in combined
    assert 'data: {"type": "response.completed"' in combined


@pytest.mark.asyncio
async def test_responses_websocket_stream_aggregates_to_internal_response(
    unused_tcp_port_factory: Callable[[], int],
) -> None:
    register_default_normalizers()
    received_payloads: list[dict[str, object]] = []
    internal_response: InternalResponse | None = None

    async with _responses_websocket_server(
        unused_tcp_port_factory, received_payloads
    ) as url:
        async with ResponsesWebSocketRequestContext(
            url=url,
            headers={"Authorization": "Bearer test-token"},
            payload={"model": "gpt-test", "input": []},
            provider_name="responses-ws-test",
            proxy_config=None,
            tls_profile=None,
            connect_timeout=5.0,
            receive_timeout=5.0,
            total_timeout=5.0,
        ) as ws_response:
            internal_response = await aggregate_upstream_stream_to_internal_response(
                ws_response.aiter_bytes(),
                provider_api_format="openai:cli",
                provider_name="responses-ws-test",
                model="gpt-test",
                request_id="req-responses-ws",
            )

    assert internal_response is not None
    assert received_payloads == [{"model": "gpt-test", "input": []}]
    assert len(internal_response.content) == 1
    assert isinstance(internal_response.content[0], TextBlock)
    assert internal_response.content[0].text == "hello"
    assert internal_response.usage is not None
    assert internal_response.usage.input_tokens == 11
    assert internal_response.usage.output_tokens == 7


@pytest.mark.asyncio
async def test_responses_websocket_raises_when_closed_before_completion(
    unused_tcp_port_factory: Callable[[], int],
) -> None:
    async with _incomplete_responses_websocket_server(unused_tcp_port_factory) as url:
        async with ResponsesWebSocketRequestContext(
            url=url,
            headers={"Authorization": "Bearer test-token"},
            payload={"model": "gpt-test", "input": []},
            provider_name="responses-ws-test",
            proxy_config=None,
            tls_profile=None,
            connect_timeout=5.0,
            receive_timeout=5.0,
            total_timeout=5.0,
        ) as ws_response:
            with pytest.raises(httpx.ReadError, match="before response.completed"):
                async for _ in ws_response.aiter_bytes():
                    pass


@pytest.mark.asyncio
async def test_responses_websocket_raises_for_response_failed(
    unused_tcp_port_factory: Callable[[], int],
) -> None:
    async with _failed_responses_websocket_server(unused_tcp_port_factory) as url:
        async with ResponsesWebSocketRequestContext(
            url=url,
            headers={"Authorization": "Bearer test-token"},
            payload={"model": "gpt-test", "input": []},
            provider_name="responses-ws-test",
            proxy_config=None,
            tls_profile=None,
            connect_timeout=5.0,
            receive_timeout=5.0,
            total_timeout=5.0,
        ) as ws_response:
            with pytest.raises(httpx.ReadError, match="upstream failed"):
                async for _ in ws_response.aiter_bytes():
                    pass
