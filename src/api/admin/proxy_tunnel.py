"""
WebSocket 隧道端点

aether-proxy 通过此端点建立 tunnel 连接。
路径: /api/internal/proxy-tunnel
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.core.logger import logger
from src.services.proxy_node.tunnel_manager import (
    TunnelConnection,
    get_tunnel_manager,
)
from src.services.proxy_node.tunnel_protocol import Frame, MsgType

router = APIRouter()

# 单帧最大 64 MB -- AI API 请求体可能包含多张 base64 图片，需要足够余量
_MAX_FRAME_SIZE = 64 * 1024 * 1024

# WebSocket 空闲超时（秒）-- 需覆盖客户端 stale_timeout(45s) + 重连延迟(最长30s) 的窗口期
_IDLE_TIMEOUT = 90.0

# 服务端应用层 ping 间隔（秒）-- 与客户端 ping 间隔一致，确保高频心跳
_SERVER_PING_INTERVAL = 15.0


async def _authenticate(ws: WebSocket) -> tuple[str, str] | None:
    """验证 WebSocket 连接的认证信息，返回 (node_id, node_name) 或 None

    认证方式：Bearer <management_token>，通过 Management Token 系统验证。
    authenticate_management_token 是 async 方法（内部有 Redis 速率限制），
    因此直接 await 调用。节点存在性检查复用同一 session。
    """
    auth = ws.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None

    token = auth[7:]
    if not token or not token.startswith("ae_"):
        return None

    client_ip = getattr(ws.client, "host", "unknown") if ws.client else "unknown"
    node_id_header = ws.headers.get("x-node-id", "").strip()
    node_name_header = ws.headers.get("x-node-name", "").strip()

    if not node_id_header:
        return None

    from src.database import create_session
    from src.models.database import ProxyNode
    from src.services.auth.service import AuthService

    db = create_session()
    try:
        result = await AuthService.authenticate_management_token(db, token, client_ip)
        if not result:
            return None

        # 节点存在性检查（复用同一 session，避免额外连接开销）
        exists = db.query(
            db.query(ProxyNode).filter(ProxyNode.id == node_id_header).exists()
        ).scalar()
        if not exists:
            logger.warning("tunnel auth: node_id={} not found in DB", node_id_header)
            return None
    finally:
        db.close()

    return node_id_header, node_name_header or node_id_header


@router.websocket("/api/internal/proxy-tunnel")
async def proxy_tunnel_ws(ws: WebSocket) -> None:
    """aether-proxy tunnel WebSocket 端点"""
    # 先 accept，避免认证（DB/Redis）慢时卡在握手阶段导致网关返回 502。
    await ws.accept()

    try:
        auth = await asyncio.wait_for(_authenticate(ws), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning("tunnel auth timeout")
        await ws.close(code=4002, reason="authentication timeout")
        return
    except Exception as e:
        logger.warning("tunnel auth error: {}", e)
        await ws.close(code=4002, reason="authentication error")
        return

    if not auth:
        await ws.close(code=4001, reason="unauthorized")
        return

    node_id: str = auth[0]
    node_name: str = auth[1]

    # Read proxy-advertised max concurrent streams (backward-compatible:
    # old proxies don't send this header, we fall back to the default).
    max_streams_raw = ws.headers.get("x-tunnel-max-streams", "").strip()
    max_streams: int | None = None
    if max_streams_raw:
        try:
            max_streams = int(max_streams_raw)
        except ValueError:
            pass

    manager = get_tunnel_manager()
    conn = TunnelConnection(node_id, node_name, ws, max_streams=max_streams)
    manager.register(conn)

    # 更新 DB: tunnel_connected = True
    await _update_tunnel_status(node_id, connected=True)

    # 启动服务端 ping 任务，防止中间代理因空闲超时关闭连接
    ping_task = asyncio.create_task(_ping_loop(conn))

    try:
        oversized_count = 0
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_bytes(), timeout=_IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("tunnel idle timeout for node_id={}", node_id)
                await ws.close(code=4004, reason="idle timeout")
                break
            if len(data) > _MAX_FRAME_SIZE:
                oversized_count += 1
                logger.warning("tunnel frame too large from {}: {} bytes", node_id, len(data))
                if oversized_count >= 5:
                    logger.warning("too many oversized frames from {}, closing", node_id)
                    await ws.close(code=4003, reason="too many oversized frames")
                    break
                continue
            oversized_count = 0  # 正常帧重置计数
            try:
                frame = Frame.decode(data)
            except ValueError as e:
                logger.warning("tunnel frame decode error from {}: {}", node_id, e)
                continue

            await manager.handle_incoming_frame(conn, frame)

    except WebSocketDisconnect:
        logger.info("tunnel WebSocket disconnected: node_id={}", node_id)
    except Exception as e:
        logger.error("tunnel WebSocket error for node_id={}: {}", node_id, e)
    finally:
        ping_task.cancel()
        manager.unregister(conn)
        if not manager.has_tunnel(node_id):
            await _update_tunnel_status(node_id, connected=False)
        else:
            logger.info("tunnel connection closed but pool still active: node_id={}", node_id)


async def _ping_loop(conn: TunnelConnection) -> None:
    """定期发送应用层 PING 帧，保持连接活跃"""
    try:
        while True:
            await asyncio.sleep(_SERVER_PING_INTERVAL)
            if not conn.is_alive:
                break
            try:
                await conn.send_frame(Frame(0, MsgType.PING, 0, b""))
            except Exception as e:
                logger.debug("ping loop send failed for node_id={}: {}", conn.node_id, e)
                break
    except asyncio.CancelledError:
        pass


async def _update_tunnel_status(node_id: str, *, connected: bool) -> None:
    """更新 ProxyNode 的 tunnel 连接状态（在线程池中执行，避免阻塞 event loop）"""

    def _sync_update() -> None:
        from datetime import datetime, timezone

        from src.database import create_session
        from src.models.database import ProxyNode, ProxyNodeStatus

        db = create_session()
        try:
            node = db.query(ProxyNode).filter(ProxyNode.id == node_id).first()
            if node:
                node.tunnel_connected = connected
                now = datetime.now(timezone.utc)
                if connected:
                    node.tunnel_connected_at = now
                    node.status = ProxyNodeStatus.ONLINE
                else:
                    # 记录断开时刻，供 health_scheduler 计算 UNHEALTHY 缓冲期
                    node.tunnel_connected_at = now
                    node.status = ProxyNodeStatus.UNHEALTHY
                db.commit()
        finally:
            db.close()

    try:
        await asyncio.to_thread(_sync_update)
    except Exception as e:
        logger.warning("failed to update tunnel status for {}: {}", node_id, e)

    # 清除节点信息缓存，确保后续请求能立即感知连接状态变化
    from src.services.proxy_node.resolver import invalidate_proxy_node_cache

    invalidate_proxy_node_cache(node_id)
