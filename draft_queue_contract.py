"""The global personal draft queue, and how each draft sees it (one contract app-wide).

The queue (session ``draft_queue``, saved with the account's workspace) belongs to the user, not to
a draft, board, room or league. Picks never delete from it (owner decision 2026-11-06): availability
is evaluated per draft. In the active draft (the Draft Room Simulator board, or the Live Draft room
while it is the active draft) a queued player taken in that draft is shown as "drafted in this
draft" and skipped by queue-based picking; the same player stays queued for every other draft (a
later mock, another league, another person's Shared Draft). Only the user removes players: one at
a time, or "Remove players drafted in this draft".

Privacy: a Shared Draft room never reads or stores anyone's queue (draft_room_participant_state);
sign-out or an account change drops this session's copy (clear_queue_for_account_change).

A reset or a new board starts a new draft (start_new_simulator_draft), so its drafted set starts
empty; imported boards are the active draft's picks like any other.
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


def drafted_in_active_draft(session: dict[str, Any]) -> set[str]:
    """Lower-case names of players picked in the active draft (empty when there is none)."""
    _source, picks = _active_draft_picks(session)
    return {name.strip().lower() for _pick, name in picks if name.strip()}


def split_queue_for_active_draft(session: dict[str, Any], queue: list[str] | None = None) -> tuple[list[str], list[str]]:
    """(available, drafted in this draft) in queue order. Never changes the queue."""
    from draft_state import DRAFT_QUEUE_KEY, _normalize_player_list

    q = _normalize_player_list(queue if queue is not None else session.get(DRAFT_QUEUE_KEY))
    taken = drafted_in_active_draft(session)
    available = [p for p in q if p.strip().lower() not in taken]
    drafted = [p for p in q if p.strip().lower() in taken]
    return available, drafted


def sync_queue_with_active_draft(session: dict[str, Any]) -> list[str]:
    """The queue as stored (picks no longer delete from it); kept for its callers."""
    from draft_state import DRAFT_QUEUE_KEY, _normalize_player_list

    return _normalize_player_list(session.get(DRAFT_QUEUE_KEY))


def remove_players_drafted_in_active_draft(session: dict[str, Any]) -> list[str]:
    """The user's explicit "Remove players drafted in this draft": returns the removed names."""
    from draft_state import sync_draft_queue

    available, drafted = split_queue_for_active_draft(session)
    if drafted:
        sync_draft_queue(session, available, reason="user_removed_players_drafted_in_this_draft")
    return drafted


def full_order_after_reorder(session: dict[str, Any], reordered_available: list[str]) -> list[str]:
    """A reorder of the available players, with this draft's drafted players kept after them, so a
    drag over the visible rows never drops queued players (reorder_user_draft_queue saves a subset
    as the whole queue)."""
    _available, drafted = split_queue_for_active_draft(session)
    seen = {p.lower() for p in reordered_available}
    return list(reordered_available) + [p for p in drafted if p.lower() not in seen]


def adopt_board_without_consuming(session: dict[str, Any]) -> None:
    """Treat the current simulator board as already applied (e.g. an imported draft board)."""
    start_new_simulator_draft(session)
    source, picks = _active_draft_picks(session)
    if source:
        entry = _ledger(session, source)
        for pick, name in picks:
            entry.setdefault(f"{pick}|{name.lower()}", {"player": name, "index": None})


def clear_queue_for_account_change(session: dict[str, Any]) -> None:
    """Sign-out / different account on this browser: drop this session's copy of the queue.

    The queue is saved with the previous account's workspace, so nothing is lost; the next
    account's own queue loads from its workspace. Never called for room joins or page changes.
    """
    for key in ("draft_queue", LEDGER_KEY, "_queue_player_meta", "_draft_queue_revision",
                "draft_queue_plan", "draft_queue_adaptive", "_draft_strategy_loaded",
                "draft_strategy_approach", "_draft_strategy_save_pending",
                "_draft_strategy_work", "_draft_strategy_open_id", "_draft_strategy_open_pick",
                "_draft_strategy_open_next"):
        session.pop(key, None)
    state = session.get("draft_state")
    if isinstance(state, dict):
        state.pop("queue", None)
