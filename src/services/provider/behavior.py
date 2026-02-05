"""Provider behavior resolver.

Keep provider-specific quirks centralized so handler code stays generic.

Concepts:
- envelope: wire-level request/response wrappers and transport side-effects
- same_format_variant: subtle same-format differences (e.g. Codex)
- cross_format_variant: cross-format conversion tweaks (e.g. Antigravity thinking blocks)
"""

from __future__ import annotations

from dataclasses import dataclass

from src.services.provider.envelope import ProviderEnvelope, get_provider_envelope


@dataclass(frozen=True, slots=True)
class ProviderBehavior:
    provider_type: str
    envelope: ProviderEnvelope | None
    same_format_variant: str | None
    cross_format_variant: str | None


def get_provider_behavior(
    *,
    provider_type: str | None,
    endpoint_sig: str | None,
) -> ProviderBehavior:
    pt = str(provider_type or "").strip().lower()
    envelope = get_provider_envelope(provider_type=pt, endpoint_sig=endpoint_sig)

    # same-format variant: apply on top of passthrough (e.g. OpenAI Responses -> Codex quirks)
    same_format_variant = pt if pt in {"codex"} else None

    # cross-format variant: apply during format conversion (e.g. Claude thinking -> Gemini thought parts)
    cross_format_variant = pt if pt in {"codex", "antigravity"} else None

    return ProviderBehavior(
        provider_type=pt,
        envelope=envelope,
        same_format_variant=same_format_variant,
        cross_format_variant=cross_format_variant,
    )


__all__ = ["ProviderBehavior", "get_provider_behavior"]
