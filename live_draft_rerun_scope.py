"""Live Draft rerun scope — skip expensive work on timer-only and queue-only ticks."""

from __future__ import annotations

from typing import Any

TIMER_TICK_KEY = "_live_draft_timer_fragment_tick"
QUEUE_TICK_KEY = "_live_draft_queue_only_tick"
PICK_TICK_KEY = "_live_draft_optimistic_pick_tick"
EXPENSIVE_WORK_KEY = "_live_draft_force_expensive_recompute"


def mark_live_draft_timer_tick(session: dict[str, Any]) -> None:
    session[TIMER_TICK_KEY] = True
    session.pop(QUEUE_TICK_KEY, None)
    session.pop(PICK_TICK_KEY, None)


def mark_live_draft_queue_tick(session: dict[str, Any]) -> None:
    """Queue add/remove/reorder — paint queue only; keep cached recommendations."""
    session[QUEUE_TICK_KEY] = True
    session.pop(TIMER_TICK_KEY, None)
    session.pop(PICK_TICK_KEY, None)
    # Never force expensive recompute for queue-only mutations.
    session.pop(EXPENSIVE_WORK_KEY, None)


def mark_live_draft_optimistic_pick_tick(session: dict[str, Any]) -> None:
    """After optimistic local pick — paint board/timer; keep patched recs until Phase 4 refresh."""
    session[PICK_TICK_KEY] = True
    session.pop(TIMER_TICK_KEY, None)
    session.pop(QUEUE_TICK_KEY, None)
    session.pop(EXPENSIVE_WORK_KEY, None)


def clear_live_draft_timer_tick(session: dict[str, Any]) -> None:
    session.pop(TIMER_TICK_KEY, None)


def clear_live_draft_queue_tick(session: dict[str, Any]) -> None:
    session.pop(QUEUE_TICK_KEY, None)


def force_live_draft_expensive_recompute(session: dict[str, Any]) -> None:
    session[EXPENSIVE_WORK_KEY] = True
    session.pop(TIMER_TICK_KEY, None)
    session.pop(QUEUE_TICK_KEY, None)
    session.pop(PICK_TICK_KEY, None)


def live_draft_expensive_recompute_required(session: dict[str, Any]) -> bool:
    """True when recommendations/scoring/category analysis should run."""
    if session.get(EXPENSIVE_WORK_KEY):
        session.pop(EXPENSIVE_WORK_KEY, None)
        session.pop(TIMER_TICK_KEY, None)
        session.pop(QUEUE_TICK_KEY, None)
        session.pop(PICK_TICK_KEY, None)
        return True
    if session.get(TIMER_TICK_KEY) or session.get(QUEUE_TICK_KEY) or session.get(PICK_TICK_KEY):
        # One-shot: timer/queue/optimistic-pick ticks skip expensive work once, then clear.
        session.pop(TIMER_TICK_KEY, None)
        session.pop(QUEUE_TICK_KEY, None)
        session.pop(PICK_TICK_KEY, None)
        return False
    # After a transactional pick, the next normal paint refreshes analytics.
    if session.pop("_live_draft_recs_pending_after_pick", None):
        return True
    return True


def live_draft_should_skip_recommendations(session: dict[str, Any], room: dict[str, Any] | None) -> bool:
    """Combine timer/queue tick guards with existing defer flags."""
    if not live_draft_expensive_recompute_required(session):
        return True
    try:
        from live_draft_start_progress import is_live_draft_start_in_flight

        if is_live_draft_start_in_flight(session):
            return True
    except ImportError:
        pass
    try:
        from live_draft_setup_persist import should_skip_live_draft_recommendations

        if should_skip_live_draft_recommendations(session, room or {}):
            return True
    except ImportError:
        pass
    return False
