"""Start Live Draft from Draft Room Simulator — board promotion and diagnostics."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

import pandas as pd


def normalize_player_name_for_merge(name: Any) -> str:
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    text = str(name)
    text = text.replace("(Batter)", "").replace("(Pitcher)", "")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text)
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def find_live_pool_row(available: Any, player_name: str) -> Any | None:
    if available is None or getattr(available, "empty", True):
        return None
    col = "fullName" if "fullName" in available.columns else "Player"
    target = str(player_name or "").strip()
    target_norm = normalize_player_name_for_merge(target)
    target_parts = target_norm.split()
    last_name = target_parts[-1] if target_parts else ""
    best_last: Any | None = None
    for _, row in available.iterrows():
        full = str(row.get(col) or "").strip()
        if not full:
            continue
        if full.lower() == target.lower() or full == target:
            return row
        full_norm = normalize_player_name_for_merge(full)
        if target_norm and full_norm == target_norm:
            return row
        if last_name and len(last_name) >= 3:
            full_parts = full_norm.split()
            if full_parts and full_parts[-1] == last_name:
                if best_last is None:
                    best_last = row
                if len(full_parts) == len(target_parts):
                    return row
    return best_last


def replay_simulator_board_on_live_room(
    room: dict[str, Any],
    board_df: Any,
    *,
    make_pick_fn: Callable[..., tuple[bool, str]],
    current_slot_fn: Callable[[dict[str, Any]], Any | None],
    available_fn: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    """Promote filled simulator board picks onto a fresh live draft room."""
    trace: dict[str, Any] = {"ok": True, "applied": 0, "skipped": 0, "error": "", "failed_players": []}
    if board_df is None or getattr(board_df, "empty", True) or "Player" not in board_df.columns:
        return trace
    work = board_df.copy()
    if "Pick" in work.columns:
        work = work.sort_values("Pick", kind="stable")
    for _, row in work.iterrows():
        player = str(row.get("Player") or "").strip()
        if not player:
            continue
        slot = current_slot_fn(room)
        if slot is None:
            trace["error"] = "Live draft completed while replaying simulator picks."
            trace["ok"] = False
            break
        available = available_fn(room)
        match = find_live_pool_row(available, player)
        if match is None:
            trace["failed_players"].append(player)
            trace["skipped"] += 1
            continue
        ok, msg = make_pick_fn(room, match.to_dict(), verdict="Promoted from simulator")
        if not ok:
            trace["ok"] = False
            trace["error"] = msg or f"Could not draft {player}"
            trace["failed_players"].append(player)
            break
        trace["applied"] += 1
    if trace["skipped"] > 0 and trace["applied"] > 0 and not trace["error"]:
        trace["error"] = f"Skipped {trace['skipped']} pick(s) not found in live pool"
    return trace


def resolve_simulator_board_for_live_start(session: dict[str, Any]) -> tuple[Any, int, str, list[str]]:
    """Richest simulator board + pick count + source key + team names."""
    from draft_room_state import _resolve_richest_draft_board, simulator_teams_from_board, table_pick_count

    board, pick_count, source = _resolve_richest_draft_board(session)
    teams = simulator_teams_from_board(board)
    return board, pick_count, source, teams


def clear_stale_live_draft_for_simulator_start(session: dict[str, Any]) -> None:
    """Remove non-running live draft rooms so Start can create a fresh room."""
    try:
        from draft_room_state import is_live_draft_runtime_active
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, clear_live_draft_state

        if is_live_draft_runtime_active(session):
            return
        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if room is not None:
            clear_live_draft_state(session, reason="start_live_from_simulator")
    except Exception:
        session["live_draft_room"] = None
