"""Live Draft rerun scope — skip expensive work on timer-only fragment ticks."""

from __future__ import annotations

from typing import Any

TIMER_TICK_KEY = "_live_draft_timer_fragment_tick"
EXPENSIVE_WORK_KEY = "_live_draft_force_expensive_recompute"


def mark_live_draft_timer_tick(session: dict[str, Any]) -> None:
    session[TIMER_TICK_KEY] = True


def clear_live_draft_timer_tick(session: dict[str, Any]) -> None:
    session.pop(TIMER_TICK_KEY, None)


def force_live_draft_expensive_recompute(session: dict[str, Any]) -> None:
    session[EXPENSIVE_WORK_KEY] = True
    session.pop(TIMER_TICK_KEY, None)


def live_draft_expensive_recompute_required(session: dict[str, Any]) -> bool:
    """True when recommendations/scoring/category analysis should run."""
    if session.get(EXPENSIVE_WORK_KEY):
        session.pop(EXPENSIVE_WORK_KEY, None)
        session.pop(TIMER_TICK_KEY, None)
        return True
    if session.get(TIMER_TICK_KEY):
        return False
    return True


def live_draft_should_skip_recommendations(session: dict[str, Any], room: dict[str, Any] | None) -> bool:
    """Combine timer tick guard with existing defer flags."""
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
