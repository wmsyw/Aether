"""Per-request context shared across layers.

We use `contextvars` so the transport layer (URL builder) can pass small bits of
state to the handler layer without changing existing return types.

This is intentionally minimal; only add fields that are safe and cheap to carry
per request.
"""

from __future__ import annotations

import contextvars

_selected_base_url: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "provider_selected_base_url",
    default=None,
)


def set_selected_base_url(url: str | None) -> None:
    _selected_base_url.set(url)


def get_selected_base_url() -> str | None:
    return _selected_base_url.get()


__all__ = ["get_selected_base_url", "set_selected_base_url"]
