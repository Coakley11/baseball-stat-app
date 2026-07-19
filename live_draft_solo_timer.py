"""Solo Live Draft timer — one authoritative expire-and-advance transition.

Shared Multiplayer keeps its own sync path. Solo must not use competing
fragments, zero-latches, or false \"handled\" returns that leave the clock at 0.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

SOLO_EXPIRE_APPLIED_KEY = "_solo_expire_applied"
SOLO_EXPIRE_PERF_KEY = "_solo_expire_perf"
SOLO_TIMER_WAKE_KEY = "_solo_timer_wake"


@dataclass
class SoloExpireSnapshot:
    draft_id: str
    pick_number: int
    pick_index: int
    team: str
    committed_picks: int
    total_configured_picks: int
    timer_seconds: int
    deadline: float | None = None


@dataclass
class SoloExpireResult:
    ok: bool
    advanced: bool = False
    complete: bool = False
    reason: str = ""
    message: str = ""
    error: str = ""
    snapshot_before: SoloExpireSnapshot | None = None
    committed_picks: int = 0
    pick_index: int = 0
    team_on_clock: str = ""
    timer_deadline: float | None = None
    zero_to_commit_ms: float | None = None
    commit_to_next_timer_ms: float | None = None
    should_rerun: bool = False
    extras: dict[str, Any] = field(default_factory=dict)


def is_solo_live_draft(session: dict[str, Any], room: dict[str, Any] | None = None) -> bool:
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        return False
    code = str(session.get("active_shared_draft_room_code") or "").strip()
    if code:
        return False
    try:
        from live_draft_setup_mode import is_solo_draft_mode

        return bool(is_solo_draft_mode(session, room=live))
    except ImportError:
        cfg = dict(live.get("config") or {})
        mode = str(cfg.get("draft_setup_mode") or session.get("live_draft_setup_mode") or "").lower()
        return "shared" not in mode


def build_solo_expire_snapshot(room: dict[str, Any]) -> SoloExpireSnapshot:
    from live_draft_timer_logic import ensure_full_pick_order, live_draft_current_slot, live_draft_timer_deadline

    ensure_full_pick_order(room)
    cfg = dict(room.get("config") or {})
    try:
        from live_draft_safe_mode import total_expected_picks

        total = int(total_expected_picks(room) or 0)
    except ImportError:
        teams = room.get("teams") or []
        rounds = int(cfg.get("picks_per_team") or cfg.get("rounds") or 0)
        total = len(teams) * rounds if teams and rounds else 0
    board = room.get("draft_board") or []
    committed = len(board) if isinstance(board, list) else 0
    idx = int(room.get("current_pick_index") or 0)
    slot = live_draft_current_slot(room) or {}
    draft_id = str(
        room.get("draft_room_id") or room.get("draft_id") or room.get("id") or "solo"
    ).strip()
    timer_seconds = int(cfg.get("timer_seconds") or room.get("timer_seconds") or 60)
    return SoloExpireSnapshot(
        draft_id=draft_id,
        pick_number=int(slot.get("Pick") or (idx + 1)),
        pick_index=idx,
        team=str(slot.get("Team") or "").strip(),
        committed_picks=committed,
        total_configured_picks=total,
        timer_seconds=max(1, timer_seconds),
        deadline=live_draft_timer_deadline(room),
    )


def _guard_token(snapshot: SoloExpireSnapshot) -> str:
    deadline_s = f"{float(snapshot.deadline):.3f}" if snapshot.deadline is not None else "none"
    return f"{snapshot.draft_id}|{snapshot.pick_index}|{snapshot.team}|{deadline_s}"


def solo_clock_expired(room: dict[str, Any]) -> bool:
    if str(room.get("status") or "") != "in_progress":
        return False
    try:
        from live_draft_timer_logic import live_draft_seconds_remaining

        return int(live_draft_seconds_remaining(room)) <= 0
    except ImportError:
        deadline = room.get("timer_deadline")
        if deadline is None:
            return False
        return float(deadline) <= time.time()


def expire_current_pick_and_advance(
    room: dict[str, Any],
    *,
    session: dict[str, Any] | None = None,
    now: float | None = None,
) -> SoloExpireResult:
    """Atomically expire the on-clock Solo pick and advance (or complete).

    Exactly one transition per (draft, pick_index, deadline). Never reports
    success without advancing the board or completing the draft. Never leaves
    an in-progress Solo draft stuck at 0:00 after a successful commit.
    """
    t0 = time.perf_counter()
    now = float(now if now is not None else time.time())
    session = session if isinstance(session, dict) else {}

    if not isinstance(room, dict):
        return SoloExpireResult(ok=False, reason="no_room", error="No live draft room.")

    try:
        from live_draft_timer_logic import (
            ensure_full_pick_order,
            live_draft_clear_timer,
            live_draft_reset_timer,
            live_draft_seconds_remaining,
            live_draft_current_slot,
        )
    except ImportError as exc:
        return SoloExpireResult(ok=False, reason="import", error=str(exc))

    ensure_full_pick_order(room)
    status = str(room.get("status") or "").strip().lower()
    if status == "complete":
        return SoloExpireResult(ok=True, complete=True, reason="already_complete", message="Draft already complete.")
    if status == "paused":
        return SoloExpireResult(ok=False, reason="paused", error="Draft is paused.")
    if status != "in_progress":
        return SoloExpireResult(ok=False, reason="not_in_progress", error=f"Status is {status or 'empty'}.")

    if live_draft_seconds_remaining(room) > 0:
        return SoloExpireResult(ok=False, reason="not_expired")

    snapshot = build_solo_expire_snapshot(room)
    guard = _guard_token(snapshot)
    if str(room.get(SOLO_EXPIRE_APPLIED_KEY) or "") == guard:
        # Prior success claimed this pick/deadline — heal a stuck zero display.
        if snapshot.total_configured_picks > 0 and snapshot.committed_picks >= snapshot.total_configured_picks:
            room["status"] = "complete"
            live_draft_clear_timer(room)
            return SoloExpireResult(
                ok=True,
                complete=True,
                reason="already_applied_complete",
                committed_picks=snapshot.committed_picks,
                should_rerun=True,
            )
        live_draft_reset_timer(room)
        slot = live_draft_current_slot(room) or {}
        return SoloExpireResult(
            ok=True,
            advanced=True,
            reason="already_applied_healed",
            message="Timer healed after prior expire.",
            committed_picks=snapshot.committed_picks,
            pick_index=int(room.get("current_pick_index") or 0),
            team_on_clock=str(slot.get("Team") or ""),
            timer_deadline=room.get("timer_deadline"),
            should_rerun=True,
        )

    if snapshot.total_configured_picks > 0 and snapshot.committed_picks >= snapshot.total_configured_picks:
        room["status"] = "complete"
        live_draft_clear_timer(room)
        room[SOLO_EXPIRE_APPLIED_KEY] = guard
        return SoloExpireResult(
            ok=True,
            complete=True,
            reason="board_full",
            message="Draft complete.",
            snapshot_before=snapshot,
            committed_picks=snapshot.committed_picks,
            should_rerun=True,
        )

    if not snapshot.team:
        return SoloExpireResult(
            ok=False,
            reason="no_team",
            error="No team on the clock — pick order may be incomplete.",
            snapshot_before=snapshot,
        )

    t_commit0 = time.perf_counter()
    try:
        from live_draft_autopick import live_draft_auto_pick

        ok, msg = live_draft_auto_pick(room, session)
    except Exception as exc:
        return SoloExpireResult(
            ok=False,
            reason="autopick_exception",
            error=f"{type(exc).__name__}: {exc}",
            snapshot_before=snapshot,
        )
    zero_to_commit_ms = (time.perf_counter() - t_commit0) * 1000.0
    if not ok:
        return SoloExpireResult(
            ok=False,
            reason="autopick_failed",
            error=str(msg or "Auto-pick failed."),
            snapshot_before=snapshot,
            zero_to_commit_ms=zero_to_commit_ms,
        )

    t_timer0 = time.perf_counter()
    board = room.get("draft_board") or []
    committed = len(board) if isinstance(board, list) else 0
    total = snapshot.total_configured_picks
    complete = bool(total > 0 and committed >= total) or str(room.get("status") or "") == "complete"
    if complete:
        room["status"] = "complete"
        live_draft_clear_timer(room)
    else:
        room["status"] = "in_progress"
        # Always stamp a fresh full-duration deadline for the next pick.
        if live_draft_seconds_remaining(room) <= 0 or room.get("timer_deadline") is None:
            live_draft_reset_timer(room)
        # Guarantee full duration from *now* (do not inherit an old deadline).
        live_draft_reset_timer(room)

    room[SOLO_EXPIRE_APPLIED_KEY] = guard
    commit_to_next_timer_ms = (time.perf_counter() - t_timer0) * 1000.0
    slot = live_draft_current_slot(room) or {}
    result = SoloExpireResult(
        ok=True,
        advanced=True,
        complete=complete,
        reason="expired_advanced" if not complete else "expired_completed",
        message=str(msg or ("Draft complete." if complete else "Pick committed.")),
        snapshot_before=snapshot,
        committed_picks=committed,
        pick_index=int(room.get("current_pick_index") or 0),
        team_on_clock=str(slot.get("Team") or ""),
        timer_deadline=float(room["timer_deadline"]) if room.get("timer_deadline") is not None else None,
        zero_to_commit_ms=zero_to_commit_ms,
        commit_to_next_timer_ms=commit_to_next_timer_ms,
        should_rerun=True,
        extras={"total_ms": (time.perf_counter() - t0) * 1000.0, "guard": guard},
    )
    session[SOLO_EXPIRE_PERF_KEY] = {
        "zero_to_commit_ms": zero_to_commit_ms,
        "commit_to_next_timer_ms": commit_to_next_timer_ms,
        "total_ms": result.extras.get("total_ms"),
        "pick_before": snapshot.pick_number,
        "committed_after": committed,
        "complete": complete,
        "at": time.time(),
    }
    session.pop(SOLO_TIMER_WAKE_KEY, None)
    return result


def run_solo_expire_if_needed(
    session: dict[str, Any],
    room: dict[str, Any],
) -> SoloExpireResult | None:
    """Page-owned Solo expire entrypoint. Returns None when Solo clock is not expired."""
    if not is_solo_live_draft(session, room):
        return None
    if not solo_clock_expired(room) and not session.get(SOLO_TIMER_WAKE_KEY):
        return None
    return expire_current_pick_and_advance(room, session=session)
