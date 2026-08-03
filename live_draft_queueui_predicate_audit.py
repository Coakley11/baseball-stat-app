"""QUEUEUI root-cause predicate audit — diagnostic ledger only (no behavior changes)."""

from __future__ import annotations

from typing import Any

EVENT_QUEUEUI_PREDICATE = "production_stage1_queueui_predicate_audit"


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def auth_evidence(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "auth_enabled": None,
        "authenticated": None,
        "user_id_present": False,
        "email_present": False,
    }
    try:
        from suite_auth import is_auth_enabled, is_authenticated

        out["auth_enabled"] = bool(is_auth_enabled())
        out["authenticated"] = bool(is_authenticated(session)) if out["auth_enabled"] else True
    except ImportError:
        out["auth_enabled"] = None
        out["authenticated"] = None
    for key in ("_suite_user_email", "user_email", "suite_user_email"):
        if str(session.get(key) or "").strip():
            out["email_present"] = True
            break
    for key in ("_suite_user_id", "suite_user_id", "auth_user_id"):
        if str(session.get(key) or "").strip():
            out["user_id_present"] = True
            break
    try:
        from suite_user import current_suite_user_display

        disp = current_suite_user_display(session)
        if disp:
            out["suite_user_display"] = str(disp)[:80]
    except Exception:
        pass
    return out


def restore_evidence(session: dict[str, Any]) -> dict[str, Any]:
    blob = session.get("live_draft_state")
    blocked = str(session.get("_live_draft_restore_blocked_reason") or "")
    allowed = None
    restore_reason = ""
    try:
        from live_draft_state import live_draft_restore_allowed

        allowed, restore_reason = live_draft_restore_allowed(session, blob if isinstance(blob, dict) else None)
    except ImportError:
        pass
    return {
        "restore_blocked_reason": blocked,
        "restore_allowed": allowed,
        "restore_gate_reason": restore_reason,
    }


def room_access_evidence(session: dict[str, Any], room: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {"membership_gate_would_run": False, "solo_room": False}
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if isinstance(room, dict):
            out["solo_room"] = bool(is_solo_live_draft(session, room))
    except ImportError:
        pass
    try:
        from draft_room_context import is_multiplayer_draft_active

        out["membership_gate_would_run"] = bool(
            is_multiplayer_draft_active(session) or session.get("active_shared_draft_room_code")
        )
    except ImportError:
        pass
    return out


def compute_render_predicates(
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None,
    lifecycle: str = "",
    slot: dict[str, Any] | None = None,
    draft_in_progress: bool | None = None,
    timer_ok: bool | None = None,
    reconcile_timer_should_run: bool | None = None,
) -> dict[str, Any]:
    """Mirror streamlit_app Live Draft Room branch terms (observability)."""
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        live = {}
    status = str(live.get("status") or "")
    if draft_in_progress is None:
        try:
            from live_draft_safe_mode import live_draft_is_in_progress

            draft_in_progress = bool(live_draft_is_in_progress(live))
        except ImportError:
            draft_in_progress = status == "in_progress"
    slot_ok = slot is not None
    if timer_ok is None:
        timer_ok = bool(
            draft_in_progress
            and slot_ok
            and (reconcile_timer_should_run is not False)
        )
    try:
        from live_draft_start_progress import is_live_draft_start_in_flight

        start_in_flight = bool(is_live_draft_start_in_flight(session))
    except ImportError:
        start_in_flight = bool(session.get("_live_draft_start_in_flight"))
    try:
        from live_draft_fast_solo_start import should_defer_heavy_first_paint

        defer_heavy = bool(should_defer_heavy_first_paint(session))
    except ImportError:
        defer_heavy = bool(session.get("_live_draft_defer_heavy_first_paint"))
    heavy_loading = bool(session.get("_live_draft_defer_heavy_loading"))
    heavy_done = bool(session.get("_live_draft_heavy_paint_done"))
    lifecycle_norm = str(lifecycle or "")
    active_branch = lifecycle_norm in ("active_draft", "waiting_shared_lobby") and isinstance(
        live if room is None else room, dict
    ) and bool((live or {}).get("draft_room_id") or (live or {}).get("draft_id"))
    partial_header = bool(active_branch and draft_in_progress)
    full_body = bool(active_branch and draft_in_progress and slot_ok)
    pause_control = bool(full_body and status == "in_progress")
    try:
        from live_draft_start_progress import is_live_draft_start_in_flight as _sif

        skip_recs = bool(_sif(session))
    except ImportError:
        skip_recs = start_in_flight
    if draft_in_progress and status in ("in_progress", "paused"):
        skip_recs = False
    recommendation = bool(full_body and not skip_recs and not defer_heavy and not heavy_loading)
    queue_control = recommendation
    countdown = bool(
        full_body
        and draft_in_progress
        and status == "in_progress"
    )
    return {
        "lifecycle": lifecycle_norm,
        "active_page": str(session.get("active_page") or ""),
        "live_draft_room_present": isinstance(session.get("live_draft_room"), dict),
        "room_id": str(live.get("draft_room_id") or live.get("draft_id") or "").upper(),
        "room_status": status,
        "pick_index": live.get("current_pick_index"),
        "start_in_flight": start_in_flight,
        "defer_heavy_first_paint": defer_heavy,
        "defer_heavy_loading": heavy_loading,
        "heavy_paint_done": heavy_done,
        "partial_header_predicate": partial_header,
        "full_body_predicate": full_body,
        "pause_control_predicate": pause_control,
        "recommendation_predicate": recommendation,
        "queue_control_predicate": queue_control,
        "countdown_declaration_predicate": countdown,
        "slot_present": slot_ok,
        "draft_in_progress": bool(draft_in_progress),
        "timer_ok": bool(timer_ok),
    }


def emit_queueui_predicate_audit(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    checkpoint: str,
    room: dict[str, Any] | None = None,
    lifecycle: str = "",
    early_return_reason: str = "",
    slot: dict[str, Any] | None = None,
    draft_in_progress: bool | None = None,
    timer_ok: bool | None = None,
    reconcile_timer_should_run: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not checkpoint:
        return {}
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

        if not stage1_production_ledger_enabled(st, session):
            return {}
    except ImportError:
        return {}

    preds = compute_render_predicates(
        session,
        room=room,
        lifecycle=lifecycle,
        slot=slot,
        draft_in_progress=draft_in_progress,
        timer_ok=timer_ok,
        reconcile_timer_should_run=reconcile_timer_should_run,
    )
    row_extra: dict[str, Any] = {
        "checkpoint": str(checkpoint)[:120],
        "streamlit_session_id": _streamlit_session_id(),
        "script_run_seq": int(session.get("_solo_stage1_script_run_seq") or 0),
        "early_return_reason": str(early_return_reason or "")[:200],
        "predicates": preds,
        "auth": auth_evidence(session),
        "restore": restore_evidence(session),
        "room_access": room_access_evidence(session, room),
    }
    if extra:
        row_extra.update(extra)
    try:
        from live_draft_stage1_production_ledger import note_stage1_event

        return note_stage1_event(
            session,
            EVENT_QUEUEUI_PREDICATE,
            st=st,
            room=room,
            widget_key=str(checkpoint)[:64],
            extra=row_extra,
        )
    except ImportError:
        return {}
