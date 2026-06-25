"""Pure live draft auto-pick selection — no Streamlit app imports."""

from __future__ import annotations

from typing import Any

import pandas as pd

from live_draft_pick_engine import live_draft_make_pick
from live_draft_pick_scoring import (
    score_available_for_rule,
    live_draft_pick_verdict,
    live_draft_target_counts,
)
from live_draft_state import live_draft_get_available
from live_draft_timer_logic import live_draft_current_slot


def _board_size(room: dict[str, Any]) -> int:
    board = room.get("draft_board") or []
    return len(board) if isinstance(board, list) else 0


def _total_expected_picks(room: dict[str, Any]) -> int:
    pick_order = room.get("pick_order") or []
    if pick_order:
        return len(pick_order)
    teams = room.get("teams") or []
    cfg = dict(room.get("config") or {})
    rounds = int(cfg.get("picks_per_team") or cfg.get("rounds") or 0)
    if teams and rounds:
        return len(teams) * rounds
    return 0


def live_draft_auto_pick(room: dict[str, Any]) -> tuple[bool, str]:
    """Select and apply the best auto-pick for the current on-clock slot."""
    slot = live_draft_current_slot(room)
    if slot is None:
        total = _total_expected_picks(room)
        board = _board_size(room)
        if total > 0 and board < total:
            return False, "Draft pick index out of sync — use Manual Draft to recover."
        return False, "Draft is already complete."

    available = live_draft_get_available(room)
    if available.empty:
        total = _total_expected_picks(room)
        board = _board_size(room)
        if total > 0 and board >= total:
            room["status"] = "complete"
        return False, "No players remain in the pool."

    team = slot["Team"]
    roster_df = pd.DataFrame(room["rosters"].get(team, []))
    cfg = dict(room.get("config", {}))
    cfg["current_pick"] = int(slot.get("Pick", 1))
    target_counts = live_draft_target_counts(cfg)
    rule = cfg.get("auto_pick_rule", "balanced recommendation")
    scored, gaps = score_available_for_rule(available, roster_df, rule, target_counts, config=cfg)
    chosen = scored.iloc[0]
    verdict = live_draft_pick_verdict(chosen, rule, gaps)
    return live_draft_make_pick(room, chosen.to_dict(), verdict=verdict)
