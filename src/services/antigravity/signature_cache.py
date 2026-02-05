"""Antigravity thinking block signature cache (minimal)."""

from __future__ import annotations

import hashlib
import threading

from src.services.antigravity.constants import DUMMY_THOUGHT_SIGNATURE


class ThinkingSignatureCache:
    """缓存 thinking block 签名。

    说明：
    - 优先使用缓存（比客户端透传更可靠）
    - Gemini 模型允许使用 dummy signature 作为兜底（跳过验证）
    - 线程安全
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._cache: dict[str, str] = {}
        self._maxsize = maxsize
        self._lock = threading.Lock()

    def get_or_dummy(self, model: str, thinking_text: str) -> str | None:
        key = self._key(model, thinking_text)
        with self._lock:
            cached = self._cache.get(key)
        if cached:
            return cached
        if str(model).startswith("gemini-"):
            return DUMMY_THOUGHT_SIGNATURE
        return None

    def cache(self, model: str, thinking_text: str, signature: str) -> None:
        key = self._key(model, thinking_text)

        with self._lock:
            if key in self._cache:
                self._cache[key] = signature
                return

            if len(self._cache) >= self._maxsize:
                # 简单 FIFO 清理（dict 保持插入顺序）
                evict_n = max(1, self._maxsize // 4)
                for k in list(self._cache.keys())[:evict_n]:
                    self._cache.pop(k, None)

            self._cache[key] = signature

    def _key(self, model: str, thinking_text: str) -> str:
        content = f"{model}:{thinking_text}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


signature_cache = ThinkingSignatureCache()

__all__ = ["ThinkingSignatureCache", "signature_cache"]
