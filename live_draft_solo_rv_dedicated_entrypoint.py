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


def _rv_real_room_bootstrap(st: Any, session: dict[str, Any], *, step: str = "") -> None:
    """Diag-only: restore auth/workspace before RV1+ mount (no cross-nav room hydration)."""
    rv3 = step == "RV3"
    probe_placeholder = None
    if rv3:
        try:
            from live_draft_solo_rv3_room_continuity import record_rv3_room_checkpoint

            record_rv3_room_checkpoint(st, session, "script_begin")
        except ImportError:
            pass
    if step not in ("RV1", "RV2", "RV3"):
        _apply_harness_room_query_context(st, session)
    if rv3:
        try:
            from live_draft_solo_rv3_room_continuity import record_rv3_room_checkpoint

            record_rv3_room_checkpoint(st, session, "before_auth_restore")
        except ImportError:
            pass
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
    if rv3:
        try:
            from live_draft_solo_rv3_room_continuity import record_rv3_room_checkpoint

            record_rv3_room_checkpoint(st, session, "after_auth_restore")
            record_rv3_room_checkpoint(st, session, "before_workspace_preparation")
        except ImportError:
            pass
    try:
        from baseball_persistent_state import prepare_baseball_workspace

        prepare_baseball_workspace(st)
    except Exception:
        pass
    if rv3:
        try:
            from live_draft_solo_rv3_room_continuity import record_rv3_room_checkpoint

            record_rv3_room_checkpoint(st, session, "after_workspace_preparation")
            record_rv3_room_checkpoint(st, session, "before_prepare_live_draft_state")
        except ImportError:
            pass
    try:
        from live_draft_state import prepare_live_draft_state

        prepare_live_draft_state(session)
    except Exception:
        pass
    if rv3:
        try:
            from live_draft_solo_rv3_room_continuity import record_rv3_room_checkpoint, restore_rv3_run_scoped_room

            record_rv3_room_checkpoint(st, session, "after_prepare_live_draft_state")
            restore_rv3_run_scoped_room(session)
        except ImportError:
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
        from live_draft_solo_rv3_phase import (
            RV3_PHASE_SETUP,
            RV3_SETUP_COMPLETE_KEY,
            append_rv3_setup_complete,
            get_rv3_phase,
            rv3_on_script_run_begin,
            set_rv3_phase,
        )

        _rv_real_room_bootstrap(st, session, step=step)
        rv3_on_script_run_begin(session)
        probe_placeholder = st.empty()
        render_native_control_probe(st, session, probe_placeholder)
        append_control_event(st, session, "script_begin", control_name=step)
        append_control_event(st, session, "rv_entrypoint_entered", control_name=step)
        render_native_control_probe(st, session, probe_placeholder)
        phase = get_rv3_phase(session)
        if phase == RV3_PHASE_SETUP and session.get(RV3_SETUP_COMPLETE_KEY):
            set_rv3_phase(session, RV3_PHASE_PRODUCTION_MOUNT)
            phase = RV3_PHASE_PRODUCTION_MOUNT
        if phase == RV3_PHASE_SETUP:
            from live_draft_solo_rv_production_room_setup import ensure_rv1_production_solo_room

            setup = ensure_rv1_production_solo_room(st, session, probe_placeholder=probe_placeholder)
            if not setup.get("ok"):
                append_control_event(
                    st,
                    session,
                    "rv_mount_failed",
                    control_name=step,
                    extra={
                        "reason": str(setup.get("reason") or setup.get("invalid") or "production_setup_failed"),
                        "invalid": str(setup.get("invalid") or "INVALID_RV3_SETUP_NOT_COMPLETED"),
                    },
                )
                render_native_control_probe(st, session, probe_placeholder)
                st.caption(f"RV ladder {step}: setup failed {setup.get('invalid') or setup.get('reason')}")
                return True
            append_rv3_setup_complete(st, session, probe_placeholder=probe_placeholder)
            render_native_control_probe(st, session, probe_placeholder)
            st.caption(f"RV ladder {step}: setup complete room={str(setup.get('room_id') or '')[:16]}")
            st.rerun()
            return True
        st.caption(f"RV ladder {step}: phase={phase} room reuse/hydrate on LDR entry")
        return False
    if step in ("RV1", "RV2"):
        _rv_real_room_bootstrap(st, session, step=step)
    if step == "RV2":
        probe_placeholder = st.empty()
        render_native_control_probe(st, session, probe_placeholder)
        append_control_event(st, session, "script_begin", control_name=step)
        append_control_event(st, session, "rv_entrypoint_entered", control_name=step)
        render_native_control_probe(st, session, probe_placeholder)
        from live_draft_solo_rv_production_room_setup import ensure_rv1_production_solo_room

        setup = ensure_rv1_production_solo_room(st, session, probe_placeholder=probe_placeholder)
        if setup.get("ok") and not session.get("_solo_rv_rv2_production_setup_done"):
            session["_solo_rv_rv2_production_setup_done"] = True
        result: dict[str, Any] = {"ok": False, "reason": str(setup.get("reason") or setup.get("invalid") or "")}
        if setup.get("ok"):
            post_delivery = bool(session.get("_solo_rv_prior_declaration_returned"))
            need_mount = not session.get("_solo_rv_rv2_initial_mount_done") or post_delivery
            if need_mount:
                result = execute_rv_step_mount(st, session, step, probe_placeholder=probe_placeholder)
                if result.get("ok") and not session.get("_solo_rv_rv2_initial_mount_done"):
                    session["_solo_rv_rv2_initial_mount_done"] = True
            else:
                result = {"ok": True, "token": str(setup.get("room") and ""), "skipped_remount": True}
        if not setup.get("ok"):
            append_control_event(
                st,
                session,
                "rv_mount_failed",
                control_name=step,
                extra={
                    "reason": str(setup.get("reason") or setup.get("invalid") or "production_setup_failed"),
                    "invalid": str(setup.get("invalid") or ""),
                },
            )
            render_native_control_probe(st, session, probe_placeholder)
        elif not result.get("ok"):
            append_control_event(
                st,
                session,
                "rv_mount_failed",
                control_name=step,
                extra={"reason": str(result.get("reason") or "")},
            )
            render_native_control_probe(st, session, probe_placeholder)
        st.caption(
            f"RV ladder {step}: setup={'ok' if setup.get('ok') else 'fail'} "
            f"mount={'ok' if result.get('ok') else 'fail'} "
            f"token={str(result.get('token') or '')[:60]}"
        )
        return False
    probe_placeholder = st.empty()
    render_native_control_probe(st, session, probe_placeholder)
    append_control_event(st, session, "script_begin", control_name=step)
    append_control_event(st, session, "rv_entrypoint_entered", control_name=step)
    render_native_control_probe(st, session, probe_placeholder)
    if step == "RV1":
        from live_draft_solo_rv_production_room_setup import ensure_rv1_production_solo_room

        setup = ensure_rv1_production_solo_room(st, session, probe_placeholder=probe_placeholder)
        if not setup.get("ok"):
            append_control_event(
                st,
                session,
                "rv_mount_failed",
                control_name=step,
                extra={
                    "reason": str(setup.get("reason") or setup.get("invalid") or "production_setup_failed"),
                    "invalid": str(setup.get("invalid") or ""),
                },
            )
            render_native_control_probe(st, session, probe_placeholder)
            st.caption(f"RV ladder {step}: production setup failed {setup.get('invalid') or setup.get('reason')}")
            if rv_pre_app_shell_should_stop(session):
                render_native_control_probe(st, session, probe_placeholder)
                return True
            return False
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
    from live_draft_solo_rv3_phase import get_rv3_phase, prepare_rv3_production_mount, rv3_allows_full_ldr_countdown

    if str(session.get("_solo_rv_ladder_step") or "") != "RV3":
        return
    if not rv3_allows_full_ldr_countdown(session):
        return
    if phase == "before":
        prep = prepare_rv3_production_mount(st, session)
        if not prep.get("ok"):
            from live_draft_solo_rv_control_probe import append_control_event

            append_control_event(
                st,
                session,
                "rv_mount_failed",
                control_name="RV3",
                extra={
                    "reason": str(prep.get("reason") or "rv3_prepare_failed"),
                    "invalid": str(prep.get("invalid") or "INVALID_RV3_REAL_ROOM_NOT_HYDRATED"),
                },
            )
            return
    from live_draft_solo_rv_binding_ladder import try_rv3_ldr_persistent_mount

    try_rv3_ldr_persistent_mount(st, session, room, phase=phase)
