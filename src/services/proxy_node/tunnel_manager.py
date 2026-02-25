"""
WebSocket 隧道管理器

管理所有活跃的 aether-proxy tunnel 连接，提供通过隧道发送 HTTP 请求的能力。
每个 proxy node 最多一条 tunnel 连接。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from starlette.websockets import WebSocket, WebSocketState

from src.core.logger import logger

from .tunnel_protocol import Frame, FrameFlags, MsgType


class TunnelConnection:
    """单条 tunnel 连接"""

    __slots__ = (
        "node_id",
        "node_name",
        "ws",
        "connected_at",
        "_pending_streams",
        "_write_lock",
        "_next_stream_id",
    )

    def __init__(self, node_id: str, node_name: str, ws: WebSocket) -> None:
        self.node_id = node_id
        self.node_name = node_name
        self.ws = ws
        self.connected_at = time.time()
        self._pending_streams: dict[int, _StreamState] = {}
        self._write_lock = asyncio.Lock()
        # Per-connection stream ID 分配器（Aether 端使用偶数，从 2 开始）
        self._next_stream_id: int = 2

    @property
    def is_alive(self) -> bool:
        return self.ws.client_state == WebSocketState.CONNECTED

    async def send_frame(self, frame: Frame) -> None:
        async with self._write_lock:
            await self.ws.send_bytes(frame.encode())

    def create_stream(self, stream_id: int) -> _StreamState:
        state = _StreamState(stream_id)
        self._pending_streams[stream_id] = state
        return state

    def get_stream(self, stream_id: int) -> _StreamState | None:
        return self._pending_streams.get(stream_id)

    def remove_stream(self, stream_id: int) -> None:
        self._pending_streams.pop(stream_id, None)

    @property
    def stream_count(self) -> int:
        return len(self._pending_streams)

    def has_stream(self, stream_id: int) -> bool:
        return stream_id in self._pending_streams

    def alloc_stream_id(self, max_streams: int) -> int:
        """分配一个未被占用的偶数 stream_id，回绕时跳过飞行中的 ID"""
        # 最多尝试 max_streams + 16 次（飞行中的 stream 数量不超过 max_streams）
        for _ in range(max_streams + 16):
            sid = self._next_stream_id
            self._next_stream_id += 2
            if self._next_stream_id > 0xFFFF_FFFE:
                self._next_stream_id = 2
            if sid not in self._pending_streams:
                return sid
        raise TunnelStreamError("stream ID space exhausted")

    def cancel_all_streams(self) -> None:
        for state in self._pending_streams.values():
            state.set_error("tunnel disconnected")
        self._pending_streams.clear()


class _StreamState:
    """跟踪单个 stream 的响应状态"""

    __slots__ = (
        "stream_id",
        "status",
        "headers",
        "_header_event",
        "_body_chunks",
        "_done_event",
        "_error",
    )

    def __init__(self, stream_id: int) -> None:
        self.stream_id = stream_id
        self.status: int = 0
        self.headers: list[list[str]] = []
        self._header_event = asyncio.Event()
        self._body_chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._done_event = asyncio.Event()
        self._error: str | None = None

    def set_response_headers(self, status: int, headers: list[list[str]] | dict[str, str]) -> None:
        self.status = status
        # headers 可能是 [[k, v], ...] (多值) 或 {k: v} (旧格式兼容)
        if isinstance(headers, list):
            self.headers = headers  # type: ignore[assignment]
        else:
            self.headers = list(headers.items())  # type: ignore[assignment]
        self._header_event.set()

    def push_body_chunk(self, data: bytes) -> None:
        self._body_chunks.put_nowait(data)

    def set_done(self) -> None:
        self._body_chunks.put_nowait(None)  # sentinel
        self._done_event.set()

    def set_error(self, msg: str) -> None:
        self._error = msg
        self._header_event.set()
        self._body_chunks.put_nowait(None)
        self._done_event.set()

    async def wait_headers(self, timeout: float = 60.0) -> None:
        await asyncio.wait_for(self._header_event.wait(), timeout=timeout)
        if self._error:
            raise TunnelStreamError(self._error)

    async def iter_body(self, chunk_timeout: float = 60.0) -> AsyncGenerator[bytes, None]:
        while True:
            try:
                chunk = await asyncio.wait_for(self._body_chunks.get(), timeout=chunk_timeout)
            except asyncio.TimeoutError:
                self._error = "body chunk timeout"
                self._done_event.set()
                raise TunnelStreamError("body chunk timeout")
            if chunk is None:
                if self._error:
                    raise TunnelStreamError(self._error)
                return
            yield chunk


class TunnelStreamError(Exception):
    pass


# ---------------------------------------------------------------------------
# 全局 TunnelManager 单例
# ---------------------------------------------------------------------------


class TunnelManager:
    """管理所有活跃的 tunnel 连接"""

    # 单条 tunnel 上允许的最大并发 stream 数（超出时拒绝新请求）
    MAX_STREAMS_PER_CONN = 2048

    def __init__(self) -> None:
        self._connections: dict[str, TunnelConnection] = {}  # node_id -> conn

    @property
    def active_count(self) -> int:
        return len(self._connections)

    def get_connection(self, node_id: str) -> TunnelConnection | None:
        conn = self._connections.get(node_id)
        if conn and not conn.is_alive:
            self._connections.pop(node_id, None)
            conn.cancel_all_streams()
            return None
        return conn

    def register(self, conn: TunnelConnection) -> None:
        old = self._connections.get(conn.node_id)
        if old:
            old.cancel_all_streams()
        self._connections[conn.node_id] = conn
        logger.info("tunnel connected: node_id={}, name={}", conn.node_id, conn.node_name)

    def unregister(self, node_id: str) -> None:
        conn = self._connections.pop(node_id, None)
        if conn:
            conn.cancel_all_streams()
            logger.info("tunnel disconnected: node_id={}, name={}", node_id, conn.node_name)

    def has_tunnel(self, node_id: str) -> bool:
        conn = self.get_connection(node_id)
        return conn is not None

    async def send_request(
        self,
        node_id: str,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None = None,
        timeout: float = 60.0,
    ) -> _StreamState:
        """
        通过 tunnel 发送 HTTP 请求，返回 StreamState 用于读取响应。
        """
        conn = self.get_connection(node_id)
        if not conn:
            raise TunnelStreamError(f"tunnel not connected for node {node_id}")

        if conn.stream_count >= self.MAX_STREAMS_PER_CONN:
            raise TunnelStreamError(
                f"tunnel stream limit reached ({self.MAX_STREAMS_PER_CONN}) for node {node_id}"
            )

        stream_id = conn.alloc_stream_id(self.MAX_STREAMS_PER_CONN)
        stream_state = conn.create_stream(stream_id)

        try:
            # 发送 REQUEST_HEADERS
            meta = json.dumps(
                {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "timeout": int(timeout),
                }
            ).encode()
            await conn.send_frame(Frame(stream_id, MsgType.REQUEST_HEADERS, 0, meta))

            # 发送 REQUEST_BODY + END_STREAM
            body_data = body or b""
            await conn.send_frame(
                Frame(stream_id, MsgType.REQUEST_BODY, FrameFlags.END_STREAM, body_data)
            )
        except Exception:
            conn.remove_stream(stream_id)
            raise

        return stream_state

    async def handle_incoming_frame(self, node_id: str, frame: Frame) -> None:
        """处理从 proxy 收到的响应帧"""
        conn = self.get_connection(node_id)
        if not conn:
            return

        stream = conn.get_stream(frame.stream_id)

        if frame.msg_type == MsgType.RESPONSE_HEADERS:
            if not stream:
                return
            try:
                meta = json.loads(frame.payload)
                stream.set_response_headers(meta["status"], meta.get("headers", []))
            except Exception as e:
                stream.set_error(f"invalid response headers: {e}")

        elif frame.msg_type == MsgType.RESPONSE_BODY:
            if stream:
                stream.push_body_chunk(frame.payload)

        elif frame.msg_type == MsgType.STREAM_END:
            if stream:
                stream.set_done()
                conn.remove_stream(frame.stream_id)

        elif frame.msg_type == MsgType.STREAM_ERROR:
            if stream:
                msg = frame.payload.decode(errors="replace") if frame.payload else "stream error"
                stream.set_error(msg)
                conn.remove_stream(frame.stream_id)

        elif frame.msg_type == MsgType.HEARTBEAT_DATA:
            await self._handle_heartbeat(conn, frame)

        elif frame.msg_type == MsgType.PING:
            await conn.send_frame(Frame(0, MsgType.PONG, 0, frame.payload))

    async def _handle_heartbeat(self, conn: TunnelConnection, frame: Frame) -> None:
        """处理 proxy 上报的心跳数据，更新 DB，返回 ACK"""
        try:
            data = json.loads(frame.payload) if frame.payload else {}
        except Exception:
            data = {}

        def _sync_heartbeat() -> dict[str, Any]:
            from src.database import create_session
            from src.services.proxy_node.service import ProxyNodeService

            db = create_session()
            try:
                node = ProxyNodeService.heartbeat(
                    db,
                    node_id=conn.node_id,
                    active_connections=data.get("active_connections"),
                    total_requests=data.get("total_requests"),
                    avg_latency_ms=data.get("avg_latency_ms"),
                )
                result: dict[str, Any] = {}
                if node.remote_config:
                    result["remote_config"] = node.remote_config
                    result["config_version"] = node.config_version or 0
                return result
            finally:
                db.close()

        try:
            ack = await asyncio.to_thread(_sync_heartbeat)
        except Exception as e:
            logger.warning("tunnel heartbeat DB update failed: {}", e)
            ack = {}

        await conn.send_frame(Frame(0, MsgType.HEARTBEAT_ACK, 0, json.dumps(ack).encode()))


# 全局单例
_tunnel_manager: TunnelManager | None = None


def get_tunnel_manager() -> TunnelManager:
    global _tunnel_manager
    if _tunnel_manager is None:
        _tunnel_manager = TunnelManager()
    return _tunnel_manager
