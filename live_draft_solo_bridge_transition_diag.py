"""Paired bridge-transition diagnostic — Control A (always actionable) vs B (inert→active)."""

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
from live_draft_solo_persistent_wake import SOLO_INERT_EXPIRE_TOKEN

TRANSITION_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
TRANSITION_LOCATION = "ldr_page_entry_early_bridge_transition"
TRANSITION_SESSION_PREFIX = "_solo_bridge_transition_"
SESSION_ENABLED = "_solo_bridge_transition_enabled"
CONTROL_KEY = "_solo_bridge_transition_control"
PLACEHOLDER_DRAFT_ID = "TRANSPLACE"
PLACEHOLDER_DEADLINE = 9999999999.999
EXPECTED_EXPIRE_TOKEN_KEY = "_solo_bridge_transition_expected_expire_token"
ACTIVATED_KEY = "_solo_bridge_transition_post_activation"
LATCHED_PROPS_KEY = "_solo_bridge_transition_latched_active_props"
ARGS_BEFORE_KEY = "_solo_bridge_transition_args_before"
ARGS_AFTER_KEY = "_solo_bridge_transition_args_after"
WIDGET_ID_BEFORE_KEY = "_solo_bridge_transition_widget_id_before"
WIDGET_ID_AFTER_KEY = "_solo_bridge_transition_widget_id_after"
MATCHING_ON_CHANGE_KEY = "_solo_bridge_transition_matching_on_change_count"
MATCHING_RAW_KEY = "_solo_bridge_transition_matching_raw_count"
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


def _diag_timer_seconds(_st: Any, session: dict[str, Any]) -> float:
    try:
        from live_draft_solo_component_diagnostics import solo_diag_timer_seconds

        sec = solo_diag_timer_seconds(session)
        if sec and sec > 0:
            return float(sec)
    except ImportError:
        pass
    return 10.0


def _placeholder_token() -> str:
    return f"{PLACEHOLDER_DRAFT_ID}|0|{PLACEHOLDER_DEADLINE:.3f}"


def _placeholder_props() -> dict[str, Any]:
    return {
        "draft_room_id": PLACEHOLDER_DRAFT_ID,
        "draft_id": PLACEHOLDER_DRAFT_ID,
        "current_pick_index": 0,
        "status": "setup",
        "timer_deadline": PLACEHOLDER_DEADLINE,
        "config": {"draft_setup_mode": "solo"},
    }


def _room_ready_for_live_timer(session: dict[str, Any], room: dict[str, Any] | None) -> bool:
    if not isinstance(room, dict) or not room:
        return False
    if str(room.get("status") or "") != "in_progress":
        return False
    try:
        from live_draft_solo_timer import is_solo_live_draft

        return bool(is_solo_live_draft(session, room))
    except ImportError:
        return True


def _live_expire_token(session: dict[str, Any], room: dict[str, Any]) -> str:
    latched = str(session.get(EXPECTED_EXPIRE_TOKEN_KEY) or "").strip()
    if latched and session.get(ACTIVATED_KEY):
        return latched

    from solo_countdown_component import build_solo_expire_token

    live = dict(room)
    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        if live_draft_timer_deadline(live) is None:
            sec = _diag_timer_seconds(None, session)
            live["timer_deadline"] = time.time() + sec
            live.setdefault("config", {})["timer_seconds"] = int(sec)
    except ImportError:
        sec = _diag_timer_seconds(None, session)
        live["timer_deadline"] = time.time() + sec
    token = build_solo_expire_token(live)
    session[EXPECTED_EXPIRE_TOKEN_KEY] = token
    session[ACTIVATED_KEY] = True
    session[LATCHED_PROPS_KEY] = {**live, "status": "in_progress"}
    return token


def resolve_transition_mount(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    ctrl: str,
) -> tuple[bool, str, dict[str, Any], str]:
    """Setup: shared placeholder deadline; post-activation: same 10s token for A and B."""
    if _room_ready_for_live_timer(session, room):
        assert room is not None
        token = _live_expire_token(session, room)
        latched_props = session.get(LATCHED_PROPS_KEY)
        props = dict(latched_props) if isinstance(latched_props, dict) else {**room, "status": "in_progress"}
        actionable = True
        return actionable, token, props, "active"

    if ctrl == "A":
        return True, _placeholder_token(), _placeholder_props(), "setup"
    return False, SOLO_INERT_EXPIRE_TOKEN, _placeholder_props(), "setup"


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
    if not session.get(ARGS_BEFORE_KEY):
        session[ARGS_BEFORE_KEY] = payload
    if session.get(ACTIVATED_KEY):
        session[PHASE_KEY] = "active"
        if not session.get(ARGS_AFTER_KEY) or str((session.get(ARGS_AFTER_KEY) or {}).get("expire_token") or "") != str(
            expire_token or ""
        ):
            session[ARGS_AFTER_KEY] = payload


def _transition_deliver_callback(st: Any, session: dict[str, Any], raw: Any, key: str) -> None:
    from live_draft_solo_heartbeat import _coerce_wake_token

    token = _coerce_wake_token(raw)
    expected = str(session.get(EXPECTED_EXPIRE_TOKEN_KEY) or "").strip()
    placement = f"TRANS_{session.get(CONTROL_KEY) or '?'}"

    if not expected:
        note_delivery_stage(
            session,
            "on_change_ignored_pre_activation",
            placement=placement,
            bridge_transition=True,
            widget_key=key,
            token=token,
        )
        return
    if token != expected:
        note_delivery_stage(
            session,
            "on_change_ignored_wrong_token",
            placement=placement,
            bridge_transition=True,
            widget_key=key,
            token=token,
            expected_token=expected,
        )
        return

    note_delivery_stage(
        session,
        "on_change_callback_entry_matching_token",
        placement=placement,
        bridge_transition=True,
        widget_key=key,
        token=token,
    )
    note_delivery_stage(
        session,
        "session_state_raw_received_matching_token",
        placement=placement,
        bridge_transition=True,
        widget_key=key,
        raw_type=type(raw).__name__ if raw is not None else "NoneType",
        token=token,
    )
    session[MATCHING_ON_CHANGE_KEY] = int(session.get(MATCHING_ON_CHANGE_KEY) or 0) + 1
    session[MATCHING_RAW_KEY] = int(session.get(MATCHING_RAW_KEY) or 0) + 1


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
    expected = str(session.get(EXPECTED_EXPIRE_TOKEN_KEY) or "")
    st.markdown(
        f'<div id="solo-bridge-transition-diag" '
        f'data-present="1" '
        f'data-control="{str(session.get(CONTROL_KEY) or "").replace(chr(34), chr(39))}" '
        f'data-key="{widget_key.replace(chr(34), chr(39))}" '
        f'data-phase="{str(session.get(PHASE_KEY) or "setup").replace(chr(34), chr(39))}" '
        f'data-actionable="{1 if actionable else 0}" '
        f'data-token="{str(expire_token or "").replace(chr(34), chr(39))}" '
        f'data-deadline="{str(props.get("timer_deadline") or "").replace(chr(34), chr(39))}" '
        f'data-expected-expire-token="{expected.replace(chr(34), chr(39))}" '
        f'data-token-before="{str(args_before.get("expire_token") or "").replace(chr(34), chr(39))}" '
        f'data-deadline-before="{str(args_before.get("timer_deadline") or "").replace(chr(34), chr(39))}" '
        f'data-token-after="{str(args_after.get("expire_token") or "").replace(chr(34), chr(39))}" '
        f'data-deadline-after="{str(args_after.get("timer_deadline") or "").replace(chr(34), chr(39))}" '
        f'data-args-before="{json.dumps(args_before, default=str)[:4000].replace(chr(34), chr(39))}" '
        f'data-args-after="{json.dumps(args_after, default=str)[:4000].replace(chr(34), chr(39))}" '
        f'data-room-status="{_room_status(room).replace(chr(34), chr(39))}" '
        f'data-room-id="{str(room.get("draft_room_id") or room.get("draft_id") or "").replace(chr(34), chr(39))}" '
        f'data-matching-on-change-count="{int(session.get(MATCHING_ON_CHANGE_KEY) or 0)}" '
        f'data-matching-raw-count="{int(session.get(MATCHING_RAW_KEY) or 0)}" '
        f'data-stages="{chain.replace(chr(34), chr(39))}" '
        f'data-widget-id-before="{str(session.get(WIDGET_ID_BEFORE_KEY) or "").replace(chr(34), chr(39))}" '
        f'data-widget-id-after="{str(session.get(WIDGET_ID_AFTER_KEY) or "").replace(chr(34), chr(39))}" '
        f'data-client-remounts="{str(client_remounts or "").replace(chr(34), chr(39))}" '
        f'data-room-status-log="{json.dumps(status_log[-24:], default=str)[:6000].replace(chr(34), chr(39))}" '
        f'data-post-activation="{1 if session.get(ACTIVATED_KEY) else 0}" '
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

    actionable, expire_token, props_room, phase_label = resolve_transition_mount(session, room_dict, ctrl)
    session[PHASE_KEY] = phase_label

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
        expected_expire_token=str(session.get(EXPECTED_EXPIRE_TOKEN_KEY) or ""),
        post_activation=bool(session.get(ACTIVATED_KEY)),
    )
    return True
