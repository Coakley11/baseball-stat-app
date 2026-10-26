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
    gaps = list(result.get("gaps") or [])
    try:
        from draft_needs import filter_bench_gaps

        gaps = filter_bench_gaps(gaps)
    except ImportError:
        gaps = [g for g in gaps if str(g or "").strip().upper() not in ("BN", "BENCH")]
    return {
        "lines": list(result.get("lines") or []),
        "filled": int(result.get("filled") or 0),
        "target": int(result.get("target") or 0),
        "open_positions": list(result.get("open_positions") or []),
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
    return _with_pool_projections(pd.DataFrame(rows), room.get("pool"))


def _with_pool_projections(roster_df: pd.DataFrame, pool: Any) -> pd.DataFrame:
    """Attach ``proj_*`` stats from the room pool to rostered players.

    Roster entries carry identity and value fields only. Without projections the
    category outlook scored every team as 0 in every category and category-need
    inference skipped every category.
    """
    if not isinstance(pool, pd.DataFrame) or pool.empty or roster_df.empty:
        return roster_df
    if pool.columns.duplicated().any():
        pool = pool.loc[:, ~pool.columns.duplicated()]
    proj_cols = [c for c in pool.columns if str(c).startswith("proj_") and c not in roster_df.columns]
    if not proj_cols:
        return roster_df
    for key in ("playerID", "fullName"):
        if key in roster_df.columns and key in pool.columns:
            lookup = pool.loc[:, [key, *proj_cols]].drop_duplicates(subset=[key]).set_index(key)
            return roster_df.join(lookup, on=key)
    return roster_df


def build_team_roster_tracker(room: dict[str, Any], team: str) -> dict[str, Any]:
    cfg = dict(room.get("config") or {})
    roster_df = roster_df_for_team(room, team)
    checklist = build_roster_checklist(roster_df, cfg)
    checklist["team"] = str(team or "").strip()
    return checklist
