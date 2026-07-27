"""Dedicated P6 diagnostic entrypoint — no Live Draft body branch required."""

from __future__ import annotations

from typing import Any

from live_draft_solo_persistent_parity_ladder import (
    PARITY_CONTROL_KEY,
    PARITY_HANDLED_WAKE_KEY,
    PARITY_MOUNTED_KEY,
    PARITY_P6_DISABLE_PICK_KEY,
    SOLO_PERSISTENT_WAKE_LATCH_KEY,
    ensure_p6_latched_production_token,
)
from live_draft_solo_persistent_wake import SOLO_PERSISTENT_WAKE_WIDGET_KEY

P6_DEDICATED_ACTIVE_KEY = "_solo_p6_dedicated_entry_active"
P6_DEDICATED_COMPLETED_RUN_KEY = "_solo_p6_dedicated_entry_completed_run"
P6_DEDICATED_STOP_KEY = "_solo_p6_dedicated_entry_stop_remainder"
P6_DEDICATED_ROUTE_REQUESTED_KEY = "_solo_p6_dedicated_route_requested"
P6_RUN_SCOPED_ROOM_KEY = "_solo_p6_run_scoped_room"


def mark_p6_dedicated_route_requested(st: Any, session: dict[str, Any]) -> None:
    if p6_dedicated_entrypoint_requested(st, session):
        session[P6_DEDICATED_ROUTE_REQUESTED_KEY] = True


def p6_dedicated_blocks_deep_parity(session: dict[str, Any]) -> bool:
    if session.get(P6_DEDICATED_STOP_KEY):
        return True
    return bool(session.get(P6_DEDICATED_ROUTE_REQUESTED_KEY))


def p6_dedicated_entrypoint_requested(st: Any, session: dict[str, Any]) -> bool:
    from live_draft_solo_parity_p6_persistent_diag import (
        P6_DIAG_LATCHED_KEY,
        P6_RUN_ID_QP,
        PARITY_QP,
        _qp_flag,
        _qp_get,
        resolve_p6_run_id,
    )

    if session.get(P6_DEDICATED_ROUTE_REQUESTED_KEY):
        rid = resolve_p6_run_id(st, session) or _qp_get(st, P6_RUN_ID_QP).strip()
        return bool(rid)

    p6_qp = _qp_get(st, PARITY_QP).strip().upper() == "P6"
    p6_session = (
        str(session.get(PARITY_CONTROL_KEY) or session.get("_solo_parity_ladder_control") or "").strip().upper() == "P6"
        or bool(session.get(P6_DIAG_LATCHED_KEY))
    )
    if not p6_qp and not p6_session:
        return False
    if not _qp_flag(st, "solo_delivery_diag") and not session.get("_solo_delivery_diag_enabled"):
        return False
    rid = resolve_p6_run_id(st, session) or _qp_get(st, P6_RUN_ID_QP).strip()
    return bool(rid)


def p6_dedicated_auth_ready(st: Any, session: dict[str, Any]) -> bool:
    try:
        from suite_auth import auth_session_complete, is_auth_enabled, is_authenticated

        if not is_auth_enabled():
            return True
        if is_authenticated(session) and auth_session_complete(session):
            return True
    except ImportError:
        return True
    try:
        from live_draft_solo_parity_p6_persistent_diag import _qp_get
        from suite_auth_browser import SESSION_QUERY_PARAM, SESSION_STATE_SID_KEY

        sid = str(session.get(SESSION_STATE_SID_KEY) or _qp_get(st, SESSION_QUERY_PARAM) or "").strip()
        if len(sid) >= 8:
            return True
    except ImportError:
        pass
    return False


def try_p6_dedicated_entrypoint(st: Any, session: dict[str, Any], *, force: bool = False) -> bool:
    """Mount production persistent wake once, probe + st.stop(); bypass normal app routing."""
    from live_draft_solo_parity_p6_persistent_diag import (
        P6_MOUNTED_RUN_ID_KEY,
        append_p6_ledger_row,
        apply_p6_clear_once_hygiene,
        latch_p6_diag_mode,
        record_p6_token_latched,
        render_p6_writer_probe,
        resolve_p6_run_id,
        synthetic_room_id_for_run,
    )

    if not force and not p6_dedicated_entrypoint_requested(st, session):
        return False
    if not p6_dedicated_auth_ready(st, session):
        from live_draft_solo_parity_p6_persistent_diag import append_p6_ledger_row

        append_p6_ledger_row(
            session,
            "diagnostic_entrypoint_auth_blocked",
            st=st,
            reason="suite_auth_not_ready",
        )
        return False

    latch_p6_diag_mode(st, session)
    run_id = resolve_p6_run_id(st, session)
    if not run_id:
        append_p6_ledger_row(
            session,
            "diagnostic_entrypoint_run_id_missing",
            st=st,
            reason="resolve_p6_run_id_empty",
        )
        return False

    session[P6_DEDICATED_ACTIVE_KEY] = True
    session[P6_DEDICATED_STOP_KEY] = True
    session[PARITY_CONTROL_KEY] = "P6"
    session["_solo_parity_ladder_control"] = "P6"
    session[PARITY_P6_DISABLE_PICK_KEY] = True
    session["_solo_delivery_diag_enabled"] = True
    session[P6_RUN_SCOPED_ROOM_KEY] = True

    append_p6_ledger_row(
        session,
        "diagnostic_entrypoint_entered",
        st=st,
        entrypoint="live_draft_solo_p6_dedicated_entrypoint.try_p6_dedicated_entrypoint",
    )

    if session.get(P6_DEDICATED_COMPLETED_RUN_KEY) == run_id:
        from live_draft_solo_parity_p6_persistent_diag import get_p6_ledger_for_run

        prior = get_p6_ledger_for_run(session, run_id)
        if any(isinstance(r, dict) and r.get("stage") == "component_declared" for r in prior):
            render_p6_writer_probe(st, session)
            st.stop()
            return True
        session.pop(P6_DEDICATED_COMPLETED_RUN_KEY, None)

    key = SOLO_PERSISTENT_WAKE_WIDGET_KEY
    apply_p6_clear_once_hygiene(st, session, widget_key=key)
    token, synth = ensure_p6_latched_production_token(session)
    room_id = synthetic_room_id_for_run(run_id)
    record_p6_token_latched(session, token=token, st=st)
    append_p6_ledger_row(
        session,
        "component_declaration_attempted",
        st=st,
        widget_key=key,
        expected_token=token,
        actual_token=token,
        synthetic_room_id=room_id,
        on_change_callback="_production_deliver_callback",
    )
    session[SOLO_PERSISTENT_WAKE_LATCH_KEY] = True
    session["_solo_expire_owner"] = "wake"
    session[PARITY_HANDLED_WAKE_KEY] = True
    session.pop("_solo_persistent_wake_flush_disabled", None)

    from live_draft_solo_persistent_wake import try_solo_persistent_wake_ldr_entry

    try_solo_persistent_wake_ldr_entry(st, session, synth)
    session[PARITY_MOUNTED_KEY] = True
    session[P6_MOUNTED_RUN_ID_KEY] = run_id
    session[P6_DEDICATED_COMPLETED_RUN_KEY] = run_id
    render_p6_writer_probe(st, session)
    st.caption("P6 dedicated persistent-wake diagnostic (production entrypoint).")
    st.stop()
    return True


def run_p6_dedicated_pre_app_shell(st: Any, session: dict[str, Any]) -> bool:
    """Auth + workspace restore, mount production wake, probe, and stop before normal app routing."""
    if not p6_dedicated_entrypoint_requested(st, session):
        return False
    mark_p6_dedicated_route_requested(st, session)
    try:
        from suite_workspace import bootstrap_suite_workspace

        bootstrap_suite_workspace(st)
    except Exception:
        pass
    try:
        from suite_auth import hard_clamp_owned_workspace_before_scoped_load

        hard_clamp_owned_workspace_before_scoped_load(session)
    except Exception:
        pass
    try:
        from baseball_account_sidebar import prepare_baseball_auth_session

        prepare_baseball_auth_session(st)
    except Exception:
        pass
    try:
        from suite_auth import is_auth_enabled, process_pending_auth_login

        if is_auth_enabled():
            process_pending_auth_login(st)
    except Exception:
        pass
    try:
        from live_draft_queue_survival import begin_queue_script_pass

        begin_queue_script_pass(session, st=st)
    except Exception:
        pass
    try:
        from baseball_persistent_state import prepare_baseball_workspace

        prepare_baseball_workspace(st)
    except Exception:
        pass
    try:
        from live_draft_solo_parity_p6_persistent_diag import (
            enable_p6_persistent_diag_from_query,
            on_ultra_early_script_run,
            render_p6_writer_probe,
        )

        enable_p6_persistent_diag_from_query(st, session)
        on_ultra_early_script_run(st, session, after_workspace=True)
    except ImportError:
        pass
    mark_p6_dedicated_route_requested(st, session)
    mounted = try_p6_dedicated_entrypoint(st, session, force=True)
    try:
        from live_draft_solo_parity_p6_persistent_diag import render_p6_writer_probe

        render_p6_writer_probe(st, session)
    except ImportError:
        pass
    if not mounted:
        st.warning("P6 dedicated entrypoint did not mount; see writer probe ledger.")
    st.caption("P6 dedicated persistent-wake diagnostic (production entrypoint).")
    st.stop()
    return True
