"""Return-value binding ladder — Python component declaration audit (diag-only)."""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Callable

RV_DECLARATION_LOG_KEY = "_solo_rv_declaration_audit_log"
RV_DECLARATION_SEQ_KEY = "_solo_rv_declaration_audit_seq"
RV_DECLARATION_AUDIT_ACTIVE_KEY = "_solo_rv_declaration_audit_active"
MAX_ROWS = 120


def rv_declaration_audit_active(st: Any | None, session: dict[str, Any]) -> bool:
    return bool(
        session.get(RV_DECLARATION_AUDIT_ACTIVE_KEY)
        or session.get("_solo_rv_declaration_audit_active")
        or session.get("_solo_rv_ladder_step")
    )


def _next_seq(session: dict[str, Any]) -> int:
    n = int(session.get(RV_DECLARATION_SEQ_KEY) or 0) + 1
    session[RV_DECLARATION_SEQ_KEY] = n
    return n


def _streamlit_session_id(st: Any | None) -> str:
    try:
        from app_page_generation import current_script_run_id

        return str(current_script_run_id(st.session_state if hasattr(st, "session_state") else {}) or "")
    except ImportError:
        pass
    try:
        return str(getattr(st, "session_state", {}).get("_live_draft_script_run_id") or "")
    except Exception:
        return ""


def _room_fields(session: dict[str, Any], room: dict[str, Any] | None) -> dict[str, Any]:
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        live = {}
    rid = str(live.get("draft_room_id") or live.get("draft_id") or "").strip()
    pick = int(live.get("current_pick_index") or 0)
    deadline = live.get("timer_deadline")
    expected = str(session.get("_solo_persistent_wake_last_token") or session.get("_solo_parity_expected_token") or "")
    if not expected and live:
        try:
            from solo_countdown_component import build_solo_expire_token

            expected = build_solo_expire_token(live)
        except ImportError:
            pass
    return {
        "room_id": rid,
        "pick_index": pick,
        "deadline": deadline,
        "expected_token": expected[:400],
    }


def record_rv_declaration_snapshot(
    st: Any,
    session: dict[str, Any],
    *,
    phase: str,
    widget_key: str,
    room: dict[str, Any] | None = None,
    component_return: Any = None,
    declaration_reached: bool | None = None,
    before_browser_send: bool | None = None,
    process_entered: bool | None = None,
    coalesced_value: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not rv_declaration_audit_active(st, session):
        return {}
    seq = _next_seq(session)
    rf = _room_fields(session, room)
    ss_before = ""
    ss_after = ""
    if widget_key:
        ss_before = repr(st.session_state.get(widget_key))[:400] if widget_key in st.session_state else "missing"
    row: dict[str, Any] = {
        "seq": seq,
        "ts": time.time(),
        "phase": str(phase or ""),
        "script_run_id": _streamlit_session_id(st),
        "script_run_seq": int(session.get(RV_DECLARATION_SEQ_KEY) or seq),
        "active_page": str(session.get("active_page") or session.get("_active_page") or ""),
        "rv_ladder_step": str(session.get("_solo_rv_ladder_step") or ""),
        "widget_key": widget_key,
        "declaration_reached": declaration_reached,
        "component_return": repr(component_return)[:400] if component_return is not None else "",
        "session_state_before": ss_before,
        "session_state_after": ss_after,
        "coalesced_value": str(coalesced_value or "")[:400],
        "before_browser_send": before_browser_send,
        "process_production_expire_token_entered": process_entered,
        "browser_delivery_seen": bool(session.get("_solo_p6_browser_delivery_seen") or session.get("_solo_rv_browser_delivery_seen")),
        **rf,
    }
    if extra:
        row.update(extra)
    log = list(session.get(RV_DECLARATION_LOG_KEY) or [])
    log.append(row)
    session[RV_DECLARATION_LOG_KEY] = log[-MAX_ROWS:]
    return row


def record_rv_declaration_after_mount(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    room: dict[str, Any] | None,
    component_return: Any,
    phase: str = "after_mount",
) -> None:
    raw = component_return
    coerced = ""
    if raw is not None:
        if isinstance(raw, str):
            coerced = raw.strip()
        else:
            coerced = str(raw).strip()
    ss_after = repr(st.session_state.get(widget_key))[:400] if widget_key in st.session_state else "missing"
    row = record_rv_declaration_snapshot(
        st,
        session,
        phase=phase,
        widget_key=widget_key,
        room=room,
        component_return=raw,
        declaration_reached=True,
        coalesced_value=coerced or ss_after.strip("'\""),
    )
    row["session_state_after"] = ss_after


def mount_with_rv_declaration_audit(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    widget_key: str,
    mount_fn: Callable[[], Any],
    phase_prefix: str = "production",
) -> Any:
    record_rv_declaration_snapshot(
        st,
        session,
        phase=f"{phase_prefix}_before_mount",
        widget_key=widget_key,
        room=room,
        declaration_reached=False,
        before_browser_send=not bool(session.get("_solo_rv_browser_delivery_seen")),
        process_entered=bool(session.get("_solo_rv_process_entered")),
    )
    raw = mount_fn()
    record_rv_declaration_after_mount(
        st,
        session,
        widget_key=widget_key,
        room=room,
        component_return=raw,
        phase=f"{phase_prefix}_after_mount",
    )
    return raw


def render_rv_declaration_audit_probe(st: Any, session: dict[str, Any]) -> None:
    if not rv_declaration_audit_active(st, session):
        return
    payload = json.dumps(
        {
            "rows": list(session.get(RV_DECLARATION_LOG_KEY) or [])[-80:],
            "seq": int(session.get(RV_DECLARATION_SEQ_KEY) or 0),
            "step": str(session.get("_solo_rv_ladder_step") or ""),
        },
        default=str,
    )[:14000]
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    st.markdown(
        f'<div id="solo-rv-declaration-audit" data-b64="{b64}"></div>',
        unsafe_allow_html=True,
    )
