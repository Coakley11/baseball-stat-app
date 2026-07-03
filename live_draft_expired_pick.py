"""Expired-pick state machine — one auto-pick attempt per pick index, backoff on failure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from live_draft_pick_commit import persist_applied_pick, resolve_live_room, run_autopick_selection, sync_expected_revision
from live_draft_timer_logic import live_draft_seconds_remaining, live_draft_timer_expired_for_pick

AUTOPICK_DIAG_KEY = "_live_draft_autopick_diag"
AUTOPICK_ATTEMPTED_INDEX_KEY = "_live_draft_autopick_attempted_for_index"
AUTOPICK_LOCK_KEY = "_live_draft_autopick_in_progress_lock"
AUTOPICK_BACKOFF_INDEX_KEY = "_live_draft_autopick_failure_backoff_index"
AUTOPICK_ERROR_KEY = "_live_draft_autopick_error"
RERUN_LOOP_PREVENTED_KEY = "_live_draft_rerun_loop_prevented"
EXPIRED_PICK_PENDING_KEY = "_live_draft_timer_expired_pending"


@dataclass
class ExpiredPickPageResult:
    handled: bool
    ok: bool
    should_rerun: bool
    message: str
    error: str


def _pick_index(room: dict[str, Any]) -> int:
    return int(room.get("current_pick_index") or 0)


def record_autopick_diagnostics(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    diag = dict(session.get(AUTOPICK_DIAG_KEY) or {})
    diag.update(fields)
    session[AUTOPICK_DIAG_KEY] = diag
    return diag


def expired_pick_detected(room: dict[str, Any]) -> bool:
    return bool(room.get("status") == "in_progress" and live_draft_timer_expired_for_pick(room))


def autopick_attempted_for_index(session: dict[str, Any], room: dict[str, Any]) -> bool:
    idx = _pick_index(room)
    attempted = session.get(AUTOPICK_ATTEMPTED_INDEX_KEY)
    return attempted is not None and int(attempted) == idx


def autopick_failure_backoff_active(session: dict[str, Any], room: dict[str, Any]) -> bool:
    if not session.get(RERUN_LOOP_PREVENTED_KEY):
        return False
    backoff_idx = session.get(AUTOPICK_BACKOFF_INDEX_KEY)
    return backoff_idx is not None and int(backoff_idx) == _pick_index(room)


def should_suppress_expired_rerun(session: dict[str, Any], room: dict[str, Any]) -> bool:
    return autopick_failure_backoff_active(session, room) or (
        autopick_attempted_for_index(session, room) and not expired_pick_detected(room)
    )


def _multiplayer_autopick_allowed(session: dict[str, Any]) -> bool:
    """Only the room host runs timer auto-pick in multiplayer (avoids duplicate commits)."""
    try:
        from draft_room_context import is_multiplayer_draft_active
        from draft_room_membership import is_room_host
        from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, get_shared_room_store

        if not is_multiplayer_draft_active(session):
            return True
        room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
        document = get_shared_room_store().load(room_code) if room_code else None
        return bool(is_room_host(session, document))
    except ImportError:
        return True


def should_fragment_trigger_full_rerun(session: dict[str, Any], room: dict[str, Any]) -> bool:
    """At most one full rerun per expired pick index before attempt is recorded."""
    try:
        from draft_ui import live_draft_autopick_disabled

        if live_draft_autopick_disabled(session):
            return False
    except ImportError:
        pass
    if session.get("_live_draft_manual_pick_in_flight") or session.get("_pending_manual_draft_pick"):
        return False
    try:
        from live_draft_safe_mode import is_safe_mode_active, timer_should_run

        if is_safe_mode_active(session) or not timer_should_run(session, room):
            return False
    except ImportError:
        pass
    if not _multiplayer_autopick_allowed(session):
        return False
    if not expired_pick_detected(room):
        session.pop(EXPIRED_PICK_PENDING_KEY, None)
        return False
    if autopick_failure_backoff_active(session, room):
        return False
    if autopick_attempted_for_index(session, room):
        return False
    if session.get(AUTOPICK_LOCK_KEY):
        return False
    if session.get(RERUN_LOOP_PREVENTED_KEY) and session.get(AUTOPICK_BACKOFF_INDEX_KEY) == _pick_index(room):
        return False
    return True


def clear_autopick_state_for_pick_advance(session: dict[str, Any], new_index: int | None = None) -> None:
    """Clear backoff/attempt locks after manual pick or successful auto-pick."""
    session.pop(AUTOPICK_ATTEMPTED_INDEX_KEY, None)
    session.pop(AUTOPICK_BACKOFF_INDEX_KEY, None)
    session.pop(AUTOPICK_ERROR_KEY, None)
    session.pop(RERUN_LOOP_PREVENTED_KEY, None)
    session.pop(EXPIRED_PICK_PENDING_KEY, None)
    session.pop(AUTOPICK_LOCK_KEY, None)
    if new_index is not None:
        record_autopick_diagnostics(
            session,
            autopick_failure_backoff_active=False,
            rerun_loop_prevented=False,
            autopick_attempted_for_index=None,
            autopick_in_progress_lock=False,
        )


def clear_autopick_backoff_for_manual(session: dict[str, Any], room: dict[str, Any]) -> None:
    """Manual pick bypasses failed auto-pick backoff for the current pick index."""
    idx = _pick_index(room)
    if session.get(AUTOPICK_BACKOFF_INDEX_KEY) == idx:
        session.pop(AUTOPICK_BACKOFF_INDEX_KEY, None)
        session.pop(RERUN_LOOP_PREVENTED_KEY, None)
        session.pop(AUTOPICK_ATTEMPTED_INDEX_KEY, None)
        session.pop(AUTOPICK_ERROR_KEY, None)
        record_autopick_diagnostics(
            session,
            autopick_failure_backoff_active=False,
            rerun_loop_prevented=False,
            autopick_attempted_for_index=None,
        )


def _mark_autopick_failed(session: dict[str, Any], room: dict[str, Any], error: str) -> None:
    idx = _pick_index(room)
    session[AUTOPICK_ATTEMPTED_INDEX_KEY] = idx
    session[AUTOPICK_BACKOFF_INDEX_KEY] = idx
    session[RERUN_LOOP_PREVENTED_KEY] = True
    session[AUTOPICK_ERROR_KEY] = error
    session.pop(EXPIRED_PICK_PENDING_KEY, None)
    record_autopick_diagnostics(
        session,
        autopick_success=False,
        autopick_error=error,
        autopick_failure_backoff_active=True,
        rerun_loop_prevented=True,
        autopick_attempted_for_index=idx,
        autopick_in_progress_lock=False,
    )
    try:
        from draft_commit_diagnostics import set_live_draft_pick_notice

        set_live_draft_pick_notice(session, "error", f"Auto-pick failed: {error}")
    except ImportError:
        pass


def _mark_autopick_success(session: dict[str, Any], room: dict[str, Any], message: str) -> None:
    idx_after = _pick_index(room)
    clear_autopick_state_for_pick_advance(session, idx_after)
    record_autopick_diagnostics(
        session,
        autopick_success=True,
        autopick_error=None,
        autopick_failure_backoff_active=False,
        rerun_loop_prevented=False,
        current_pick_index_after_autopick=idx_after,
    )
    try:
        from draft_commit_diagnostics import set_live_draft_pick_notice

        board_len = len(room.get("draft_board") or [])
        player_id = str((room.get("draft_board") or [{}])[-1].get("playerID") or message)
        set_live_draft_pick_notice(session, "success", message, pick_key=f"{board_len}:{player_id}")
        try:
            from live_draft_ui_cache import invalidate_draft_assistant_scoring_cache, invalidate_live_draft_ui_caches

            invalidate_live_draft_ui_caches(session)
            invalidate_draft_assistant_scoring_cache(session)
        except ImportError:
            session.pop("_live_draft_rec_cache", None)
    except ImportError:
        pass


def run_expired_autopick_once(session: dict[str, Any], room: dict[str, Any], *, source: str = "page_autopick") -> ExpiredPickPageResult:
    """Attempt auto-pick exactly once for the current expired pick index."""
    room = resolve_live_room(session, room) or room
    idx = _pick_index(room)

    record_autopick_diagnostics(
        session,
        expired_pick_detected=expired_pick_detected(room),
        autopick_attempted_for_index=session.get(AUTOPICK_ATTEMPTED_INDEX_KEY),
        autopick_in_progress_lock=bool(session.get(AUTOPICK_LOCK_KEY)),
        autopick_failure_backoff_active=autopick_failure_backoff_active(session, room),
        rerun_loop_prevented=bool(session.get(RERUN_LOOP_PREVENTED_KEY)),
        current_pick_index_before_autopick=idx,
        board_size_before_autopick=len(room.get("draft_board") or []),
    )

    if room.get("status") != "in_progress":
        return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")

    if not expired_pick_detected(room):
        return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")

    if autopick_failure_backoff_active(session, room):
        err = str(session.get(AUTOPICK_ERROR_KEY) or "Auto-pick failed for this pick.")
        return ExpiredPickPageResult(handled=True, ok=False, should_rerun=False, message="", error=err)

    if not _multiplayer_autopick_allowed(session):
        return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")

    if autopick_attempted_for_index(session, room):
        return ExpiredPickPageResult(handled=True, ok=False, should_rerun=False, message="", error="")

    if session.get(AUTOPICK_LOCK_KEY):
        return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")

    session[AUTOPICK_LOCK_KEY] = True
    record_autopick_diagnostics(session, autopick_in_progress_lock=True, autopick_commit_path=source)

    board_before = len(room.get("draft_board") or [])
    idx_before = idx
    expected_revision = sync_expected_revision(session)

    try:
        ok_select, select_msg = run_autopick_selection(room, session)
        if not ok_select:
            _mark_autopick_failed(session, room, select_msg or "Auto-pick selection failed.")
            return ExpiredPickPageResult(
                handled=True,
                ok=False,
                should_rerun=False,
                message="",
                error=select_msg or "Auto-pick selection failed.",
            )

        commit = persist_applied_pick(
            session,
            room,
            source=f"timer_autopick:{source}",
            expected_revision=expected_revision,
            board_size_before=board_before,
            idx_before=idx_before,
        )

        record_autopick_diagnostics(
            session,
            autopick_commit_path=commit.commit_path,
            board_size_after_autopick=commit.board_size_after,
            current_pick_index_after_autopick=commit.current_pick_index_after,
        )

        if not commit.ok:
            _mark_autopick_failed(session, room, commit.message)
            return ExpiredPickPageResult(
                handled=True,
                ok=False,
                should_rerun=False,
                message="",
                error=commit.message,
            )

        msg = select_msg or commit.message
        _mark_autopick_success(session, room, msg)
        return ExpiredPickPageResult(handled=True, ok=True, should_rerun=True, message=msg, error="")
    finally:
        session.pop(AUTOPICK_LOCK_KEY, None)
        record_autopick_diagnostics(session, autopick_in_progress_lock=False)


def handle_expired_pick_on_page(session: dict[str, Any], room: dict[str, Any], *, source: str = "page_autopick") -> ExpiredPickPageResult:
    """Process expired pick on full page render — never loops reruns on failure."""
    room = resolve_live_room(session, room) or room

    try:
        from draft_ui import live_draft_autopick_disabled

        if live_draft_autopick_disabled(session):
            return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")
    except ImportError:
        pass

    if session.get("_live_draft_manual_pick_in_flight") or session.get("_pending_manual_draft_pick"):
        return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")

    if autopick_failure_backoff_active(session, room):
        err = str(session.get(AUTOPICK_ERROR_KEY) or "Auto-pick failed for this pick.")
        record_autopick_diagnostics(
            session,
            expired_pick_detected=expired_pick_detected(room),
            autopick_failure_backoff_active=True,
            rerun_loop_prevented=True,
            autopick_error=err,
        )
        return ExpiredPickPageResult(handled=True, ok=False, should_rerun=False, message="", error=err)

    try:
        from live_draft_safe_mode import is_safe_mode_active, timer_should_run

        if is_safe_mode_active(session) or not timer_should_run(session, room):
            return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")
    except ImportError:
        pass

    if not expired_pick_detected(room) and not session.get(EXPIRED_PICK_PENDING_KEY):
        return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")

    return run_expired_autopick_once(session, room, source=source)


def autopick_error_message(session: dict[str, Any], room: dict[str, Any]) -> str:
    if autopick_failure_backoff_active(session, room):
        return str(session.get(AUTOPICK_ERROR_KEY) or "")
    return ""
