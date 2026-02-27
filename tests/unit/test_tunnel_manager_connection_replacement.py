import asyncio

import pytest
from starlette.websockets import WebSocketState

from src.services.proxy_node.tunnel_manager import (
    TunnelConnection,
    TunnelManager,
    TunnelStreamError,
)
from src.services.proxy_node.tunnel_protocol import Frame, MsgType


class _DummyWebSocket:
    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.sent: list[bytes] = []

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:  # noqa: ARG002
        self.client_state = WebSocketState.DISCONNECTED


@pytest.mark.asyncio
async def test_pool_register_and_unregister() -> None:
    """register 将连接追加到池中，unregister 按连接实例移除"""
    manager = TunnelManager()

    ws1 = _DummyWebSocket()
    conn1 = TunnelConnection("node-1", "node-1", ws1)  # type: ignore[arg-type]
    manager.register(conn1)
    assert manager.connection_count("node-1") == 1
    assert manager.get_connection("node-1") is conn1

    ws2 = _DummyWebSocket()
    conn2 = TunnelConnection("node-1", "node-1", ws2)  # type: ignore[arg-type]
    manager.register(conn2)
    assert manager.connection_count("node-1") == 2

    # unregister conn1 不影响 conn2
    assert manager.unregister(conn1) is True
    assert manager.connection_count("node-1") == 1
    assert manager.get_connection("node-1") is conn2

    # 重复 unregister 返回 False
    assert manager.unregister(conn1) is False

    # unregister conn2 清空池
    assert manager.unregister(conn2) is True
    assert manager.get_connection("node-1") is None


@pytest.mark.asyncio
async def test_least_loaded_selection() -> None:
    """get_connection 返回 stream_count 最小的连接"""
    manager = TunnelManager()

    ws1 = _DummyWebSocket()
    conn1 = TunnelConnection("node-1", "node-1", ws1)  # type: ignore[arg-type]
    ws2 = _DummyWebSocket()
    conn2 = TunnelConnection("node-1", "node-1", ws2)  # type: ignore[arg-type]
    manager.register(conn1)
    manager.register(conn2)

    # 两个都空闲，返回任一（实际返回 min，两者相同时返回第一个）
    selected = manager.get_connection("node-1")
    assert selected in (conn1, conn2)

    # 给 conn1 加一个 stream，conn2 应被优先选中
    conn1.create_stream(2)
    assert manager.get_connection("node-1") is conn2


@pytest.mark.asyncio
async def test_dead_connections_cleaned_on_get() -> None:
    """get_connection 自动清理 dead 连接"""
    manager = TunnelManager()

    ws1 = _DummyWebSocket()
    conn1 = TunnelConnection("node-1", "node-1", ws1)  # type: ignore[arg-type]
    ws2 = _DummyWebSocket()
    conn2 = TunnelConnection("node-1", "node-1", ws2)  # type: ignore[arg-type]
    manager.register(conn1)
    manager.register(conn2)

    # 模拟 conn1 断开
    ws1.client_state = WebSocketState.DISCONNECTED
    assert manager.get_connection("node-1") is conn2
    assert manager.connection_count("node-1") == 1


@pytest.mark.asyncio
async def test_removed_connection_frames_ignored() -> None:
    """已 unregister 的连接帧不应被处理"""
    manager = TunnelManager()

    ws1 = _DummyWebSocket()
    conn1 = TunnelConnection("node-1", "node-1", ws1)  # type: ignore[arg-type]
    ws2 = _DummyWebSocket()
    conn2 = TunnelConnection("node-1", "node-1", ws2)  # type: ignore[arg-type]
    manager.register(conn1)
    manager.register(conn2)

    # unregister conn1
    manager.unregister(conn1)

    ping = Frame(0, MsgType.PING, 0, b"hello")

    # conn1 已不在池中，帧应被忽略
    await manager.handle_incoming_frame(conn1, ping)
    # 等待 fire-and-forget task 完成
    await asyncio.sleep(0.05)
    assert ws1.sent == []

    # conn2 仍在池中，帧正常处理
    await manager.handle_incoming_frame(conn2, ping)
    await asyncio.sleep(0.05)
    assert len(ws2.sent) == 1
    pong = Frame.decode(ws2.sent[0])
    assert pong.msg_type == MsgType.PONG
    assert pong.payload == b"hello"


@pytest.mark.asyncio
async def test_max_streams_from_header() -> None:
    """TunnelConnection respects proxy-advertised max_streams (clamped)"""
    ws = _DummyWebSocket()

    # Explicit value within range
    conn = TunnelConnection("n", "n", ws, max_streams=256)  # type: ignore[arg-type]
    assert conn.max_streams == 256

    # Clamped to minimum 64
    conn_low = TunnelConnection("n", "n", ws, max_streams=10)  # type: ignore[arg-type]
    assert conn_low.max_streams == 64

    # Clamped to maximum 2048
    conn_high = TunnelConnection("n", "n", ws, max_streams=9999)  # type: ignore[arg-type]
    assert conn_high.max_streams == 2048

    # None falls back to TunnelManager.MAX_STREAMS_PER_CONN
    conn_default = TunnelConnection("n", "n", ws)  # type: ignore[arg-type]
    assert conn_default.max_streams == TunnelManager.MAX_STREAMS_PER_CONN


@pytest.mark.asyncio
async def test_send_request_respects_per_conn_max_streams() -> None:
    """send_request raises TunnelStreamError when per-connection limit is reached"""
    manager = TunnelManager()
    ws = _DummyWebSocket()
    # Set a very low max_streams (clamped to minimum 64)
    conn = TunnelConnection("node-1", "node-1", ws, max_streams=64)  # type: ignore[arg-type]
    manager.register(conn)

    # Fill up to max_streams
    for i in range(64):
        conn.create_stream(i * 2 + 2)

    assert conn.stream_count == 64

    # Next send_request should fail
    with pytest.raises(TunnelStreamError, match="stream limit reached"):
        await manager.send_request("node-1", method="GET", url="https://example.com", headers={})
