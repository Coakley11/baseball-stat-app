"""Deferred durable persistence for Live Draft picks (Phase 2 optimistic path).

Local board/roster/timer mutation is authoritative for display. Workspace save,
shared-room sync, and activity logging run after paint via dirty-flag flush.
"""

from __future__ import annotations

import time
from typing import Any

PICK_PERSIST_DIRTY_KEY = "_live_draft_pick_persist_dirty"
PICK_PERSIST_DIRTY_TS_KEY = "_live_draft_pick_persist_dirty_ts"
PICK_PERSIST_PAYLOAD_KEY = "_live_draft_pick_persist_payload"
PICK_SYNC_WARNING_KEY = "_live_draft_pick_sync_warning"
PICK_APPLIED_GUARD_KEY = "_live_draft_applied_pick_guard"
PICK_AUTOSAVE_SEC = 1.5


def pick_guard_token(room: dict[str, Any], *, player_id: str = "", player_name: str = "") -> str:
    room_id = str(room.get("draft_room_id") or "")
    idx = int(room.get("current_pick_index") or 0)
    pid = str(player_id or "").strip() or str(player_name or "").strip().lower()
    return f"{room_id}:{idx}:{pid}"


def already_applied_pick_guard(session: dict[str, Any], token: str) -> bool:
    return bool(token) and str(session.get(PICK_APPLIED_GUARD_KEY) or "") == token


def mark_applied_pick_guard(session: dict[str, Any], token: str) -> None:
    if token:
        session[PICK_APPLIED_GUARD_KEY] = token


def mark_pick_persist_dirty(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    source: str,
    expected_revision: int | None = None,
) -> None:
    session[PICK_PERSIST_DIRTY_KEY] = True
    session[PICK_PERSIST_DIRTY_TS_KEY] = time.time()
    session[PICK_PERSIST_PAYLOAD_KEY] = {
        "source": str(source or "manual_pick"),
        "expected_revision": expected_revision,
        "board_size": len(room.get("draft_board") or []),
        "current_pick_index": int(room.get("current_pick_index") or 0),
        "draft_room_id": str(room.get("draft_room_id") or ""),
    }


def clear_pick_persist_dirty(session: dict[str, Any]) -> None:
    session.pop(PICK_PERSIST_DIRTY_KEY, None)
    session.pop(PICK_PERSIST_DIRTY_TS_KEY, None)
    session.pop(PICK_PERSIST_PAYLOAD_KEY, None)


def is_pick_persist_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(PICK_PERSIST_DIRTY_KEY))


def set_pick_sync_warning(session: dict[str, Any], message: str) -> None:
    msg = str(message or "").strip()
    if msg:
        session[PICK_SYNC_WARNING_KEY] = msg


def consume_pick_sync_warning(session: dict[str, Any]) -> str:
    return str(session.pop(PICK_SYNC_WARNING_KEY, "") or "").strip()


def flush_deferred_pick_persist(session: dict[str, Any], *, st_obj: Any = None) -> bool:
    """Run durable pick persistence after local optimistic commit."""
    if not is_pick_persist_dirty(session):
        return False
    payload = dict(session.get(PICK_PERSIST_PAYLOAD_KEY) or {})
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        room = session.get(LIVE_DRAFT_ROOM_KEY)
    except ImportError:
        room = session.get("live_draft_room")
    if not isinstance(room, dict):
        clear_pick_persist_dirty(session)
        return False

    source = str(payload.get("source") or "deferred_pick")
    expected_revision = payload.get("expected_revision")
    try:
        expected_revision = int(expected_revision) if expected_revision is not None else None
    except (TypeError, ValueError):
        expected_revision = None

    try:
        from live_draft_pick_commit import persist_applied_pick

        result = persist_applied_pick(
            session,
            room,
            source=source,
            expected_revision=expected_revision,
            board_size_before=int(payload.get("board_size") or len(room.get("draft_board") or [])),
            idx_before=max(0, int(payload.get("current_pick_index") or 0) - 1),
            fast_path=False,
            allow_shared_failure=True,
        )
        if not result.ok:
            set_pick_sync_warning(session, result.message or "Pick sync failed — retrying.")
            # Keep dirty so debounce / page-end can retry; do not roll back local room.
            session[PICK_PERSIST_DIRTY_TS_KEY] = time.time()
            return False
    except Exception as exc:
        set_pick_sync_warning(session, f"Pick sync failed — retrying ({exc}).")
        session[PICK_PERSIST_DIRTY_TS_KEY] = time.time()
        return False

    # Durable workspace save (off the interactive pick path).
    if st_obj is not None:
        try:
            from baseball_persistent_state import force_save_baseball_state

            force_save_baseball_state(st_obj, reason=f"draft_pick_deferred:{source}")
        except Exception:
            set_pick_sync_warning(session, "Workspace save pending — pick is already on the board.")
            session[PICK_PERSIST_DIRTY_TS_KEY] = time.time()
            return False

    clear_pick_persist_dirty(session)
    session.pop(PICK_SYNC_WARNING_KEY, None)
    return True


def maybe_flush_deferred_pick_persist(st: Any, session: dict[str, Any]) -> bool:
    if not is_pick_persist_dirty(session):
        return False
    ts = float(session.get(PICK_PERSIST_DIRTY_TS_KEY) or 0.0)
    if ts <= 0 or (time.time() - ts) < PICK_AUTOSAVE_SEC:
        return False
    return flush_deferred_pick_persist(session, st_obj=st)
