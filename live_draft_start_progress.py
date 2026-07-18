"""Live draft start progress — stage timings, poll gating, and visible debug."""

from __future__ import annotations

import time
from typing import Any

START_IN_FLIGHT_KEY = "_live_draft_start_in_flight"
START_PROGRESS_KEY = "_live_draft_start_progress"
START_ERROR_KEY = "_live_draft_start_error"
PENDING_ACTIVITY_EVENT_KEY = "_pending_live_draft_created_activity"
MONO_START_KEY = "_live_draft_start_mono_t0"
# Hard ceiling so "Preparing Draft…" cannot trap the user after a hung/exception path.
START_IN_FLIGHT_TTL_SEC = 90.0


def _mono_t0(session: dict[str, Any]) -> float:
    t0 = session.get(MONO_START_KEY)
    if isinstance(t0, (int, float)) and t0 > 0:
        return float(t0)
    return time.monotonic()


def clear_post_delete_create_blocks(session: dict[str, Any]) -> None:
    """Allow a brand-new create after End/Delete (lifecycle must not nuke the new room)."""
    session.pop("_live_draft_deleting", None)
    session.pop("_live_draft_force_setup_after_delete", None)
    session.pop("_live_draft_exit_deleted_room", None)
    session.pop("_live_draft_controls_locked", None)
    try:
        from live_draft_termination import SUPPRESS_FRAGMENTS_KEY

        session.pop(SUPPRESS_FRAGMENTS_KEY, None)
    except ImportError:
        session.pop("_live_draft_suppress_fragments", None)


def begin_live_draft_start(session: dict[str, Any], *, mode: str = "new") -> None:
    clear_post_delete_create_blocks(session)
    session[START_IN_FLIGHT_KEY] = True
    session[MONO_START_KEY] = time.monotonic()
    session.pop(START_ERROR_KEY, None)
    session[START_PROGRESS_KEY] = {
        "start_draft_clicked_ts": time.time(),
        "current_step": "start_clicked",
        "mode": mode,
        "lifecycle": "creating",
        "steps": {"start_clicked": 0.0},
    }
    session.pop("_live_draft_rerun_count", None)
    session.pop("_live_draft_rerun_loop_prevented", None)


def mark_start_step(session: dict[str, Any], step: str, **fields: Any) -> None:
    prog = dict(session.get(START_PROGRESS_KEY) or {})
    steps = dict(prog.get("steps") or {})
    elapsed = round(time.monotonic() - _mono_t0(session), 3)
    steps[step] = elapsed
    prog["steps"] = steps
    prog["current_step"] = step
    prog["last_step_elapsed_sec"] = elapsed
    if step == "start_clicked":
        prog["click_received_ts"] = time.time()
    for key, val in fields.items():
        if val is not None:
            prog[key] = val
    session[START_PROGRESS_KEY] = prog
    try:
        from draft_ui import record_start_live_draft_diagnostics

        record_start_live_draft_diagnostics(session, current_start_step=step, step_elapsed_sec=elapsed, **fields)
    except ImportError:
        pass


def finish_live_draft_start(session: dict[str, Any], *, ok: bool = True, error: str = "") -> None:
    mark_start_step(
        session,
        "first_render_ready" if ok else "start_failed",
        start_completed=ok,
        start_error=error or None,
        lifecycle="waiting_shared_lobby_or_active" if ok else "creation_failed",
    )
    session.pop(START_IN_FLIGHT_KEY, None)
    session.pop(MONO_START_KEY, None)
    session.pop("_start_live_draft_pending", None)
    if ok:
        session.pop(START_ERROR_KEY, None)
    elif error:
        session[START_ERROR_KEY] = {
            "step": str((session.get(START_PROGRESS_KEY) or {}).get("current_step") or "start_failed"),
            "error": str(error),
            "mode": str((session.get(START_PROGRESS_KEY) or {}).get("mode") or ""),
            "at": time.time(),
            "partial_room": bool(isinstance(session.get("live_draft_room"), dict)),
            "room_code": str(session.get("active_shared_draft_room_code") or "").strip().upper(),
        }


def expire_stale_live_draft_start(session: dict[str, Any]) -> bool:
    """Clear a stuck creating flag after TTL. Returns True when expired."""
    if not session.get(START_IN_FLIGHT_KEY):
        return False
    t0 = session.get(MONO_START_KEY)
    if not isinstance(t0, (int, float)) or t0 <= 0:
        # In-flight without a clock — keep gating; begin() always sets MONO_START_KEY.
        return False
    elapsed = time.monotonic() - float(t0)
    if elapsed < START_IN_FLIGHT_TTL_SEC:
        return False
    step = str((session.get(START_PROGRESS_KEY) or {}).get("current_step") or "unknown")
    finish_live_draft_start(
        session,
        ok=False,
        error=f"Draft creation timed out after {int(elapsed)}s at step '{step}'.",
    )
    return True


def is_live_draft_start_in_flight(session: dict[str, Any]) -> bool:
    # Pending alone (no mono clock yet) still gates polls; TTL only applies once begin() ran.
    if session.get(START_IN_FLIGHT_KEY):
        expire_stale_live_draft_start(session)
    if session.get(START_IN_FLIGHT_KEY):
        return True
    if session.get("_start_live_draft_pending"):
        return True
    return False


def should_skip_live_draft_poll(session: dict[str, Any]) -> bool:
    return is_live_draft_start_in_flight(session)


def defer_cloud_autosave_during_start(session: dict[str, Any], *, seconds: float = 45.0) -> None:
    try:
        from suite_egress_policy import block_cloud_autosave_for_poll_sync

        block_cloud_autosave_for_poll_sync(session)
    except ImportError:
        session["_suite_defer_cloud_autosave_until"] = time.time() + float(seconds)


def queue_live_draft_created_activity(session: dict[str, Any]) -> None:
    session[PENDING_ACTIVITY_EVENT_KEY] = True


def flush_pending_live_draft_created_activity(session: dict[str, Any], room: dict[str, Any] | None) -> None:
    if not session.pop(PENDING_ACTIVITY_EVENT_KEY, None):
        return
    if not isinstance(room, dict):
        return
    try:
        from baseball_draft_activity import log_live_draft_room_created

        log_live_draft_room_created(room, session=session)
    except Exception:
        pass


def render_draft_start_progress(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    expire_stale_live_draft_start(session)
    err = session.get(START_ERROR_KEY)
    if isinstance(err, dict) and err.get("error"):
        st.error(
            f"Draft creation failed at **{err.get('step') or 'unknown'}**: {err.get('error')}"
        )
        if developer_mode:
            st.caption(
                f"mode={err.get('mode') or '—'} · partial_room={err.get('partial_room')} · "
                f"room_code={err.get('room_code') or '—'}"
            )
        if st.button("Dismiss creation error", key="live_draft_dismiss_start_error"):
            session.pop(START_ERROR_KEY, None)
            st.rerun()

    prog = session.get(START_PROGRESS_KEY)
    if not isinstance(prog, dict):
        return
    in_flight = is_live_draft_start_in_flight(session)
    if not developer_mode:
        if not in_flight:
            return
        step = str(prog.get("current_step") or "")
        try:
            from live_draft_ux import user_facing_start_step

            label = user_facing_start_step(step)
        except ImportError:
            label = "Preparing Draft…"
        st.info(label)
        return
    with st.expander("Draft start progress", expanded=bool(in_flight or developer_mode)):
        if in_flight:
            st.info(f"Starting draft… current step: **{prog.get('current_step', '—')}**")
        steps = prog.get("steps") if isinstance(prog.get("steps"), dict) else {}
        for step, elapsed in steps.items():
            st.text(f"{step}: {elapsed}s")
        for key in (
            "click_received_ts",
            "room_created_ts",
            "market_data_loaded",
            "pool_build_start_ts",
            "pool_build_end_ts",
            "room_initialized_ts",
            "shared_write_start_ts",
            "shared_write_end_ts",
            "shared_write_ok",
            "shared_write_error",
            "local_save_start_ts",
            "local_save_end_ts",
            "activity_write_start_ts",
            "activity_write_end_ts",
            "timer_deadline_set",
            "pool_loaded",
            "recommendations_loaded",
            "first_render_ready",
            "rerun_requested",
            "last_rerun_reason",
            "start_error",
            "lifecycle",
        ):
            val = prog.get(key)
            if val is not None and val != "":
                st.text(f"{key}: {val}")
        try:
            from live_draft_safe_mode import RERUN_DIAG_KEY

            rerun = session.get(RERUN_DIAG_KEY) or {}
            if isinstance(rerun, dict) and rerun.get("rerun_source"):
                st.text(f"last_rerun_reason: {rerun.get('rerun_source')}")
        except ImportError:
            pass
