"""Personalized roster slot tracker for Live Draft Room."""

from __future__ import annotations

from typing import Any

import pandas as pd

from live_draft_roster_slots import assign_roster_to_slot_instances


def build_roster_checklist(
    roster_df: pd.DataFrame | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Checklist rows from host-created slot instances — sequential assignment, not primary-position counts."""
    result = assign_roster_to_slot_instances(roster_df, config or {})
    return {
        "lines": list(result.get("lines") or []),
        "filled": int(result.get("filled") or 0),
        "target": int(result.get("target") or 0),
        "open_positions": list(result.get("open_positions") or []),
        "gaps": list(result.get("gaps") or []),
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
