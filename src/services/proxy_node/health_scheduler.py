"""
ProxyNode 心跳检测调度器

定期检查 proxy_nodes 的 tunnel 连接状态，更新节点状态：
- tunnel 实际连接中  -> ONLINE
- tunnel 未连接      -> OFFLINE
以 TunnelManager 内存中的实际连接状态为准。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.logger import logger
from src.database import create_session
from src.models.database import ProxyNode, ProxyNodeStatus
from src.services.system.scheduler import get_scheduler

# 事件保留天数
_EVENT_RETENTION_DAYS = 30
# 每隔多少次心跳检测执行一次事件清理（15s * 240 = 1h）
_EVENT_CLEANUP_INTERVAL = 240


class ProxyNodeHealthScheduler:
    """代理节点心跳检测调度器"""

    def __init__(self) -> None:
        self.running = False
        self._check_count = 0

    async def start(self) -> Any:
        if self.running:
            logger.warning("ProxyNodeHealthScheduler already running")
            return

        self.running = True
        logger.info("ProxyNodeHealthScheduler started")

        scheduler = get_scheduler()
        scheduler.add_interval_job(
            self._scheduled_check,
            seconds=15,
            job_id="proxy_node_health_check",
            name="代理节点心跳检测",
        )

        # 启动时立即执行一次
        await self._check_heartbeats()

    async def stop(self) -> Any:
        if not self.running:
            return
        self.running = False
        logger.info("ProxyNodeHealthScheduler stopped")

    async def _scheduled_check(self) -> None:
        await self._check_heartbeats()
        self._check_count = (self._check_count + 1) % _EVENT_CLEANUP_INTERVAL
        if self._check_count == 0:
            await self._cleanup_old_events()

    async def _check_heartbeats(self) -> None:
        from src.services.proxy_node.tunnel_manager import get_tunnel_manager

        manager = get_tunnel_manager()
        db = create_session()
        try:
            now = datetime.now(timezone.utc)
            # 检查所有非手动节点（手动节点无心跳，始终保持 ONLINE）
            # 包括 OFFLINE 节点：tunnel 重连后如果 _update_tunnel_status 失败，
            # 健康检查需要能根据 TunnelManager 内存状态将其恢复为 ONLINE
            nodes = (
                db.query(ProxyNode)
                .filter(
                    ProxyNode.is_manual == False,  # noqa: E712
                )
                .all()
            )
            if not nodes:
                return

            changed = 0
            for node in nodes:
                # 以 TunnelManager 内存中的实际连接状态为准，
                # 而非仅依赖 DB 的 tunnel_connected 字段。
                # 服务端重启后 DB 可能残留 tunnel_connected=True，
                # 但 TunnelManager 内存中已无连接。
                actually_connected = manager.has_tunnel(node.id)

                # 同步修正 DB 中不一致的 tunnel_connected 字段
                if node.tunnel_connected != actually_connected:
                    node.tunnel_connected = actually_connected
                    if not actually_connected:
                        node.tunnel_connected_at = now
                    changed += 1

                new_status = (
                    ProxyNodeStatus.ONLINE if actually_connected else ProxyNodeStatus.OFFLINE
                )

                if node.status != new_status:
                    node.status = new_status
                    node.updated_at = now
                    changed += 1

            if changed:
                db.commit()
                logger.info("ProxyNode 心跳状态已更新: {} 个节点", changed)
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.exception("ProxyNode 心跳检测失败: {}", e)
        finally:
            db.close()

    async def _cleanup_old_events(self) -> None:
        """清理超过保留期的连接事件记录（在线程池中执行，避免阻塞事件循环）"""
        import asyncio

        def _sync_cleanup() -> None:
            from datetime import timedelta

            from src.models.database import ProxyNodeEvent

            db = create_session()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=_EVENT_RETENTION_DAYS)
                deleted = (
                    db.query(ProxyNodeEvent)
                    .filter(ProxyNodeEvent.created_at < cutoff)
                    .delete(synchronize_session=False)
                )
                if deleted:
                    db.commit()
                    logger.info(
                        "清理 {} 条过期代理节点事件 (>{} 天)", deleted, _EVENT_RETENTION_DAYS
                    )
            except Exception as e:
                try:
                    db.rollback()
                except Exception:
                    pass
                logger.warning("清理代理节点事件失败: {}", e)
            finally:
                db.close()

        try:
            await asyncio.to_thread(_sync_cleanup)
        except Exception as e:
            logger.warning("清理代理节点事件线程执行失败: {}", e)


_proxy_node_health_scheduler: ProxyNodeHealthScheduler | None = None


def get_proxy_node_health_scheduler() -> ProxyNodeHealthScheduler:
    global _proxy_node_health_scheduler
    if _proxy_node_health_scheduler is None:
        _proxy_node_health_scheduler = ProxyNodeHealthScheduler()
    return _proxy_node_health_scheduler
