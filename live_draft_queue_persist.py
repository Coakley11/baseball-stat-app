"""Deferred workspace persistence for draft queue mutations (Live Draft real-time Phase 1).

Queue add/remove/reorder must update session state immediately without
``force_save_baseball_state`` on the critical path. Durable disk/cloud flush
runs on debounce, Live Draft page-end, or page leave.
"""

from __future__ import annotations

import time
from typing import Any

DRAFT_QUEUE_PERSIST_DIRTY_KEY = "_draft_queue_persist_dirty"
DRAFT_QUEUE_PERSIST_DIRTY_TS_KEY = "_draft_queue_persist_dirty_ts"
DRAFT_QUEUE_AUTOSAVE_SEC = 3.0


def mark_draft_queue_persist_dirty(session: dict[str, Any]) -> None:
    """Mark that queue/watchlist durable save is needed (no I/O)."""
    session[DRAFT_QUEUE_PERSIST_DIRTY_KEY] = True
    session[DRAFT_QUEUE_PERSIST_DIRTY_TS_KEY] = time.time()
    try:
        from draft_state import mark_draft_pending_sync

        mark_draft_pending_sync(session)
    except ImportError:
        pass


def clear_draft_queue_persist_dirty(session: dict[str, Any]) -> None:
    session.pop(DRAFT_QUEUE_PERSIST_DIRTY_KEY, None)
    session.pop(DRAFT_QUEUE_PERSIST_DIRTY_TS_KEY, None)


def is_draft_queue_persist_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(DRAFT_QUEUE_PERSIST_DIRTY_KEY))


def note_queue_mutation(session: dict[str, Any], *, reason: str = "queue_change") -> None:
    """Call after session/canonical queue mutate — never force-saves."""
    del reason  # retained for call-site diagnostics / future tracing
    mark_draft_queue_persist_dirty(session)


def flush_draft_queue_persist(
    st: Any,
    session: dict[str, Any],
    *,
    reason: str,
) -> bool:
    """Write durable workspace state for deferred queue edits."""
    force = reason in ("draft_queue_force", "page_change", "draft_queue_debounced_autosave", "live_draft_page_end")
    if not is_draft_queue_persist_dirty(session) and not force:
        return False
    if not is_draft_queue_persist_dirty(session):
        try:
            from draft_state import DRAFT_PENDING_SYNC_KEY

            if not session.get(DRAFT_PENDING_SYNC_KEY):
                return False
        except ImportError:
            return False
    try:
        from draft_state import flush_draft_workflow_edits

        # Deferred path only — flush_draft_workflow_edits may force_save when st is set.
        flushed = flush_draft_workflow_edits(session, st_obj=st, reason=reason)
    except ImportError:
        flushed = False
        try:
            from baseball_persistent_state import force_save_baseball_state

            force_save_baseball_state(st, reason="draft_edit")
            flushed = True
        except Exception:
            pass
    clear_draft_queue_persist_dirty(session)
    return bool(flushed)


def maybe_flush_deferred_draft_queue_autosave(st: Any, session: dict[str, Any]) -> bool:
    """Debounced background flush while the user keeps editing the queue."""
    if not is_draft_queue_persist_dirty(session):
        return False
    ts = float(session.get(DRAFT_QUEUE_PERSIST_DIRTY_TS_KEY) or 0.0)
    if ts <= 0 or (time.time() - ts) < DRAFT_QUEUE_AUTOSAVE_SEC:
        return False
    return flush_draft_queue_persist(st, session, reason="draft_queue_debounced_autosave")
