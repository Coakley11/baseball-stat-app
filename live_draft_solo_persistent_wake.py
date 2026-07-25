"""Production Solo expiration wake — early LDR entry, persistent widget key."""

from __future__ import annotations

from typing import Any

SOLO_PERSISTENT_WAKE_LATCH_KEY = "_solo_persistent_wake_early_latch"
SOLO_PERSISTENT_WAKE_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
SOLO_PERSISTENT_WAKE_TOKEN_KEY = "_solo_persistent_wake_last_token"
SOLO_PERSISTENT_WAKE_SESSION_PREFIX = "_solo_persistent_wake_"
SOLO_INERT_EXPIRE_TOKEN = ""
SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY = "_solo_persistent_wake_actionable"
SOLO_PERSISTENT_WAKE_DECLARED_ON_SETUP_KEY = "_solo_persistent_wake_declared_on_setup"
SOLO_PERSISTENT_WAKE_PICK_LATCH_KEY = "_solo_persistent_wake_pick_latch"


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
        from live_draft_solo_bridge_transition_diag import bridge_transition_active

        if bridge_transition_active(st, session):
            return True
    except ImportError:
        pass
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
    live = session.get("live_draft_room")
    if isinstance(live, dict) and live:
        return live
    if isinstance(room, dict) and room:
        return room
    return None


def build_solo_idle_expire_token(*, draft_id: str = "idle") -> str:
    """Legacy idle token — do not use for production inert mount (use SOLO_INERT_EXPIRE_TOKEN)."""
    return SOLO_INERT_EXPIRE_TOKEN


def resolve_persistent_wake_mount(
    session: dict[str, Any], room: dict[str, Any] | None
) -> tuple[bool, str, dict[str, Any], str]:
    """Return (actionable, expire_token, props_room, lifecycle_phase)."""
    from solo_countdown_component import build_solo_expire_token

    setup_props: dict[str, Any] = {
        "draft_room_id": "",
        "draft_id": "",
        "current_pick_index": 0,
        "status": "setup",
        "config": {"draft_setup_mode": "solo"},
    }
    if not room:
        return False, SOLO_INERT_EXPIRE_TOKEN, setup_props, "setup"

    try:
        from live_draft_solo_timer import is_solo_live_draft

        if not is_solo_live_draft(session, room):
            return False, SOLO_INERT_EXPIRE_TOKEN, {**setup_props, **room, "status": "setup"}, "setup"
    except ImportError:
        pass

    if str(room.get("status") or "") != "in_progress":
        phase = "paused" if str(room.get("status") or "") == "paused" else "setup"
        return False, SOLO_INERT_EXPIRE_TOKEN, {**room, "status": str(room.get("status") or "setup")}, phase

    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        deadline = live_draft_timer_deadline(room)
    except ImportError:
        deadline = None
    if deadline is None:
        raw = room.get("timer_deadline")
        deadline = float(raw) if raw is not None else None
    if deadline is None:
        try:
            from live_draft_solo_timer import is_solo_live_draft

            if is_solo_live_draft(session, room):
                token = build_solo_expire_token(room)
                return True, token, room, "active"
        except ImportError:
            pass
        return False, SOLO_INERT_EXPIRE_TOKEN, room, "setup"

    token = build_solo_expire_token(room)
    return True, token, room, "active"


def _apply_actionable_hold(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    actionable: bool,
    expire_token: str,
    props_room: dict[str, Any],
    phase: str,
) -> tuple[bool, str, dict[str, Any], str]:
    """Keep the same active mount through transient reruns while a pick timer is expiring."""
    if actionable:
        session[SOLO_PERSISTENT_WAKE_PICK_LATCH_KEY] = int(props_room.get("current_pick_index") or 0)
        return actionable, expire_token, props_room, phase
    if not session.get(SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY):
        return actionable, expire_token, props_room, phase
    if not isinstance(room, dict) or str(room.get("status") or "") != "in_progress":
        return actionable, expire_token, props_room, phase
    latched = session.get(SOLO_PERSISTENT_WAKE_PICK_LATCH_KEY)
    pick = int(room.get("current_pick_index") or 0)
    if latched is None or int(latched) != pick:
        return actionable, expire_token, props_room, phase
    held_token = str(session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or "").strip()
    if not held_token or held_token == SOLO_INERT_EXPIRE_TOKEN:
        return actionable, expire_token, props_room, phase
    return True, held_token, room, "active"


def expire_token_for_persistent_wake(
    session: dict[str, Any], room: dict[str, Any] | None
) -> tuple[str, dict[str, Any]]:
    """Test/helper wrapper — returns (expire_token, props_room) only."""
    _actionable, token, props, _phase = resolve_persistent_wake_mount(session, room)
    return token, props


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
    actionable, _, _, _ = resolve_persistent_wake_mount(session, room)
    return actionable


def render_persistent_wake_lifecycle_probe(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    actionable: bool,
    phase: str,
    expire_token: str,
) -> None:
    if not session.get(SOLO_PERSISTENT_WAKE_DECLARED_ON_SETUP_KEY) and not actionable:
        session[SOLO_PERSISTENT_WAKE_DECLARED_ON_SETUP_KEY] = True
    st.markdown(
        f'<div id="solo-persistent-wake-lifecycle-diag" '
        f'data-key="{widget_key}" '
        f'data-actionable="{1 if actionable else 0}" '
        f'data-phase="{phase}" '
        f'data-declared-on-setup="{1 if session.get(SOLO_PERSISTENT_WAKE_DECLARED_ON_SETUP_KEY) else 0}" '
        f'data-token="{str(expire_token or "").replace(chr(34), chr(39))}" '
        f'data-same-key="{1 if widget_key == SOLO_PERSISTENT_WAKE_WIDGET_KEY else 0}"></div>',
        unsafe_allow_html=True,
    )


def _production_deliver_callback(st: Any, session: dict[str, Any], raw: Any, key: str) -> None:
    from live_draft_solo_heartbeat import _coerce_wake_token, process_solo_component_wake

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
    token = _coerce_wake_token(raw)
    if not session.get(SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY):
        return
    if not token or token == SOLO_INERT_EXPIRE_TOKEN:
        return
    live = _resolve_room(session, None)
    if not isinstance(live, dict):
        return
    process_solo_component_wake(st, session, live, token, delivery_via="on_change")
    session.pop(SOLO_PERSISTENT_WAKE_PICK_LATCH_KEY, None)


def flush_persistent_wake_delivery(st: Any, session: dict[str, Any]) -> None:
    """After widget values bind, deliver expire token from session_state (on_change equivalent)."""
    if session.get("_solo_persistent_wake_flush_disabled"):
        return
    try:
        from live_draft_solo_bridge_transition_diag import bridge_transition_active

        if bridge_transition_active(st, session):
            return
    except ImportError:
        pass
    if not solo_persistent_wake_active(session):
        return
    key = solo_persistent_wake_widget_key(session)
    raw = st.session_state.get(key)
    if raw is None:
        return
    from live_draft_solo_heartbeat import _coerce_wake_token

    token = _coerce_wake_token(raw)
    if not token or token == SOLO_INERT_EXPIRE_TOKEN:
        return
    _production_deliver_callback(st, session, raw, key)


def try_solo_persistent_wake_ldr_entry(st: Any, session: dict[str, Any], room: Any) -> bool:
    """Mount/update the Solo wake at LDR page entry. Never st.stop(). Returns True when handled."""
    if not _should_mount_persistent_wake(st, session):
        return False

    from live_draft_solo_delivery_diag import render_parent_postmessage_listener

    render_parent_postmessage_listener(st)

    from solo_countdown_wake_micro_core import render_micro_isolation_once

    room_dict = _resolve_room(session, room)
    session[SOLO_PERSISTENT_WAKE_LATCH_KEY] = True

    key = solo_persistent_wake_widget_key(session)
    from live_draft_solo_heartbeat import _coerce_wake_token

    pending_raw = st.session_state.get(key)
    pending_token = _coerce_wake_token(pending_raw)
    delivery_only = bool(
        pending_token
        and pending_token != SOLO_INERT_EXPIRE_TOKEN
        and pending_raw is not None
        and session.get(SOLO_PERSISTENT_WAKE_LATCH_KEY)
    )
    if pending_token and pending_token != SOLO_INERT_EXPIRE_TOKEN:
        props_room = room_dict if isinstance(room_dict, dict) else {}
        actionable = True
        expire_token = pending_token
        phase = "active"
    else:
        actionable, expire_token, props_room, phase = resolve_persistent_wake_mount(session, room_dict)
        actionable, expire_token, props_room, phase = _apply_actionable_hold(
            session, room_dict, actionable, expire_token, props_room, phase
        )
    session[SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY] = actionable
    session[SOLO_PERSISTENT_WAKE_TOKEN_KEY] = expire_token
    key = solo_persistent_wake_widget_key(session)
    did = str(props_room.get("draft_room_id") or props_room.get("draft_id") or "")

    render_micro_isolation_once(
        st,
        session,
        placement="PROD",
        location="ldr_page_entry_early_persistent",
        draft_id=did,
        route=True,
        persistent=True,
        session_prefix=SOLO_PERSISTENT_WAKE_SESSION_PREFIX,
        widget_key=key,
        production_room=props_room,
        production_expire_token=expire_token,
        production_actionable=actionable,
        production_delivery_only=delivery_only,
        deliver_callback=_production_deliver_callback,
    )
    render_persistent_wake_lifecycle_probe(
        st,
        session,
        widget_key=key,
        actionable=actionable,
        phase=phase,
        expire_token=expire_token,
    )
    try:
        from live_draft_solo_component_diagnostics import (
            record_solo_component_mount_attempt,
            solo_component_diag_enabled,
        )

        if solo_component_diag_enabled(st, session):
            record_solo_component_mount_attempt(
                session,
                props_room,
                key=solo_persistent_wake_widget_key(session),
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
            widget_key=solo_persistent_wake_widget_key(session),
            expire_token=expire_token,
            room_status=str((room_dict or {}).get("status") or ""),
        )
    except ImportError:
        pass
    return True
