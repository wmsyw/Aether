"""Antigravity API 客户端（最小封装）。"""

from __future__ import annotations

from typing import Any

from src.clients.http_client import HTTPClientPool
from src.services.antigravity.constants import (
    DAILY_BASE_URL,
    HTTP_USER_AGENT,
    PROD_BASE_URL,
)
from src.services.antigravity.url_availability import url_availability


async def load_code_assist(
    access_token: str,
    proxy_config: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """调用 /v1internal:loadCodeAssist 获取账户信息。

    注意：
    - email 需通过 Google userinfo API 获取（由 enrich_auth_config 复用已有逻辑）
    - 这里仅负责 project_id / tier 等信息
    - 使用 url_availability 决定优先尝试的 URL
    """
    if not access_token:
        raise ValueError("missing access_token")

    client = await HTTPClientPool.get_proxy_client(proxy_config)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": HTTP_USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {"metadata": {"ideType": "ANTIGRAVITY"}}

    # 使用可用性排序（prod 优先，但会参考历史成功/失败记录）
    urls = url_availability.get_ordered_urls(prefer_daily=False)
    if not urls:
        urls = [PROD_BASE_URL, DAILY_BASE_URL]
    last_exc: Exception | None = None

    for base_url in urls:
        try:
            resp = await client.post(
                f"{base_url}/v1internal:loadCodeAssist",
                json=body,
                headers=headers,
                timeout=timeout_seconds,
            )
            if 200 <= resp.status_code < 300:
                url_availability.mark_success(base_url)
                data = resp.json()
                return data if isinstance(data, dict) else {}

            # 非 2xx：标记不可用并继续 fallback
            if resp.status_code in (429, 500, 502, 503, 504):
                url_availability.mark_unavailable(base_url)
            last_exc = RuntimeError(
                f"loadCodeAssist failed: status={resp.status_code} base_url={base_url}"
            )
        except Exception as e:
            url_availability.mark_unavailable(base_url)
            last_exc = e
            continue

    raise last_exc or RuntimeError("loadCodeAssist failed")


__all__ = ["load_code_assist"]
