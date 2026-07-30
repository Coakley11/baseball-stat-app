"""Stage 1A post-commit next-timer continuity: ledger + session cleanup after autopick commit."""

from __future__ import annotations

import copy
import time
from typing import Any

SOLO_INERT_EXPIRE_TOKEN = ""


def _script_run_seq(session: dict[str, Any]) -> int:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _room_fingerprint(room: dict[str, Any] | None) -> str:
    if not isinstance(room, dict):
        return ""
    try:
        from live_draft_solo_declaration_room_context import _room_fingerprint

        return str(_room_fingerprint(room) or "")
    except ImportError:
        rid = str(room.get("draft_room_id") or room.get("draft_id") or "")
        return f"{rid}:{room.get('current_pick_index')}:{room.get('status')}"


def _deadline_for_room(room: dict[str, Any]) -> float | None:
    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        dl = live_draft_timer_deadline(room)
        if dl is not None:
            return float(dl)
    except ImportError:
        pass
    if room.get("timer_deadline") is not None:
        return float(room.get("timer_deadline") or 0.0)
    return None


def _state_snapshot(
    st: Any | None,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    expected_token: str = "",
    completed_token: str = "",
) -> dict[str, Any]:
    pick_index = int(room.get("current_pick_index") or 0)
    deadline = _deadline_for_room(room)
    ss_token = ""
    ss_deadline = None
    widget_key = ""
    try:
        from live_draft_solo_persistent_wake import solo_persistent_wake_widget_key

        widget_key = solo_persistent_wake_widget_key(session)
        if st is not None and widget_key:
            ss_token = str(st.session_state.get(widget_key) or "")[:400]
    except ImportError:
        pass
    action_complete = None
    try:
        from live_draft_stage1_expire_audit import get_token_action_complete

        if completed_token:
            action_complete = get_token_action_complete(session, completed_token)
    except ImportError:
        pass
    return {
        "room_id": str(room.get("draft_room_id") or room.get("draft_id") or "").strip(),
        "room_fingerprint": _room_fingerprint(room),
        "pick_index": pick_index,
        "pick_number": pick_index + 1,
        "room_status": str(room.get("status") or ""),
        "previous_deadline": None,
        "current_deadline": deadline,
        "previous_token": str(completed_token or "")[:400],
        "expected_current_token": str(expected_token or "")[:400],
        "canonical_deadline": deadline,
        "canonical_token": str(expected_token or "")[:400],
        "session_state_token": ss_token,
        "session_state_deadline": ss_deadline,
        "declaration_token": "",
        "widget_key": widget_key,
        "action_complete_token": str(completed_token or "")[:400],
        "old_token_suppressed": bool(action_complete),
        "revision": str(room.get("revision") or room.get("_revision") or "")[:120],
        "script_run_seq": _script_run_seq(session),
    }


def _note(st: Any | None, session: dict[str, Any], event: str, room: dict[str, Any] | None, extra: dict[str, Any]) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled
    except ImportError:
        return
    if not stage1_production_ledger_enabled(st, session):
        return
    note_stage1_event(session, event, st=st, room=room, extra=extra)


def pending_mount_token_usable(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    pending_token: str,
    *,
    pending_raw: Any = None,
) -> bool:
    """True only when session-bound widget value matches the current on-clock pick timer."""
    tok = str(pending_token or "").strip()
    if not tok or tok == SOLO_INERT_EXPIRE_TOKEN:
        return False
    if pending_raw is None:
        return False
    try:
        from live_draft_stage1_expire_audit import is_token_action_complete

        if is_token_action_complete(session, tok):
            return False
    except ImportError:
        pass
    try:
        from live_draft_solo_persistent_wake import SOLO_SKIP_LATE_FLUSH_TOKEN_KEY

        if tok == str(session.get(SOLO_SKIP_LATE_FLUSH_TOKEN_KEY) or ""):
            return False
    except ImportError:
        pass
    try:
        from live_draft_solo_heartbeat import SOLO_COMPONENT_WAKE_SEEN_KEY

        if tok == str(session.get(SOLO_COMPONENT_WAKE_SEEN_KEY) or ""):
            return False
    except ImportError:
        pass
    if not isinstance(room, dict):
        return False
    try:
        from solo_countdown_component import build_solo_expire_token, parse_solo_expire_token

        canonical = build_solo_expire_token(room)
        if tok == canonical:
            return True
        parsed = parse_solo_expire_token(tok)
        if not parsed:
            return False
        if int(parsed.get("pick_index") or -1) != int(room.get("current_pick_index") or 0):
            return False
        live_dl = _deadline_for_room(room)
        tok_dl = float(parsed.get("deadline") or 0.0)
        if live_dl is not None and tok_dl > 0 and abs(float(live_dl) - tok_dl) > 0.75:
            return False
    except ImportError:
        return False
    return True


def compute_next_pick_timer_state(room: dict[str, Any]) -> tuple[str, float | None]:
    from solo_countdown_component import build_solo_expire_token

    token = build_solo_expire_token(room)
    return token, _deadline_for_room(room)


def finalize_post_commit_timer_continuity(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    completed_token: str,
    result: Any | None = None,
) -> dict[str, Any]:
    """After a successful expire commit, persist next-pick timer and drop stale mount inputs."""
    if not isinstance(room, dict):
        return {"ok": False, "reason": "no_room"}
    room_copy = copy.deepcopy(room)
    prev_deadline = None
    try:
        from solo_countdown_component import parse_solo_expire_token

        parsed = parse_solo_expire_token(str(completed_token or ""))
        if parsed:
            prev_deadline = float(parsed.get("deadline") or 0.0)
    except ImportError:
        pass

    snap_enter = _state_snapshot(st, session, room_copy, completed_token=completed_token)
    snap_enter["previous_deadline"] = prev_deadline
    _note(st, session, "production_stage1_post_commit_state_entered", room_copy, snap_enter)

    next_token, next_deadline = compute_next_pick_timer_state(room_copy)
    next_snap = dict(snap_enter)
    next_snap.update(
        {
            "expected_current_token": next_token[:400],
            "canonical_token": next_token[:400],
            "current_deadline": next_deadline,
            "canonical_deadline": next_deadline,
        }
    )
    _note(st, session, "production_stage1_next_pick_state_computed", room_copy, next_snap)
    _note(
        st,
        session,
        "production_stage1_next_deadline_about_to_create",
        room_copy,
        {"current_deadline": next_deadline, "pick_index": int(room_copy.get("current_pick_index") or 0)},
    )
    if next_deadline is not None:
        _note(
            st,
            session,
            "production_stage1_next_deadline_created",
            room_copy,
            {"current_deadline": next_deadline, "pick_index": int(room_copy.get("current_pick_index") or 0)},
        )
    _note(
        st,
        session,
        "production_stage1_next_token_created",
        room_copy,
        {"expected_current_token": next_token[:400], "pick_index": int(room_copy.get("current_pick_index") or 0)},
    )

    try:
        from live_draft_solo_persistent_wake import (
            SOLO_PERSISTENT_WAKE_PICK_LATCH_KEY,
            SOLO_PERSISTENT_WAKE_TOKEN_KEY,
            solo_persistent_wake_widget_key,
        )

        session[SOLO_PERSISTENT_WAKE_TOKEN_KEY] = next_token
        session[SOLO_PERSISTENT_WAKE_PICK_LATCH_KEY] = int(room_copy.get("current_pick_index") or 0)
        widget_key = solo_persistent_wake_widget_key(session)
        try:
            from live_draft_stage1_expire_audit import clear_persistent_wake_widget_value

            clear_persistent_wake_widget_value(st, session, completed_token)
        except ImportError:
            pass
        if widget_key and st is not None:
            try:
                cur = st.session_state.get(widget_key)
                if cur is not None and str(cur).strip() == str(completed_token or "").strip():
                    del st.session_state[widget_key]
            except Exception:
                pass
    except ImportError:
        widget_key = ""

    try:
        from live_draft_solo_declaration_room_context import (
            clear_declaration_room_context,
            register_production_countdown_declaration_context,
        )

        clear_declaration_room_context(session, reason="post_commit_pick_advanced")
        register_production_countdown_declaration_context(
            st,
            session,
            room=room_copy,
            expected_token=next_token,
            widget_key=widget_key or "solo_countdown_wake_solo_persistent",
        )
    except ImportError:
        pass

    persisted = _state_snapshot(st, session, room_copy, expected_token=next_token, completed_token=completed_token)
    persisted["previous_deadline"] = prev_deadline
    _note(st, session, "production_stage1_next_room_state_persisted", room_copy, persisted)

    rerun_requested = False
    try:
        from live_draft_safe_mode import request_live_draft_rerun

        rerun_requested = bool(
            request_live_draft_rerun(st, session, "solo_post_commit_next_timer", room=room_copy)
        )
    except ImportError:
        pass
    _note(
        st,
        session,
        "production_stage1_post_commit_rerun_requested",
        room_copy,
        {"rerun_requested": rerun_requested, "expected_current_token": next_token[:400]},
    )
    if rerun_requested:
        _note(st, session, "production_stage1_post_commit_rerun_entered", room_copy, persisted)

    return {
        "ok": True,
        "completed_token": completed_token,
        "next_token": next_token,
        "next_deadline": next_deadline,
        "pick_index": int(room_copy.get("current_pick_index") or 0),
        "rerun_requested": rerun_requested,
    }


def note_next_countdown_declaration_about_to_mount(
    st: Any | None,
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None,
    expire_token: str,
    widget_key: str,
) -> None:
    if not isinstance(room, dict):
        return
    extra = _state_snapshot(st, session, room, expected_token=expire_token)
    extra["widget_key"] = widget_key
    _note(st, session, "production_stage1_next_countdown_declaration_about_to_mount", room, extra)


def note_next_countdown_declaration_returned(
    st: Any | None,
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None,
    expire_token: str,
    returned_value: Any,
    widget_key: str,
) -> None:
    if not isinstance(room, dict):
        return
    extra = _state_snapshot(st, session, room, expected_token=expire_token)
    extra["widget_key"] = widget_key
    extra["returned_value"] = repr(returned_value)[:400]
    _note(st, session, "production_stage1_next_countdown_declaration_returned", room, extra)
