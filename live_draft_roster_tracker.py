"""Personalized roster slot tracker for Live Draft Room."""

from __future__ import annotations

from typing import Any

import pandas as pd

from live_draft_pick_scoring import live_draft_target_counts


def _position_counts(roster_df: pd.DataFrame) -> dict[str, int]:
    if roster_df is None or roster_df.empty or "Primary Position" not in roster_df.columns:
        return {}
    return {
        str(k): int(v)
        for k, v in roster_df["Primary Position"].fillna("DH").astype(str).value_counts().items()
    }


def _slot_label(pos: str) -> str:
    if pos == "DH":
        return "UTIL"
    return pos


def build_roster_checklist(
    roster_df: pd.DataFrame | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Checklist rows for one fantasy team — ✓ filled slots, ✗ open slots."""
    targets = live_draft_target_counts(config or {})
    counts = _position_counts(roster_df if roster_df is not None else pd.DataFrame())

    lines: list[dict[str, Any]] = []
    filled_total = 0
    target_total = 0

    for pos in ("C", "1B", "2B", "3B", "SS"):
        target = int(targets.get(pos, 0) or 0)
        have = int(counts.get(pos, 0) or 0)
        label = _slot_label(pos)
        for i in range(target):
            target_total += 1
            is_filled = i < have
            if is_filled:
                filled_total += 1
            lines.append({"label": label, "position": pos, "filled": is_filled})

    of_target = int(targets.get("OF", 0) or 0)
    of_have = int(counts.get("OF", 0) or 0)
    for i in range(of_target):
        target_total += 1
        is_filled = i < of_have
        if is_filled:
            filled_total += 1
        lines.append({"label": "OF", "position": "OF", "filled": is_filled})

    util_target = int(targets.get("DH", 0) or 0)
    util_have = int(counts.get("DH", 0) or 0)
    for i in range(util_target):
        target_total += 1
        is_filled = i < util_have
        if is_filled:
            filled_total += 1
        lines.append({"label": "UTIL", "position": "DH", "filled": is_filled})

    p_target = int(targets.get("P", 0) or 0)
    p_have = int(counts.get("P", 0) or 0)
    for i in range(p_target):
        target_total += 1
        is_filled = i < p_have
        if is_filled:
            filled_total += 1
        lines.append({"label": "P", "position": "P", "filled": is_filled})

    open_positions = sorted({ln["label"] for ln in lines if not ln["filled"]})
    return {
        "lines": lines,
        "filled": filled_total,
        "target": target_total,
        "open_positions": open_positions,
        "gaps": open_positions,
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
