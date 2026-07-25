"""Paired bridge-transition diagnostic — Control A (frozen actionable) vs B (inert→active)."""

from __future__ import annotations

import json
import time
from typing import Any

from live_draft_solo_delivery_diag import (
    SOLO_DELIVERY_LOG_KEY,
    SOLO_DELIVERY_META_KEY,
    bump_delivery_rerun,
    delivery_diag_active,
    note_delivery_stage,
    render_parent_postmessage_listener,
)

TRANSITION_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
TRANSITION_LOCATION = "ldr_page_entry_early_bridge_transition"
TRANSITION_SESSION_PREFIX = "_solo_bridge_transition_"
SESSION_ENABLED = "_solo_bridge_transition_enabled"
CONTROL_KEY = "_solo_bridge_transition_control"
FROZEN_TOKEN_KEY = "_solo_bridge_transition_frozen_token"
FROZEN_DEADLINE_KEY = "_solo_bridge_transition_frozen_deadline"
ARGS_BEFORE_KEY = "_solo_bridge_transition_args_before"
ARGS_AFTER_KEY = "_solo_bridge_transition_args_after"
WIDGET_ID_BEFORE_KEY = "_solo_bridge_transition_widget_id_before"
WIDGET_ID_AFTER_KEY = "_solo_bridge_transition_widget_id_after"
ON_CHANGE_COUNT_KEY = "_solo_bridge_transition_on_change_count"
PHASE_KEY = "_solo_bridge_transition_phase"
ROOM_STATUS_LOG_KEY = "_solo_bridge_transition_room_status_log"


def _qp_get(st: Any, name: str) -> str:
    try:
        from live_draft_cloud_diagnostics import _qp_get as _get

        return _get(st, name)
    except ImportError:
        return ""


def bridge_transition_control(st: Any | None, session: dict[str, Any]) -> str:
    raw = str(session.get(CONTROL_KEY) or "").strip().upper()
    if raw in ("A", "B"):
        return raw
    if st is not None:
        q = _qp_get(st, "solo_bridge_transition").strip().upper()
        if q in ("A", "B"):
            session[CONTROL_KEY] = q
            return q
    return ""


def bridge_transition_active(st: Any | None, session: dict[str, Any]) -> bool:
    if session.get(SESSION_ENABLED):
        return True
    return bridge_transition_control(st, session) in ("A", "B")


def enable_bridge_transition_from_query(st: Any, session: dict[str, Any]) -> None:
    ctrl = bridge_transition_control(st, session)
    if ctrl in ("A", "B"):
        session[SESSION_ENABLED] = True
        session["_solo_delivery_diag_enabled"] = True
        session["_solo_placement_ladder_block_picks"] = True
        session["_solo_persistent_wake_flush_disabled"] = True


def _script_run_id(session: dict[str, Any]) -> str:
    try:
        from app_page_generation import current_script_run_id

        return str(current_script_run_id(session) or "")
    except ImportError:
        return str(session.get("_live_draft_script_run_id") or "")


def _resolve_room(session: dict[str, Any], room: Any) -> dict[str, Any] | None:
    live = session.get("live_draft_room")
    if isinstance(live, dict) and live:
        return live
    if isinstance(room, dict) and room:
        return room
    return None


def _room_status(room: dict[str, Any] | None) -> str:
    if not room:
        return "none"
    return str(room.get("status") or "unknown")


def _log_room_status(session: dict[str, Any], room: dict[str, Any] | None, *, phase: str) -> None:
    log = list(session.get(ROOM_STATUS_LOG_KEY) or [])
    log.append(
        {
            "ts": time.time(),
            "phase": phase,
            "status": _room_status(room),
            "room_id": str((room or {}).get("draft_room_id") or (room or {}).get("draft_id") or ""),
            "pick": int((room or {}).get("current_pick_index") or 0) if room else 0,
            "script_run": _script_run_id(session),
        }
    )
    session[ROOM_STATUS_LOG_KEY] = log[-120:]


def _diag_timer_seconds(st: Any, session: dict[str, Any]) -> float:
    try:
        from live_draft_solo_component_diagnostics import solo_diag_timer_seconds

        sec = solo_diag_timer_seconds(st, session)
        if sec and sec > 0:
            return float(sec)
    except ImportError:
        pass
    return 10.0


def _frozen_control_a_mount(
    st: Any, session: dict[str, Any]
) -> tuple[bool, str, dict[str, Any], str]:
    """One actionable token + deadline locked before draft start; unchanged after activation."""
    token = str(session.get(FROZEN_TOKEN_KEY) or "").strip()
    deadline = session.get(FROZEN_DEADLINE_KEY)
    if not token or deadline is None:
        sec = _diag_timer_seconds(st, session)
        deadline = time.time() + sec
        token = f"DIAGTRANSA|0|{float(deadline):.3f}"
        session[FROZEN_TOKEN_KEY] = token
        session[FROZEN_DEADLINE_KEY] = float(deadline)
    props = {
        "draft_room_id": "DIAGTRANSA",
        "draft_id": "DIAGTRANSA",
        "current_pick_index": 0,
        "status": "in_progress",
        "timer_deadline": float(session[FROZEN_DEADLINE_KEY]),
        "config": {"draft_setup_mode": "solo", "timer_seconds": _diag_timer_seconds(st, session)},
    }
    return True, token, props, "frozen_actionable"


def _control_b_mount(
    session: dict[str, Any], room: dict[str, Any] | None
) -> tuple[bool, str, dict[str, Any], str]:
    from live_draft_solo_persistent_wake import (
        SOLO_INERT_EXPIRE_TOKEN,
        resolve_persistent_wake_mount,
    )

    return resolve_persistent_wake_mount(session, room)


def _snapshot_args(
    session: dict[str, Any],
    *,
    phase: str,
    actionable: bool,
    expire_token: str,
    props: dict[str, Any],
    widget_key: str,
) -> None:
    payload = {
        "phase": phase,
        "actionable": actionable,
        "expire_token": expire_token,
        "timer_deadline": props.get("timer_deadline"),
        "status": props.get("status"),
        "pick_index": props.get("current_pick_index"),
        "draft_id": props.get("draft_room_id") or props.get("draft_id"),
        "widget_key": widget_key,
        "script_run": _script_run_id(session),
        "ts": time.time(),
    }
    if phase == "before_start" or not session.get(ARGS_BEFORE_KEY):
        if not session.get(ARGS_BEFORE_KEY):
            session[ARGS_BEFORE_KEY] = payload
    room = session.get("live_draft_room")
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if isinstance(room, dict) and is_solo_live_draft(session, room):
            if str(room.get("status") or "") == "in_progress":
                session[PHASE_KEY] = "active"
                session[ARGS_AFTER_KEY] = payload
    except ImportError:
        if str(props.get("status") or "") == "in_progress" and actionable and expire_token:
            session[ARGS_AFTER_KEY] = payload


def _transition_deliver_callback(st: Any, session: dict[str, Any], raw: Any, key: str) -> None:
    from live_draft_solo_heartbeat import _coerce_wake_token

    note_delivery_stage(
        session,
        "on_change_callback_entry",
        placement=f"TRANS_{session.get(CONTROL_KEY) or '?'}",
        bridge_transition=True,
        widget_key=key,
    )
    note_delivery_stage(
        session,
        "session_state_raw_received",
        placement=f"TRANS_{session.get(CONTROL_KEY) or '?'}",
        bridge_transition=True,
        widget_key=key,
        raw_type=type(raw).__name__ if raw is not None else "NoneType",
    )
    session[ON_CHANGE_COUNT_KEY] = int(session.get(ON_CHANGE_COUNT_KEY) or 0) + 1
    token = _coerce_wake_token(raw)
    if token:
        note_delivery_stage(
            session,
            "on_change_delivery_complete",
            placement=f"TRANS_{session.get(CONTROL_KEY) or '?'}",
            bridge_transition=True,
            token=token,
        )


def render_bridge_transition_probe(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    actionable: bool,
    expire_token: str,
    props: dict[str, Any],
    client_remounts: str = "",
) -> None:
    log = list(session.get(SOLO_DELIVERY_LOG_KEY) or [])
    stages = [str(r.get("stage") or "") for r in log if isinstance(r, dict)]
    chain = "|".join(stages[-80:])
    args_before = session.get(ARGS_BEFORE_KEY) or {}
    args_after = session.get(ARGS_AFTER_KEY) or {}
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    status_log = list(session.get(ROOM_STATUS_LOG_KEY) or [])
    st.markdown(
        f'<div id="solo-bridge-transition-diag" '
        f'data-present="1" '
        f'data-control="{str(session.get(CONTROL_KEY) or "").replace(chr(34), chr(39))}" '
        f'data-key="{widget_key.replace(chr(34), chr(39))}" '
        f'data-phase="{str(session.get(PHASE_KEY) or "setup").replace(chr(34), chr(39))}" '
        f'data-actionable="{1 if actionable else 0}" '
        f'data-token="{str(expire_token or "").replace(chr(34), chr(39))}" '
        f'data-deadline="{str(props.get("timer_deadline") or "").replace(chr(34), chr(39))}" '
        f'data-token-before="{str(args_before.get("expire_token") or "").replace(chr(34), chr(39))}" '
        f'data-deadline-before="{str(args_before.get("timer_deadline") or "").replace(chr(34), chr(39))}" '
        f'data-token-after="{str(args_after.get("expire_token") or "").replace(chr(34), chr(39))}" '
        f'data-deadline-after="{str(args_after.get("timer_deadline") or "").replace(chr(34), chr(39))}" '
        f'data-args-before="{json.dumps(args_before, default=str)[:4000].replace(chr(34), chr(39))}" '
        f'data-args-after="{json.dumps(args_after, default=str)[:4000].replace(chr(34), chr(39))}" '
        f'data-room-status="{_room_status(room).replace(chr(34), chr(39))}" '
        f'data-room-id="{str(room.get("draft_room_id") or room.get("draft_id") or "").replace(chr(34), chr(39))}" '
        f'data-on-change-count="{int(session.get(ON_CHANGE_COUNT_KEY) or 0)}" '
        f'data-stages="{chain.replace(chr(34), chr(39))}" '
        f'data-widget-id-before="{str(session.get(WIDGET_ID_BEFORE_KEY) or "").replace(chr(34), chr(39))}" '
        f'data-widget-id-after="{str(session.get(WIDGET_ID_AFTER_KEY) or "").replace(chr(34), chr(39))}" '
        f'data-client-remounts="{str(client_remounts or "").replace(chr(34), chr(39))}" '
        f'data-room-status-log="{json.dumps(status_log[-24:], default=str)[:6000].replace(chr(34), chr(39))}" '
        f'data-same-key="{1 if args_before.get("widget_key") == args_after.get("widget_key", args_before.get("widget_key")) else 0}" '
        f'data-token-unchanged="{1 if args_before.get("expire_token") and args_before.get("expire_token") == args_after.get("expire_token") else 0}" '
        f'></div>',
        unsafe_allow_html=True,
    )


def try_bridge_transition_ldr_entry(st: Any, session: dict[str, Any], room: Any) -> bool:
    """Early LDR mount for paired transition test; never st.stop()."""
    ctrl = bridge_transition_control(st, session)
    if ctrl not in ("A", "B"):
        return False
    if not delivery_diag_active(st, session):
        return False

    session[SESSION_ENABLED] = True
    session["_solo_persistent_wake_flush_disabled"] = True
    room_dict = _resolve_room(session, room)
    _log_room_status(session, room_dict, phase=f"entry_{ctrl}")

    session[SOLO_DELIVERY_META_KEY] = {
        **dict(session.get(SOLO_DELIVERY_META_KEY) or {}),
        "bridge_transition": ctrl,
        "mount_location": TRANSITION_LOCATION,
        "rerun_count": bump_delivery_rerun(session),
    }
    render_parent_postmessage_listener(st)

    if ctrl == "A":
        actionable, expire_token, props_room, _phase = _frozen_control_a_mount(st, session)
        phase_label = "before_start" if not session.get(ARGS_BEFORE_KEY) else str(session.get(PHASE_KEY) or "setup")
    else:
        actionable, expire_token, props_room, _phase = _control_b_mount(session, room_dict)
        phase_label = "before_start" if not session.get(ARGS_BEFORE_KEY) else str(session.get(PHASE_KEY) or "setup")

    _snapshot_args(
        session,
        phase=phase_label,
        actionable=actionable,
        expire_token=expire_token,
        props=props_room,
        widget_key=TRANSITION_WIDGET_KEY,
    )

    from solo_countdown_wake_micro_core import render_micro_isolation_once

    render_micro_isolation_once(
        st,
        session,
        placement=f"TRANS{ctrl}",
        location=TRANSITION_LOCATION,
        draft_id=str(props_room.get("draft_room_id") or props_room.get("draft_id") or ""),
        route=True,
        persistent=True,
        session_prefix=TRANSITION_SESSION_PREFIX,
        widget_key=TRANSITION_WIDGET_KEY,
        production_room=props_room,
        production_expire_token=expire_token,
        production_actionable=actionable,
        production_delivery_only=False,
        deliver_callback=_transition_deliver_callback,
    )

    raw = st.session_state.get(TRANSITION_WIDGET_KEY)
    session_state_token = ""
    if raw is not None:
        from live_draft_solo_heartbeat import _coerce_wake_token

        session_state_token = _coerce_wake_token(raw)
        if session_state_token and not session.get(WIDGET_ID_AFTER_KEY):
            session[WIDGET_ID_AFTER_KEY] = f"session_state:{session_state_token[:48]}"

    render_bridge_transition_probe(
        st,
        session,
        widget_key=TRANSITION_WIDGET_KEY,
        actionable=actionable,
        expire_token=expire_token,
        props=props_room,
    )
    note_delivery_stage(
        session,
        "bridge_transition_mounted",
        bridge_transition=ctrl,
        widget_key=TRANSITION_WIDGET_KEY,
        actionable=actionable,
        expire_token=expire_token,
        session_state_token=session_state_token,
    )
    return True
