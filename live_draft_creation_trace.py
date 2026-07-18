"""Deployed Live Draft creation trace + receipt (Developer Mode + user-facing steps)."""

from __future__ import annotations

import time
import uuid
from typing import Any

CREATION_RECEIPT_KEY = "_live_draft_creation_receipt"
CREATION_TRACE_KEY = "_live_draft_creation_trace"
PROTECT_ROOM_UNTIL_KEY = "_live_draft_protect_new_room_until"

# Soft thresholds — surface diagnostics before the hard 90s start TTL.
STEP_SOFT_TIMEOUT_SEC: dict[str, float] = {
    "pool_build_start": 20.0,
    "pool_build_end": 25.0,
    "room_initialized": 8.0,
    "shared_room_create_start": 15.0,
    "commissioner_registered": 10.0,
    "session_installed": 5.0,
    "lifecycle_resolved": 5.0,
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
    "start_failed": "Draft creation failed",
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
    entry = {
        "step": step,
        "ok": bool(ok),
        "elapsed_ms": elapsed_ms,
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
    if not ok:
        trace["failure_summary"] = str(error or step)
        trace["success"] = False
    soft = STEP_SOFT_TIMEOUT_SEC.get(step)
    if soft is not None and elapsed_ms >= int(soft * 1000):
        trace["soft_timeout_step"] = step
        trace["soft_timeout_ms"] = elapsed_ms
    session[CREATION_TRACE_KEY] = trace

    receipt = dict(session.get(CREATION_RECEIPT_KEY) or {})
    receipt["attempt_id"] = trace.get("attempt_id")
    receipt["selected_mode"] = trace.get("mode")
    receipt["started_time"] = trace.get("started_at")
    receipt["completed_step"] = step
    receipt["draft_id"] = trace.get("draft_id") or ""
    receipt["room_id"] = trace.get("room_id") or ""
    receipt["room_code"] = trace.get("room_code") or ""
    receipt["creation_success"] = trace.get("success")
    receipt["lifecycle_after_creation"] = str(fields.get("lifecycle") or receipt.get("lifecycle_after_creation") or "")
    receipt["failure_summary"] = str(trace.get("failure_summary") or "")
    receipt["elapsed_ms"] = elapsed_ms
    receipt["force_setup_after_delete"] = entry["force_setup_after_delete"]
    receipt["deleting"] = entry["deleting"]
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
    session[CREATION_TRACE_KEY] = trace
    receipt = dict(session.get(CREATION_RECEIPT_KEY) or {})
    receipt["creation_success"] = bool(success)
    receipt["lifecycle_after_creation"] = str(lifecycle or "")
    receipt["failure_summary"] = str(error or "")
    receipt["completed_step"] = str(trace.get("current_step") or "")
    session[CREATION_RECEIPT_KEY] = receipt
    if success:
        protect_new_room(session)
    return receipt


def user_facing_creation_status(session: dict[str, Any]) -> str:
    trace = session.get(CREATION_TRACE_KEY) or {}
    step = str(trace.get("current_step") or "")
    if trace.get("soft_timeout_step"):
        return (
            f"Still working on **{USER_STEP_STATUS.get(step, step)}** "
            f"({int(trace.get('elapsed_ms') or 0)} ms). Check Developer Mode creation receipt."
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
        st.json(data)
