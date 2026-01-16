"""
LDAP 认证模块

提供 LDAP/Active Directory 用户认证支持
"""

from src.core.modules.base import (
    ModuleCategory,
    ModuleDefinition,
    ModuleHealth,
    ModuleMetadata,
)


def _get_router():
    """延迟导入路由（避免启动时加载重依赖）"""
    from src.api.admin.ldap import router

    return router


async def _health_check() -> ModuleHealth:
    """健康检查 - 简化版，不依赖数据库连接"""
    # 健康检查在启动时调用，此时可能没有数据库会话
    # 返回 UNKNOWN 表示需要进一步检查
    return ModuleHealth.UNKNOWN


# LDAP 模块定义
ldap_module = ModuleDefinition(
    metadata=ModuleMetadata(
        name="ldap",
        display_name="LDAP 认证",
        description="支持通过 LDAP/Active Directory 进行用户认证",
        category=ModuleCategory.AUTH,
        # 可用性控制
        env_key="LDAP_AVAILABLE",
        default_available=True,
        required_packages=["ldap3"],
        # 路由配置（使用现有路由，不改变路径）
        api_prefix="/api/admin/ldap",
        # 前端配置
        admin_route="/admin/ldap",
        admin_menu_icon="Users",
        admin_menu_group="system",
        admin_menu_order=50,
    ),
    router_factory=_get_router,
    health_check=_health_check,
)
