"""Antigravity 全局常量定义。

注意：这里的 PROVIDER_TYPE 指的是 Provider.provider_type（用于路由与特判），
不是 endpoint signature（family:kind）。
"""

from __future__ import annotations

# ============== Provider 标识 ==============
PROVIDER_TYPE = "antigravity"

# ============== API 端点 ==============
PROD_BASE_URL = "https://cloudcode-pa.googleapis.com"
DAILY_BASE_URL = "https://daily-cloudcode-pa.sandbox.googleapis.com"

# ============== User-Agent ==============
# HTTP Header
HTTP_USER_AGENT = "antigravity/1.15.8 windows/amd64"
# V1InternalRequest.userAgent 字段
REQUEST_USER_AGENT = "antigravity"

# ============== URL 可用性 ==============
URL_UNAVAILABLE_TTL_SECONDS = 300  # 5 分钟

# ============== Thinking Signature ==============
DUMMY_THOUGHT_SIGNATURE = "skip_thought_signature_validator"

# ============== v1internal 路径 ==============
V1INTERNAL_PATH_TEMPLATE = "/v1internal:{action}"

__all__ = [
    "DAILY_BASE_URL",
    "DUMMY_THOUGHT_SIGNATURE",
    "HTTP_USER_AGENT",
    "PROD_BASE_URL",
    "PROVIDER_TYPE",
    "REQUEST_USER_AGENT",
    "URL_UNAVAILABLE_TTL_SECONDS",
    "V1INTERNAL_PATH_TEMPLATE",
]
