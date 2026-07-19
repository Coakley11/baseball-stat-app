"""Deployed Live Draft creation trace + receipt (Developer Mode + user-facing steps)."""

from __future__ import annotations

import time
import uuid
from typing import Any

CREATION_RECEIPT_KEY = "_live_draft_creation_receipt"
CREATION_TRACE_KEY = "_live_draft_creation_trace"
PROTECT_ROOM_UNTIL_KEY = "_live_draft_protect_new_room_until"
POST_CREATE_OPEN_KEY = "_live_draft_post_create_open"
POST_CREATE_DEADLINE_KEY = "_live_draft_post_create_deadline"
POST_CREATE_FAIL_KEY = "_live_draft_post_create_transition_fail"
POST_CREATE_WATCHDOG_SEC = 5.0

# Soft thresholds are per-step duration (not total create elapsed).
STEP_SOFT_TIMEOUT_SEC: dict[str, float] = {
    "pool_build_start": 8.0,
    "pool_build_end": 8.0,
    "room_initialized": 3.0,
    "shared_room_create_start": 10.0,
    "commissioner_registered": 8.0,
    "session_installed": 3.0,
    "lifecycle_resolved": 3.0,
    "local_save_start": 5.0,
    "persist_complete": 8.0,
}

USER_STEP_STATUS: dict[str, str] = {
    "button_clicked": "Starting…",
    "begin_live_draft_start": "Starting…",
    "handler_begin": "Starting…",
    "settings_captured": "Creating draft…",
    "market_loaded": "Building player pool…",
    "pool_build_start": "Building player pool…",
    "pool_build_end": "Building player pool…",
    "room_initialized": "Creating draft…",
    "shared_room_create_start": "Creating shared room…",
    "commissioner_registered": "Registering commissioner…",
    "shared_room_create_end": "Opening lobby…",
    "session_installed": "Opening lobby…",
    "solo_started": "Opening draft…",
    "lifecycle_resolved": "Opening draft…",
    "rerun_requested": "Opening draft…",
    "first_render_ready": "Draft ready",
    "active_page_entered": "Draft ready",
    "start_failed": "Draft creation failed",
    "post_create_transition_failed": "Draft created — open failed",
}


def _now() -> float:
    return time.time()


def _mono() -> float:
    return time.monotonic()


def new_attempt_id() -> str:
    return uuid.uuid4().hex[:12]


def init_creation_trace(session: dict[str, Any], *, mode: str, attempt_id: str = "") -> dict[str, Any]:
    aid = str(attempt_id or new_attempt_id())
    started = _now()
    trace = {
        "attempt_id": aid,
        "mode": str(mode or ""),
        "started_at": started,
        "started_mono": _mono(),
        "steps": [],
        "current_step": "button_clicked",
        "success": None,
        "draft_id": "",
        "room_id": "",
        "room_code": "",
        "lifecycle_after": "",
        "failure_summary": "",
        "force_setup_after_delete": bool(session.get("_live_draft_force_setup_after_delete")),
        "deleting": str(session.get("_live_draft_deleting") or ""),
        "page_generation": int(session.get("_live_draft_page_epoch") or session.get("page_generation") or 0),
    }
    session[CREATION_TRACE_KEY] = trace
    session[CREATION_RECEIPT_KEY] = {
        "attempt_id": aid,
        "selected_mode": str(mode or ""),
        "started_time": started,
        "completed_step": "button_clicked",
        "draft_id": "",
        "room_id": "",
        "room_code": "",
        "creation_success": None,
        "lifecycle_after_creation": "",
        "failure_summary": "",
    }
    session.pop(POST_CREATE_FAIL_KEY, None)
    return trace


def note_creation_step(
    session: dict[str, Any],
    step: str,
    *,
    ok: bool = True,
    error: str = "",
    **fields: Any,
) -> dict[str, Any]:
    trace = dict(session.get(CREATION_TRACE_KEY) or {})
    if not trace:
        trace = init_creation_trace(session, mode=str(session.get("_start_live_draft_mode") or ""))
    started_mono = float(trace.get("started_mono") or _mono())
    elapsed_ms = int(max(0.0, (_mono() - started_mono) * 1000))
    prev_elapsed = int(trace.get("elapsed_ms") or 0)
    step_ms = int(fields.get("step_ms") or max(0, elapsed_ms - prev_elapsed))
    entry = {
        "step": step,
        "ok": bool(ok),
        "elapsed_ms": elapsed_ms,
        "step_ms": step_ms,
        "error": str(error or ""),
        "draft_id": str(fields.get("draft_id") or trace.get("draft_id") or ""),
        "room_id": str(fields.get("room_id") or trace.get("room_id") or ""),
        "room_code": str(fields.get("room_code") or trace.get("room_code") or ""),
        "lifecycle": str(fields.get("lifecycle") or ""),
        "force_setup_after_delete": bool(session.get("_live_draft_force_setup_after_delete")),
        "deleting": str(session.get("_live_draft_deleting") or ""),
        "start_in_flight": bool(session.get("_live_draft_start_in_flight")),
        "page_generation": int(session.get("_live_draft_page_epoch") or 0),
        "at": _now(),
    }
    for key, val in fields.items():
        if key not in entry and val is not None:
            entry[key] = val
    steps = list(trace.get("steps") or [])
    steps.append(entry)
    trace["steps"] = steps[-40:]
    trace["current_step"] = step
    trace["elapsed_ms"] = elapsed_ms
    if entry["draft_id"]:
        trace["draft_id"] = entry["draft_id"]
    if entry["room_id"]:
        trace["room_id"] = entry["room_id"]
    if entry["room_code"]:
        trace["room_code"] = entry["room_code"]
    if fields.get("pool_live_count") is not None:
        trace["pool_live_count"] = fields.get("pool_live_count")
    if not ok:
        trace["failure_summary"] = str(error or step)
        trace["success"] = False
    soft = STEP_SOFT_TIMEOUT_SEC.get(step)
    # Soft timeout uses this step's duration — not total create time.
    if soft is not None and step_ms >= int(soft * 1000):
        trace["soft_timeout_step"] = step
        trace["soft_timeout_ms"] = step_ms
        trace["soft_timeout_total_ms"] = elapsed_ms
    session[CREATION_TRACE_KEY] = trace

    receipt = dict(session.get(CREATION_RECEIPT_KEY) or {})
    receipt["attempt_id"] = trace.get("attempt_id")
    receipt["selected_mode"] = trace.get("mode")
    receipt["started_time"] = trace.get("started_at")
    receipt["completed_step"] = step
    receipt["current_step"] = step
    receipt["draft_id"] = trace.get("draft_id") or ""
    receipt["room_id"] = trace.get("room_id") or ""
    receipt["room_code"] = trace.get("room_code") or ""
    receipt["creation_success"] = trace.get("success")
    receipt["lifecycle_after_creation"] = str(fields.get("lifecycle") or receipt.get("lifecycle_after_creation") or "")
    receipt["failure_summary"] = str(trace.get("failure_summary") or "")
    receipt["elapsed_ms"] = elapsed_ms
    receipt["last_step_ms"] = step_ms
    receipt["force_setup_after_delete"] = entry["force_setup_after_delete"]
    receipt["deleting"] = entry["deleting"]
    receipt["start_in_flight"] = entry["start_in_flight"]
    receipt["page_generation"] = entry["page_generation"]
    if fields.get("pool_live_count") is not None:
        receipt["pool_live_count"] = fields.get("pool_live_count")
    # Accumulate named step timings on the receipt.
    for key, val in fields.items():
        if str(key).endswith("_ms") and val is not None:
            receipt[str(key)] = val
    session[CREATION_RECEIPT_KEY] = receipt

    try:
        from live_draft_start_progress import mark_start_step

        mark_start_step(session, step, **{k: v for k, v in fields.items() if v is not None})
    except Exception:
        pass
    return entry


def protect_new_room(session: dict[str, Any], *, seconds: float = 120.0) -> None:
    """Prevent delete/lifecycle/membership repair from wiping a brand-new room."""
    session[PROTECT_ROOM_UNTIL_KEY] = _now() + float(seconds)
    receipt = dict(session.get(CREATION_RECEIPT_KEY) or {})
    receipt["protect_room"] = True
    receipt["protect_until"] = session[PROTECT_ROOM_UNTIL_KEY]
    session[CREATION_RECEIPT_KEY] = receipt


def new_room_is_protected(session: dict[str, Any]) -> bool:
    until = session.get(PROTECT_ROOM_UNTIL_KEY)
    if isinstance(until, (int, float)) and float(until) > _now():
        return True
    receipt = session.get(CREATION_RECEIPT_KEY) or {}
    if isinstance(receipt, dict) and receipt.get("protect_room"):
        until2 = receipt.get("protect_until")
        if isinstance(until2, (int, float)) and float(until2) > _now():
            return True
    return False


def finalize_creation_receipt(
    session: dict[str, Any],
    *,
    success: bool,
    lifecycle: str = "",
    error: str = "",
) -> dict[str, Any]:
    note_creation_step(
        session,
        "first_render_ready" if success else "start_failed",
        ok=success,
        error=error,
        lifecycle=lifecycle,
    )
    trace = dict(session.get(CREATION_TRACE_KEY) or {})
    trace["success"] = bool(success)
    trace["lifecycle_after"] = str(lifecycle or "")
    if error:
        trace["failure_summary"] = str(error)
    # Never keep a soft-timeout banner after Draft ready / failure terminal.
    trace.pop("soft_timeout_step", None)
    trace.pop("soft_timeout_ms", None)
    session[CREATION_TRACE_KEY] = trace
    receipt = dict(session.get(CREATION_RECEIPT_KEY) or {})
    receipt["creation_success"] = bool(success)
    receipt["lifecycle_after_creation"] = str(lifecycle or "")
    receipt["failure_summary"] = str(error or "")
    receipt["completed_step"] = str(trace.get("current_step") or "")
    receipt["start_in_flight"] = bool(session.get("_live_draft_start_in_flight"))
    receipt["force_setup_after_delete"] = bool(session.get("_live_draft_force_setup_after_delete"))
    receipt["deleting"] = str(session.get("_live_draft_deleting") or "")
    session[CREATION_RECEIPT_KEY] = receipt
    if success:
        protect_new_room(session)
        arm_post_create_open(session, lifecycle=lifecycle)
    return receipt


def arm_post_create_open(session: dict[str, Any], *, lifecycle: str = "") -> None:
    """After Draft ready: next full run must enter active/lobby within ~5s."""
    session[POST_CREATE_OPEN_KEY] = True
    session[POST_CREATE_DEADLINE_KEY] = _now() + float(POST_CREATE_WATCHDOG_SEC)
    receipt = dict(session.get(CREATION_RECEIPT_KEY) or {})
    receipt["post_create_armed"] = True
    receipt["post_create_deadline"] = session[POST_CREATE_DEADLINE_KEY]
    receipt["lifecycle_at_arm"] = str(lifecycle or "")
    session[CREATION_RECEIPT_KEY] = receipt
    # Stale queue-fast-paint must not st.stop() the first active render.
    try:
        from live_draft_rerun_scope import QUEUE_FAST_PAINT_KEY, QUEUE_TICK_KEY

        session.pop(QUEUE_FAST_PAINT_KEY, None)
        session.pop(QUEUE_TICK_KEY, None)
    except ImportError:
        session.pop("_live_draft_queue_fast_paint", None)
        session.pop("_live_draft_queue_only_tick", None)
    session.pop("_live_draft_skip_queue_flush_this_run", None)


def mark_active_draft_page_entered(session: dict[str, Any], *, lifecycle: str = "") -> None:
    """Call when the active-draft / lobby renderer is entered after create."""
    # Always clear leftover queue fast-paint — never abort active page for it.
    try:
        from live_draft_rerun_scope import clear_live_draft_queue_fast_paint

        clear_live_draft_queue_fast_paint(session, reason="active_page_entered")
    except ImportError:
        session.pop("_live_draft_queue_fast_paint", None)
    if not session.pop(POST_CREATE_OPEN_KEY, None) and not session.get(POST_CREATE_DEADLINE_KEY):
        return
    session.pop(POST_CREATE_DEADLINE_KEY, None)
    session.pop(POST_CREATE_FAIL_KEY, None)
    note_creation_step(
        session,
        "active_page_entered",
        ok=True,
        lifecycle=lifecycle,
    )
    receipt = dict(session.get(CREATION_RECEIPT_KEY) or {})
    receipt["active_page_entered"] = True
    receipt["lifecycle_on_active_enter"] = str(lifecycle or "")
    session[CREATION_RECEIPT_KEY] = receipt


def evaluate_post_create_watchdog(session: dict[str, Any]) -> dict[str, Any] | None:
    """If Draft ready but active page never opened within ~5s, return failure payload."""
    receipt = session.get(CREATION_RECEIPT_KEY)
    if not isinstance(receipt, dict) or receipt.get("creation_success") is not True:
        return None
    if receipt.get("active_page_entered"):
        return None
    if session.get(POST_CREATE_FAIL_KEY):
        return dict(session[POST_CREATE_FAIL_KEY])
    deadline = session.get(POST_CREATE_DEADLINE_KEY)
    if not isinstance(deadline, (int, float)):
        return None
    if _now() < float(deadline):
        return None

    try:
        from live_draft_completion import resolve_live_draft_lifecycle

        life = resolve_live_draft_lifecycle(session)
    except ImportError:
        life = "unknown"
    room = session.get("live_draft_room")
    has_room = isinstance(room, dict)
    draft_id = str(
        (room or {}).get("draft_room_id")
        or receipt.get("draft_id")
        or ""
    ).strip()
    failed_step = "active_draft_render"
    if not has_room:
        failed_step = "draft_id_missing_from_session"
    elif life in ("setup",):
        failed_step = "lifecycle_reverted_to_setup"
    elif bool(session.get("_live_draft_force_setup_after_delete")):
        failed_step = "force_setup_after_delete"
    elif str(session.get("_live_draft_deleting") or ""):
        failed_step = "deleting_flag"
    elif bool(session.get("_live_draft_start_in_flight")):
        failed_step = "start_in_flight_stuck"

    detail = (
        f"Draft ready but active page did not open within {int(POST_CREATE_WATCHDOG_SEC)}s "
        f"(failed_step={failed_step}, lifecycle={life}, has_room={has_room}, draft_id={draft_id or '—'})."
    )
    payload = {
        "failed_step": failed_step,
        "lifecycle": life,
        "draft_id": draft_id,
        "attempt_id": receipt.get("attempt_id"),
        "detail": detail,
        "start_in_flight": bool(session.get("_live_draft_start_in_flight")),
        "force_setup_after_delete": bool(session.get("_live_draft_force_setup_after_delete")),
        "deleting": str(session.get("_live_draft_deleting") or ""),
        "page_generation": int(session.get("_live_draft_page_epoch") or 0),
        "at": _now(),
    }
    session[POST_CREATE_FAIL_KEY] = payload
    session.pop(POST_CREATE_OPEN_KEY, None)
    session.pop(POST_CREATE_DEADLINE_KEY, None)
    # Clear stuck creating banner — draft object is preserved for Open Draft.
    session.pop("_live_draft_start_in_flight", None)
    session.pop("_live_draft_start_mono_t0", None)
    session.pop("_start_live_draft_pending", None)
    note_creation_step(
        session,
        "post_create_transition_failed",
        ok=False,
        error=detail,
        lifecycle=life,
        failed_step=failed_step,
        draft_id=draft_id,
    )
    receipt = dict(session.get(CREATION_RECEIPT_KEY) or {})
    receipt["post_create_failed_step"] = failed_step
    receipt["failure_summary"] = detail
    session[CREATION_RECEIPT_KEY] = receipt
    return payload


def open_preserved_created_draft(session: dict[str, Any]) -> dict[str, Any]:
    """Safe Retry/Open: reopen the already-created room — never create a duplicate."""
    room = session.get("live_draft_room")
    receipt = dict(session.get(CREATION_RECEIPT_KEY) or {})
    result = {
        "ok": False,
        "draft_id": str(receipt.get("draft_id") or ""),
        "reason": "",
    }
    if not isinstance(room, dict):
        result["reason"] = "No preserved draft in session — return to setup and create again."
        return result
    # Clear gates that bounce a valid room back to setup.
    session.pop("_live_draft_force_setup_after_delete", None)
    session.pop("_live_draft_deleting", None)
    session.pop("_live_draft_start_in_flight", None)
    session.pop("_start_live_draft_pending", None)
    session.pop(POST_CREATE_FAIL_KEY, None)
    protect_new_room(session)
    status = str(room.get("status") or "").strip().lower()
    if status in ("", "not_started", "waiting"):
        room["status"] = "in_progress"
        try:
            from live_draft_timer_logic import live_draft_reset_timer

            live_draft_reset_timer(room)
        except ImportError:
            pass
    session["live_draft_room"] = room
    arm_post_create_open(session, lifecycle="active_draft")
    note_creation_step(
        session,
        "rerun_requested",
        ok=True,
        lifecycle="active_draft",
        draft_id=str(room.get("draft_room_id") or ""),
        open_preserved=True,
    )
    result["ok"] = True
    result["draft_id"] = str(room.get("draft_room_id") or "")
    result["reason"] = "opening_preserved_draft"
    return result


def user_facing_creation_status(session: dict[str, Any]) -> str:
    receipt = session.get(CREATION_RECEIPT_KEY) or {}
    trace = session.get(CREATION_TRACE_KEY) or {}
    step = str(trace.get("current_step") or "")
    hard = session.get("_live_draft_creation_hard_warn") or session.get("_live_draft_creation_hard_abort")
    if isinstance(hard, dict) and hard.get("detail"):
        return str(hard["detail"])
    # Never keep "Still working on Draft ready" after successful create.
    if isinstance(receipt, dict) and receipt.get("creation_success") is True:
        if receipt.get("active_page_entered"):
            return ""
        if session.get(POST_CREATE_FAIL_KEY):
            return ""
        return "Opening draft…"
    if step in ("first_render_ready", "rerun_requested", "active_page_entered"):
        return "Opening draft…"
    if step == "post_create_transition_failed" or step == "start_failed":
        return ""
    soft_step = str(trace.get("soft_timeout_step") or "")
    if soft_step and soft_step not in (
        "first_render_ready",
        "rerun_requested",
        "active_page_entered",
    ):
        soft_ms = int(trace.get("soft_timeout_ms") or trace.get("elapsed_ms") or 0)
        total_ms = int(trace.get("elapsed_ms") or 0)
        label = USER_STEP_STATUS.get(soft_step, soft_step)
        return (
            f"Still working on **{label}** "
            f"(step {soft_ms} ms · total {total_ms} ms). Check Developer Mode creation receipt."
        )
    if not step:
        try:
            from live_draft_start_progress import START_PROGRESS_KEY

            step = str((session.get(START_PROGRESS_KEY) or {}).get("current_step") or "")
        except Exception:
            step = ""
    return USER_STEP_STATUS.get(step, "Preparing Draft…")


def render_creation_receipt_panel(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    if not developer_mode:
        return
    receipt = session.get(CREATION_RECEIPT_KEY)
    trace = session.get(CREATION_TRACE_KEY)
    if not isinstance(receipt, dict) and not isinstance(trace, dict):
        return
    with st.expander("Live Draft creation receipt (Dev)", expanded=True):
        data = dict(receipt or {})
        if isinstance(trace, dict):
            data["current_step"] = trace.get("current_step")
            data["elapsed_ms"] = trace.get("elapsed_ms")
            data["soft_timeout_step"] = trace.get("soft_timeout_step")
            data["steps"] = trace.get("steps")
        fail = session.get(POST_CREATE_FAIL_KEY)
        if isinstance(fail, dict):
            data["post_create_transition_fail"] = fail
        st.json(data)
