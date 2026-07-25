"""Production Solo expiration wake — early LDR entry, persistent widget key."""

from __future__ import annotations

import time
from typing import Any

SOLO_PERSISTENT_WAKE_LATCH_KEY = "_solo_persistent_wake_early_latch"
SOLO_PERSISTENT_WAKE_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
SOLO_PERSISTENT_WAKE_TOKEN_KEY = "_solo_persistent_wake_last_token"
SOLO_PERSISTENT_WAKE_MOUNTED_KEY = "_solo_persistent_wake_component_mounted"
SOLO_PERSISTENT_WAKE_MOUNTED_TOKEN_KEY = "_solo_persistent_wake_mounted_token"
SOLO_IDLE_DRAFT_ID = "idle"
SOLO_IDLE_DEADLINE = 9999999999.999


def solo_persistent_wake_widget_key(_session: dict[str, Any] | None = None) -> str:
    """One stable Streamlit widget key for the entire Solo draft session."""
    return SOLO_PERSISTENT_WAKE_WIDGET_KEY


def solo_persistent_wake_active(session: dict[str, Any]) -> bool:
    """True when early-route production wake owns expiration (Cloud wake owner)."""
    if not session.get(SOLO_PERSISTENT_WAKE_LATCH_KEY):
        return False
    try:
        from live_draft_solo_expire_chain import solo_expire_owner

        return solo_expire_owner(session) == "wake"
    except ImportError:
        return bool(session.get(SOLO_PERSISTENT_WAKE_LATCH_KEY))


def _diag_blocks_persistent_wake(st: Any, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_early_bridge_diag import early_bridge_active

        if early_bridge_active(st, session):
            return True
    except ImportError:
        pass
    try:
        from live_draft_solo_placement_micro import micro_isolation_active

        if micro_isolation_active(st, session):
            return True
    except ImportError:
        pass
    try:
        from live_draft_solo_placement_ladder import placement_ladder_active

        if placement_ladder_active(st, session):
            return True
    except ImportError:
        pass
    try:
        from live_draft_solo_delivery_diag import delivery_diag_active, delivery_matrix_cell

        if delivery_diag_active(st, session) and delivery_matrix_cell(st) > 0:
            return True
    except ImportError:
        pass
    return False


def _resolve_room(session: dict[str, Any], room: Any) -> dict[str, Any] | None:
    if isinstance(room, dict) and room:
        return room
    live = session.get("live_draft_room")
    return live if isinstance(live, dict) else None


def build_solo_idle_expire_token(*, draft_id: str = SOLO_IDLE_DRAFT_ID) -> str:
    did = str(draft_id or SOLO_IDLE_DRAFT_ID).strip() or SOLO_IDLE_DRAFT_ID
    return f"{did}|0|{SOLO_IDLE_DEADLINE:.3f}"


def expire_token_for_persistent_wake(session: dict[str, Any], room: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """Return (expire_token, props_room) for component mount — idle when no actionable timer."""
    from solo_countdown_component import build_solo_expire_token

    if not room:
        tok = build_solo_idle_expire_token()
        return tok, {
            "draft_room_id": SOLO_IDLE_DRAFT_ID,
            "draft_id": SOLO_IDLE_DRAFT_ID,
            "current_pick_index": 0,
            "status": "setup",
            "timer_deadline": SOLO_IDLE_DEADLINE,
        }
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if not is_solo_live_draft(session, room):
            tok = build_solo_idle_expire_token(
                draft_id=str(room.get("draft_room_id") or room.get("draft_id") or SOLO_IDLE_DRAFT_ID)
            )
            return tok, {
                **room,
                "status": "setup",
                "timer_deadline": SOLO_IDLE_DEADLINE,
                "current_pick_index": int(room.get("current_pick_index") or 0),
            }
    except ImportError:
        pass
    if str(room.get("status") or "") != "in_progress":
        did = str(room.get("draft_room_id") or room.get("draft_id") or SOLO_IDLE_DRAFT_ID)
        return build_solo_idle_expire_token(draft_id=did), {
            **room,
            "status": str(room.get("status") or "setup"),
            "timer_deadline": SOLO_IDLE_DEADLINE,
            "current_pick_index": int(room.get("current_pick_index") or 0),
        }
    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        deadline = live_draft_timer_deadline(room)
    except ImportError:
        deadline = None
    if deadline is None:
        raw = room.get("timer_deadline")
        deadline = float(raw) if raw is not None else None
    if deadline is None:
        did = str(room.get("draft_room_id") or room.get("draft_id") or SOLO_IDLE_DRAFT_ID)
        return build_solo_idle_expire_token(draft_id=did), {
            **room,
            "timer_deadline": SOLO_IDLE_DEADLINE,
        }
    return build_solo_expire_token(room), room


def _should_mount_persistent_wake(st: Any, session: dict[str, Any]) -> bool:
    if _diag_blocks_persistent_wake(st, session):
        return False
    try:
        from live_draft_solo_expire_chain import solo_expire_owner

        if solo_expire_owner(session) != "wake":
            return False
    except ImportError:
        return False
    return True


def _actionable_solo_timer(session: dict[str, Any], room: dict[str, Any] | None) -> bool:
    if not room:
        return False
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if not is_solo_live_draft(session, room):
            return False
    except ImportError:
        return False
    if str(room.get("status") or "") != "in_progress":
        return False
    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        deadline = live_draft_timer_deadline(room)
    except ImportError:
        deadline = room.get("timer_deadline")
    if deadline is None:
        return False
    return float(deadline) < SOLO_IDLE_DEADLINE - 86400


def try_solo_persistent_wake_ldr_entry(st: Any, session: dict[str, Any], room: Any) -> bool:
    """Mount/update the Solo wake at LDR page entry. Never st.stop(). Returns True when handled."""
    if not _should_mount_persistent_wake(st, session):
        return False

    from live_draft_solo_heartbeat import _coerce_wake_token, process_solo_component_wake
    from solo_countdown_component import mount_solo_countdown_wake_with_token

    room_dict = _resolve_room(session, room)
    key = solo_persistent_wake_widget_key(session)
    session[SOLO_PERSISTENT_WAKE_LATCH_KEY] = True

    if not _actionable_solo_timer(session, room_dict):
        session[SOLO_PERSISTENT_WAKE_TOKEN_KEY] = build_solo_idle_expire_token()
        return True

    live_did = ""
    if room_dict:
        live_did = str(room_dict.get("draft_room_id") or room_dict.get("draft_id") or "")
    prev_did = str(session.get("_solo_persistent_wake_bound_draft_id") or "")
    if live_did and prev_did and live_did != prev_did:
        session.pop(SOLO_PERSISTENT_WAKE_MOUNTED_KEY, None)
        session.pop(SOLO_PERSISTENT_WAKE_MOUNTED_TOKEN_KEY, None)
    if live_did:
        session["_solo_persistent_wake_bound_draft_id"] = live_did

    expire_token, props_room = expire_token_for_persistent_wake(session, room_dict)
    session[SOLO_PERSISTENT_WAKE_TOKEN_KEY] = expire_token

    def _on_component_change() -> None:
        raw = st.session_state.get(key)
        try:
            from live_draft_solo_expire_chain import note_solo_expire_chain

            note_solo_expire_chain(
                session,
                "on_change_callback_entry",
                source="persistent_wake",
                widget_key=key,
            )
            note_solo_expire_chain(
                session,
                "session_state_raw_received",
                source="persistent_wake",
                widget_key=key,
                raw_type=type(raw).__name__ if raw is not None else "NoneType",
            )
        except ImportError:
            pass
        try:
            from live_draft_solo_delivery_diag import note_production_on_change_if_diag

            live = _resolve_room(session, room) or props_room
            note_production_on_change_if_diag(st, session, live if isinstance(live, dict) else props_room, key)
        except ImportError:
            pass
        token = _coerce_wake_token(raw)
        if not token or token == build_solo_idle_expire_token():
            return
        if token.startswith(f"{SOLO_IDLE_DRAFT_ID}|"):
            return
        live = _resolve_room(session, room) or props_room
        if not isinstance(live, dict):
            return
        process_solo_component_wake(st, session, live, token, delivery_via="on_change")

    last_mounted = str(session.get(SOLO_PERSISTENT_WAKE_MOUNTED_TOKEN_KEY) or "")
    need_declare = not session.get(SOLO_PERSISTENT_WAKE_MOUNTED_KEY) or expire_token != last_mounted
    if need_declare:
        mount_solo_countdown_wake_with_token(
            props_room,
            key=key,
            expire_token=expire_token,
            on_change=_on_component_change,
        )
        session[SOLO_PERSISTENT_WAKE_MOUNTED_KEY] = True
        session[SOLO_PERSISTENT_WAKE_MOUNTED_TOKEN_KEY] = expire_token
    else:
        raw = st.session_state.get(key)
        if raw is not None:
            _on_component_change()
    try:
        from live_draft_solo_component_diagnostics import (
            record_solo_component_mount_attempt,
            solo_component_diag_enabled,
        )

        if solo_component_diag_enabled(st, session):
            record_solo_component_mount_attempt(
                session,
                props_room,
                key=key,
                mounted=True,
                reason="persistent_early",
                expire_token=expire_token,
            )
    except ImportError:
        pass
    try:
        from live_draft_solo_expire_chain import note_solo_expire_chain

        note_solo_expire_chain(
            session,
            "persistent_wake_mounted",
            source="persistent_wake",
            widget_key=key,
            expire_token=expire_token,
            room_status=str((room_dict or {}).get("status") or ""),
        )
    except ImportError:
        pass
    return True
