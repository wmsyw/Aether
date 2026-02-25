"""
代理节点模块

提供海外 VPS 代理节点的注册、心跳、管理功能。
aether-proxy 部署在海外 VPS 上，通过 WebSocket 隧道连接 Aether 转发 API 请求。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.modules.base import (
    ModuleCategory,
    ModuleDefinition,
    ModuleHealth,
    ModuleMetadata,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _get_router() -> Any:
    """延迟导入路由"""
    from src.api.admin.proxy_nodes import router

    return router


async def _on_startup() -> None:
    """启动心跳检测调度器"""
    import logging

    from src.services.proxy_node.health_scheduler import get_proxy_node_health_scheduler
    from src.utils.task_coordinator import StartupTaskCoordinator

    logger = logging.getLogger("aether.modules.proxy_nodes")

    from src.clients import get_redis_client

    redis_client = await get_redis_client()
    task_coordinator = StartupTaskCoordinator(redis_client)

    proxy_node_health_scheduler = get_proxy_node_health_scheduler()
    active = await task_coordinator.acquire("proxy_node_health")
    if active:
        logger.info("启动 ProxyNode 心跳检测调度器...")
        await proxy_node_health_scheduler.start()
    else:
        logger.info("检测到其他 worker 已运行 ProxyNode 心跳检测，本实例跳过")


async def _on_shutdown() -> None:
    """停止心跳检测调度器"""
    import logging

    from src.services.proxy_node.health_scheduler import get_proxy_node_health_scheduler
    from src.utils.task_coordinator import StartupTaskCoordinator

    logger = logging.getLogger("aether.modules.proxy_nodes")

    from src.clients import get_redis_client

    redis_client = await get_redis_client()
    task_coordinator = StartupTaskCoordinator(redis_client)

    scheduler = get_proxy_node_health_scheduler()
    if scheduler.running:
        logger.info("停止 ProxyNode 心跳检测调度器...")
        await scheduler.stop()
        await task_coordinator.release("proxy_node_health")


async def _health_check() -> ModuleHealth:
    """健康检查 - 检查是否有在线节点"""
    return ModuleHealth.HEALTHY


def _validate_config(db: Session) -> tuple[bool, str]:
    """验证配置（tunnel 模式无需额外密钥配置）"""
    return True, ""


proxy_nodes_module = ModuleDefinition(
    metadata=ModuleMetadata(
        name="proxy_nodes",
        display_name="代理节点",
        description="海外 VPS 代理节点管理，通过 WebSocket 隧道转发 API 请求",
        category=ModuleCategory.INTEGRATION,
        env_key="PROXY_NODES_AVAILABLE",
        default_available=True,
        required_packages=[],
        api_prefix="/api/admin/proxy-nodes",
        admin_route="/admin/proxy-nodes",
        admin_menu_icon="Server",
        admin_menu_group="system",
        admin_menu_order=60,
    ),
    router_factory=_get_router,
    on_startup=_on_startup,
    on_shutdown=_on_shutdown,
    health_check=_health_check,
    validate_config=_validate_config,
)
