"""Bridge-transition diagnostic — A0 (frozen bridge), A1 (token switch), B (actionable+token)."""

from __future__ import annotations

import base64
import json
import time
import traceback
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
VALID_CONTROLS = frozenset({"A0", "A1", "B"})

PLACEHOLDER_DRAFT_ID = "TRANSPLACE"
PLACEHOLDER_DEADLINE = 9999999999.999
A0_DRAFT_ID = "BRIDGEA0"
A0_DEFAULT_SECONDS = 90.0

EXPECTED_EXPIRE_TOKEN_KEY = "_solo_bridge_transition_expected_expire_token"
ACTIVATED_KEY = "_solo_bridge_transition_post_activation"
LATCHED_PROPS_KEY = "_solo_bridge_transition_latched_active_props"
A0_FROZEN_TOKEN_KEY = "_solo_bridge_transition_a0_frozen_token"
A0_FROZEN_DEADLINE_KEY = "_solo_bridge_transition_a0_frozen_deadline"
POPPED_FOR_ACTIVE_KEY = "_solo_bridge_transition_popped_for_active"
ARGS_BEFORE_KEY = "_solo_bridge_transition_args_before"
ARGS_AFTER_KEY = "_solo_bridge_transition_args_after"
PHASE_KEY = "_solo_bridge_transition_phase"
ROOM_STATUS_LOG_KEY = "_solo_bridge_transition_room_status_log"
PROVENANCE_KEY = "_solo_bridge_transition_provenance"
VALID_EXPIRATION_EVENTS_KEY = "_solo_bridge_transition_valid_expiration_events"
CLIENT_CROSS_TS_KEY = "_solo_bridge_transition_client_cross_ts"
CLIENT_SENT_TS_KEY = "_solo_bridge_transition_client_sent_ts"
ROOM_LEDGER_KEY = "_solo_bridge_transition_room_ledger"
ROOM_MUTATION_LOG_KEY = "_solo_bridge_transition_room_mutation_log"
BRIDGE_LAST_ROOM_SNAPSHOT_KEY = "_solo_bridge_transition_last_room_snapshot"
SCRIPT_RUN_COUNTER_KEY = "_solo_bridge_transition_script_run_counter"
STREAMLIT_SESSION_ID_KEY = "_solo_bridge_transition_streamlit_session_id"


def _qp_get(st: Any, name: str) -> str:
    try:
        from live_draft_cloud_diagnostics import _qp_get as _get

        return _get(st, name)
    except ImportError:
        return ""


def normalize_control(raw: str) -> str:
    c = str(raw or "").strip().upper()
    if c == "A":
        return "A1"
    if c in VALID_CONTROLS:
        return c
    return ""


def bridge_transition_control(st: Any | None, session: dict[str, Any]) -> str:
    raw = str(session.get(CONTROL_KEY) or "").strip().upper()
    norm = normalize_control(raw)
    if norm:
        return norm
    if st is not None:
        q = normalize_control(_qp_get(st, "solo_bridge_transition"))
        if q:
            session[CONTROL_KEY] = q
            return q
    return ""


def bridge_transition_active(st: Any | None, session: dict[str, Any]) -> bool:
    if session.get(SESSION_ENABLED):
        return True
    return bridge_transition_control(st, session) in VALID_CONTROLS


def enable_bridge_transition_from_query(st: Any, session: dict[str, Any]) -> None:
    ctrl = bridge_transition_control(st, session)
    if ctrl in VALID_CONTROLS:
        session[SESSION_ENABLED] = True
        session["_solo_delivery_diag_enabled"] = True
        session["_solo_placement_ladder_block_picks"] = True
        session["_solo_persistent_wake_flush_disabled"] = True


def _b64_json(payload: Any) -> str:
    return base64.b64encode(json.dumps(payload, default=str).encode("utf-8")).decode("ascii")


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")
    except Exception:
        return ""


def _observe_room_state(session: dict[str, Any], room: dict[str, Any] | None, *, ctrl: str) -> None:
    session[SCRIPT_RUN_COUNTER_KEY] = int(session.get(SCRIPT_RUN_COUNTER_KEY) or 0) + 1
    session[STREAMLIT_SESSION_ID_KEY] = _streamlit_session_id()
    snap = {
        "ts": time.time(),
        "script_run": _script_run_id(session),
        "streamlit_session_id": session.get(STREAMLIT_SESSION_ID_KEY),
        "control": ctrl,
        "room_id": _room_id(room),
        "status": _room_status(room),
        "present": isinstance(room, dict) and bool(room),
    }
    ledger = list(session.get(ROOM_LEDGER_KEY) or [])
    ledger.append(snap)
    session[ROOM_LEDGER_KEY] = ledger[-200:]

    prev = session.get(BRIDGE_LAST_ROOM_SNAPSHOT_KEY)
    if isinstance(prev, dict):
        mutations = list(session.get(ROOM_MUTATION_LOG_KEY) or [])
        prev_id = str(prev.get("room_id") or "")
        prev_present = bool(prev.get("present"))
        cur_present = snap["present"]
        cur_id = str(snap.get("room_id") or "")
        stack_tail = [line.strip() for line in traceback.format_stack(limit=10)[:-1]][-6:]
        if prev_present and not cur_present:
            mutations.append(
                {
                    "ts": time.time(),
                    "kind": "live_draft_room_removed",
                    "path": "bridge_entry_observed_absent",
                    "prev_room_id": prev_id,
                    "prev_status": prev.get("status"),
                    "script_run": snap["script_run"],
                    "stack_tail": stack_tail,
                }
            )
        elif prev_present and cur_present and prev_id and cur_id and prev_id != cur_id:
            mutations.append(
                {
                    "ts": time.time(),
                    "kind": "live_draft_room_replaced",
                    "path": "bridge_entry_observed_id_change",
                    "prev_room_id": prev_id,
                    "new_room_id": cur_id,
                    "script_run": snap["script_run"],
                    "stack_tail": stack_tail,
                }
            )
        session[ROOM_MUTATION_LOG_KEY] = mutations[-80:]
    session[BRIDGE_LAST_ROOM_SNAPSHOT_KEY] = snap


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


def _room_id(room: dict[str, Any] | None) -> str:
    if not room:
        return ""
    return str(room.get("draft_room_id") or room.get("draft_id") or "").strip().upper()


def _log_room_status(session: dict[str, Any], room: dict[str, Any] | None, *, phase: str) -> None:
    log = list(session.get(ROOM_STATUS_LOG_KEY) or [])
    log.append(
        {
            "ts": time.time(),
            "phase": phase,
            "status": _room_status(room),
            "room_id": _room_id(room),
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


def _a0_seconds(st: Any | None, session: dict[str, Any]) -> float:
    if st is not None:
        raw = _qp_get(st, "solo_bridge_a0_seconds").strip()
        if raw:
            try:
                sec = float(raw)
                if 60.0 <= sec <= 180.0:
                    return sec
            except ValueError:
                pass
    return A0_DEFAULT_SECONDS


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


def _a0_frozen_mount(st: Any | None, session: dict[str, Any], room: dict[str, Any] | None) -> tuple[bool, str, dict[str, Any], str]:
    token = str(session.get(A0_FROZEN_TOKEN_KEY) or "").strip()
    deadline = session.get(A0_FROZEN_DEADLINE_KEY)
    if not token or deadline is None:
        sec = _a0_seconds(st, session)
        deadline = time.time() + sec
        token = f"{A0_DRAFT_ID}|0|{float(deadline):.3f}"
        session[A0_FROZEN_TOKEN_KEY] = token
        session[A0_FROZEN_DEADLINE_KEY] = float(deadline)
    phase = "setup"
    status = "setup"
    draft_id = A0_DRAFT_ID
    if room and str(room.get("status") or "") == "in_progress":
        phase = "active"
        status = "in_progress"
        draft_id = _room_id(room) or A0_DRAFT_ID
    props = {
        "draft_room_id": draft_id,
        "draft_id": draft_id,
        "current_pick_index": 0,
        "status": status,
        "timer_deadline": float(session[A0_FROZEN_DEADLINE_KEY]),
        "config": {"draft_setup_mode": "solo", "timer_seconds": int(_a0_seconds(st, session))},
    }
    session[EXPECTED_EXPIRE_TOKEN_KEY] = token
    if phase == "active":
        session[ACTIVATED_KEY] = True
    return True, token, props, phase


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
    st: Any | None = None,
) -> tuple[bool, str, dict[str, Any], str]:
    if ctrl == "A0":
        return _a0_frozen_mount(st, session, room)

    if _room_ready_for_live_timer(session, room):
        assert room is not None
        token = _live_expire_token(session, room)
        latched_props = session.get(LATCHED_PROPS_KEY)
        props = dict(latched_props) if isinstance(latched_props, dict) else {**room, "status": "in_progress"}
        return True, token, props, "active"

    if ctrl == "A1":
        return True, _placeholder_token(), _placeholder_props(), "setup"
    return False, SOLO_INERT_EXPIRE_TOKEN, _placeholder_props(), "setup"


def _append_provenance(
    session: dict[str, Any],
    *,
    control: str,
    phase: str,
    expected_token: str,
    actual_raw: Any,
    widget_key: str,
    source: str,
    browser_zero_cross_ts: str = "",
    component_value_sent_ts: str = "",
) -> None:
    from live_draft_solo_heartbeat import _coerce_wake_token

    actual = _coerce_wake_token(actual_raw)
    log = list(session.get(PROVENANCE_KEY) or [])
    log.append(
        {
            "ts": time.time(),
            "control": control,
            "phase": phase,
            "expected_token": expected_token,
            "actual_raw": actual,
            "widget_key": widget_key,
            "source": source,
            "browser_zero_cross_ts": browser_zero_cross_ts,
            "component_value_sent_ts": component_value_sent_ts,
        }
    )
    session[PROVENANCE_KEY] = log[-200:]


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
    if session.get(ACTIVATED_KEY) and phase == "active":
        session[PHASE_KEY] = "active"
        if not session.get(ARGS_AFTER_KEY) or str((session.get(ARGS_AFTER_KEY) or {}).get("expire_token") or "") != str(
            expire_token or ""
        ):
            session[ARGS_AFTER_KEY] = payload


def _clear_widget_before_active_arm(st: Any, session: dict[str, Any], phase_label: str, ctrl: str) -> None:
    if ctrl == "A0":
        return
    if phase_label != "active":
        return
    if session.get(POPPED_FOR_ACTIVE_KEY):
        return
    st.session_state.pop(TRANSITION_WIDGET_KEY, None)
    session[POPPED_FOR_ACTIVE_KEY] = True
    _append_provenance(
        session,
        control=ctrl,
        phase="active",
        expected_token=str(session.get(EXPECTED_EXPIRE_TOKEN_KEY) or ""),
        actual_raw=None,
        widget_key=TRANSITION_WIDGET_KEY,
        source="session_state_pop_before_active_arm",
    )
    note_delivery_stage(
        session,
        "bridge_transition_widget_session_cleared",
        bridge_transition=ctrl,
        widget_key=TRANSITION_WIDGET_KEY,
    )


def _chain_persist_key(session: dict[str, Any], ctrl: str, room: dict[str, Any] | None) -> str:
    rid = _room_id(room) or "setup"
    return f"solo_bridge_{ctrl}_{rid}"


def _transition_deliver_callback(st: Any, session: dict[str, Any], raw: Any, key: str) -> None:
    from live_draft_solo_heartbeat import _coerce_wake_token

    ctrl = str(session.get(CONTROL_KEY) or "?")
    phase = str(session.get(PHASE_KEY) or "setup")
    token = _coerce_wake_token(raw)
    expected = str(session.get(EXPECTED_EXPIRE_TOKEN_KEY) or "").strip()
    placement = f"TRANS_{ctrl}"
    cross_ts = str(session.get(CLIENT_CROSS_TS_KEY) or "")
    sent_ts = str(session.get(CLIENT_SENT_TS_KEY) or "")

    _append_provenance(
        session,
        control=ctrl,
        phase=phase,
        expected_token=expected,
        actual_raw=raw,
        widget_key=key,
        source="on_change_callback",
        browser_zero_cross_ts=cross_ts,
        component_value_sent_ts=sent_ts,
    )

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

    client_ok = bool(cross_ts and sent_ts)
    if client_ok and token == expected and str(raw).strip() == expected:
        events = list(session.get(VALID_EXPIRATION_EVENTS_KEY) or [])
        events.append(
            {
                "ts": time.time(),
                "control": ctrl,
                "expected_token": expected,
                "actual_raw": token,
                "browser_zero_cross_ts": cross_ts,
                "component_value_sent_ts": sent_ts,
            }
        )
        session[VALID_EXPIRATION_EVENTS_KEY] = events[-20:]
        note_delivery_stage(
            session,
            "valid_expiration_delivery",
            placement=placement,
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
) -> None:
    log = list(session.get(SOLO_DELIVERY_LOG_KEY) or [])
    stages = [str(r.get("stage") or "") for r in log if isinstance(r, dict)]
    chain = "|".join(stages[-80:])
    args_before = session.get(ARGS_BEFORE_KEY) or {}
    args_after = session.get(ARGS_AFTER_KEY) or {}
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    status_log = list(session.get(ROOM_STATUS_LOG_KEY) or [])
    expected = str(session.get(EXPECTED_EXPIRE_TOKEN_KEY) or "")
    provenance = list(session.get(PROVENANCE_KEY) or [])
    valid_events = list(session.get(VALID_EXPIRATION_EVENTS_KEY) or [])
    room_ledger = list(session.get(ROOM_LEDGER_KEY) or [])
    mutation_log = list(session.get(ROOM_MUTATION_LOG_KEY) or [])
    py_present = isinstance(room, dict) and bool(room)
    prov_b64 = _b64_json(provenance[-40:])
    ledger_b64 = _b64_json(room_ledger[-48:])
    mut_b64 = _b64_json(mutation_log[-24:])
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
        f'data-python-room-present="{1 if py_present else 0}" '
        f'data-python-room-status="{_room_status(room).replace(chr(34), chr(39))}" '
        f'data-python-room-id="{_room_id(room).replace(chr(34), chr(39))}" '
        f'data-room-status="{_room_status(room).replace(chr(34), chr(39))}" '
        f'data-room-id="{_room_id(room).replace(chr(34), chr(39))}" '
        f'data-valid-expiration-count="{len(valid_events)}" '
        f'data-provenance-b64="{prov_b64}" '
        f'data-room-ledger-b64="{ledger_b64}" '
        f'data-room-mutation-log-b64="{mut_b64}" '
        f'data-streamlit-session-id="{str(session.get(STREAMLIT_SESSION_ID_KEY) or "").replace(chr(34), chr(39))}" '
        f'data-script-run-counter="{int(session.get(SCRIPT_RUN_COUNTER_KEY) or 0)}" '
        f'data-valid-events="{json.dumps(valid_events, default=str)[:4000].replace(chr(34), chr(39))}" '
        f'data-stages="{chain.replace(chr(34), chr(39))}" '
        f'data-room-status-log="{json.dumps(status_log[-24:], default=str)[:6000].replace(chr(34), chr(39))}" '
        f'data-post-activation="{1 if session.get(ACTIVATED_KEY) else 0}" '
        f'data-widget-popped="{1 if session.get(POPPED_FOR_ACTIVE_KEY) else 0}" '
        f'></div>',
        unsafe_allow_html=True,
    )


def try_bridge_transition_ldr_entry(st: Any, session: dict[str, Any], room: Any) -> bool:
    ctrl = bridge_transition_control(st, session)
    if ctrl not in VALID_CONTROLS:
        return False
    if not delivery_diag_active(st, session):
        return False

    session[SESSION_ENABLED] = True
    session["_solo_persistent_wake_flush_disabled"] = True
    room_dict = _resolve_room(session, room)
    _observe_room_state(session, room_dict, ctrl=ctrl)
    _log_room_status(session, room_dict, phase=f"entry_{ctrl}")

    session[SOLO_DELIVERY_META_KEY] = {
        **dict(session.get(SOLO_DELIVERY_META_KEY) or {}),
        "bridge_transition": ctrl,
        "mount_location": TRANSITION_LOCATION,
        "rerun_count": bump_delivery_rerun(session),
    }
    render_parent_postmessage_listener(st)

    actionable, expire_token, props_room, phase_label = resolve_transition_mount(session, room_dict, ctrl, st)
    session[PHASE_KEY] = phase_label
    _clear_widget_before_active_arm(st, session, phase_label, ctrl)

    _snapshot_args(
        session,
        phase=phase_label,
        actionable=actionable,
        expire_token=expire_token,
        props=props_room,
        widget_key=TRANSITION_WIDGET_KEY,
    )

    persist_key = _chain_persist_key(session, ctrl, room_dict)

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
        suppress_immediate_session_on_change=True,
        chain_persist_key=persist_key,
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
        chain_persist_key=persist_key,
    )
    return True
