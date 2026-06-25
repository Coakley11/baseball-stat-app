"""Live draft timer display, diagnostics, and guarded auto-pick."""

from __future__ import annotations

import time
from typing import Any

LIVE_DRAFT_TIMER_DIAG_KEY = "_live_draft_timer_diag"
_AUTOPICK_GRACE_SEC = 2.0


def record_timer_diagnostics(session: dict[str, Any], room: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    try:
        from streamlit_app import live_draft_seconds_remaining
    except ImportError:
        return {}

    cfg = dict(room.get("config") or {})
    timer_seconds = int(cfg.get("timer_seconds") or 60)
    started = room.get("timer_started_at")
    deadline = None
    if started is not None and room.get("status") == "in_progress":
        deadline = float(started) + timer_seconds
    remaining = live_draft_seconds_remaining(room) if room.get("status") == "in_progress" else int(
        room.get("paused_remaining_seconds") or timer_seconds
    )
    diag = {
        "timer_start_time": started,
        "timer_deadline": deadline,
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


def maybe_timer_autopick(session: dict[str, Any], room: dict[str, Any], *, source: str) -> tuple[bool, str]:
    """Run auto-pick when timer expired; skip during page-load grace."""
    if room.get("status") != "in_progress":
        return False, ""
    if _page_load_grace_active(session):
        record_timer_diagnostics(session, room, source=f"{source}_grace_skip")
        return False, ""

    try:
        from streamlit_app import live_draft_auto_pick, live_draft_current_slot, live_draft_seconds_remaining
    except ImportError:
        return False, ""

    idx = int(room.get("current_pick_index", 0))
    remaining = live_draft_seconds_remaining(room)
    record_timer_diagnostics(session, room, source=source)
    if remaining > 0 or room.get("timer_handled_index") == idx:
        return False, ""

    expected_revision: int | None = None
    try:
        from draft_room_context import is_multiplayer_draft_active
        from draft_room_shared_state import (
            ACTIVE_SHARED_ROOM_CODE_KEY,
            SHARED_ROOM_META_KEY,
            get_shared_room_store,
            publish_shared_room_runtime,
        )

        if is_multiplayer_draft_active(session):
            room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
            backend = get_shared_room_store()
            shared_doc = backend.load(room_code) if room_code else None
            head_rev = int(shared_doc.get("revision") or 0) if isinstance(shared_doc, dict) else 0
            meta_rev = int((session.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0)
            if head_rev > meta_rev and isinstance(shared_doc, dict):
                publish_shared_room_runtime(session, shared_doc, reason="shared_room_pre_autopick_sync")
            expected_revision = head_rev
    except ImportError:
        pass

    ok, msg = live_draft_auto_pick(room)
    room["timer_handled_index"] = idx
    diag = {
        "autopick_triggered": True,
        "autopick_reason": "timer_expired",
        "autopick_deadline": room.get("timer_started_at"),
        "autopick_elapsed_seconds": max(
            0,
            int(time.time() - float(room.get("timer_started_at") or time.time())),
        ),
    }
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        slot = live_draft_current_slot(room)
        record_draft_commit_diagnostics(
            session,
            diag,
            commit_path="timer_autopick",
            on_clock_team_after=str((slot or {}).get("Team") or ""),
            current_pick_index_after=room.get("current_pick_index"),
        )
    except ImportError:
        pass

    if ok:
        try:
            from draft_room_context import commit_shared_room_state, is_multiplayer_draft_active

            if is_multiplayer_draft_active(session):
                commit_shared_room_state(
                    session,
                    room,
                    pick_already_applied=True,
                    expected_revision=expected_revision,
                )
            else:
                from streamlit_app import _persist_live_draft_room

                _persist_live_draft_room(room, reason="timer_auto_pick", rerun=False)
        except ImportError:
            pass
    return ok, msg


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
        ok, msg = maybe_timer_autopick(session, room, source="fragment_autopick")
        if ok:
            st.toast(msg)
            st.rerun()

    _timer_tick()


def _render_timer_static(st: Any, session: dict[str, Any], room: dict[str, Any], *, source: str = "static") -> None:
    try:
        from streamlit_app import live_draft_seconds_remaining
    except ImportError:
        return
    remaining = live_draft_seconds_remaining(room) if room.get("status") == "in_progress" else int(
        room.get("paused_remaining_seconds") or room.get("config", {}).get("timer_seconds", 60)
    )
    record_timer_diagnostics(session, room, source=source)
    st.markdown(f"**Time on clock:** {remaining}s")
