"""Diagnostic A/B: rec-card Add-to-Queue `help=` tooltip (solo_component_diag only)."""

from __future__ import annotations

from typing import Any

SOLO_REC_QUEUE_HELP_VARIANT_QP = "solo_rec_queue_help_variant"
SESSION_VARIANT_KEY = "_solo_rec_queue_help_variant"
VALID_DIAG_VARIANTS = frozenset({"with_help", "no_help"})


def _qp_get(st: Any | None, name: str) -> str:
    try:
        from live_draft_cloud_diagnostics import _qp_get as _get

        return _get(st, name)
    except ImportError:
        return ""


def _solo_diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return bool(solo_component_diag_enabled(st, session))
    except ImportError:
        return bool(session.get("_solo_component_diag_enabled"))


def latch_rec_queue_help_variant_from_query(st: Any | None, session: dict[str, Any]) -> None:
    """Persist ?solo_rec_queue_help_variant= from URL when solo diagnostics are active."""
    if not _solo_diag_enabled(st, session):
        return
    raw = str(_qp_get(st, SOLO_REC_QUEUE_HELP_VARIANT_QP) if st is not None else "").strip().lower()
    if raw == "no_help":
        session[SESSION_VARIANT_KEY] = "no_help"
    else:
        # Default control for A/B: with_help (matches production button semantics).
        session[SESSION_VARIANT_KEY] = "with_help"


def resolve_rec_queue_help_variant(st: Any | None, session: dict[str, Any]) -> tuple[str, bool]:
    """
    Returns (help_variant, help_present).

    Outside solo diagnostics: production path always uses help= (unchanged).
    """
    if not _solo_diag_enabled(st, session):
        return ("production_default", True)
    variant = str(session.get(SESSION_VARIANT_KEY) or "with_help").strip().lower()
    if variant not in VALID_DIAG_VARIANTS:
        variant = "with_help"
    if variant == "no_help":
        return ("no_help", False)
    return ("with_help", True)


def rec_queue_add_button_help_kwargs(st: Any | None, session: dict[str, Any], *, player_name: str) -> dict[str, str]:
    """Extra st.button kwargs for Add-to-Queue only — empty when help is omitted."""
    _variant, present = resolve_rec_queue_help_variant(st, session)
    if not present:
        return {}
    name = str(player_name or "").strip()
    return {"help": f"Add {name} to your draft queue."}
