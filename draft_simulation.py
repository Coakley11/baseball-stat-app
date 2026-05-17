"""Pure helpers for showing a simulated draft pick's roster/category impact."""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


COUNT_CATEGORY_SPECS = [
    ("R", ["proj_R", "Projected R", "R"], "sum"),
    ("H", ["proj_H", "Projected H", "H"], "sum"),
    ("2B+3B", ["proj_XBH", "Projected XBH", "XBH", "XBH_noHR"], "sum"),
    ("HR", ["proj_HR", "Projected HR", "HR"], "sum"),
    ("RBI", ["proj_RBI", "Projected RBI", "RBI"], "sum"),
    ("SB", ["proj_SB", "Projected SB", "SB"], "sum"),
    ("BB", ["proj_BB", "Projected BB", "BB"], "sum"),
]

RATE_CATEGORY_SPECS = [
    ("AVG", ["proj_BA", "Projected BA", "BA"], "player mean"),
    ("OBP", ["proj_OBP", "Projected OBP", "OBP"], "player mean"),
    ("SLG", ["proj_SLG", "Projected SLG", "SLG"], "player mean"),
    ("OPS", ["proj_OPS", "Projected OPS", "OPS"], "player mean"),
]

VALUE_SPECS = [
    ("Expected Fantasy Value", ["Expected Fantasy Value"], "sum"),
    ("Draft Fit Score", ["Draft Fit Score", "Recommendation Score"], "sum"),
    ("Blended Projection Score", ["Blended Projection Score"], "sum"),
    ("Valuation Score", ["Valuation_Score", "Valuation Score"], "sum"),
    ("Current Score", ["Perf_Score", "Current Score"], "sum"),
    ("Fantasy Edge", ["Fantasy Edge"], "sum"),
]


def _clean_name(name) -> str:
    """Normalize display labels without trying to solve player-name identity globally."""
    text = "" if name is None or pd.isna(name) else str(name).strip()
    if " (" in text and text.endswith(")"):
        text = text.rsplit(" (", 1)[0].strip()
    return text


def _player_names_for_team(draft_room_table: pd.DataFrame, team_name: str) -> list[str]:
    if draft_room_table is None or draft_room_table.empty:
        return []
    if "Team" not in draft_room_table.columns or "Player" not in draft_room_table.columns:
        return []
    team = str(team_name).strip()
    rows = draft_room_table[draft_room_table["Team"].astype(str).str.strip().eq(team)].copy()
    names = [_clean_name(x) for x in rows["Player"].dropna().tolist()]
    return [n for n in names if n]


def _all_drafted_names(draft_room_table: pd.DataFrame) -> set[str]:
    if draft_room_table is None or draft_room_table.empty or "Player" not in draft_room_table.columns:
        return set()
    return {_clean_name(x) for x in draft_room_table["Player"].dropna().tolist() if _clean_name(x)}


def _lookup_by_name(projection_df: pd.DataFrame, name_col: str) -> dict[str, pd.Series]:
    if projection_df is None or projection_df.empty:
        return {}
    df = projection_df.copy()
    if name_col not in df.columns:
        if "Player" in df.columns:
            name_col = "Player"
        elif "fullName" in df.columns:
            name_col = "fullName"
        else:
            return {}
    df["_sim_name_key"] = df[name_col].map(_clean_name)
    out: dict[str, pd.Series] = {}
    for _, row in df.iterrows():
        key = row.get("_sim_name_key", "")
        if key and key not in out:
            out[key] = row
    return out


def _rows_for_names(names: Iterable[str], lookup: dict[str, pd.Series]) -> tuple[pd.DataFrame, list[str]]:
    rows = []
    missing = []
    for name in [_clean_name(n) for n in names]:
        if not name:
            continue
        row = lookup.get(name)
        if row is None:
            missing.append(name)
        else:
            rows.append(row)
    if not rows:
        return pd.DataFrame(), missing
    return pd.DataFrame(rows).reset_index(drop=True), missing


def _first_existing_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _aggregate_metric(df: pd.DataFrame, col: str | None, mode: str) -> float:
    if df is None or df.empty or not col or col not in df.columns:
        return np.nan if mode != "sum" else 0.0
    values = pd.to_numeric(df[col], errors="coerce")
    if mode == "sum":
        return float(values.fillna(0).sum())
    return float(values.mean()) if values.notna().any() else np.nan


def _build_metric_table(
    before_df: pd.DataFrame,
    after_df: pd.DataFrame,
    specs: list[tuple[str, list[str], str]],
    metric_label: str,
) -> pd.DataFrame:
    rows = []
    for label, candidates, mode in specs:
        col = _first_existing_col(after_df, candidates) or _first_existing_col(before_df, candidates)
        if not col:
            continue
        before_val = _aggregate_metric(before_df, col, mode)
        after_val = _aggregate_metric(after_df, col, mode)
        if pd.isna(before_val) or pd.isna(after_val):
            change = np.nan
        else:
            change = after_val - before_val
        rows.append(
            {
                metric_label: label,
                "Before": before_val,
                "After": after_val,
                "Change": change,
                "Source column": col,
                "Aggregation": mode,
            }
        )
    return pd.DataFrame(rows)


def _roster_table(names: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Roster Spot": i + 1, "Player": name} for i, name in enumerate(names)]
    )


def _summary_line(player_name: str, category_table: pd.DataFrame, value_table: pd.DataFrame) -> str:
    parts = []
    if category_table is not None and not category_table.empty:
        priority = ["HR", "RBI", "R", "SB", "AVG", "OBP", "OPS", "2B+3B"]
        for cat in priority:
            hit = category_table[category_table["Category"].astype(str).eq(cat)]
            if hit.empty:
                continue
            row = hit.iloc[0]
            before = row.get("Before")
            after = row.get("After")
            change = row.get("Change")
            if pd.isna(before) or pd.isna(after) or pd.isna(change):
                continue
            if cat in {"AVG", "OBP", "OPS"}:
                parts.append(f"{cat} from {before:.3f} to {after:.3f} ({change:+.3f})")
            else:
                parts.append(f"{cat} from {before:.0f} to {after:.0f} ({change:+.0f})")
            if len(parts) >= 4:
                break

    value_part = ""
    if value_table is not None and not value_table.empty:
        for value_name in ["Expected Fantasy Value", "Draft Fit Score", "Valuation Score"]:
            hit = value_table[value_table["Value Metric"].astype(str).eq(value_name)]
            if hit.empty:
                continue
            change = hit.iloc[0].get("Change")
            if pd.notna(change):
                value_part = f"; {value_name} changes by {float(change):+.4f}"
                break

    if parts:
        return f"If you draft {player_name} next, projected team impact: " + ", ".join(parts) + value_part + "."
    if value_part:
        return f"If you draft {player_name} next, team value impact is shown below{value_part}."
    return f"If you draft {player_name} next, the before/after roster is shown below."


def build_draft_pick_simulation(
    draft_room_table: pd.DataFrame,
    player_name: str,
    team_name: str,
    projection_df: pd.DataFrame,
    *,
    name_col: str = "fullName",
) -> dict:
    """Return before/after roster and category impact for adding one player.

    The helper uses existing projection/value columns only. It does not rank players,
    alter projection formulas, or write draft-room state.
    """
    player = _clean_name(player_name)
    team = str(team_name or "").strip()
    before_names = _player_names_for_team(draft_room_table, team)
    all_drafted = _all_drafted_names(draft_room_table)
    already_on_team = player in before_names
    already_elsewhere = player in all_drafted and not already_on_team

    after_names = list(before_names)
    if player and not already_on_team and not already_elsewhere:
        after_names.append(player)

    lookup = _lookup_by_name(projection_df, name_col)
    before_df, before_missing = _rows_for_names(before_names, lookup)
    after_df, after_missing = _rows_for_names(after_names, lookup)
    missing = list(dict.fromkeys(before_missing + after_missing))

    category_table = _build_metric_table(
        before_df,
        after_df,
        COUNT_CATEGORY_SPECS + RATE_CATEGORY_SPECS,
        "Category",
    )
    value_table = _build_metric_table(before_df, after_df, VALUE_SPECS, "Value Metric")

    if already_elsewhere:
        status = f"{player} is already drafted by another team, so the simulated roster does not add him."
    elif already_on_team:
        status = f"{player} is already on {team}, so the simulated roster is unchanged."
    else:
        status = _summary_line(player, category_table, value_table)

    return {
        "player_name": player,
        "team_name": team,
        "before_roster": _roster_table(before_names),
        "after_roster": _roster_table(after_names),
        "category_table": category_table,
        "value_table": value_table,
        "missing_players": missing,
        "status": status,
        "already_on_team": already_on_team,
        "already_elsewhere": already_elsewhere,
    }
