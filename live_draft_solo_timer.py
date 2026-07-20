"""Solo Live Draft timer — one authoritative expire-and-advance + display snapshot.

Fragment owns expire+countdown so the browser never sits at 0 while the page
rebuilds for 30s. Page script must not also expire the same pick.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

SOLO_EXPIRE_APPLIED_KEY = "_solo_expire_applied"
SOLO_EXPIRE_PERF_KEY = "_solo_expire_perf"
SOLO_TIMER_WAKE_KEY = "_solo_timer_wake"
SOLO_DISPLAY_SNAPSHOT_KEY = "_solo_timer_display_snapshot"
SOLO_FRAGMENT_OWNED_EXPIRE_KEY = "_solo_fragment_owned_expire_ts"
SOLO_DRAFT_REVISION_KEY = "_solo_draft_revision"
VISIBLE_TIMER_COUNT_KEY = "_live_draft_visible_timer_count"


@dataclass
class SoloAuthoritativeSnapshot:
    """Single source of truth for what the Solo UI may display."""

    draft_id: str
    pick_number: int
    pick_index: int
    team: str
    committed_picks: int
    total_picks: int
    timer_deadline: float | None
    timer_duration: int
    latest_committed_pick_id: str
    draft_revision: int
    status: str
    remaining_seconds: int = 0
    updated_at: float = 0.0


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
    display: SoloAuthoritativeSnapshot | None = None
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


def bump_solo_draft_revision(session: dict[str, Any], room: dict[str, Any]) -> int:
    rev = int(session.get(SOLO_DRAFT_REVISION_KEY) or room.get("draft_revision") or 0) + 1
    session[SOLO_DRAFT_REVISION_KEY] = rev
    room["draft_revision"] = rev
    return rev


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


def install_solo_display_snapshot(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    now: float | None = None,
) -> SoloAuthoritativeSnapshot:
    """Publish the only snapshot Solo UI surfaces may render."""
    from live_draft_timer_logic import (
        ensure_full_pick_order,
        live_draft_current_slot,
        live_draft_seconds_remaining,
        live_draft_timer_deadline,
    )

    ensure_full_pick_order(room)
    now = float(now if now is not None else time.time())
    cfg = dict(room.get("config") or {})
    try:
        from live_draft_safe_mode import total_expected_picks

        total = int(total_expected_picks(room) or 0)
    except ImportError:
        total = 0
    board = room.get("draft_board") if isinstance(room.get("draft_board"), list) else []
    committed = len(board)
    latest_id = ""
    if board:
        last = board[-1] if isinstance(board[-1], dict) else {}
        latest_id = str(last.get("playerID") or last.get("Pick") or committed).strip()
    slot = live_draft_current_slot(room) or {}
    idx = int(room.get("current_pick_index") or 0)
    duration = max(1, int(cfg.get("timer_seconds") or 60))
    deadline = live_draft_timer_deadline(room)
    status = str(room.get("status") or "")
    remaining = 0 if status == "complete" else int(live_draft_seconds_remaining(room))
    rev = int(session.get(SOLO_DRAFT_REVISION_KEY) or room.get("draft_revision") or 0)
    snap = SoloAuthoritativeSnapshot(
        draft_id=str(room.get("draft_room_id") or room.get("draft_id") or "solo").strip(),
        pick_number=int(slot.get("Pick") or (idx + 1)),
        pick_index=idx,
        team=str(slot.get("Team") or "").strip(),
        committed_picks=committed,
        total_picks=total,
        timer_deadline=float(deadline) if deadline is not None else None,
        timer_duration=duration,
        latest_committed_pick_id=latest_id,
        draft_revision=rev,
        status=status,
        remaining_seconds=remaining,
        updated_at=now,
    )
    session[SOLO_DISPLAY_SNAPSHOT_KEY] = asdict(snap)
    room["_solo_display_snapshot"] = asdict(snap)
    return snap


def get_solo_display_snapshot(session: dict[str, Any], room: dict[str, Any] | None = None) -> dict[str, Any]:
    snap = session.get(SOLO_DISPLAY_SNAPSHOT_KEY)
    if isinstance(snap, dict) and snap.get("draft_id"):
        return dict(snap)
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if isinstance(live, dict):
        return asdict(install_solo_display_snapshot(session, live))
    return {}


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
    request_full_rerun: bool = False,
) -> SoloExpireResult:
    """Atomically expire the on-clock Solo pick and install the next pick+timer.

    Deadline for the next pick is always ``transition_time + full_duration`` —
    never derived from the previous expired deadline.
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
        display = install_solo_display_snapshot(session, room, now=now)
        return SoloExpireResult(
            ok=True, complete=True, reason="already_complete", message="Draft already complete.", display=display
        )
    if status == "paused":
        return SoloExpireResult(ok=False, reason="paused", error="Draft is paused.")
    if status != "in_progress":
        return SoloExpireResult(ok=False, reason="not_in_progress", error=f"Status is {status or 'empty'}.")

    if live_draft_seconds_remaining(room) > 0:
        display = install_solo_display_snapshot(session, room, now=now)
        return SoloExpireResult(ok=False, reason="not_expired", display=display)

    snapshot = build_solo_expire_snapshot(room)
    guard = _guard_token(snapshot)
    if str(room.get(SOLO_EXPIRE_APPLIED_KEY) or "") == guard:
        if snapshot.total_configured_picks > 0 and snapshot.committed_picks >= snapshot.total_configured_picks:
            room["status"] = "complete"
            live_draft_clear_timer(room)
            display = install_solo_display_snapshot(session, room, now=now)
            return SoloExpireResult(
                ok=True,
                complete=True,
                reason="already_applied_complete",
                committed_picks=snapshot.committed_picks,
                display=display,
                should_rerun=False,
            )
        # Heal stuck zero without double-picking: stamp a fresh deadline from *now*.
        transition = time.time()
        live_draft_reset_timer(room)
        room["timer_started_at"] = transition
        room["timer_deadline"] = transition + snapshot.timer_seconds
        display = install_solo_display_snapshot(session, room, now=transition)
        return SoloExpireResult(
            ok=True,
            advanced=True,
            reason="already_applied_healed",
            message="Timer healed after prior expire.",
            committed_picks=snapshot.committed_picks,
            pick_index=int(room.get("current_pick_index") or 0),
            team_on_clock=display.team,
            timer_deadline=display.timer_deadline,
            display=display,
            should_rerun=False,
        )

    if snapshot.total_configured_picks > 0 and snapshot.committed_picks >= snapshot.total_configured_picks:
        room["status"] = "complete"
        live_draft_clear_timer(room)
        room[SOLO_EXPIRE_APPLIED_KEY] = guard
        bump_solo_draft_revision(session, room)
        display = install_solo_display_snapshot(session, room, now=now)
        return SoloExpireResult(
            ok=True,
            complete=True,
            reason="board_full",
            message="Draft complete.",
            snapshot_before=snapshot,
            committed_picks=snapshot.committed_picks,
            display=display,
            should_rerun=bool(request_full_rerun),
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

    # Transition time = after commit. Next deadline must not inherit the expired clock.
    t_timer0 = time.perf_counter()
    transition = time.time()
    board = room.get("draft_board") or []
    committed = len(board) if isinstance(board, list) else 0
    total = snapshot.total_configured_picks
    complete = bool(total > 0 and committed >= total) or str(room.get("status") or "") == "complete"
    if complete:
        room["status"] = "complete"
        live_draft_clear_timer(room)
    else:
        room["status"] = "in_progress"
        duration = snapshot.timer_seconds
        room["timer_started_at"] = transition
        room["timer_deadline"] = transition + duration
        room["timer_handled_index"] = -1
        # Drop any stale token so the next pick can expire cleanly.
        room.pop("last_processed_expiration_token", None)

    room[SOLO_EXPIRE_APPLIED_KEY] = guard
    bump_solo_draft_revision(session, room)
    commit_to_next_timer_ms = (time.perf_counter() - t_timer0) * 1000.0
    display = install_solo_display_snapshot(session, room, now=transition)
    try:
        from live_draft_canonical_snapshot import (
            install_canonical_live_draft_snapshot,
            note_pick_transition,
        )

        snap = install_canonical_live_draft_snapshot(session, room, state_source="solo_expire")
        note_pick_transition(
            session,
            event="solo_expire_advanced",
            draft_id=str(snap.get("draft_id") or ""),
            pick_index=int(snap.get("current_pick_index") or 0),
            revision=int(snap.get("revision") or 0),
            team_on_clock=str(snap.get("team_on_clock") or ""),
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            extra={
                "zero_to_commit_ms": zero_to_commit_ms,
                "commit_to_next_timer_ms": commit_to_next_timer_ms,
                "committed": committed,
            },
        )
    except Exception:
        pass
    # Queue / rec caches already handled by finalize inside auto_pick; keep a
    # best-effort prune for older auto_pick paths that skipped finalize.
    try:
        from draft_state import remove_drafted_player_from_active_queues

        if board and isinstance(board[-1], dict):
            last = board[-1]
            pname = str(last.get("fullName") or last.get("Player") or "").strip()
            pid = str(last.get("playerID") or "").strip()
            if pname:
                remove_drafted_player_from_active_queues(session, pname)
            if pid and pid != pname:
                remove_drafted_player_from_active_queues(session, pid)
    except Exception:
        pass

    result = SoloExpireResult(
        ok=True,
        advanced=True,
        complete=complete,
        reason="expired_advanced" if not complete else "expired_completed",
        message=str(msg or ("Draft complete." if complete else "Pick committed.")),
        snapshot_before=snapshot,
        display=display,
        committed_picks=committed,
        pick_index=display.pick_index,
        team_on_clock=display.team,
        timer_deadline=display.timer_deadline,
        zero_to_commit_ms=zero_to_commit_ms,
        commit_to_next_timer_ms=commit_to_next_timer_ms,
        should_rerun=bool(request_full_rerun),
        extras={"total_ms": (time.perf_counter() - t0) * 1000.0, "guard": guard, "transition": transition},
    )
    session[SOLO_EXPIRE_PERF_KEY] = {
        "zero_to_commit_ms": zero_to_commit_ms,
        "commit_to_next_timer_ms": commit_to_next_timer_ms,
        "total_ms": result.extras.get("total_ms"),
        "pick_before": snapshot.pick_number,
        "committed_after": committed,
        "team_after": display.team,
        "complete": complete,
        "at": transition,
    }
    session.pop(SOLO_TIMER_WAKE_KEY, None)
    return result


def run_solo_expire_if_needed(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    request_full_rerun: bool = False,
) -> SoloExpireResult | None:
    """Expire entrypoint. Prefer fragment ownership; page uses request_full_rerun=False."""
    if not is_solo_live_draft(session, room):
        return None
    # Fragment already handled expire within the last 2s — do not double-advance.
    owned_at = float(session.get(SOLO_FRAGMENT_OWNED_EXPIRE_KEY) or 0.0)
    if owned_at and (time.time() - owned_at) < 2.0 and not session.get(SOLO_TIMER_WAKE_KEY):
        if not solo_clock_expired(room):
            return None
    if not solo_clock_expired(room) and not session.get(SOLO_TIMER_WAKE_KEY):
        return None
    return expire_current_pick_and_advance(
        room, session=session, request_full_rerun=request_full_rerun
    )


def note_solo_fragment_owned_expire(session: dict[str, Any]) -> None:
    session[SOLO_FRAGMENT_OWNED_EXPIRE_KEY] = time.time()


def record_visible_timer_count(session: dict[str, Any], count: int) -> None:
    session[VISIBLE_TIMER_COUNT_KEY] = int(count)
