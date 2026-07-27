"""Native Streamlit RV control ledger (diag-only) — no HTML/localStorage probe."""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Callable

RV_LEDGERS_BY_RUN_KEY = "solo_rv_control_ledgers_v1"
RV_SCRIPT_RUN_SEQ_KEY = "_solo_rv_control_script_run_seq"
RV_LEDGER_B64_PREFIX = "SOLO_RV_CONTROL_LEDGER_B64:"
MAX_LEDGER_ROWS = 200


def _qp_run_id(st: Any, session: dict[str, Any]) -> str:
    rid = str(session.get("_solo_rv_run_id") or "").strip()
    if rid:
        return rid
    try:
        from live_draft_solo_rv_binding_ladder import RV_RUN_ID_QP, _qp_get

        return str(_qp_get(st, RV_RUN_ID_QP) or "").strip()
    except ImportError:
        return ""


def rv_control_probe_active(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_rv_binding_ladder import rv_ladder_requested

        return rv_ladder_requested(st, session)
    except ImportError:
        return bool(session.get("_solo_rv_ladder_step"))


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


def _next_script_run_seq(session: dict[str, Any]) -> int:
    n = int(session.get(RV_SCRIPT_RUN_SEQ_KEY) or 0) + 1
    session[RV_SCRIPT_RUN_SEQ_KEY] = n
    return n


def _ledger_for_run(session: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    if not run_id:
        return []
    store = dict(session.get(RV_LEDGERS_BY_RUN_KEY) or {})
    return list(store.get(run_id) or [])


def _persist_ledger(session: dict[str, Any], run_id: str, rows: list[dict[str, Any]]) -> None:
    store = dict(session.get(RV_LEDGERS_BY_RUN_KEY) or {})
    store[run_id] = rows[-MAX_LEDGER_ROWS:]
    session[RV_LEDGERS_BY_RUN_KEY] = store


def build_control_probe_payload(session: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "step": str(session.get("_solo_rv_ladder_step") or ""),
        "script_run_seq": int(session.get(RV_SCRIPT_RUN_SEQ_KEY) or 0),
        "rows": _ledger_for_run(session, run_id),
    }


def encode_control_probe_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, default=str)[:48000]
    return RV_LEDGER_B64_PREFIX + base64.b64encode(raw.encode("utf-8")).decode("ascii")


def decode_control_probe_text(text: str) -> dict[str, Any]:
    if not text:
        return {}
    idx = text.find(RV_LEDGER_B64_PREFIX)
    if idx < 0:
        return {}
    b64 = text[idx + len(RV_LEDGER_B64_PREFIX) :].strip().split()[0]
    if not b64:
        return {}
    pad = b64 + "==="[: (4 - len(b64) % 4) % 4]
    try:
        return json.loads(base64.b64decode(pad).decode("utf-8"))
    except Exception:
        return {}


def render_native_control_probe(st: Any, session: dict[str, Any], probe_placeholder: Any) -> None:
    """Render ledger via st.code on a local placeholder (never stored in session_state)."""
    if probe_placeholder is None:
        return
    run_id = _qp_run_id(st, session)
    payload = build_control_probe_payload(session, run_id)
    line = encode_control_probe_payload(payload)
    probe_placeholder.code(line, language=None)


def append_control_event(
    st: Any,
    session: dict[str, Any],
    event: str,
    *,
    control_name: str = "",
    widget_key: str = "",
    room: dict[str, Any] | None = None,
    expected_token: str = "",
    component_return: Any = None,
    coalesced_value: str = "",
    callback_mode: str = "on_change=None",
    component_widget_id: str = "",
    browser_send_seen: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = _qp_run_id(st, session)
    if not run_id:
        return {}
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        live = {}
    ss_before = ""
    ss_after = ""
    if widget_key:
        ss_before = repr(session.get(widget_key))[:400] if widget_key in session else "missing"
        ss_after = ss_before
    if browser_send_seen is None:
        browser_send_seen = bool(
            session.get("_solo_rv_browser_delivery_recorded")
            or session.get("_solo_rv_prior_declaration_returned")
        )
    rows = _ledger_for_run(session, run_id)
    event_seq = len(rows) + 1
    decl_num = sum(1 for r in rows if r.get("event") == "declaration_attempt") + (
        1 if event == "declaration_attempt" else 0
    )
    row: dict[str, Any] = {
        "event": event,
        "event_sequence": event_seq,
        "declaration_occurrence_number": decl_num if event == "declaration_attempt" else None,
        "ts": time.time(),
        "streamlit_session_id": _streamlit_session_id(st),
        "script_run_seq": int(session.get(RV_SCRIPT_RUN_SEQ_KEY) or 0),
        "run_id": run_id,
        "control_name": control_name or str(session.get("_solo_rv_ladder_step") or ""),
        "room_id": str(live.get("draft_room_id") or live.get("draft_id") or ""),
        "pick_index": int(live.get("current_pick_index") or 0),
        "deadline": live.get("timer_deadline"),
        "expected_token": (expected_token or str(session.get("_solo_persistent_wake_last_token") or ""))[:400],
        "widget_key": widget_key,
        "session_state_before": ss_before,
        "session_state_after": ss_after,
        "browser_send_seen": browser_send_seen,
        "component_return": repr(component_return)[:400] if component_return is not None else "",
        "coalesced_value": str(coalesced_value or "")[:400],
        "component_widget_id": component_widget_id[:120],
        "callback_mode": callback_mode,
    }
    if extra:
        row.update(extra)
    rows.append(row)
    _persist_ledger(session, run_id, rows)
    return row


def rv_ultra_early_probe_hook(st: Any, session: dict[str, Any]) -> None:
    """Latch RV query params only — native probe renders in dedicated entrypoint."""
    if not rv_control_probe_active(st, session):
        return
    try:
        from live_draft_solo_rv_binding_ladder import enable_rv_ladder_session

        enable_rv_ladder_session(st, session)
    except ImportError:
        pass
    _next_script_run_seq(session)


def mount_with_rv_control_declaration(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    widget_key: str,
    mount_fn: Callable[[], Any],
    control_name: str,
    location: str,
    probe_placeholder: Any = None,
) -> Any:
    expected = str(session.get("_solo_persistent_wake_last_token") or session.get("_solo_parity_expected_token") or "")
    was_post_delivery_run = bool(session.get("_solo_rv_prior_declaration_returned"))
    append_control_event(
        st,
        session,
        "declaration_attempt",
        control_name=control_name,
        widget_key=widget_key,
        room=room,
        expected_token=expected,
        browser_send_seen=was_post_delivery_run,
        extra={"location": location},
    )
    render_native_control_probe(st, session, probe_placeholder)
    raw = mount_fn()
    coerced = ""
    if raw is not None:
        coerced = raw.strip() if isinstance(raw, str) else str(raw).strip()
    ss_after = repr(session.get(widget_key))[:400] if widget_key in session else "missing"
    if not coerced and ss_after not in ("missing", "None", "''", '""'):
        coerced = ss_after.strip("'\"")
    append_control_event(
        st,
        session,
        "declaration_returned",
        control_name=control_name,
        widget_key=widget_key,
        room=room,
        expected_token=expected,
        component_return=raw,
        coalesced_value=coerced,
        browser_send_seen=was_post_delivery_run,
        extra={"location": location, "session_state_after": ss_after},
    )
    if was_post_delivery_run:
        append_control_event(
            st,
            session,
            "post_delivery_redeclaration",
            control_name=control_name,
            widget_key=widget_key,
            room=room,
            expected_token=expected,
            component_return=raw,
            coalesced_value=coerced,
            browser_send_seen=True,
            extra={"location": location, "session_state_after": ss_after},
        )
    elif not session.get("_solo_rv_prior_declaration_returned"):
        session["_solo_rv_prior_declaration_returned"] = True
    if coerced:
        session["_solo_rv_browser_delivery_recorded"] = True
    render_native_control_probe(st, session, probe_placeholder)
    return raw


def ledger_rows_for_probe_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(payload.get("rows") or [])


def ledger_to_declaration_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for row in rows:
        ev = str(row.get("event") or "")
        phase = ev
        if ev == "declaration_attempt":
            phase = "before_mount"
        elif ev == "declaration_returned":
            phase = "after_mount"
        elif ev == "post_delivery_redeclaration":
            phase = "post_delivery_redeclaration"
        mapped.append(
            {
                **row,
                "phase": phase,
                "script_run_id": row.get("streamlit_session_id"),
                "rv_ladder_step": row.get("control_name"),
                "browser_delivery_seen": bool(row.get("browser_send_seen") or ev == "post_delivery_redeclaration"),
                "before_browser_send": ev == "declaration_attempt" and not row.get("browser_send_seen"),
            }
        )
    return mapped
