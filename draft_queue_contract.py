"""The global working draft queue: when committed picks consume it (one contract app-wide).

The queue (session ``draft_queue``, saved with the workspace) belongs to the user, not to a
draft, board or league. A queued player leaves it only when a pick is committed in the *active*
draft (the Draft Room Simulator board, or the Live Draft room while it is the active draft) — not
because the player appears on an old, finished or unrelated board, and not because the queue was
viewed.

Each committed pick is applied once (ledger keyed by draft and pick), so reruns and duplicate
events cannot remove twice. A pick that disappears from the same draft (Undo) puts the player
back at their old position. A reset or a new board starts a new draft, so it neither restores nor
clears anything.
"""

from __future__ import annotations

from typing import Any

LEDGER_KEY = "_draft_queue_consumed"  # {draft_source: {pick_key: {"player": str, "index": int|None}}}
BOARD_EPOCH_KEY = "_simulator_board_epoch"
_MAX_SOURCES = 8


def start_new_simulator_draft(session: dict[str, Any]) -> None:
    """A reset / new / imported board is a different draft for consumption purposes."""
    session[BOARD_EPOCH_KEY] = int(session.get(BOARD_EPOCH_KEY) or 0) + 1


def _active_draft_picks(session: dict[str, Any]) -> tuple[str, list[tuple[int, str]]]:
    try:
        from draft_room_state import (
            ACTIVE_DRAFT_SOURCE_LIVE,
            DRAFT_ROOM_TABLE_KEY,
            _player_cell_filled,
            coerce_board_table,
            resolve_active_draft_source,
        )
    except ImportError:
        return "", []
    if resolve_active_draft_source(session) == ACTIVE_DRAFT_SOURCE_LIVE:
        room = session.get("live_draft_room")
        if not isinstance(room, dict):
            return "", []
        rid = str(room.get("draft_room_id") or room.get("draft_id") or session.get("active_shared_draft_room_code") or "")
        picks = []
        for entry in room.get("draft_board") or []:
            if isinstance(entry, dict):
                name = str(entry.get("fullName") or entry.get("Player") or "").strip()
                try:
                    pick = int(entry.get("Pick") or entry.get("pick") or 0)
                except (TypeError, ValueError):
                    pick = 0
                if name:
                    picks.append((pick, name))
        return f"live:{rid.strip().upper()}", picks
    df = coerce_board_table(session.get(DRAFT_ROOM_TABLE_KEY))
    picks = []
    if not df.empty and "Player" in df.columns:
        for _, row in df.iterrows():
            if _player_cell_filled(row.get("Player")):
                try:
                    pick = int(row.get("Pick") or 0)
                except (TypeError, ValueError):
                    pick = 0
                picks.append((pick, str(row.get("Player")).strip()))
    return f"sim:{int(session.get(BOARD_EPOCH_KEY) or 0)}", picks


def _ledger(session: dict[str, Any], source: str) -> dict[str, Any]:
    ledger = session.get(LEDGER_KEY)
    if not isinstance(ledger, dict):
        ledger = {}
    entry = ledger.get(source)
    if not isinstance(entry, dict):
        entry = {}
        ledger[source] = entry
        for stale in list(ledger)[:-_MAX_SOURCES]:
            ledger.pop(stale, None)
    session[LEDGER_KEY] = ledger
    return entry


def sync_queue_with_active_draft(session: dict[str, Any]) -> list[str]:
    """Apply newly committed picks of the active draft (and undone ones); return the queue."""
    from draft_state import DRAFT_QUEUE_KEY, _normalize_player_list, sync_draft_queue

    queue = _normalize_player_list(session.get(DRAFT_QUEUE_KEY))
    source, picks = _active_draft_picks(session)
    if not source:
        return queue
    entry = _ledger(session, source)
    current = {f"{pick}|{name.lower()}" for pick, name in picks}
    q = list(queue)
    changed = False
    # Undo: a recorded pick of this draft is gone — put the player back where they were.
    for key in [k for k in entry if k not in current]:
        rec = entry.pop(key) or {}
        player, index = str(rec.get("player") or ""), rec.get("index")
        if index is not None and player and player.lower() not in {p.lower() for p in q}:
            q.insert(min(int(index), len(q)), player)
            changed = True
    for pick, name in picks:
        key = f"{pick}|{name.lower()}"
        if key in entry:
            continue
        idx = next((i for i, p in enumerate(q) if p.lower() == name.lower()), None)
        entry[key] = {"player": q[idx] if idx is not None else name, "index": idx}
        if idx is not None:
            q.pop(idx)
            changed = True
    if changed:
        sync_draft_queue(session, q, reason="queue_consumed_by_committed_pick")
    return q


def adopt_board_without_consuming(session: dict[str, Any]) -> None:
    """Treat the current simulator board as already applied (e.g. an imported draft board)."""
    start_new_simulator_draft(session)
    source, picks = _active_draft_picks(session)
    if source:
        entry = _ledger(session, source)
        for pick, name in picks:
            entry.setdefault(f"{pick}|{name.lower()}", {"player": name, "index": None})
