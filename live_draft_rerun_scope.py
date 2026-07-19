"""Live Draft rerun scope — skip expensive work on timer/queue ticks.

IMPORTANT: Never use a page-level ``st.stop()`` for queue mutations. That aborted
the first active-draft render after Solo create (queue-only shell). Queue ticks
only skip expensive recommendation recompute; the full page always paints.
"""

from __future__ import annotations

from typing import Any

TIMER_TICK_KEY = "_live_draft_timer_fragment_tick"
QUEUE_TICK_KEY = "_live_draft_queue_only_tick"
# Legacy key — must never drive a page-level st.stop(). Cleared on every active paint.
QUEUE_FAST_PAINT_KEY = "_live_draft_queue_fast_paint"
PICK_TICK_KEY = "_live_draft_optimistic_pick_tick"
EXPENSIVE_WORK_KEY = "_live_draft_force_expensive_recompute"


def mark_live_draft_timer_tick(session: dict[str, Any]) -> None:
    session[TIMER_TICK_KEY] = True
    session.pop(QUEUE_TICK_KEY, None)
    session.pop(PICK_TICK_KEY, None)
    session.pop(QUEUE_FAST_PAINT_KEY, None)


def mark_live_draft_queue_tick(session: dict[str, Any]) -> None:
    """Queue add/remove/reorder — skip expensive recs once; never abort the page."""
    session[QUEUE_TICK_KEY] = True
    # Do NOT set QUEUE_FAST_PAINT_KEY — that previously caused st.stop() after queue.
    session.pop(QUEUE_FAST_PAINT_KEY, None)
    session.pop(TIMER_TICK_KEY, None)
    session.pop(PICK_TICK_KEY, None)
    session.pop(EXPENSIVE_WORK_KEY, None)


def clear_live_draft_queue_fast_paint(session: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
    """Clear any leftover fast-paint flag. Returns diagnostic of what was cleared."""
    had = bool(session.pop(QUEUE_FAST_PAINT_KEY, None))
    session.pop("_live_draft_skip_queue_flush_this_run", None)
    return {"cleared": had, "reason": str(reason or "")}


def consume_live_draft_queue_fast_paint(session: dict[str, Any]) -> bool:
    """Deprecated: always False. Legacy callers must not abort the page.

    Clears any leftover flag for diagnostics but never authorizes st.stop().
    """
    had = bool(session.pop(QUEUE_FAST_PAINT_KEY, None))
    session.pop(QUEUE_TICK_KEY, None)
    if had:
        session["_live_draft_queue_fast_paint_ignored"] = {
            "cleared": True,
            "stop_authorized": False,
            "note": "page-level queue fast-paint st.stop removed",
        }
    return False


def mark_live_draft_optimistic_pick_tick(session: dict[str, Any]) -> None:
    """After optimistic local pick — paint board/timer; keep patched recs until Phase 4 refresh."""
    session[PICK_TICK_KEY] = True
    session.pop(TIMER_TICK_KEY, None)
    session.pop(QUEUE_TICK_KEY, None)
    session.pop(QUEUE_FAST_PAINT_KEY, None)
    session.pop(EXPENSIVE_WORK_KEY, None)


def clear_live_draft_timer_tick(session: dict[str, Any]) -> None:
    session.pop(TIMER_TICK_KEY, None)


def clear_live_draft_queue_tick(session: dict[str, Any]) -> None:
    session.pop(QUEUE_TICK_KEY, None)
    session.pop(QUEUE_FAST_PAINT_KEY, None)


def force_live_draft_expensive_recompute(session: dict[str, Any]) -> None:
    session[EXPENSIVE_WORK_KEY] = True
    session.pop(TIMER_TICK_KEY, None)
    session.pop(QUEUE_TICK_KEY, None)
    session.pop(PICK_TICK_KEY, None)
    session.pop(QUEUE_FAST_PAINT_KEY, None)


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
