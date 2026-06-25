"""Pure live draft pick helpers — no Streamlit imports or side effects."""

from __future__ import annotations

from typing import Any

from live_draft_timer_logic import live_draft_current_slot, live_draft_reset_timer


def live_draft_bump_sync_revision(room: dict[str, Any], event: str = "pick") -> None:
    import time

    meta = room.setdefault("meta", {})
    sync = meta.setdefault("sync", {"revision": 0, "storage_backend": "session_state"})
    sync["revision"] = int(sync.get("revision", 0)) + 1
    sync["last_event"] = event
    sync["updated_at"] = time.time()


def live_draft_make_pick(room: dict[str, Any], player_row: dict[str, Any], verdict: str = "Manual pick") -> tuple[bool, str]:
    slot = live_draft_current_slot(room)
    if slot is None:
        return False, "Draft is already complete."
    team = slot["Team"]
    pid = str(player_row.get("playerID", ""))
    if pid in set(room.get("drafted_player_ids", [])):
        return False, "That player has already been drafted."
    pick_record = dict(player_row)
    pick_record.update(
        {
            "Round": slot["Round"],
            "Pick": slot["Pick"],
            "Fantasy Team": team,
            "Pick Verdict": verdict,
        }
    )
    room.setdefault("draft_board", []).append(pick_record)
    room.setdefault("rosters", {}).setdefault(team, []).append(pick_record)
    room.setdefault("drafted_player_ids", []).append(pid)
    room["current_pick_index"] = int(room.get("current_pick_index", 0)) + 1
    live_draft_bump_sync_revision(room, event="pick")
    if room.get("meta"):
        room["meta"].setdefault("turn_model", {})["current_pick_index"] = room["current_pick_index"]
    if room["current_pick_index"] >= len(room.get("pick_order", [])):
        room["status"] = "complete"
        room["timer_started_at"] = None
    else:
        live_draft_reset_timer(room)
    return True, f"Drafted {player_row.get('fullName', 'player')} to {team}."
