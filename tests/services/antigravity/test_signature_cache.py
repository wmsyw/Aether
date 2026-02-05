from __future__ import annotations

from src.services.antigravity.constants import DUMMY_THOUGHT_SIGNATURE
from src.services.antigravity.signature_cache import ThinkingSignatureCache


def test_get_or_dummy_returns_dummy_for_gemini_models() -> None:
    cache = ThinkingSignatureCache(maxsize=10)
    assert cache.get_or_dummy("gemini-3-pro", "thinking...") == DUMMY_THOUGHT_SIGNATURE


def test_get_or_dummy_returns_none_for_non_gemini_models() -> None:
    cache = ThinkingSignatureCache(maxsize=10)
    assert cache.get_or_dummy("claude-sonnet", "thinking...") is None


def test_cached_signature_preferred() -> None:
    cache = ThinkingSignatureCache(maxsize=10)
    cache.cache("gemini-3-pro", "t", "sig-1")
    assert cache.get_or_dummy("gemini-3-pro", "t") == "sig-1"


def test_eviction_fifo() -> None:
    cache = ThinkingSignatureCache(maxsize=4)
    cache.cache("gemini-3-pro", "t1", "s1")
    cache.cache("gemini-3-pro", "t2", "s2")
    cache.cache("gemini-3-pro", "t3", "s3")
    cache.cache("gemini-3-pro", "t4", "s4")

    # Trigger eviction (evict 1 key when maxsize=4)
    cache.cache("gemini-3-pro", "t5", "s5")

    # Oldest key should be gone
    assert cache.get_or_dummy("gemini-3-pro", "t1") == DUMMY_THOUGHT_SIGNATURE

