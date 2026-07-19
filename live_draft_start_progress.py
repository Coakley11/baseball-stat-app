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
# Hard ceiling — Solo create watchdog aborts earlier (~20s); this is the last resort.
START_IN_FLIGHT_TTL_SEC = 25.0


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
    hard = None
    try:
        from live_draft_solo_create import evaluate_creation_hard_watchdog

        hard = evaluate_creation_hard_watchdog(session)
    except ImportError:
        hard = None
    try:
        from live_draft_creation_trace import (
            evaluate_post_create_watchdog,
            open_preserved_created_draft,
            render_creation_receipt_panel,
        )

        fail = evaluate_post_create_watchdog(session)
    except ImportError:
        fail = None
        open_preserved_created_draft = None  # type: ignore[assignment]
        render_creation_receipt_panel = None  # type: ignore[assignment]

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

    if isinstance(hard, dict) and hard.get("level") == "abort" and hard.get("detail"):
        st.error(hard["detail"])
        room = session.get("live_draft_room")
        if isinstance(room, dict) and open_preserved_created_draft is not None:
            st.warning("A draft object may already exist — **Open Draft** will not create a duplicate.")
            if st.button("Open Draft", key="live_draft_open_after_create_abort", type="primary"):
                opened = open_preserved_created_draft(session)
                if opened.get("ok"):
                    st.rerun()
                else:
                    st.error(str(opened.get("reason") or "Could not open preserved draft."))
        elif st.button("Retry create", key="live_draft_retry_after_create_abort"):
            session.pop("_live_draft_creation_hard_abort", None)
            session.pop(START_ERROR_KEY, None)
            st.rerun()
    elif isinstance(hard, dict) and hard.get("level") == "warn" and hard.get("detail"):
        st.warning(hard["detail"])

    if isinstance(fail, dict) and fail.get("detail"):
        st.error(fail["detail"])
        st.warning(
            "The draft was created successfully, but the active page did not open. "
            "Your draft is preserved — use **Open Draft** (does not create a duplicate)."
        )
        if open_preserved_created_draft is not None and st.button(
            "Open Draft",
            key="live_draft_open_preserved_after_transition_fail",
            type="primary",
        ):
            opened = open_preserved_created_draft(session)
            if opened.get("ok"):
                st.rerun()
            else:
                st.error(str(opened.get("reason") or "Could not open preserved draft."))

    in_flight = is_live_draft_start_in_flight(session)
    if in_flight:
        try:
            from live_draft_creation_trace import user_facing_creation_status

            label = user_facing_creation_status(session)
        except ImportError:
            prog = session.get(START_PROGRESS_KEY) if isinstance(session.get(START_PROGRESS_KEY), dict) else {}
            step = str((prog or {}).get("current_step") or "")
            try:
                from live_draft_ux import user_facing_start_step

                label = user_facing_start_step(step)
            except ImportError:
                label = "Starting…"
        if label:
            st.info(label)

    if developer_mode:
        if render_creation_receipt_panel is not None:
            try:
                render_creation_receipt_panel(st, session, developer_mode=True)
            except Exception:
                pass
        prog = session.get(START_PROGRESS_KEY)
        if isinstance(prog, dict):
            with st.expander("Draft start progress steps", expanded=bool(in_flight)):
                if in_flight:
                    st.caption(f"current step: **{prog.get('current_step', '—')}**")
                steps = prog.get("steps") if isinstance(prog.get("steps"), dict) else {}
                for step, elapsed in steps.items():
                    st.text(f"{step}: {elapsed}s")
