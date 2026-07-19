"""Minimal Solo Live Draft creation — open active page before heavy persist/analytics.

Production create must not wait on recommendations, library save, full workspace sync,
or Shared membership. Persistence is deferred until after the active page opens.
"""

from __future__ import annotations

import time
from typing import Any, Callable

CREATION_HARD_WARN_SEC = 10.0
CREATION_HARD_ABORT_SEC = 20.0
DEFERRED_CREATE_PERSIST_KEY = "_live_draft_deferred_create_persist"


def note_timed_step(
    session: dict[str, Any],
    step: str,
    *,
    ok: bool = True,
    error: str = "",
    t_step0: float | None = None,
    **fields: Any,
) -> float:
    """Note a creation step and record ``{step}_ms`` on the receipt. Returns now."""
    now = time.perf_counter()
    step_ms = None
    if t_step0 is not None:
        step_ms = round((now - float(t_step0)) * 1000.0, 1)
    try:
        from live_draft_creation_trace import note_creation_step

        kwargs = dict(fields)
        if step_ms is not None:
            kwargs[f"{step}_ms"] = step_ms
            kwargs["step_ms"] = step_ms
        note_creation_step(session, step, ok=ok, error=error, **kwargs)
        if step_ms is not None:
            receipt = dict(session.get("_live_draft_creation_receipt") or {})
            receipt[f"{step}_ms"] = step_ms
            # Friendly aliases for the required report fields.
            alias = {
                "settings_captured": "setup_validated_ms",
                "pool_build_end": "player_pool_loaded_ms",
                "room_initialized": "pick_order_created_ms",
                "session_installed": "draft_state_installed_ms",
                "persist_complete": "persistence_completed_ms",
                "active_page_entered": "active_page_opened_ms",
            }.get(step)
            if alias:
                receipt[alias] = step_ms
            session["_live_draft_creation_receipt"] = receipt
    except Exception:
        pass
    return now


def mark_deferred_create_persist(session: dict[str, Any]) -> None:
    session[DEFERRED_CREATE_PERSIST_KEY] = True


def needs_deferred_create_persist(session: dict[str, Any]) -> bool:
    return bool(session.get(DEFERRED_CREATE_PERSIST_KEY))


def clear_deferred_create_persist(session: dict[str, Any]) -> None:
    session.pop(DEFERRED_CREATE_PERSIST_KEY, None)


def flush_deferred_create_persist(
    st: Any,
    session: dict[str, Any],
    *,
    persist_room_fn: Callable[..., None] | None = None,
) -> bool:
    """Run durable save after the active Solo page is already visible."""
    if not session.pop(DEFERRED_CREATE_PERSIST_KEY, None):
        return False
    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        return False
    t0 = time.perf_counter()
    try:
        from user_page_preferences import persist_live_draft_setup_preferences

        persist_live_draft_setup_preferences(session, st=st, force_disk=False)
    except Exception:
        pass
    if persist_room_fn is not None:
        try:
            persist_room_fn(room, reason="start_draft_deferred", rerun=False)
        except TypeError:
            try:
                persist_room_fn(room, reason="start_draft_deferred")
            except Exception:
                pass
        except Exception:
            pass
    else:
        try:
            from live_draft_state import write_canonical_live_draft_state

            write_canonical_live_draft_state(session, room, reason="start_draft_deferred", local_edit=True)
        except Exception:
            pass
    note_timed_step(session, "persist_complete", ok=True, t_step0=t0)
    return True


def evaluate_creation_hard_watchdog(session: dict[str, Any]) -> dict[str, Any] | None:
    """10s warn / 20s abort while create is in flight (before Draft ready)."""
    try:
        from live_draft_start_progress import START_IN_FLIGHT_KEY, MONO_START_KEY, is_live_draft_start_in_flight
    except ImportError:
        return None
    if not is_live_draft_start_in_flight(session):
        return None
    receipt = session.get("_live_draft_creation_receipt") or {}
    if isinstance(receipt, dict) and receipt.get("creation_success") is True:
        return None
    t0 = session.get(MONO_START_KEY)
    if not isinstance(t0, (int, float)) or t0 <= 0:
        return None
    elapsed = time.monotonic() - float(t0)
    trace = session.get("_live_draft_creation_trace") or {}
    step = str(trace.get("current_step") or (receipt or {}).get("completed_step") or "unknown")
    if elapsed < CREATION_HARD_WARN_SEC:
        return None
    payload = {
        "elapsed_sec": round(elapsed, 1),
        "active_step": step,
        "attempt_id": (receipt or {}).get("attempt_id"),
        "draft_id": (receipt or {}).get("draft_id") or "",
        "pool_live_count": (receipt or {}).get("pool_live_count"),
        "level": "warn" if elapsed < CREATION_HARD_ABORT_SEC else "abort",
        "detail": (
            f"Creation still on **{step}** after {int(elapsed)}s."
            if elapsed < CREATION_HARD_ABORT_SEC
            else (
                f"Creation aborted after {int(elapsed)}s at step **{step}**. "
                "Any draft already created is preserved."
            )
        ),
    }
    if elapsed < CREATION_HARD_ABORT_SEC:
        session["_live_draft_creation_hard_warn"] = payload
        return payload

    # Hard abort — clear in-flight; keep room if present.
    room = session.get("live_draft_room")
    has_room = isinstance(room, dict)
    session.pop(START_IN_FLIGHT_KEY, None)
    session.pop(MONO_START_KEY, None)
    session.pop("_start_live_draft_pending", None)
    session["_live_draft_creation_hard_abort"] = payload
    try:
        from live_draft_creation_trace import note_creation_step

        note_creation_step(
            session,
            "start_failed",
            ok=False,
            error=payload["detail"],
            failed_step=step,
            draft_id=str((room or {}).get("draft_room_id") or ""),
            preserved_room=has_room,
        )
        if has_room:
            from live_draft_creation_trace import protect_new_room

            protect_new_room(session)
    except Exception:
        pass
    return payload
