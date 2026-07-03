"""Personalized roster slot tracker for Live Draft Room."""

from __future__ import annotations

from typing import Any

import pandas as pd

from live_draft_roster_slots import (
    get_active_draft_roster_slots,
    get_filled_position_counts,
    get_remaining_position_needs,
)


def build_roster_checklist(
    roster_df: pd.DataFrame | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Checklist rows from host-created slot instances — no default positions."""
    slots = get_active_draft_roster_slots(config or {})
    if not slots:
        return {
            "lines": [],
            "filled": 0,
            "target": 0,
            "open_positions": [],
            "gaps": [],
        }

    remaining = get_filled_position_counts(roster_df if roster_df is not None else pd.DataFrame())
    pool = dict(remaining)

    lines: list[dict[str, Any]] = []
    filled_total = 0
    for slot in slots:
        pos = str(slot.get("position") or "")
        label = str(slot.get("label") or pos)
        left = int(pool.get(pos, 0) or 0)
        is_filled = left > 0
        if is_filled:
            pool[pos] = left - 1
            filled_total += 1
        lines.append({"label": label, "position": pos, "filled": is_filled})

    open_labels = sorted({ln["label"] for ln in lines if not ln["filled"]})
    gaps = get_remaining_position_needs(roster_df, config)
    return {
        "lines": lines,
        "filled": filled_total,
        "target": len(slots),
        "open_positions": open_labels,
        "gaps": gaps,
    }


def roster_df_for_team(room: dict[str, Any], team: str) -> pd.DataFrame:
    """Roster picks for one fantasy team."""
    team_s = str(team or "").strip()
    if not team_s:
        return pd.DataFrame()
    rows = list((room.get("rosters") or {}).get(team_s) or [])
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def build_team_roster_tracker(room: dict[str, Any], team: str) -> dict[str, Any]:
    cfg = dict(room.get("config") or {})
    roster_df = roster_df_for_team(room, team)
    checklist = build_roster_checklist(roster_df, cfg)
    checklist["team"] = str(team or "").strip()
    return checklist
