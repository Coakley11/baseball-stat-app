"""Temporary pause on deleting saved Draft Strategies (Slice 0 compatibility release).

Until Slice 2 introduces recoverable deletion (a 30-day "Recently deleted" list and a separately
confirmed permanent delete), no saved strategy may be removed: the page shows a disabled Delete
button with ``PAUSED_MESSAGE``, and every layer below it refuses as well (the strategy store, both
storage backends and the Supabase saved-item call), so nothing can remove one by another route.
Viewing, editing and saving strategies are unaffected. Slice 2 lifts the pause.
"""

from __future__ import annotations

DELETION_PAUSED = True
PAUSED_MESSAGE = "Deleting strategies is temporarily paused while recoverable deletion is being introduced."
STRATEGY_ITEM_TYPES = frozenset({"draft_strategy"})


class StrategyDeletionPaused(RuntimeError):
    """Raised by any attempt to remove a saved Draft Strategy while deletion is paused."""


def deletion_allowed() -> bool:
    return not DELETION_PAUSED


def assert_strategy_deletion_allowed(item_type: str = "draft_strategy") -> None:
    """Refuse removal of a strategy row while the pause is on (other item types are unaffected)."""
    if DELETION_PAUSED and str(item_type or "").strip() in STRATEGY_ITEM_TYPES:
        raise StrategyDeletionPaused(PAUSED_MESSAGE)
