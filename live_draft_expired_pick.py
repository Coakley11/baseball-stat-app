"""Expired-pick state machine — one auto-pick attempt per pick index, backoff on failure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from live_draft_pick_commit import persist_applied_pick, resolve_live_room, run_autopick_selection, sync_expected_revision
from live_draft_timer_logic import (
    build_expiration_token,
    expiration_already_processed,
    live_draft_seconds_remaining,
    live_draft_timer_expired_for_pick,
    mark_expiration_processed,
    reconstruct_timer_deadline,
)

AUTOPICK_DIAG_KEY = "_live_draft_autopick_diag"
AUTOPICK_ATTEMPTED_INDEX_KEY = "_live_draft_autopick_attempted_for_index"
AUTOPICK_LOCK_KEY = "_live_draft_autopick_in_progress_lock"
AUTOPICK_BACKOFF_INDEX_KEY = "_live_draft_autopick_failure_backoff_index"
AUTOPICK_BACKOFF_UNTIL_KEY = "_live_draft_autopick_failure_backoff_until"
AUTOPICK_ERROR_KEY = "_live_draft_autopick_error"
AUTOPICK_RETRY_SECONDS = 1.0
RERUN_LOOP_PREVENTED_KEY = "_live_draft_rerun_loop_prevented"
EXPIRED_PICK_PENDING_KEY = "_live_draft_timer_expired_pending"
# One full-app timer_fragment_zero per pick index — prevents fragment attach → sync tick →
# st.rerun() from aborting room_controls_timer before handle_expired_pick_on_page runs.
TIMER_ZERO_RERUN_LATCH_KEY = "_live_draft_timer_zero_rerun_pick"
# Session-scoped single-flight for the current expiration token (covers duplicate Streamlit reruns).
LAST_PROCESSED_EXPIRATION_TOKEN_SESSION_KEY = "_live_draft_last_processed_expiration_token"
CLAIMED_EXPIRATION_TOKEN_KEY = "_live_draft_claimed_expiration_token"


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
    """True while a short cooldown after a failed auto-pick is still in effect.

    Permanent stall at 0s is not allowed — retries resume after AUTOPICK_RETRY_SECONDS.
    """
    import time

    backoff_idx = session.get(AUTOPICK_BACKOFF_INDEX_KEY)
    if backoff_idx is None or int(backoff_idx) != _pick_index(room):
        return False
    until = session.get(AUTOPICK_BACKOFF_UNTIL_KEY)
    if until is None:
        # Legacy permanent backoff — convert to a short retry window.
        session[AUTOPICK_BACKOFF_UNTIL_KEY] = time.time() + AUTOPICK_RETRY_SECONDS
        return True
    if float(until) > time.time():
        return True
    # Cooldown elapsed — allow another attempt for this pick index.
    session.pop(AUTOPICK_BACKOFF_INDEX_KEY, None)
    session.pop(AUTOPICK_BACKOFF_UNTIL_KEY, None)
    session.pop(AUTOPICK_ATTEMPTED_INDEX_KEY, None)
    session.pop(RERUN_LOOP_PREVENTED_KEY, None)
    return False


def should_suppress_expired_rerun(session: dict[str, Any], room: dict[str, Any]) -> bool:
    return autopick_failure_backoff_active(session, room) or (
        autopick_attempted_for_index(session, room) and not expired_pick_detected(room)
    )


def _multiplayer_autopick_allowed(session: dict[str, Any]) -> bool:
    """Host preferred; lease takeover allowed when authority stalls (watchdog)."""
    try:
        from live_draft_timer_authority import multiparty_may_run_autopick

        return bool(multiparty_may_run_autopick(session))
    except ImportError:
        pass
    try:
        from draft_room_context import is_multiplayer_draft_active
        from draft_room_membership import is_room_host
        from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, load_shared_room_document

        if not is_multiplayer_draft_active(session):
            return True
        mp_diag = session.get("_live_draft_mp_diag")
        if isinstance(mp_diag, dict) and mp_diag.get("is_host") is not None:
            return bool(mp_diag.get("is_host"))
        room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
        document = load_shared_room_document(session, room_code) if room_code else None
        return bool(is_room_host(session, document))
    except ImportError:
        return True


EXPIRED_PICK_PERF_KEY = "_live_draft_expired_pick_perf"


def _perf_ms(t0: float) -> int:
    import time

    return int((time.perf_counter() - t0) * 1000)


def record_expired_pick_perf(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Always-on timing breakdown for timer_handle_expired_pick (ms)."""
    prev = dict(session.get(EXPIRED_PICK_PERF_KEY) or {})
    prev.update({k: v for k, v in fields.items() if v is not None})
    session[EXPIRED_PICK_PERF_KEY] = prev
    return prev


def format_expired_pick_perf(session: dict[str, Any]) -> str:
    perf = session.get(EXPIRED_PICK_PERF_KEY)
    if not isinstance(perf, dict) or not perf:
        return ""
    keys = (
        "stage",
        "total_ms",
        "host_check_ms",
        "sync_revision_ms",
        "recommendation_ms",
        "recommendation_cache_hit",
        "shared_commit_ms",
        "board_save_ms",
        "cloud_write_ms",
        "activity_ms",
        "cache_invalidate_ms",
        "poll_diag_ms",
        "ui_rerun_ms",
        "error",
    )
    parts = [f"{k}={perf.get(k)}" for k in keys if perf.get(k) is not None]
    return " | ".join(parts)


def timer_zero_rerun_already_latched(session: dict[str, Any], room: dict[str, Any]) -> bool:
    return session.get(TIMER_ZERO_RERUN_LATCH_KEY) == _pick_index(room)


def claim_timer_zero_rerun(session: dict[str, Any], room: dict[str, Any]) -> bool:
    """Claim the single timer_fragment_zero full-app rerun for this pick index."""
    idx = _pick_index(room)
    if session.get(TIMER_ZERO_RERUN_LATCH_KEY) == idx:
        return False
    session[TIMER_ZERO_RERUN_LATCH_KEY] = idx
    session[EXPIRED_PICK_PENDING_KEY] = True
    return True


def should_attach_timer_fragment(session: dict[str, Any], room: dict[str, Any]) -> bool:
    """False when clock is already expired — page script must own autopick, not the fragment."""
    if str(room.get("status") or "") != "in_progress":
        return True
    try:
        if live_draft_timer_expired_for_pick(room) or live_draft_seconds_remaining(room) <= 0:
            session[EXPIRED_PICK_PENDING_KEY] = True
            return False
    except Exception:
        pass
    return True


def clock_needs_autopick(session: dict[str, Any], room: dict[str, Any]) -> bool:
    """True when the draft clock demands a commit (expired or pending zero-cross)."""
    if str(room.get("status") or "") != "in_progress":
        return False
    if bool(session.get(EXPIRED_PICK_PENDING_KEY)):
        return True
    try:
        if live_draft_seconds_remaining(room) <= 0:
            return True
    except Exception:
        pass
    return expired_pick_detected(room)


def should_fragment_trigger_full_rerun(session: dict[str, Any], room: dict[str, Any]) -> bool:
    """Request a full-app rerun so page_autopick can commit an expired pick.

    Soft UI gates (safe_mode / timer_should_run) must not block recovery when the
    clock is already at 0 — that combination previously froze Solo Drafts at 0s.
    """
    try:
        from draft_ui import live_draft_autopick_disabled

        if live_draft_autopick_disabled(session):
            return False
    except ImportError:
        pass
    if session.get("_live_draft_manual_pick_in_flight") or session.get("_pending_manual_draft_pick"):
        return False
    expired = clock_needs_autopick(session, room)
    if not expired:
        try:
            from live_draft_safe_mode import is_safe_mode_active, timer_should_run

            if is_safe_mode_active(session) or not timer_should_run(session, room):
                return False
        except ImportError:
            pass
        session.pop(EXPIRED_PICK_PENDING_KEY, None)
        return False
    if not _multiplayer_autopick_allowed(session):
        return False
    if autopick_failure_backoff_active(session, room):
        return False
    if session.get(AUTOPICK_LOCK_KEY):
        return False
    if timer_zero_rerun_already_latched(session, room):
        return False
    if autopick_attempted_for_index(session, room):
        return False
    if session.get(RERUN_LOOP_PREVENTED_KEY) and session.get(AUTOPICK_BACKOFF_INDEX_KEY) == _pick_index(room):
        return False
    return True


MANUAL_PREEMPTED_EXPIRATION_TOKEN_KEY = "_live_draft_manual_preempted_expiration_token"


def _expiration_token_already_done(session: dict[str, Any], room: dict[str, Any], token: str) -> bool:
    if not token:
        return False
    if str(session.get(LAST_PROCESSED_EXPIRATION_TOKEN_SESSION_KEY) or "").strip() == token:
        return True
    return expiration_already_processed(room, token)


def claim_expiration_token(session: dict[str, Any], token: str) -> bool:
    """Claim a deadline token for single-flight processing. Returns False if already claimed/done."""
    tok = str(token or "").strip()
    if not tok:
        return False
    if str(session.get(LAST_PROCESSED_EXPIRATION_TOKEN_SESSION_KEY) or "").strip() == tok:
        return False
    claimed = str(session.get(CLAIMED_EXPIRATION_TOKEN_KEY) or "").strip()
    if claimed == tok:
        return False
    session[CLAIMED_EXPIRATION_TOKEN_KEY] = tok
    return True


def remember_processed_expiration_token(
    session: dict[str, Any],
    room: dict[str, Any],
    token: str,
    *,
    expired_pick_index: int | None = None,
) -> None:
    tok = str(token or "").strip()
    if not tok:
        return
    session[LAST_PROCESSED_EXPIRATION_TOKEN_SESSION_KEY] = tok
    mark_expiration_processed(room, tok, expired_pick_index=expired_pick_index)


def clear_autopick_backoff_for_manual(session: dict[str, Any], room: dict[str, Any]) -> None:
    """Manual pick bypasses failed auto-pick backoff for the current pick index.

    Stashes the current expiration token so a successful manual pick can mark it
    processed and block a duplicate timer auto-pick for the same deadline.
    """
    idx = _pick_index(room)
    try:
        token = build_expiration_token(room)
        if token:
            session[MANUAL_PREEMPTED_EXPIRATION_TOKEN_KEY] = token
    except Exception:
        pass
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
    session.pop(EXPIRED_PICK_PENDING_KEY, None)
    session.pop(TIMER_ZERO_RERUN_LATCH_KEY, None)
    try:
        token = str(session.get(MANUAL_PREEMPTED_EXPIRATION_TOKEN_KEY) or "").strip()
        if token:
            session[CLAIMED_EXPIRATION_TOKEN_KEY] = token
        else:
            session.pop(CLAIMED_EXPIRATION_TOKEN_KEY, None)
    except Exception:
        session.pop(CLAIMED_EXPIRATION_TOKEN_KEY, None)


def clear_autopick_state_for_pick_advance(session: dict[str, Any], new_index: int | None = None) -> None:
    """Clear backoff/attempt locks after manual pick or successful auto-pick."""
    preempted = str(session.pop(MANUAL_PREEMPTED_EXPIRATION_TOKEN_KEY, None) or "").strip()
    if preempted:
        try:
            room = session.get("live_draft_room")
            if isinstance(room, dict):
                remember_processed_expiration_token(session, room, preempted)
            else:
                session[LAST_PROCESSED_EXPIRATION_TOKEN_SESSION_KEY] = preempted
        except Exception:
            session[LAST_PROCESSED_EXPIRATION_TOKEN_SESSION_KEY] = preempted
    session.pop(AUTOPICK_ATTEMPTED_INDEX_KEY, None)
    session.pop(AUTOPICK_BACKOFF_INDEX_KEY, None)
    session.pop(AUTOPICK_BACKOFF_UNTIL_KEY, None)
    session.pop(AUTOPICK_ERROR_KEY, None)
    session.pop(RERUN_LOOP_PREVENTED_KEY, None)
    session.pop(EXPIRED_PICK_PENDING_KEY, None)
    session.pop(AUTOPICK_LOCK_KEY, None)
    session.pop(TIMER_ZERO_RERUN_LATCH_KEY, None)
    session.pop(CLAIMED_EXPIRATION_TOKEN_KEY, None)
    # Fresh pick = fresh rerun budget so page_autopick can refresh the UI after commit.
    session.pop("_live_draft_rerun_count", None)
    if new_index is not None:
        record_autopick_diagnostics(
            session,
            autopick_failure_backoff_active=False,
            rerun_loop_prevented=False,
            autopick_attempted_for_index=None,
            autopick_in_progress_lock=False,
        )


def _mark_autopick_failed(session: dict[str, Any], room: dict[str, Any], error: str) -> None:
    import time

    idx = _pick_index(room)
    session[AUTOPICK_ATTEMPTED_INDEX_KEY] = idx
    session[AUTOPICK_BACKOFF_INDEX_KEY] = idx
    session[AUTOPICK_BACKOFF_UNTIL_KEY] = time.time() + AUTOPICK_RETRY_SECONDS
    session[RERUN_LOOP_PREVENTED_KEY] = True
    session[AUTOPICK_ERROR_KEY] = error
    # Keep pending + clear zero-rerun latch so a recovery tick can fire after backoff.
    session[EXPIRED_PICK_PENDING_KEY] = True
    session.pop(TIMER_ZERO_RERUN_LATCH_KEY, None)
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
        from live_draft_autopick_chain import note_autopick_chain

        note_autopick_chain(
            session,
            "auto_pick_applied",
            ok=False,
            error=error,
            pick_index=idx,
        )
    except ImportError:
        pass
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
    import time

    t_total = time.perf_counter()
    room = resolve_live_room(session, room) or room
    try:
        reconstruct_timer_deadline(room)
    except Exception:
        pass
    idx = _pick_index(room)
    expiration_token = build_expiration_token(room)
    record_expired_pick_perf(session, source=source, pick_index=idx, expiration_token=expiration_token)

    record_autopick_diagnostics(
        session,
        expired_pick_detected=expired_pick_detected(room),
        clock_needs_autopick=clock_needs_autopick(session, room),
        autopick_attempted_for_index=session.get(AUTOPICK_ATTEMPTED_INDEX_KEY),
        autopick_in_progress_lock=bool(session.get(AUTOPICK_LOCK_KEY)),
        autopick_failure_backoff_active=autopick_failure_backoff_active(session, room),
        rerun_loop_prevented=bool(session.get(RERUN_LOOP_PREVENTED_KEY)),
        current_pick_index_before_autopick=idx,
        board_size_before_autopick=len(room.get("draft_board") or []),
        expiration_token=expiration_token,
    )

    if room.get("status") != "in_progress":
        return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")

    if room.get("status") == "complete":
        return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")

    if _expiration_token_already_done(session, room, expiration_token):
        record_expired_pick_perf(session, stage="token_already_processed", total_ms=_perf_ms(t_total))
        return ExpiredPickPageResult(handled=True, ok=True, should_rerun=False, message="", error="")

    if not clock_needs_autopick(session, room):
        return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")

    try:
        from live_draft_autopick_chain import note_autopick_chain, reset_autopick_chain

        reset_autopick_chain(session, pick_index=idx)
        note_autopick_chain(
            session,
            "timer_hit_zero",
            ok=True,
            detail=f"remaining={live_draft_seconds_remaining(room)} token={expiration_token}",
            pick_index=idx,
        )
    except ImportError:
        pass

    if autopick_failure_backoff_active(session, room):
        err = str(session.get(AUTOPICK_ERROR_KEY) or "Auto-pick failed for this pick.")
        return ExpiredPickPageResult(handled=True, ok=False, should_rerun=False, message="", error=err)

    t0 = time.perf_counter()
    host_ok = _multiplayer_autopick_allowed(session)
    record_expired_pick_perf(session, host_check_ms=_perf_ms(t0))
    try:
        from live_draft_timer_authority import (
            expired_pick_needs_watchdog,
            record_watchdog_diagnostics,
        )

        if expired_pick_needs_watchdog(session, room):
            record_watchdog_diagnostics(
                session,
                expiration_token=expiration_token,
                pick_index=idx,
                authority_allowed=host_ok,
                elapsed_after_deadline_sec=max(
                    0.0,
                    time.time() - float(room.get("timer_deadline") or time.time()),
                ),
                source=source,
            )
    except ImportError:
        pass
    if not host_ok:
        return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")

    if autopick_attempted_for_index(session, room):
        return ExpiredPickPageResult(handled=True, ok=False, should_rerun=False, message="", error="")

    if session.get(AUTOPICK_LOCK_KEY):
        return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")

    if not claim_expiration_token(session, expiration_token):
        record_expired_pick_perf(session, stage="token_claim_denied", total_ms=_perf_ms(t_total))
        return ExpiredPickPageResult(handled=True, ok=True, should_rerun=False, message="", error="")

    session[AUTOPICK_LOCK_KEY] = True
    record_autopick_diagnostics(session, autopick_in_progress_lock=True, autopick_commit_path=source)

    board_before = len(room.get("draft_board") or [])
    idx_before = idx
    t0 = time.perf_counter()
    expected_revision = sync_expected_revision(session)
    record_expired_pick_perf(session, sync_revision_ms=_perf_ms(t0))

    try:
        t0 = time.perf_counter()
        ok_select, select_msg = run_autopick_selection(room, session)
        record_expired_pick_perf(
            session,
            recommendation_ms=_perf_ms(t0),
            recommendation_cache_hit=bool(session.get("_live_draft_autopick_used_rec_cache")),
        )
        selected_name = ""
        try:
            diag = session.get(AUTOPICK_DIAG_KEY) or {}
            selected_name = str(diag.get("selected_auto_pick_player") or diag.get("top_recommendation_player") or "")
        except Exception:
            selected_name = ""
        try:
            from live_draft_autopick_chain import note_autopick_chain

            note_autopick_chain(
                session,
                "auto_pick_selected",
                ok=bool(ok_select),
                detail=select_msg or "",
                error=None if ok_select else (select_msg or "selection failed"),
                selected_player=selected_name or None,
                pick_index=idx_before,
            )
        except ImportError:
            pass
        if not ok_select:
            session.pop(CLAIMED_EXPIRATION_TOKEN_KEY, None)
            _mark_autopick_failed(session, room, select_msg or "Auto-pick selection failed.")
            record_expired_pick_perf(session, total_ms=_perf_ms(t_total), ok=False)
            # Rerun so UI shows the error and the recovery fragment can remount.
            return ExpiredPickPageResult(
                handled=True,
                ok=False,
                should_rerun=True,
                message="",
                error=select_msg or "Auto-pick selection failed.",
            )

        t0 = time.perf_counter()
        commit = persist_applied_pick(
            session,
            room,
            source=f"timer_autopick:{source}",
            expected_revision=expected_revision,
            board_size_before=board_before,
            idx_before=idx_before,
            fast_path=True,
        )
        persist_ms = _perf_ms(t0)
        # persist_applied_pick records sub-bucket keys when fast_path/profiling enabled
        sub = dict(session.get("_live_draft_persist_perf") or {})
        record_expired_pick_perf(
            session,
            shared_commit_ms=sub.get("shared_commit_ms"),
            board_save_ms=sub.get("board_save_ms"),
            cloud_write_ms=sub.get("cloud_write_ms"),
            activity_ms=sub.get("activity_ms"),
            poll_diag_ms=sub.get("poll_diag_ms"),
            persist_total_ms=persist_ms,
        )

        record_autopick_diagnostics(
            session,
            autopick_commit_path=commit.commit_path,
            board_size_after_autopick=commit.board_size_after,
            current_pick_index_after_autopick=commit.current_pick_index_after,
        )

        if not commit.ok:
            session.pop(CLAIMED_EXPIRATION_TOKEN_KEY, None)
            _mark_autopick_failed(session, room, commit.message)
            record_expired_pick_perf(session, total_ms=_perf_ms(t_total), ok=False)
            return ExpiredPickPageResult(
                handled=True,
                ok=False,
                should_rerun=True,
                message="",
                error=commit.message,
            )

        # Persist the pre-advance token so duplicate Streamlit reruns cannot re-pick it.
        # Do not stamp timer_handled_index here — make_pick already reset the next deadline.
        remember_processed_expiration_token(session, room, expiration_token)
        # Successful pick resets the deadline; never leave an active draft parked at 0:00.
        if room.get("status") == "in_progress" and live_draft_seconds_remaining(room) <= 0:
            try:
                from live_draft_timer_logic import live_draft_reset_timer

                live_draft_reset_timer(room)
            except Exception:
                pass

        msg = select_msg or commit.message
        t0 = time.perf_counter()
        _mark_autopick_success(session, room, msg)
        idx_after = _pick_index(room)
        board_after = len(room.get("draft_board") or [])
        try:
            from live_draft_autopick_chain import note_autopick_chain
            from live_draft_timer_logic import live_draft_seconds_remaining as _secs

            note_autopick_chain(
                session,
                "auto_pick_applied",
                ok=True,
                detail=msg,
                selected_player=selected_name or None,
                pick_index=idx_after,
            )
            note_autopick_chain(
                session,
                "board_advanced",
                ok=board_after > board_before and idx_after > idx_before,
                detail=f"board {board_before}→{board_after} idx {idx_before}→{idx_after}",
                pick_index=idx_after,
            )
            timer_ok = bool(
                room.get("status") == "complete"
                or (
                    room.get("timer_deadline") is not None
                    and _secs(room) > 0
                )
            )
            note_autopick_chain(
                session,
                "next_timer_started",
                ok=timer_ok,
                detail=f"remaining={_secs(room) if room.get('status') != 'complete' else 'complete'}",
                pick_index=idx_after,
                error=None if timer_ok else "timer not restarted after pick",
            )
        except ImportError:
            pass
        try:
            from live_draft_chat_system import maybe_post_draft_system_message

            maybe_post_draft_system_message(
                session,
                "auto_pick",
                detail=msg,
                pick_index=idx_after,
            )
        except ImportError:
            pass
        record_expired_pick_perf(
            session,
            stage="committed",
            cache_invalidate_ms=_perf_ms(t0),
            total_ms=_perf_ms(t_total),
            ok=True,
            pick_index_after=idx_after,
            board_size_after=board_after,
        )
        return ExpiredPickPageResult(handled=True, ok=True, should_rerun=True, message=msg, error="")
    finally:
        session.pop(AUTOPICK_LOCK_KEY, None)
        record_autopick_diagnostics(session, autopick_in_progress_lock=False)
        if session.get(EXPIRED_PICK_PERF_KEY) and "total_ms" not in (session.get(EXPIRED_PICK_PERF_KEY) or {}):
            record_expired_pick_perf(session, total_ms=_perf_ms(t_total))


def handle_expired_pick_on_page(session: dict[str, Any], room: dict[str, Any], *, source: str = "page_autopick") -> ExpiredPickPageResult:
    """Process expired pick on full page render — never loops reruns on failure.

    State machine (must not stall):
      timer expired → select pick → persist/commit → revision++ → next pick → timer restart
    Soft gates (rerun budget / timer_should_run UI pause) must not skip the commit step.
    """
    room = resolve_live_room(session, room) or room
    record_expired_pick_perf(session, stage="handle_entered", source=source)

    try:
        from draft_ui import live_draft_autopick_disabled

        if live_draft_autopick_disabled(session):
            record_expired_pick_perf(session, stage="blocked_autopick_disabled")
            return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")
    except ImportError:
        pass

    if session.get("_live_draft_manual_pick_in_flight") or session.get("_pending_manual_draft_pick"):
        record_expired_pick_perf(session, stage="blocked_manual_pick_in_flight")
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
        record_expired_pick_perf(session, stage="blocked_backoff", error=err)
        return ExpiredPickPageResult(handled=True, ok=False, should_rerun=False, message="", error=err)

    clock_expired = clock_needs_autopick(session, room)
    if not clock_expired:
        try:
            from live_draft_safe_mode import is_safe_mode_active, timer_should_run

            # UI-only pause: only skip when the clock is *not* demanding a commit.
            if is_safe_mode_active(session) or not timer_should_run(session, room):
                record_expired_pick_perf(session, stage="blocked_timer_ui_gate")
                return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")
        except ImportError:
            pass
        record_expired_pick_perf(session, stage="not_expired")
        return ExpiredPickPageResult(handled=False, ok=False, should_rerun=False, message="", error="")

    # Soft rerun lockout stops st.rerun thrash, not the draft engine. Clear before commit so
    # a successful pick can request one UI refresh afterward.
    session.pop(RERUN_LOOP_PREVENTED_KEY, None)
    session.pop("_live_draft_rerun_count", None)
    record_expired_pick_perf(session, stage="commit_attempt", pick_index=_pick_index(room))

    return run_expired_autopick_once(session, room, source=source)


def autopick_error_message(session: dict[str, Any], room: dict[str, Any]) -> str:
    if autopick_failure_backoff_active(session, room):
        return str(session.get(AUTOPICK_ERROR_KEY) or "")
    return ""
