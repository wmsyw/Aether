"""
Tunnel Hub 配置

控制 worker 是否通过 aether-hub 转发 tunnel 帧。

设计约束：
- Hub 作为 Docker 内部固定服务运行
- 不对外暴露运行时配置项（不依赖 TUNNEL_HUB_* 环境变量）
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_DOCKER_HUB_URL = "ws://127.0.0.1:8085"
_DOCKER_HUB_CONNECT_TIMEOUT_SECONDS = 5.0
_DOCKER_HUB_PING_INTERVAL_SECONDS = 15.0
_DOCKER_HUB_SEND_TIMEOUT_SECONDS = 10.0
_DOCKER_HUB_MAX_STREAMS = 2048
_DOCKER_HUB_MAX_FRAME_SIZE = 64 * 1024 * 1024


@dataclass(frozen=True)
class HubConfig:
    enabled: bool
    url: str
    connect_timeout_seconds: float
    ping_interval_seconds: float
    send_timeout_seconds: float
    max_streams: int
    max_frame_size: int

    @property
    def worker_ws_url(self) -> str:
        return f"{self.url.rstrip('/')}/worker"


_hub_config: HubConfig | None = None


def _is_docker_runtime() -> bool:
    if os.getenv("DOCKER_CONTAINER", "").strip().lower() == "true":
        return True
    return os.path.exists("/.dockerenv")


def get_hub_config() -> HubConfig:
    """读取 Hub 配置（进程内缓存）。"""
    global _hub_config
    if _hub_config is not None:
        return _hub_config

    docker_runtime = _is_docker_runtime()
    _hub_config = HubConfig(
        enabled=docker_runtime,
        url=_DOCKER_HUB_URL,
        connect_timeout_seconds=_DOCKER_HUB_CONNECT_TIMEOUT_SECONDS,
        ping_interval_seconds=_DOCKER_HUB_PING_INTERVAL_SECONDS,
        send_timeout_seconds=_DOCKER_HUB_SEND_TIMEOUT_SECONDS,
        max_streams=_DOCKER_HUB_MAX_STREAMS,
        max_frame_size=_DOCKER_HUB_MAX_FRAME_SIZE,
    )
    return _hub_config


def reset_hub_config_cache() -> None:
    """测试或热更新场景下清理配置缓存。"""
    global _hub_config
    _hub_config = None
