"""Live draft lifecycle reconcile, safe mode, and rerun gating."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from live_draft_state import LIVE_DRAFT_ROOM_KEY, repair_stale_live_draft_progress

SAFE_MODE_DIAG_KEY = "_live_draft_safe_mode_diag"
RERUN_DIAG_KEY = "_live_draft_rerun_diag"
SAFE_MODE_ACTIVE_KEY = "_live_draft_safe_mode_active"
SAFE_MODE_ERROR_KEY = "_live_draft_draft_state_error"
SAFE_MODE_ERROR_REASON_KEY = "_live_draft_draft_state_error_reason"

# Rerun sources that must never fire when rerun_allowed is false (timer/autopick loops)
_BLOCKED_RERUN_SOURCES = frozenset(
    {
        "timer_fragment",
        "timer_fragment_zero",
        "page_autopick",
        "poll_shared_draft",
        "shared_draft_room_panel",
        "expired_pick_pending",
        "live_draft_queue",
        "poll_fragment",
    }
)

# Remote revision apply must always repaint — not subject to passive-receiver rerun budget
_POLL_APPLY_RERUN_SOURCES = frozenset({"poll_apply", "poll_remote_revision"})


@dataclass
class ReconcileResult:
    room: dict[str, Any]
    board_size: int
    total_expected_picks: int
    draft_status_before: str
    draft_status_after: str
    stale_draft_status_detected: bool
    stale_current_pick_index_detected: bool
    false_complete_detected: bool = False
    saved_draft_status: str = ""
    computed_draft_status: str = ""
    draft_status_source: str = ""
    completion_source: str = ""
    current_pick_index_before_reconcile: int = 0
    current_pick_index_after_reconcile: int = 0
    contradictions: list[str] = field(default_factory=list)
    safe_mode_active: bool = False
    draft_state_error: bool = False
    draft_state_error_reason: str = ""
    manual_recovery_available: bool = False
    timer_should_run: bool = False


def _board_size(room: dict[str, Any]) -> int:
    board = room.get("draft_board") or []
    return len(board) if isinstance(board, list) else 0


def total_expected_picks(room: dict[str, Any]) -> int:
    pick_order = room.get("pick_order") or []
    if pick_order:
        return len(pick_order)
    teams = room.get("teams") or []
    cfg = dict(room.get("config") or {})
    rounds = int(cfg.get("picks_per_team") or cfg.get("rounds") or 0)
    if teams and rounds:
        return len(teams) * rounds
    return 0


def compute_draft_status(room: dict[str, Any]) -> tuple[str, str]:
    """Derive draft status from board length — never trust saved complete alone."""
    saved = str(room.get("status") or "").strip()
    board = _board_size(room)
    total = total_expected_picks(room)
    if total <= 0:
        return saved, "saved_status_no_pick_order"
    if saved == "paused" and board < total:
        return "paused", "explicitly_paused"
    if board >= total:
        return "complete", "board_full"
    if board > 0:
        return "in_progress", "board_incomplete"
    if saved in ("", "not_started"):
        return "not_started", "board_empty"
    return "in_progress", "board_empty_reopened"


def is_draft_truly_complete(room: dict[str, Any]) -> bool:
    """Derived completion only: board picks >= expected total."""
    total = total_expected_picks(room)
    if total <= 0:
        return False
    return _board_size(room) >= total


def live_draft_is_in_progress(room: dict[str, Any]) -> bool:
    """True while picks remain — ignores stale saved status flags."""
    total = total_expected_picks(room)
    if total <= 0:
        return False
    return _board_size(room) < total


def record_safe_mode_diagnostics(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    diag = dict(session.get(SAFE_MODE_DIAG_KEY) or {})
    diag.update(fields)
    session[SAFE_MODE_DIAG_KEY] = diag
    return diag


def record_rerun_diagnostics(
    session: dict[str, Any],
    *,
    rerun_source: str,
    rerun_allowed: bool,
    rerun_blocked_reason: str | None = None,
) -> None:
    session[RERUN_DIAG_KEY] = {
        "rerun_source": rerun_source,
        "rerun_allowed": rerun_allowed,
        "rerun_blocked_reason": rerun_blocked_reason or None,
        "safe_mode_active": bool(session.get(SAFE_MODE_ACTIVE_KEY)),
    }


def is_safe_mode_active(session: dict[str, Any]) -> bool:
    return bool(session.get(SAFE_MODE_ACTIVE_KEY))


def draft_state_error_reason(session: dict[str, Any]) -> str:
    return str(session.get(SAFE_MODE_ERROR_REASON_KEY) or session.get(SAFE_MODE_ERROR_KEY) or "").strip()


def _detect_contradictions(session: dict[str, Any], room: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    status = str(room.get("status") or "").strip()
    board = _board_size(room)
    total = total_expected_picks(room)
    idx = int(room.get("current_pick_index") or 0)

    if total > 0 and status == "complete" and board < total:
        reasons.append(f"draft_status=complete but board_size={board} < total_expected_picks={total}")
    if status == "complete" and room.get("timer_started_at") is not None:
        reasons.append("draft_status=complete but timer_started_at is set")
    if total > 0 and board < total and idx != board:
        reasons.append(f"current_pick_index={idx} != board_size={board} while draft incomplete")
    if total > 0 and idx > total:
        reasons.append(f"current_pick_index={idx} > total_expected_picks={total}")

    try:
        from live_draft_expired_pick import autopick_failure_backoff_active, RERUN_LOOP_PREVENTED_KEY

        if autopick_failure_backoff_active(session, room) and session.get("_live_draft_last_rerun_source") in (
            "timer_fragment",
            "page_autopick",
            "poll_shared_draft",
        ):
            reasons.append("autopick_failure_backoff_active but rerun source still firing")
        if session.get(RERUN_LOOP_PREVENTED_KEY) and session.get("_live_draft_rerun_count", 0) > 3:
            reasons.append("rerun_loop_prevented but excessive reruns detected")
    except ImportError:
        pass

    return reasons


def reconcile_live_draft_room(session: dict[str, Any], room: dict[str, Any]) -> ReconcileResult:
    """Reconcile board/index/status before timer, autopick, or manual pick."""
    if not isinstance(room, dict):
        return ReconcileResult(
            room=room,
            board_size=0,
            total_expected_picks=0,
            draft_status_before="",
            draft_status_after="",
            stale_draft_status_detected=False,
            stale_current_pick_index_detected=False,
        )

    status_before = str(room.get("status") or "").strip()
    idx_before = int(room.get("current_pick_index") or 0)
    board_before = _board_size(room)
    total = total_expected_picks(room)
    computed_before, completion_source = compute_draft_status(room)
    false_complete = bool(total > 0 and status_before == "complete" and board_before < total)

    stale_status = bool(total > 0 and status_before == "complete" and board_before < total)
    stale_idx = bool(idx_before != board_before and board_before < total)

    room = repair_stale_live_draft_progress(dict(room))
    board = _board_size(room)

    if total > 0 and board < total:
        status_now = str(room.get("status") or "").strip()
        if status_now == "paused":
            room["status"] = "paused"
        elif board > 0:
            room["status"] = "in_progress"
        else:
            room["status"] = (
                "not_started"
                if status_now in ("", "not_started")
                else ("paused" if status_now == "paused" else "in_progress")
            )
        idx_now = int(room.get("current_pick_index") or 0)
        if idx_now != board:
            room["current_pick_index"] = board
            stale_idx = True
        if int(room.get("current_pick_index") or 0) > total:
            room["current_pick_index"] = min(board, total)
        room["timer_handled_index"] = -1
    elif total > 0 and board >= total:
        room["status"] = "complete"
        room["current_pick_index"] = total
        room["timer_started_at"] = None
        room["timer_deadline"] = None

    status_after, completion_source_after = compute_draft_status(room)
    if total > 0:
        if status_before == "paused" and board < total:
            room["status"] = "paused"
            status_after = "paused"
        else:
            room["status"] = status_after

    status_after = str(room.get("status") or "").strip()
    idx_after = int(room.get("current_pick_index") or 0)
    session[LIVE_DRAFT_ROOM_KEY] = room

    contradictions = _detect_contradictions(session, room)
    safe_mode = bool(contradictions)
    error_reason = "; ".join(contradictions) if contradictions else ""

    session[SAFE_MODE_ACTIVE_KEY] = safe_mode
    session[SAFE_MODE_ERROR_KEY] = safe_mode
    session[SAFE_MODE_ERROR_REASON_KEY] = error_reason

    timer_should = bool(
        status_after == "in_progress"
        and status_after != "paused"
        and not safe_mode
        and total > 0
        and board < total
        and idx_after < total
    )
    try:
        from live_draft_expired_pick import autopick_failure_backoff_active

        if autopick_failure_backoff_active(session, room):
            timer_should = False
    except ImportError:
        pass

    manual_recovery = bool(total > 0 and board < total)

    record_safe_mode_diagnostics(
        session,
        draft_state_error=safe_mode,
        draft_state_error_reason=error_reason or None,
        safe_mode_active=safe_mode,
        manual_recovery_available=manual_recovery,
        timer_fragment_active=False,
        timer_should_run=timer_should,
        stale_draft_status_detected=stale_status,
        stale_current_pick_index_detected=stale_idx,
        false_complete_detected=false_complete,
        saved_draft_status=status_before,
        computed_draft_status=status_after,
        draft_status_source="derived_from_board",
        completion_source=completion_source_after,
        board_size=board,
        total_expected_picks=total,
        current_pick_index=idx_after,
        current_pick_index_before_reconcile=idx_before,
        current_pick_index_after_reconcile=idx_after,
        draft_status_before=status_before,
        draft_status_after=status_after,
    )

    return ReconcileResult(
        room=room,
        board_size=board,
        total_expected_picks=total,
        draft_status_before=status_before,
        draft_status_after=status_after,
        stale_draft_status_detected=stale_status,
        stale_current_pick_index_detected=stale_idx,
        false_complete_detected=false_complete,
        saved_draft_status=status_before,
        computed_draft_status=status_after,
        draft_status_source="derived_from_board",
        completion_source=completion_source_after,
        current_pick_index_before_reconcile=idx_before,
        current_pick_index_after_reconcile=idx_after,
        contradictions=contradictions,
        safe_mode_active=safe_mode,
        draft_state_error=safe_mode,
        draft_state_error_reason=error_reason,
        manual_recovery_available=manual_recovery,
        timer_should_run=timer_should,
    )


def prepare_manual_pick_recovery(session: dict[str, Any]) -> ReconcileResult | None:
    """Bypass autopick/timer blockers and reconcile state for a manual pick attempt."""
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    if not isinstance(room, dict):
        return None

    try:
        from live_draft_expired_pick import clear_autopick_state_for_pick_advance

        clear_autopick_state_for_pick_advance(session)
    except ImportError:
        pass

    session.pop(SAFE_MODE_ACTIVE_KEY, None)
    session.pop(SAFE_MODE_ERROR_KEY, None)
    session.pop(SAFE_MODE_ERROR_REASON_KEY, None)

    result = reconcile_live_draft_room(session, room)
    room = result.room
    total = result.total_expected_picks
    if total > 0 and result.board_size < total:
        room["status"] = "in_progress"
        if int(room.get("current_pick_index") or 0) < result.board_size:
            room["current_pick_index"] = result.board_size
        room["timer_handled_index"] = -1
        session[LIVE_DRAFT_ROOM_KEY] = room
        result = reconcile_live_draft_room(session, room)

    record_safe_mode_diagnostics(session, manual_recovery_available=result.manual_recovery_available)
    return result


def clear_safe_mode_after_successful_pick(session: dict[str, Any], room: dict[str, Any]) -> None:
    session.pop(SAFE_MODE_ACTIVE_KEY, None)
    session.pop(SAFE_MODE_ERROR_KEY, None)
    session.pop(SAFE_MODE_ERROR_REASON_KEY, None)
    try:
        from live_draft_expired_pick import clear_autopick_state_for_pick_advance

        clear_autopick_state_for_pick_advance(session, int(room.get("current_pick_index") or 0))
    except ImportError:
        pass
    reconcile_live_draft_room(session, room)


def timer_should_run(session: dict[str, Any], room: dict[str, Any]) -> bool:
    try:
        from live_draft_start_progress import is_live_draft_start_in_flight

        if is_live_draft_start_in_flight(session):
            return False
    except ImportError:
        pass
    diag = session.get(SAFE_MODE_DIAG_KEY) or {}
    if isinstance(diag, dict) and "timer_should_run" in diag:
        return bool(diag.get("timer_should_run"))
    result = reconcile_live_draft_room(session, room)
    return result.timer_should_run


def reset_poll_rerun_budget(session: dict[str, Any]) -> None:
    """Clear passive-receiver rerun lockout after a remote revision is applied."""
    session.pop("_live_draft_rerun_count", None)
    session.pop("_live_draft_rerun_loop_prevented", None)
    try:
        from live_draft_expired_pick import RERUN_LOOP_PREVENTED_KEY

        session.pop(RERUN_LOOP_PREVENTED_KEY, None)
    except ImportError:
        pass


def is_rerun_allowed(session: dict[str, Any], source: str, *, room: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Central gate for all Live Draft Room st.rerun() calls."""
    if source in _POLL_APPLY_RERUN_SOURCES and session.get("_live_draft_poll_apply_pending"):
        return True, ""
    try:
        from live_draft_start_progress import is_live_draft_start_in_flight

        if is_live_draft_start_in_flight(session) and source in (
            "poll_fragment",
            "poll_shared_draft",
            "poll_apply",
            "poll_remote_revision",
            "timer_fragment",
            "timer_fragment_zero",
            "page_autopick",
        ):
            return False, "draft_start_in_flight"
    except ImportError:
        pass
    if is_safe_mode_active(session) and source in _BLOCKED_RERUN_SOURCES:
        return False, f"safe_mode_blocks_{source}"

    try:
        from live_draft_expired_pick import (
            RERUN_LOOP_PREVENTED_KEY,
            autopick_failure_backoff_active,
            timer_zero_rerun_already_latched,
        )

        live = room or session.get(LIVE_DRAFT_ROOM_KEY)
        if session.get(RERUN_LOOP_PREVENTED_KEY) and source in _BLOCKED_RERUN_SOURCES:
            return False, "rerun_loop_prevented"
        if isinstance(live, dict) and autopick_failure_backoff_active(session, live) and source in _BLOCKED_RERUN_SOURCES:
            return False, "autopick_failure_backoff_active"
        if source == "timer_fragment_zero" and isinstance(live, dict):
            if timer_zero_rerun_already_latched(session, live):
                return False, "timer_zero_rerun_already_latched"
    except ImportError:
        pass

    count = int(session.get("_live_draft_rerun_count") or 0)
    if count > 8 and source in _BLOCKED_RERUN_SOURCES:
        session["_live_draft_rerun_loop_prevented"] = True
        return False, "excessive_reruns_blocked"

    return True, ""


def request_poll_apply_rerun(st: Any, session: dict[str, Any], *, room: dict[str, Any] | None = None) -> bool:
    """Rerun after remote revision apply — bypasses passive-receiver rerun budget."""
    session["_live_draft_poll_apply_pending"] = True
    allowed, reason = is_rerun_allowed(session, "poll_apply", room=room)
    record_rerun_diagnostics(session, rerun_source="poll_apply", rerun_allowed=allowed, rerun_blocked_reason=reason or None)
    try:
        from live_draft_mp_diagnostics import record_poll_sync_trace

        record_poll_sync_trace(
            session,
            rerun_requested_after_apply=allowed,
            rerun_blocked_reason=reason or None,
        )
    except ImportError:
        pass
    if not allowed:
        session.pop("_live_draft_poll_apply_pending", None)
        return False
    session["_live_draft_last_rerun_source"] = "poll_apply"
    session.pop("_live_draft_poll_apply_pending", None)
    try:
        from fantasy_workflow_trace import note_rerun

        note_rerun(
            session,
            function="request_poll_apply_rerun",
            reason="poll_apply",
            page="Live Draft Room",
            st=st,
        )
    except ImportError:
        pass
    st.rerun()
    return True


def request_live_draft_rerun(st: Any, session: dict[str, Any], source: str, *, room: dict[str, Any] | None = None) -> bool:
    """Call instead of st.rerun() on Live Draft Room paths."""
    allowed, reason = is_rerun_allowed(session, source, room=room)
    record_rerun_diagnostics(session, rerun_source=source, rerun_allowed=allowed, rerun_blocked_reason=reason or None)
    if not allowed:
        try:
            from fantasy_workflow_trace import log_wf

            log_wf(
                session,
                function="request_live_draft_rerun",
                reason=f"rerun_blocked:{reason}",
                page="Live Draft Room",
                key="rerun",
                previous=True,
                new=False,
                st=st,
            )
        except ImportError:
            pass
        return False
    if source == "timer_fragment_zero":
        try:
            from live_draft_expired_pick import claim_timer_zero_rerun

            live = room or session.get(LIVE_DRAFT_ROOM_KEY)
            if isinstance(live, dict) and not claim_timer_zero_rerun(session, live):
                record_rerun_diagnostics(
                    session,
                    rerun_source=source,
                    rerun_allowed=False,
                    rerun_blocked_reason="timer_zero_rerun_claim_failed",
                )
                return False
        except ImportError:
            pass
    session["_live_draft_last_rerun_source"] = source
    session["_live_draft_rerun_count"] = int(session.get("_live_draft_rerun_count") or 0) + 1
    try:
        from live_draft_rerun_scope import (
            force_live_draft_expensive_recompute,
            mark_live_draft_timer_tick,
        )

        if source in ("timer_fragment", "timer_fragment_zero"):
            # Timer / zero-cross ticks stay light; page_autopick forces rebuild after pick.
            mark_live_draft_timer_tick(session)
        elif source == "poll_fragment":
            # Shared-board poll changed state — must rebuild recommendations.
            force_live_draft_expensive_recompute(session)
        elif source in (
            "manual_pick",
            "auto_pick",
            "page_autopick",
            "live_draft_queue",
            "pause_draft",
            "resume_draft",
            "pick_commit",
            "auto_pick_complete",
        ):
            force_live_draft_expensive_recompute(session)
    except ImportError:
        pass
    try:
        from fantasy_workflow_trace import note_rerun

        note_rerun(
            session,
            function="request_live_draft_rerun",
            reason=str(source),
            page="Live Draft Room",
            st=st,
        )
    except ImportError:
        pass
    st.rerun()
    return True
