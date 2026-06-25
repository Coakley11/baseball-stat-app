"""Live draft timer display and diagnostics — fragment-safe (no streamlit_app imports)."""

from __future__ import annotations

import time
from typing import Any

from live_draft_timer_logic import (
    live_draft_display_seconds,
    live_draft_seconds_remaining,
    live_draft_timer_deadline,
)

LIVE_DRAFT_TIMER_DIAG_KEY = "_live_draft_timer_diag"
LIVE_DRAFT_TIMER_EXPIRED_KEY = "_live_draft_timer_expired_pending"
_AUTOPICK_GRACE_SEC = 2.0


def record_timer_diagnostics(session: dict[str, Any], room: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    cfg = dict(room.get("config") or {})
    timer_seconds = int(cfg.get("timer_seconds") or 60)
    started = room.get("timer_started_at")
    remaining = live_draft_display_seconds(room)
    diag = {
        "timer_start_time": started,
        "timer_deadline": live_draft_timer_deadline(room),
        "seconds_remaining": remaining,
        "timer_refresh_source": source or None,
        "timer_tick_active": bool(source == "fragment_tick"),
        "autopick_enabled": room.get("status") == "in_progress",
        "current_pick_index": room.get("current_pick_index"),
        "timer_handled_index": room.get("timer_handled_index"),
        "draft_status": room.get("status"),
    }
    session[LIVE_DRAFT_TIMER_DIAG_KEY] = diag
    return diag


def _page_load_grace_active(session: dict[str, Any]) -> bool:
    loaded = float(session.get("_live_draft_page_load_ts") or 0)
    if loaded <= 0:
        return False
    return (time.time() - loaded) < _AUTOPICK_GRACE_SEC


def note_live_draft_page_load(session: dict[str, Any]) -> None:
    session["_live_draft_page_load_ts"] = time.time()


def _timer_expired_pending(session: dict[str, Any], room: dict[str, Any]) -> bool:
    if room.get("status") != "in_progress":
        return False
    if _page_load_grace_active(session):
        return False
    idx = int(room.get("current_pick_index", 0))
    if room.get("timer_handled_index") == idx:
        return False
    return live_draft_seconds_remaining(room) <= 0


def render_live_draft_timer_diagnostics(st: Any, session: dict[str, Any]) -> None:
    raw = session.get(LIVE_DRAFT_TIMER_DIAG_KEY)
    if not isinstance(raw, dict):
        return
    with st.expander("Draft timer diagnostics", expanded=False):
        for key in (
            "timer_start_time",
            "timer_deadline",
            "seconds_remaining",
            "timer_refresh_source",
            "timer_tick_active",
            "autopick_enabled",
            "autopick_triggered",
            "autopick_reason",
            "autopick_deadline",
            "autopick_elapsed_seconds",
            "current_pick_index",
            "timer_handled_index",
            "draft_status",
        ):
            val = raw.get(key)
            st.text(f"{key}: {val if val is not None and val != '' else '—'}")


def render_live_draft_timer_bar(st: Any, session: dict[str, Any], room: dict[str, Any]) -> None:
    """Countdown that refreshes every second via Streamlit fragment when available."""
    try:
        fragment = st.fragment
    except AttributeError:
        _render_timer_static(st, session, room)
        return

    @fragment(run_every=1)
    def _timer_tick() -> None:
        _render_timer_static(st, session, room, source="fragment_tick")
        if _timer_expired_pending(session, room):
            session[LIVE_DRAFT_TIMER_EXPIRED_KEY] = True
            st.rerun()

    _timer_tick()


def _render_timer_static(st: Any, session: dict[str, Any], room: dict[str, Any], *, source: str = "static") -> None:
    remaining = live_draft_display_seconds(room)
    record_timer_diagnostics(session, room, source=source)
    st.markdown(f"**Time on clock:** {remaining}s")
