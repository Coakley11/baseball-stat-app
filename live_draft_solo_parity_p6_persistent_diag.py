"""P6 writer-session diagnostic ledger (st.session_state) and #solo-p6-writer-probe."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_WAKE_TOKEN_KEY,
    SOLO_PERSISTENT_WAKE_WIDGET_KEY,
)

PARITY_QP = "solo_persistent_parity"
P6_RUN_ID_QP = "solo_p6_run_id"
P6_WRITER_PROBE_ID = "solo-p6-writer-probe"
P6_SESSION_LEDGERS_KEY = "_solo_p6_writer_ledgers"
P6_CLEAR_ONCE_GUARD_KEY = "_solo_p6_permanent_key_clear_run_id"
P6_SCRIPT_RUN_KEY = "_solo_p6_writer_script_run"
P6_ACTIVE_RUN_ID_SESSION_KEY = "_solo_p6_active_diagnostic_run_id"
P6_MOUNTED_RUN_ID_KEY = "_solo_p6_mounted_run_id"
P6_DIAG_LATCHED_KEY = "_solo_p6_diag_latched"
P6_DIAG_DELIVERY_SEEN_KEY = "_solo_p6_delivery_seen"
_MAX_ROWS = 400


def _qp_get(st: Any | None, name: str) -> str:
    if st is None:
        return ""
    try:
        from live_draft_cloud_diagnostics import _qp_get as get_qp

        return get_qp(st, name)
    except ImportError:
        return ""


def _qp_flag(st: Any | None, name: str) -> bool:
    if st is None:
        return False
    try:
        from live_draft_cloud_diagnostics import _qp_flag as flag

        return flag(st, name)
    except ImportError:
        return False


def _streamlit_session_id() -> str:
    try:
        from live_draft_callback_boundary_diag import _streamlit_session_id as sid_fn

        return sid_fn()
    except ImportError:
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx

            ctx = get_script_run_ctx()
            return str(getattr(ctx, "session_id", "") or "")
        except Exception:
            return ""


def resolve_p6_run_id(st: Any | None, session: dict[str, Any]) -> str:
    rid = str(session.get("_solo_p6_run_id") or "").strip()
    if not rid and st is not None:
        rid = _qp_get(st, P6_RUN_ID_QP).strip()
    if rid:
        session["_solo_p6_run_id"] = rid
    return rid


def parity_p6_active(session: dict[str, Any]) -> bool:
    return str(session.get("_solo_parity_ladder_control") or "").strip().upper() == "P6"


def parity_p6_pick_processing_disabled(session: dict[str, Any]) -> bool:
    return parity_p6_active(session) and bool(session.get("_solo_parity_p6_disable_pick_processing"))


def p6_persistent_diag_active(st: Any | None, session: dict[str, Any]) -> bool:
    if session.get(P6_DIAG_LATCHED_KEY) or session.get("_solo_parity_p6_persistent_diag"):
        return True
    if str(session.get("_solo_parity_ladder_control") or "").strip().upper() == "P6":
        return True
    if st is not None and _qp_get(st, PARITY_QP).strip().upper() == "P6":
        return True
    return parity_p6_active(session)


def reset_p6_diagnostic_lifecycle_for_run_id(session: dict[str, Any], new_run_id: str) -> bool:
    """Clear P6 diagnostic lifecycle only when solo_p6_run_id changes."""
    new_run_id = str(new_run_id or "").strip()
    if not new_run_id:
        return False
    prior = str(session.get(P6_ACTIVE_RUN_ID_SESSION_KEY) or "").strip()
    if prior == new_run_id:
        return False
    try:
        from live_draft_solo_persistent_parity_ladder import (
            PARITY_HANDLED_WAKE_KEY,
            PARITY_MOUNTED_KEY,
            PARITY_P6_CALLBACK_SEQ_KEY,
            PARITY_P6_DISABLE_PICK_KEY,
            PARITY_P6_TOKEN_LATCHED_KEY,
        )
    except ImportError:
        PARITY_MOUNTED_KEY = "_solo_parity_ladder_mounted"
        PARITY_P6_TOKEN_LATCHED_KEY = "_solo_parity_p6_token_latched"
        PARITY_P6_DISABLE_PICK_KEY = "_solo_parity_p6_disable_pick_processing"
        PARITY_P6_CALLBACK_SEQ_KEY = "_solo_parity_p6_production_callback_seq"
        PARITY_HANDLED_WAKE_KEY = "_solo_parity_handled_persistent_wake"

    session.pop(PARITY_MOUNTED_KEY, None)
    session.pop(P6_MOUNTED_RUN_ID_KEY, None)
    session.pop(P6_CLEAR_ONCE_GUARD_KEY, None)
    session.pop(PARITY_P6_TOKEN_LATCHED_KEY, None)
    session.pop("_solo_parity_expected_token", None)
    session.pop(SOLO_PERSISTENT_WAKE_TOKEN_KEY, None)
    session.pop("_solo_parity_p6_deadline", None)
    session.pop(PARITY_P6_CALLBACK_SEQ_KEY, None)
    session.pop(PARITY_P6_DISABLE_PICK_KEY, None)
    session.pop(P6_DIAG_DELIVERY_SEEN_KEY, None)
    session.pop("_solo_p6_delivery_seen", None)
    session.pop(PARITY_HANDLED_WAKE_KEY, None)
    session.pop(P6_SCRIPT_RUN_KEY, None)
    session.pop("_solo_p6_run_scoped_room", None)
    try:
        from live_draft_solo_p6_early_shell import (
            P6_EARLY_SHELL_ACTIVE_KEY,
            P6_EARLY_SHELL_COMPLETED_RUN_KEY,
            P6_EARLY_SHELL_STOP_KEY,
            P6_RUN_SCOPED_ROOM_KEY,
        )

        session.pop(P6_EARLY_SHELL_ACTIVE_KEY, None)
        session.pop(P6_EARLY_SHELL_COMPLETED_RUN_KEY, None)
        session.pop(P6_EARLY_SHELL_STOP_KEY, None)
        session.pop(P6_RUN_SCOPED_ROOM_KEY, None)
    except ImportError:
        pass
    try:
        from live_draft_solo_transport_boundary_diag import PRODUCTION_CALLBACK_FLAG

        session.pop(PRODUCTION_CALLBACK_FLAG, None)
        session.pop(f"{PRODUCTION_CALLBACK_FLAG}_count", None)
    except ImportError:
        pass
    store = session.get(P6_SESSION_LEDGERS_KEY)
    if isinstance(store, dict):
        store.pop(new_run_id, None)
    session[P6_ACTIVE_RUN_ID_SESSION_KEY] = new_run_id
    session["_solo_p6_run_id"] = new_run_id
    return True


def latch_p6_diag_mode(st: Any, session: dict[str, Any]) -> None:
    session[P6_DIAG_LATCHED_KEY] = True
    session["_solo_parity_p6_persistent_diag"] = True
    session["_solo_parity_ladder_control"] = "P6"
    session["_solo_delivery_diag_enabled"] = True
    try:
        from live_draft_solo_persistent_parity_ladder import PARITY_CONTROL_KEY

        session[PARITY_CONTROL_KEY] = "P6"
    except ImportError:
        pass
    page = _qp_get(st, "active_page").strip()
    if page:
        session["active_page"] = page


def enable_p6_persistent_diag_from_query(st: Any, session: dict[str, Any]) -> None:
    qp_control = _qp_get(st, PARITY_QP).strip().upper()
    rid_qp = _qp_get(st, P6_RUN_ID_QP).strip()
    if qp_control == "P6":
        latch_p6_diag_mode(st, session)
    elif session.get(P6_DIAG_LATCHED_KEY):
        latch_p6_diag_mode(st, session)
    rid = rid_qp or str(session.get("_solo_p6_run_id") or "").strip()
    if rid_qp:
        reset_p6_diagnostic_lifecycle_for_run_id(session, rid_qp)
        session["_solo_p6_run_id"] = rid_qp
        rid = rid_qp
    if rid and session.get(P6_DIAG_LATCHED_KEY):
        resolve_p6_run_id(st, session)
    if not p6_persistent_diag_active(st, session):
        return
    if _qp_flag(st, "solo_transport_probe"):
        try:
            from live_draft_solo_transport_boundary_diag import bootstrap_transport_diagnostics

            bootstrap_transport_diagnostics(st, session)
        except ImportError:
            pass


def synthetic_room_id_for_run(run_id: str) -> str:
    short = str(run_id or "").replace("-", "")[:8]
    return f"PARITY_{short}" if short else "PARITY"


def synthetic_room_for_run(run_id: str, *, deadline: float) -> dict[str, Any]:
    rid = synthetic_room_id_for_run(run_id)
    return {
        "draft_room_id": rid,
        "draft_id": rid,
        "status": "in_progress",
        "current_pick_index": 0,
        "timer_deadline": deadline,
        "config": {"draft_setup_mode": "solo", "timer_seconds": 10},
    }


def _common_row_fields(session: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "solo_p6_run_id": run_id,
        "synthetic_room_id": synthetic_room_id_for_run(run_id),
    }


def _expected_token(session: dict[str, Any]) -> str:
    return str(
        session.get("_solo_parity_expected_token") or session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or ""
    )[:400]


def _ledger_for_run(session: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    if not run_id:
        return []
    store = session.get(P6_SESSION_LEDGERS_KEY)
    if not isinstance(store, dict):
        store = {}
        session[P6_SESSION_LEDGERS_KEY] = store
    rows = store.get(run_id)
    if not isinstance(rows, list):
        rows = []
        store[run_id] = rows
    return rows


def _widget_raw(st: Any, widget_key: str) -> str:
    try:
        if widget_key in st.session_state:
            return repr(st.session_state.get(widget_key))[:400]
    except Exception:
        pass
    return ""


def append_p6_ledger_row(
    session: dict[str, Any],
    stage: str,
    *,
    st: Any | None = None,
    actual_token: str = "",
    expected_token: str = "",
    **fields: Any,
) -> dict[str, Any]:
    if not p6_persistent_diag_active(st, session) and not parity_p6_active(session):
        return {}
    run_id = resolve_p6_run_id(st, session)
    if not run_id:
        return {}
    sid = _streamlit_session_id() or str(session.get("_solo_parity_p6_streamlit_session_id") or "")
    if sid:
        session["_solo_parity_p6_streamlit_session_id"] = sid
    run_n = int(session.get(P6_SCRIPT_RUN_KEY) or 0)
    exp = (expected_token or _expected_token(session))[:400]
    act = (actual_token or "")[:400]
    row: dict[str, Any] = {
        "ts": time.time(),
        "stage": str(stage),
        "diagnostic_run_id": run_id,
        "streamlit_session_id": sid,
        "script_run": run_n,
        "expected_token": exp,
        "actual_token": act,
        "event_sequence": 0,
        **_common_row_fields(session, run_id),
        **fields,
    }
    ledger = _ledger_for_run(session, run_id)
    row["seq"] = len(ledger) + 1
    row["event_sequence"] = row["seq"]
    ledger.append(row)
    if len(ledger) > _MAX_ROWS:
        session[P6_SESSION_LEDGERS_KEY][run_id] = ledger[-_MAX_ROWS:]
    return row


def bump_p6_script_run(st: Any | None, session: dict[str, Any]) -> int:
    resolve_p6_run_id(st, session)
    n = int(session.get(P6_SCRIPT_RUN_KEY) or 0) + 1
    session[P6_SCRIPT_RUN_KEY] = n
    if session.get(P6_DIAG_DELIVERY_SEEN_KEY) or session.get("_solo_p6_delivery_seen"):
        append_p6_ledger_row(
            session,
            "post_delivery_script_run",
            st=st,
            prior_delivery_seen=True,
            script_run=n,
        )
    return n


def note_p6_delivery_completed(session: dict[str, Any], *, token: str = "", st: Any | None = None) -> None:
    session[P6_DIAG_DELIVERY_SEEN_KEY] = True
    session["_solo_p6_delivery_seen"] = True
    append_p6_ledger_row(
        session,
        "delivery_completed_marker",
        st=st,
        actual_token=str(token or "")[:400],
    )


def apply_p6_clear_once_hygiene(st: Any, session: dict[str, Any], *, widget_key: str | None = None) -> dict[str, Any]:
    """Diagnostic-only: clear permanent production widget key once before first P6 mount."""
    if not p6_persistent_diag_active(st, session) and not parity_p6_active(session):
        return {}
    run_id = resolve_p6_run_id(st, session)
    if not run_id:
        return {}
    if session.get(P6_CLEAR_ONCE_GUARD_KEY) == run_id:
        return {"skipped": True, "reason": "already_cleared_for_run"}
    key = widget_key or SOLO_PERSISTENT_WAKE_WIDGET_KEY
    initial_raw = _widget_raw(st, key)
    append_p6_ledger_row(
        session,
        "initial_widget_state",
        st=st,
        widget_key=key,
        raw_widget_value=initial_raw,
        actual_token=initial_raw.strip("'\"")[:400],
        source="session_state_pre_mount",
    )
    append_p6_ledger_row(
        session,
        "widget_state_before_clear",
        st=st,
        widget_key=key,
        raw_widget_value=initial_raw,
        actual_token=initial_raw.strip("'\"")[:400],
    )
    try:
        if key in st.session_state:
            del st.session_state[key]
        else:
            st.session_state.pop(key, None)
    except Exception:
        session.pop(key, None)
    after_raw = _widget_raw(st, key)
    append_p6_ledger_row(
        session,
        "widget_state_after_clear",
        st=st,
        widget_key=key,
        raw_widget_value=after_raw or "missing",
        actual_token=after_raw.strip("'\"")[:400] if after_raw else "",
    )
    session[P6_CLEAR_ONCE_GUARD_KEY] = run_id
    return {
        "initial_raw": initial_raw,
        "after_clear_missing": key not in st.session_state,
    }


def record_p6_token_latched(session: dict[str, Any], *, token: str, st: Any | None = None) -> None:
    append_p6_ledger_row(
        session,
        "production_token_latched",
        st=st,
        expected_token=str(token or "")[:400],
        actual_token=str(token or "")[:400],
    )


def on_ultra_early_script_run(st: Any, session: dict[str, Any]) -> None:
    if not p6_persistent_diag_active(st, session):
        return
    if not resolve_p6_run_id(st, session):
        return
    run_n = bump_p6_script_run(st, session)
    widget_key = SOLO_PERSISTENT_WAKE_WIDGET_KEY
    raw = _widget_raw(st, widget_key)
    append_p6_ledger_row(
        session,
        "script_begin",
        st=st,
        expected_token="",
        actual_token=raw.strip("'\"")[:400],
        widget_key=widget_key,
        raw_widget_value=raw,
        script_run=run_n,
        active_page=str(session.get("active_page") or _qp_get(st, "active_page") or ""),
    )
    render_p6_writer_probe(st, session)


def _room_declaration_fields(session: dict[str, Any], *, expire_token: str) -> dict[str, Any]:
    live = session.get("live_draft_room")
    room_id = ""
    pick_index: Any = None
    deadline: Any = None
    if isinstance(live, dict):
        room_id = str(live.get("draft_room_id") or live.get("draft_id") or "")
        pick_index = live.get("current_pick_index")
        deadline = live.get("timer_deadline")
        try:
            from live_draft_timer_logic import live_draft_timer_deadline

            deadline = live_draft_timer_deadline(live) or deadline
        except ImportError:
            pass
    if not deadline and expire_token.count("|") >= 2:
        try:
            deadline = float(expire_token.split("|")[-1])
        except ValueError:
            pass
    run_id = str(session.get("_solo_p6_run_id") or "")
    return {
        "room_id": room_id,
        "pick_index": pick_index,
        "deadline": deadline,
        "diagnostic_run_id": run_id,
        "on_change_callback": "_production_deliver_callback",
    }


def record_p6_component_declaration(
    session: dict[str, Any],
    *,
    widget_key: str,
    expire_token: str,
    component_return: Any = None,
    mount_location: str = "",
    st: Any | None = None,
    component_default: Any = None,
) -> None:
    extra = _room_declaration_fields(session, expire_token=str(expire_token or ""))
    append_p6_ledger_row(
        session,
        "component_declared",
        st=st,
        widget_key=widget_key,
        expected_token=str(expire_token or "")[:400],
        actual_token=str(expire_token or "")[:400],
        component_return=repr(component_return)[:400],
        mount_location=mount_location,
        component_value_default=repr(component_default if component_default is not None else None),
        **extra,
    )


def record_p6_callback_entry(
    session: dict[str, Any],
    *,
    raw: Any,
    widget_key: str,
    expected_token: str = "",
    st: Any | None = None,
) -> None:
    actual = str(raw).strip("'\"")[:400] if raw is not None else ""
    fields = dict(
        st=st,
        raw_widget_value=repr(raw)[:400],
        widget_key=widget_key,
        expected_token=(expected_token or _expected_token(session))[:400],
        actual_token=actual,
    )
    append_p6_ledger_row(session, "callback_entry", **fields)
    append_p6_ledger_row(session, "on_change_callback_entry", **fields)


def record_p6_raw_widget_value(session: dict[str, Any], *, raw: Any, st: Any | None = None) -> None:
    append_p6_ledger_row(
        session,
        "raw_widget_value",
        st=st,
        raw_widget_value=repr(raw)[:400],
        actual_token=str(raw).strip("'\"")[:400] if raw is not None else "",
    )


def record_p6_ownership_claim(
    session: dict[str, Any],
    *,
    attempted: bool,
    accepted: bool | None,
    reject_code: str = "",
    token: str = "",
    delivery_via: str = "",
    st: Any | None = None,
) -> None:
    if attempted:
        attempt_fields = dict(
            st=st,
            expected_token=str(token or _expected_token(session))[:400],
            actual_token=str(token or "")[:400],
            delivery_via=delivery_via,
        )
        append_p6_ledger_row(session, "ownership_attempted", **attempt_fields)
        append_p6_ledger_row(session, "ownership_claim_attempted", **attempt_fields)
    stage = "ownership_claim_accepted" if accepted else "ownership_claim_rejected"
    append_p6_ledger_row(
        session,
        stage,
        st=st,
        ownership_claim_attempted=attempted,
        ownership_claim_accepted=accepted,
        rejection_code=str(reject_code or "")[:120],
        reject_code=str(reject_code or "")[:120],
        expected_token=str(token or _expected_token(session))[:400],
        actual_token=str(token or "")[:400],
        delivery_via=delivery_via,
    )


def record_p6_callback_return(
    session: dict[str, Any],
    *,
    reason: str,
    pick_processing_skipped: bool = False,
    raw: Any = None,
    st: Any | None = None,
) -> None:
    append_p6_ledger_row(
        session,
        "callback_return",
        st=st,
        callback_return_reason=str(reason or "")[:200],
        pick_processing_intentionally_skipped=bool(pick_processing_skipped),
        raw_widget_value=repr(raw)[:400] if raw is not None else "",
        actual_token=str(raw).strip("'\"")[:400] if raw is not None else "",
    )


def record_p6_diagnostic_pick_skipped(
    session: dict[str, Any],
    *,
    reason: str,
    token: str = "",
    st: Any | None = None,
) -> None:
    append_p6_ledger_row(
        session,
        "pick_processing_skipped",
        st=st,
        skip_reason=str(reason or "")[:200],
        expected_token=str(token or _expected_token(session))[:400],
        actual_token=str(token or "")[:400],
    )


def get_p6_ledger_for_run(session: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    return list(_ledger_for_run(session, run_id))


def build_writer_probe_payload(st: Any, session: dict[str, Any]) -> dict[str, Any]:
    run_id = resolve_p6_run_id(st, session)
    rows = _ledger_for_run(session, run_id) if run_id else []
    expected = _expected_token(session)
    widget_key = SOLO_PERSISTENT_WAKE_WIDGET_KEY
    widget_raw = _widget_raw(st, widget_key)
    stale = analyze_stale_state(rows, expected_token=expected, widget_raw=widget_raw)
    cb_stages = {"callback_entry", "on_change_callback_entry"}
    prod_count = sum(1 for r in rows if isinstance(r, dict) and r.get("stage") in cb_stages)
    return {
        "diagnostic_run_id": run_id,
        "solo_p6_run_id": run_id,
        "streamlit_session_id": _streamlit_session_id(),
        "synthetic_room_id": synthetic_room_id_for_run(run_id) if run_id else "",
        "expected_token": expected,
        "script_run_number": int(session.get(P6_SCRIPT_RUN_KEY) or 0),
        "current_widget_raw": widget_raw,
        "raw_session_state_value": widget_raw,
        "ledger_rows": rows,
        "callback_rows": rows,
        "production_callback_entries": prod_count,
        "pick_processing_disabled": parity_p6_pick_processing_disabled(session),
        "stale_state": stale,
        "clear_once_applied": session.get(P6_CLEAR_ONCE_GUARD_KEY) == run_id,
    }


def analyze_stale_state(
    rows: list[dict[str, Any]], *, expected_token: str, widget_raw: str
) -> dict[str, Any]:
    initial = ""
    before_clear = ""
    after_clear = ""
    latched = ""
    latched_ts = 0.0
    for r in rows:
        if not isinstance(r, dict):
            continue
        stage = str(r.get("stage") or "")
        if stage == "initial_widget_state":
            initial = str(r.get("raw_widget_value") or r.get("actual_token") or "")
        elif stage == "widget_state_before_clear":
            before_clear = str(r.get("raw_widget_value") or "")
        elif stage == "widget_state_after_clear":
            after_clear = str(r.get("raw_widget_value") or "")
        elif stage == "production_token_latched":
            latched = str(r.get("expected_token") or "")
            latched_ts = float(r.get("ts") or 0)
    init_token = initial.strip("'\"")
    matched_expected = bool(expected_token and init_token == expected_token)
    matched_parity_prefix = init_token.startswith("PARITY|")
    return {
        "initial_widget_raw": initial,
        "initial_token_normalized": init_token,
        "before_clear_raw": before_clear,
        "after_clear_raw": after_clear,
        "latched_token": latched,
        "latched_ts": latched_ts,
        "expected_token": expected_token,
        "current_widget_raw": widget_raw,
        "initial_equals_expected": matched_expected,
        "initial_was_parity_token": matched_parity_prefix,
        "widget_empty_after_clear": after_clear in ("missing", "", "None"),
    }


def render_p6_writer_probe(st: Any, session: dict[str, Any]) -> None:
    if not p6_persistent_diag_active(st, session):
        return
    if not resolve_p6_run_id(st, session):
        return
    payload = build_writer_probe_payload(st, session)
    raw_json = json.dumps(payload, default=str)
    if len(raw_json) > 240000:
        raw_json = raw_json[:240000]
    b64 = base64.b64encode(raw_json.encode("utf-8")).decode("ascii")
    token = str(payload.get("expected_token") or "")
    st.markdown(
        f'<div id="{P6_WRITER_PROBE_ID}" '
        f'data-run-id="{str(payload.get("diagnostic_run_id") or "").replace(chr(34), chr(39))}" '
        f'data-expected-token="{token.replace(chr(34), chr(39))[:200]}" '
        f'data-row-count="{len(payload.get("ledger_rows") or [])}" '
        f'data-b64="{b64}"></div>',
        unsafe_allow_html=True,
    )


# --- Observer (legacy read-only; not used for grading) ---


def get_p6_ledger(session_or_run_id: str) -> list[dict[str, Any]]:
    return []


def build_ledger_snapshot_for_run(run_id: str) -> dict[str, Any]:
    return {"diagnostic_run_id": run_id, "ledger_rows": [], "callback_rows": []}


def build_p6_probe_payload(st: Any, session: dict[str, Any]) -> dict[str, Any]:
    return build_writer_probe_payload(st, session)


def render_p6_persistent_probe(st: Any, session: dict[str, Any]) -> None:
    render_p6_writer_probe(st, session)


def first_nonempty_p6_snapshot_criteria(payload: dict[str, Any]) -> bool:
    expected = str(payload.get("expected_token") or "")
    if not expected.startswith("PARITY|"):
        return False
    rows = payload.get("callback_rows") if isinstance(payload.get("callback_rows"), list) else []
    has_entry = any(
        isinstance(r, dict) and r.get("stage") in ("callback_entry", "on_change_callback_entry") for r in rows
    )
    has_owner = any(
        isinstance(r, dict)
        and str(r.get("stage") or "")
        in ("ownership_claim_accepted", "ownership_claim_rejected", "ownership_attempted")
        for r in rows
    )
    return has_entry and has_owner


def python_receipt_from_payload(payload: dict[str, Any]) -> bool:
    expected = str(payload.get("expected_token") or "")
    if not expected.startswith("PARITY|"):
        return False
    rows = payload.get("callback_rows") if isinstance(payload.get("callback_rows"), list) else []
    for r in rows:
        if not isinstance(r, dict) or r.get("stage") not in ("callback_entry", "on_change_callback_entry"):
            continue
        act = str(r.get("actual_token") or "")
        if act == expected or expected in act:
            return True
    for r in rows:
        if not isinstance(r, dict) or r.get("stage") != "raw_widget_value":
            continue
        act = str(r.get("actual_token") or "")
        if act == expected:
            return True
    return False
