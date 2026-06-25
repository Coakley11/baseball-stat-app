"""Live draft timer display and diagnostics — fragment-safe (no streamlit_app imports)."""

from __future__ import annotations

import time
from typing import Any

from live_draft_timer_logic import (
    ensure_live_draft_timer_for_pick,
    live_draft_display_seconds,
    live_draft_seconds_remaining,
    live_draft_timer_deadline,
    live_draft_timer_expired_for_pick,
)

LIVE_DRAFT_TIMER_DIAG_KEY = "_live_draft_timer_diag"
from live_draft_expired_pick import EXPIRED_PICK_PENDING_KEY, should_fragment_trigger_full_rerun
LIVE_DRAFT_GRACE_MARKER_KEY = "_live_draft_grace_marker"
_AUTOPICK_GRACE_SEC = 2.0


def record_timer_diagnostics(session: dict[str, Any], room: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    cfg = dict(room.get("config") or {})
    started = room.get("timer_started_at")
    remaining = live_draft_display_seconds(room)
    prev = dict(session.get(LIVE_DRAFT_TIMER_DIAG_KEY) or {})
    tick_active = bool(source == "fragment_tick") or bool(prev.get("timer_tick_active"))
    diag = {
        "timer_start_time": started,
        "timer_deadline": live_draft_timer_deadline(room),
        "seconds_remaining": remaining,
        "timer_refresh_source": source or prev.get("timer_refresh_source"),
        "timer_tick_active": tick_active,
        "autopick_enabled": room.get("status") == "in_progress",
        "current_pick_index": room.get("current_pick_index"),
        "timer_handled_index": room.get("timer_handled_index"),
        "draft_status": room.get("status"),
        "page_load_grace_active": _page_load_grace_active(session, room),
        "timer_expired_for_pick": live_draft_timer_expired_for_pick(room),
    }
    if source.endswith("_grace_skip"):
        diag["autopick_skipped_reason"] = "page_load_grace"
    session[LIVE_DRAFT_TIMER_DIAG_KEY] = diag
    return diag


def _grace_marker(session: dict[str, Any], room: dict[str, Any]) -> tuple[str, int]:
    page = str(session.get("active_page") or session.get("_shared_draft_poll_active_page") or "Live Draft Room")
    idx = int(room.get("current_pick_index") or 0)
    return page, idx


def _page_load_grace_active(session: dict[str, Any], room: dict[str, Any] | None = None) -> bool:
    loaded = float(session.get("_live_draft_page_load_ts") or 0)
    if loaded <= 0:
        return False
    if room is not None and live_draft_timer_expired_for_pick(room):
        return False
    return (time.time() - loaded) < _AUTOPICK_GRACE_SEC


def note_live_draft_page_load(session: dict[str, Any], room: dict[str, Any]) -> None:
    """Start grace window only when entering Live Draft or when pick index advances — not every rerun."""
    marker = _grace_marker(session, room)
    if session.get(LIVE_DRAFT_GRACE_MARKER_KEY) != marker:
        session[LIVE_DRAFT_GRACE_MARKER_KEY] = marker
        session["_live_draft_page_load_ts"] = time.time()


def _resolve_live_room(session: dict[str, Any], room: dict[str, Any]) -> dict[str, Any]:
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        live = session.get(LIVE_DRAFT_ROOM_KEY)
        if isinstance(live, dict):
            return live
    except ImportError:
        pass
    return room


def _timer_expired_pending(session: dict[str, Any], room: dict[str, Any]) -> bool:
    live_room = _resolve_live_room(session, room)
    if live_room.get("status") != "in_progress":
        return False
    if _page_load_grace_active(session, live_room):
        return False
    return live_draft_timer_expired_for_pick(live_room)


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
            "page_load_grace_active",
            "timer_expired_for_pick",
            "autopick_enabled",
            "autopick_skipped_reason",
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
    live_room = _resolve_live_room(session, room)
    ensure_live_draft_timer_for_pick(live_room)

    try:
        fragment = st.fragment
    except AttributeError:
        _render_timer_static(st, session, live_room, source="static_no_fragment")
        return

    @fragment(run_every=1)
    def _timer_tick() -> None:
        tick_room = _resolve_live_room(session, room)
        ensure_live_draft_timer_for_pick(tick_room)
        _render_timer_static(st, session, tick_room, source="fragment_tick")
        if should_fragment_trigger_full_rerun(session, tick_room):
            session[EXPIRED_PICK_PENDING_KEY] = True
            st.rerun()

    _timer_tick()


def _render_timer_static(st: Any, session: dict[str, Any], room: dict[str, Any], *, source: str = "static") -> None:
    remaining = live_draft_display_seconds(room)
    record_timer_diagnostics(session, room, source=source)
    st.markdown(f"**Time on clock:** {remaining}s")
