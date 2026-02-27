"""
Tunnel httpx Transport

自定义 httpx AsyncBaseTransport，将 HTTP 请求通过 WebSocket tunnel 发送到 aether-proxy。
对 handler 层完全透明 -- 只需在创建 httpx.AsyncClient 时使用此 transport。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

import httpx

from .tunnel_manager import TunnelManager, TunnelStreamError, _StreamState, get_tunnel_manager

_HOP_BY_HOP_HEADERS = frozenset(
    {
        "host",
        "transfer-encoding",
        "content-length",
        "connection",
        "upgrade",
        "keep-alive",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
    }
)

# bytes 版本，用于直接比较 httpx raw headers（key 已经是小写 bytes）
_HOP_BY_HOP_HEADERS_BYTES = frozenset(h.encode("ascii") for h in _HOP_BY_HOP_HEADERS)


class TunnelTransport(httpx.AsyncBaseTransport):
    """通过 WebSocket tunnel 发送请求的 httpx transport"""

    def __init__(self, node_id: str, timeout: float = 60.0) -> None:
        self._node_id = node_id
        self._timeout = timeout

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        manager = get_tunnel_manager()

        # 构建 headers dict（跳过 hop-by-hop 和 httpx 内部 headers）
        # request.headers.raw 返回 (bytes, bytes) 元组，key 已经是小写
        headers: dict[str, str] = {}
        for key, value in request.headers.raw:
            if key not in _HOP_BY_HOP_HEADERS_BYTES:
                headers[key.decode("latin-1")] = value.decode("latin-1")

        # 读取 body -- request.content 在 json= 传参时已由 httpx 序列化好；
        # 对 stream 类型的 request 需要先 read() 才能拿到完整 content。
        body = request.content or await request.aread() or None

        stream_state: _StreamState | None = None
        try:
            stream_state = await manager.send_request(
                self._node_id,
                method=request.method,
                url=str(request.url),
                headers=headers,
                body=body,
                timeout=self._timeout,
            )

            # 等待响应头
            await stream_state.wait_headers(timeout=self._timeout)

            # 构建 httpx.Response（流式 body）
            resp_headers = httpx.Headers(stream_state.headers)

            return httpx.Response(
                status_code=stream_state.status,
                headers=resp_headers,
                stream=TunnelResponseStream(
                    manager, self._node_id, stream_state, timeout=self._timeout
                ),
            )

        except TunnelStreamError as e:
            self._cleanup_stream(manager, stream_state)
            # 区分连接阶段和响应阶段的错误
            if stream_state and stream_state.status > 0:
                raise httpx.ReadError(str(e)) from e
            raise httpx.ConnectError(str(e)) from e
        except asyncio.TimeoutError:
            self._cleanup_stream(manager, stream_state)
            raise httpx.ReadTimeout("tunnel request timeout") from None

    def _cleanup_stream(self, manager: TunnelManager, stream_state: _StreamState | None) -> None:
        if stream_state is None:
            return
        # 优先从 stream 记住的原始连接上移除，避免连接池竞态
        conn = stream_state._conn
        if conn is None:
            conn = manager.get_connection(self._node_id)
        if conn:
            conn.remove_stream(stream_state.stream_id)


class TunnelResponseStream(httpx.AsyncByteStream):
    """将 tunnel stream 的 body chunks 包装为 httpx AsyncByteStream"""

    def __init__(
        self,
        manager: TunnelManager,
        node_id: str,
        stream_state: _StreamState,
        timeout: float = 60.0,
    ) -> None:
        self._manager = manager
        self._node_id = node_id
        self._stream_state = stream_state
        self._timeout = timeout

    async def __aiter__(self) -> AsyncGenerator[bytes, None]:
        async for chunk in self._stream_state.iter_body(chunk_timeout=self._timeout):
            yield chunk

    async def aclose(self) -> None:
        # 从 stream 记住的原始连接上精确移除，避免连接池竞态
        conn = self._stream_state._conn
        if conn is None:
            conn = self._manager.get_connection(self._node_id)
        if conn:
            conn.remove_stream(self._stream_state.stream_id)


def is_tunnel_node(node_info: dict[str, Any] | None) -> bool:
    """检查节点是否为 tunnel 模式且已连接"""
    if not node_info:
        return False
    return bool(node_info.get("tunnel_mode")) and bool(node_info.get("tunnel_connected"))
