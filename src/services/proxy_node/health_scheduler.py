"""
ProxyNode 心跳检测调度器

定期检查 proxy_nodes 的 tunnel 连接状态，更新节点状态：
- tunnel_connected=True  -> ONLINE
- tunnel 刚断开 (<60s)   -> UNHEALTHY（缓冲期，避免正在进行的请求被立即切走）
- tunnel 断开超过 60s    -> OFFLINE
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.logger import logger
from src.database import create_session
from src.models.database import ProxyNode, ProxyNodeStatus
from src.services.system.scheduler import get_scheduler


class ProxyNodeHealthScheduler:
    """代理节点心跳检测调度器"""

    def __init__(self) -> None:
        self.running = False

    async def start(self) -> Any:
        if self.running:
            logger.warning("ProxyNodeHealthScheduler already running")
            return

        self.running = True
        logger.info("ProxyNodeHealthScheduler started")

        scheduler = get_scheduler()
        scheduler.add_interval_job(
            self._scheduled_check,
            seconds=30,
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

    async def _check_heartbeats(self) -> None:
        db = create_session()
        try:
            now = datetime.now(timezone.utc)
            # 仅检查非手动节点（手动节点无心跳，始终保持 ONLINE）
            # 非手动节点均为 tunnel 模式，由 tunnel 连接状态决定
            nodes = (
                db.query(ProxyNode)
                .filter(
                    ProxyNode.status != ProxyNodeStatus.OFFLINE,
                    ProxyNode.is_manual == False,  # noqa: E712
                )
                .all()
            )
            if not nodes:
                return

            changed = 0
            for node in nodes:
                if node.tunnel_connected:
                    new_status = ProxyNodeStatus.ONLINE
                elif node.tunnel_connected_at:
                    # tunnel 刚断开：给 60s 缓冲期标记为 UNHEALTHY
                    elapsed = (now - node.tunnel_connected_at).total_seconds()
                    new_status = (
                        ProxyNodeStatus.UNHEALTHY if elapsed < 60 else ProxyNodeStatus.OFFLINE
                    )
                else:
                    new_status = ProxyNodeStatus.OFFLINE

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


_proxy_node_health_scheduler: ProxyNodeHealthScheduler | None = None


def get_proxy_node_health_scheduler() -> ProxyNodeHealthScheduler:
    global _proxy_node_health_scheduler
    if _proxy_node_health_scheduler is None:
        _proxy_node_health_scheduler = ProxyNodeHealthScheduler()
    return _proxy_node_health_scheduler
