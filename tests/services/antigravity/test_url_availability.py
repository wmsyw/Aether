from __future__ import annotations

import src.services.antigravity.url_availability as ua_mod
from src.services.antigravity.constants import (
    DAILY_BASE_URL,
    PROD_BASE_URL,
    URL_UNAVAILABLE_TTL_SECONDS,
)
from src.services.antigravity.url_availability import url_availability


def _reset_state() -> None:
    # Singleton: tests need to reset global state
    with url_availability._mu:  # type: ignore[attr-defined]
        url_availability._unavailable.clear()  # type: ignore[attr-defined]
        url_availability._last_success = None  # type: ignore[attr-defined]


def test_mark_success_priority() -> None:
    _reset_state()

    url_availability.mark_success(PROD_BASE_URL)
    ordered = url_availability.get_ordered_urls(prefer_daily=True)

    assert ordered[0] == PROD_BASE_URL


def test_mark_unavailable_filters_url() -> None:
    _reset_state()

    url_availability.mark_unavailable(DAILY_BASE_URL)
    ordered = url_availability.get_ordered_urls(prefer_daily=True)

    assert ordered[0] == PROD_BASE_URL
    assert url_availability.is_available(DAILY_BASE_URL) is False


def test_ttl_recovery(monkeypatch) -> None:
    _reset_state()

    t0 = 1000.0
    monkeypatch.setattr(ua_mod.time, "time", lambda: t0)
    url_availability.mark_unavailable(PROD_BASE_URL)
    assert url_availability.is_available(PROD_BASE_URL) is False

    monkeypatch.setattr(ua_mod.time, "time", lambda: t0 + URL_UNAVAILABLE_TTL_SECONDS + 1)
    assert url_availability.is_available(PROD_BASE_URL) is True


def test_all_unavailable_fallback_returns_base_order() -> None:
    _reset_state()

    url_availability.mark_unavailable(PROD_BASE_URL)
    url_availability.mark_unavailable(DAILY_BASE_URL)

    ordered = url_availability.get_ordered_urls(prefer_daily=True)
    assert ordered == [DAILY_BASE_URL, PROD_BASE_URL]

