"""Timer auto-pick orchestration — runs on full page reruns, not inside fragments."""

from __future__ import annotations

import time
from typing import Any

from live_draft_timer_logic import live_draft_current_slot, live_draft_seconds_remaining

LIVE_DRAFT_TIMER_EXPIRED_KEY = "_live_draft_timer_expired_pending"
_AUTOPICK_GRACE_SEC = 2.0


def _page_load_grace_active(session: dict[str, Any]) -> bool:
    loaded = float(session.get("_live_draft_page_load_ts") or 0)
    if loaded <= 0:
        return False
    return (time.time() - loaded) < _AUTOPICK_GRACE_SEC


def maybe_timer_autopick(session: dict[str, Any], room: dict[str, Any], *, source: str) -> tuple[bool, str]:
    """Run auto-pick when timer expired; skip during page-load grace."""
    from live_draft_timer_ui import record_timer_diagnostics

    if room.get("status") != "in_progress":
        session.pop(LIVE_DRAFT_TIMER_EXPIRED_KEY, None)
        return False, ""
    if _page_load_grace_active(session):
        record_timer_diagnostics(session, room, source=f"{source}_grace_skip")
        return False, ""

    try:
        from streamlit_app import live_draft_auto_pick
    except ImportError:
        try:
            from Streamlit_app import live_draft_auto_pick  # type: ignore[no-redef]
        except ImportError:
            return False, ""

    idx = int(room.get("current_pick_index", 0))
    remaining = live_draft_seconds_remaining(room)
    record_timer_diagnostics(session, room, source=source)
    if remaining > 0 or room.get("timer_handled_index") == idx:
        session.pop(LIVE_DRAFT_TIMER_EXPIRED_KEY, None)
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
    session.pop(LIVE_DRAFT_TIMER_EXPIRED_KEY, None)
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
