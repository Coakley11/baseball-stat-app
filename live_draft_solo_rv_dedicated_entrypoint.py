"""RV return-value binding ladder — dedicated early shell (diag-only)."""

from __future__ import annotations

from typing import Any

from live_draft_solo_rv_binding_ladder import (
    _apply_harness_room_query_context,
    enable_rv_ladder_session,
    execute_rv_step_mount,
    rv_ladder_requested,
    rv_pre_app_shell_should_stop,
)
from live_draft_solo_rv_control_probe import (
    append_control_event,
    render_native_control_probe,
)


def _rv_real_room_bootstrap(st: Any, session: dict[str, Any]) -> None:
    """Diag-only: restore auth/workspace so real Solo room is in session before RV1+ mount."""
    _apply_harness_room_query_context(st, session)
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
        from baseball_persistent_state import prepare_baseball_workspace

        prepare_baseball_workspace(st)
    except Exception:
        pass
    try:
        from live_draft_state import prepare_live_draft_state

        prepare_live_draft_state(session)
    except Exception:
        pass
    try:
        from live_draft_queue_survival import begin_queue_script_pass

        begin_queue_script_pass(session, st=st)
    except Exception:
        pass


def run_rv_pre_app_shell(st: Any, session: dict[str, Any]) -> bool:
    """Returns True when the app must st.stop() after RV0/RV1 shell mount."""
    if not rv_ladder_requested(st, session):
        return False
    step = enable_rv_ladder_session(st, session)
    if not step:
        return False
    if step == "RV3":
        return False
    if step in ("RV1", "RV2"):
        _rv_real_room_bootstrap(st, session)
    if step == "RV2":
        probe_placeholder = st.empty()
        render_native_control_probe(st, session, probe_placeholder)
        append_control_event(st, session, "script_begin", control_name=step)
        append_control_event(st, session, "rv_entrypoint_entered", control_name=step)
        render_native_control_probe(st, session, probe_placeholder)
        result = execute_rv_step_mount(st, session, step, probe_placeholder=probe_placeholder)
        if not result.get("ok"):
            append_control_event(
                st,
                session,
                "rv_mount_failed",
                control_name=step,
                extra={"reason": str(result.get("reason") or "")},
            )
            render_native_control_probe(st, session, probe_placeholder)
        else:
            session["_solo_rv_rv2_initial_mount_done"] = True
        st.caption(f"RV ladder {step}: mount={'ok' if result.get('ok') else 'fail'} token={str(result.get('token') or '')[:60]}")
        return False
    probe_placeholder = st.empty()
    render_native_control_probe(st, session, probe_placeholder)
    append_control_event(st, session, "script_begin", control_name=step)
    append_control_event(st, session, "rv_entrypoint_entered", control_name=step)
    render_native_control_probe(st, session, probe_placeholder)
    result = execute_rv_step_mount(st, session, step, probe_placeholder=probe_placeholder)
    if not result.get("ok"):
        append_control_event(
            st,
            session,
            "rv_mount_failed",
            control_name=step,
            extra={"reason": str(result.get("reason") or "")},
        )
        render_native_control_probe(st, session, probe_placeholder)
    st.caption(f"RV ladder {step}: mount={'ok' if result.get('ok') else 'fail'} token={str(result.get('token') or '')[:60]}")
    if rv_pre_app_shell_should_stop(session):
        render_native_control_probe(st, session, probe_placeholder)
        return True
    return False


def rv3_on_ldr_entry(st: Any, session: dict[str, Any], room: Any, *, phase: str) -> None:
    from live_draft_solo_rv_binding_ladder import try_rv3_ldr_persistent_mount

    try_rv3_ldr_persistent_mount(st, session, room, phase=phase)
