"""Live interactive recommendation widgets — separate from one-shot heavy/deferred compute."""

from __future__ import annotations

import time
from typing import Any

PREPARED_REC_INTERACTIVE_KEY = "_live_draft_rec_interactive_paint_v1"
HEAVY_REC_COMPUTE_DONE_KEY = "_live_draft_heavy_rec_compute_done"


def store_prepared_rec_interactive(
    session: dict[str, Any],
    *,
    room_id: str,
    gaps: list[str] | None,
    category_needs: list[str] | None,
    max_cards: int = 6,
    multiplayer: bool = False,
) -> None:
    """Persist render inputs; top_rec rows come from REC_CACHE_KEY (no duplicate scoring)."""
    session[PREPARED_REC_INTERACTIVE_KEY] = {
        "room_id": str(room_id or "").strip(),
        "gaps": list(gaps or []),
        "category_needs": list(category_needs or []),
        "max_cards": int(max_cards),
        "multiplayer": bool(multiplayer),
        "prepared_ts": time.time(),
    }


def mark_heavy_rec_compute_done(session: dict[str, Any]) -> None:
    session[HEAVY_REC_COMPUTE_DONE_KEY] = True


def heavy_rec_compute_done(session: dict[str, Any]) -> bool:
    return bool(session.get(HEAVY_REC_COMPUTE_DONE_KEY))


def _top_rec_from_cache(session: dict[str, Any]) -> Any:
    try:
        from live_draft_ui_cache import REC_CACHE_KEY

        entry = session.get(REC_CACHE_KEY)
    except ImportError:
        entry = session.get("_live_draft_rec_cache")
    if isinstance(entry, dict):
        return entry.get("top_rec")
    return None


def render_rec_interactive_widgets(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    fmt_rate_4=None,
    fmt_int=None,
) -> bool:
    """Render recommendation card Streamlit widgets from prepared cache (live path)."""
    prep = session.get(PREPARED_REC_INTERACTIVE_KEY)
    if not isinstance(prep, dict):
        return False
    rid = str(room.get("draft_room_id") or "").strip()
    if rid and str(prep.get("room_id") or "").strip() not in ("", rid):
        return False
    top_rec = _top_rec_from_cache(session)
    if top_rec is None or getattr(top_rec, "empty", True):
        return False
    gaps = list(prep.get("gaps") or [])
    category_needs = list(prep.get("category_needs") or [])
    max_cards = int(prep.get("max_cards") or 6)
    multiplayer = bool(prep.get("multiplayer"))
    try:
        from live_draft_room_ui import render_live_draft_rec_cards, render_live_draft_rec_summary_banner

        render_live_draft_rec_summary_banner(st, top_rec, gaps=gaps)
        render_live_draft_rec_cards(
            st,
            session,
            room,
            top_rec,
            max_cards=max_cards,
            multiplayer=multiplayer,
            fmt_rate_4=fmt_rate_4,
            fmt_int=fmt_int,
            gaps=gaps,
            category_needs=category_needs,
        )
        return True
    except ImportError:
        return False


def count_add_to_queue_widget_keys_in_session(session: dict[str, Any], *, room_id: str, pick_index: int) -> int:
    """Test helper: count registered rec-card queue keys for one pick (duplicate detection)."""
    prefix = f"rec_card_queue_{str(room_id or '').strip().upper()[:16]}_{int(pick_index)}_"
    reg = session.get("_live_draft_rec_queue_render_registry")
    if not isinstance(reg, list):
        return 0
    return sum(
        1
        for row in reg
        if isinstance(row, dict) and str(row.get("widget_key") or "").startswith(prefix)
    )
