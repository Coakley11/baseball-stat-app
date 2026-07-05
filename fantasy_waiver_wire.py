"""Waiver Wire / Add-Drop Center — pool, needs, recommendations, and league activity."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from fantasy_league_context import (
    WORKFLOW_KEY_ACQUIRE_TARGETS,
    add_workflow_target,
    build_ownership_map,
    get_active_league_context,
    get_league_context,
    get_workflow_targets,
    normalize_player_key,
    remove_workflow_target,
    upsert_league_context,
)

WAIVER_WIRE_PAGE = "Waiver Wire / Add-Drop Center"
GLOBAL_WAIVER_FILTER_KEY = "use_active_league_context_waiver_filter"
FANTASY_RESEARCH_SYNC_KEY = GLOBAL_WAIVER_FILTER_KEY
WORKFLOW_KEY_ADD_TARGETS = "add_targets"
WORKFLOW_KEY_DROP_CANDIDATES = "drop_candidates"
WORKFLOW_KEY_LEAGUE_ACTIVITY = "league_activity"
TRADE_MODE_ADD = "add"
TRADE_MODE_DROP = "drop"

ROTO_CATEGORIES = ("HR", "RBI", "SB", "AVG", "R", "S", "K", "ERA", "WHIP")
WAIVER_HITTER_CATEGORIES: tuple[str, ...] = ("HR", "RBI", "R", "SB", "AVG", "OPS", "OBP")
WAIVER_PITCHING_CATEGORIES: tuple[str, ...] = ("W", "SV", "K", "ERA", "WHIP")
WAIVER_CURRENT_CATEGORIES: tuple[str, ...] = WAIVER_HITTER_CATEGORIES
HITTER_ONLY_FORMATS = frozenset({"5x5 roto", "points league", ""})
CURRENT_STAT_ALIASES: dict[str, tuple[str, ...]] = {
    "HR": ("HR",),
    "RBI": ("RBI",),
    "R": ("R",),
    "SB": ("SB",),
    "AVG": ("BA", "AVG"),
    "OPS": ("OPS",),
    "OBP": ("OBP",),
    "W": ("W",),
    "SV": ("SV", "S"),
    "K": ("K", "SO"),
    "ERA": ("ERA",),
    "WHIP": ("WHIP",),
}


def fantasy_format_includes_pitching(
    fantasy_format: str,
    context: dict[str, Any] | None = None,
) -> bool:
    """True only when the active league format explicitly includes pitching categories."""
    if context:
        meta = context.get("metadata") or {}
        if meta.get("includes_pitching") is True:
            return True
        if meta.get("pitching_categories"):
            return True
    fmt = str(fantasy_format or "").strip().lower()
    if fmt in HITTER_ONLY_FORMATS:
        return False
    pitching_tokens = ("pitch", "era", "whip", "saves", "9x9", "10x10", "8x8", "6x6")
    return any(tok in fmt for tok in pitching_tokens)


def waiver_categories_for_context(context: dict[str, Any] | None) -> tuple[str, ...]:
    """Resolve waiver categories from the active league context fantasy format."""
    fmt = str((context or {}).get("fantasy_format") or "5x5 Roto").strip()
    fmt_l = fmt.lower()
    if fmt_l == "points league":
        cats: list[str] = ["HR", "RBI", "R", "SB", "AVG", "OPS"]
    elif fmt_l == "5x5 roto":
        cats = ["HR", "RBI", "R", "SB", "AVG"]
    else:
        cats = list(WAIVER_HITTER_CATEGORIES)
    if fantasy_format_includes_pitching(fmt, context):
        for cat in WAIVER_PITCHING_CATEGORIES:
            if cat not in cats:
                cats.append(cat)
    return tuple(cats)


LOWER_IS_BETTER_CATEGORIES = frozenset({"ERA", "WHIP"})
WAIVER_PENDING_PAIRS_KEY = "_waiver_pending_move_pairs"
WAIVER_PLANNER_ADD_KEY = "waiver_planner_add_pick"
WAIVER_PLANNER_DROP_KEY = "waiver_planner_drop_pick"
ROTO_STAT_MAP = {
    "HR": ("HR", "proj_HR", "Total HR"),
    "RBI": ("RBI", "proj_RBI", "Total RBI"),
    "SB": ("SB", "proj_SB", "Total SB"),
    "AVG": ("BA", "proj_BA", "Average BA"),
    "R": ("R", "proj_R", "Total R"),
    "S": ("SV", "proj_SV", "Total SV"),
    "K": ("SO", "proj_SO", "Total SO"),
    "ERA": ("ERA", "proj_ERA", "Average ERA"),
    "WHIP": ("WHIP", "proj_WHIP", "Average WHIP"),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def research_league_sync_enabled(session: dict[str, Any]) -> bool:
    """When ON, research pages exclude active-league rostered players."""
    return bool(session.get(FANTASY_RESEARCH_SYNC_KEY))


def waiver_filter_enabled(session: dict[str, Any]) -> bool:
    return research_league_sync_enabled(session)


def rostered_player_keys(context: dict[str, Any] | None) -> set[str]:
    if not context:
        return set()
    ownership = context.get("ownership_map") or build_ownership_map(context)
    return {str(k).strip() for k in ownership.keys() if str(k).strip()}


def rostered_player_names(context: dict[str, Any] | None) -> set[str]:
    if not context:
        return set()
    ownership = context.get("ownership_map") or build_ownership_map(context)
    names: set[str] = set()
    for rec in ownership.values():
        if not isinstance(rec, dict):
            continue
        name = str(rec.get("player_name") or "").strip()
        if name:
            names.add(name)
    return names


def _player_name_col(df: pd.DataFrame) -> str:
    for col in ("fullName", "Player", "player_name", "name"):
        if col in df.columns:
            return col
    return "fullName"


def build_waiver_pool(
    player_pool: pd.DataFrame,
    context: dict[str, Any] | None,
) -> pd.DataFrame:
    """Available players = active pool minus anyone rostered in the league context."""
    if player_pool is None or getattr(player_pool, "empty", True):
        return pd.DataFrame()
    pool = player_pool.copy()
    name_col = _player_name_col(pool)
    if name_col not in pool.columns:
        return pool
    rostered = rostered_player_names(context)
    if not rostered:
        rostered_keys = rostered_player_keys(context)
        if rostered_keys:
            pool["_waiver_key"] = pool[name_col].astype(str).str.strip().str.lower()
            pool = pool[~pool["_waiver_key"].isin(rostered_keys)].drop(columns=["_waiver_key"])
        return pool.reset_index(drop=True)
    pool = pool[~pool[name_col].astype(str).str.strip().isin(rostered)].reset_index(drop=True)
    return pool


def filter_unrostered_players(
    session: dict[str, Any],
    df: pd.DataFrame,
    *,
    name_col: str | None = None,
) -> pd.DataFrame:
    """Exclude active-league rostered players when research sync is ON."""
    if not research_league_sync_enabled(session):
        return df
    context = get_active_league_context(session)
    if context is None or df is None or getattr(df, "empty", True):
        return df
    col = name_col or _player_name_col(df)
    if col not in df.columns:
        return df
    rostered = rostered_player_names(context)
    if not rostered:
        return df
    return df[~df[col].astype(str).str.strip().isin(rostered)].reset_index(drop=True)


def my_team_roster_dataframe(context: dict[str, Any] | None) -> pd.DataFrame:
    if not context:
        return pd.DataFrame()
    my_team = str(context.get("my_team_name") or "").strip()
    league_rosters = context.get("league_rosters") or {}
    if not isinstance(league_rosters, dict) or not my_team:
        return pd.DataFrame()
    entry = league_rosters.get(my_team) or {}
    rows: list[dict[str, Any]] = []
    for player in entry.get("players") or []:
        if not isinstance(player, dict):
            continue
        name = str(player.get("player_name") or "").strip()
        if not name:
            continue
        row = {"Player": name, "fullName": name}
        positions = player.get("positions") or []
        if positions:
            row["Primary Position"] = str(positions[0])
        rows.append(row)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _stat_series(df: pd.DataFrame, aliases: tuple[str, ...]) -> pd.Series:
    for col in aliases:
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(dtype=float)


def _resolve_current_stat_col(df: pd.DataFrame, category: str) -> str | None:
    for col in CURRENT_STAT_ALIASES.get(category, (category,)):
        if col in df.columns:
            return col
    return None


def _category_value_for_team(subset: pd.DataFrame, category: str) -> float | None:
    col = _resolve_current_stat_col(subset, category)
    if not col:
        return None
    vals = pd.to_numeric(subset[col], errors="coerce")
    if not vals.notna().any():
        return None
    if category in LOWER_IS_BETTER_CATEGORIES:
        return float(vals.mean())
    if category == "AVG":
        return float(vals.mean())
    return float(vals.sum())


def analyze_current_team_needs(
    my_roster: pd.DataFrame,
    league_rosters_df: pd.DataFrame,
    *,
    categories: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Category strengths/weaknesses from current-season stat columns (not projections)."""
    result: dict[str, Any] = {
        "strengths": [],
        "weaknesses": [],
        "targets": [],
        "category_ranks": {},
        "available_categories": [],
        "n_teams": 0,
    }
    if my_roster is None or my_roster.empty:
        return result
    if league_rosters_df is None or league_rosters_df.empty or "Team" not in league_rosters_df.columns:
        return result

    available = [
        cat
        for cat in (categories or WAIVER_HITTER_CATEGORIES)
        if _resolve_current_stat_col(league_rosters_df, cat) or _resolve_current_stat_col(my_roster, cat)
    ]
    result["available_categories"] = available
    if not available:
        return result

    team_totals: dict[str, dict[str, float]] = {}
    for team, subset in league_rosters_df.groupby(league_rosters_df["Team"].astype(str), sort=False):
        totals: dict[str, float] = {}
        for cat in available:
            val = _category_value_for_team(subset, cat)
            if val is not None:
                totals[cat] = val
        if totals:
            team_totals[str(team)] = totals

    result["n_teams"] = len(team_totals)
    my_team_name = str(my_roster.get("Team").iloc[0]) if "Team" in my_roster.columns and not my_roster.empty else ""
    if not my_team_name and len(team_totals) == 1:
        my_team_name = next(iter(team_totals.keys()))
    my_totals = team_totals.get(my_team_name) or {}
    if not my_totals:
        for cat in available:
            val = _category_value_for_team(my_roster, cat)
            if val is not None:
                my_totals[cat] = val

    for cat in available:
        if cat not in my_totals:
            continue
        values = [team_totals[t].get(cat, 0.0) for t in team_totals if cat in team_totals.get(t, {})]
        if not values:
            continue
        my_val = my_totals.get(cat, 0.0)
        lower_is_better = cat in LOWER_IS_BETTER_CATEGORIES
        if lower_is_better:
            rank = sum(1 for v in values if v < my_val) + 1
            league_best = min(values)
            weakness = my_val > league_best * 1.08 if league_best else False
            strength = my_val <= league_best * 1.02 if league_best else False
        else:
            rank = sum(1 for v in values if v > my_val) + 1
            league_best = max(values)
            weakness = my_val < league_best * 0.85 if league_best else False
            strength = my_val >= league_best * 0.95 if league_best else False
        result["category_ranks"][cat] = rank
        if strength:
            result["strengths"].append(cat)
        if weakness:
            result["weaknesses"].append(cat)
            result["targets"].append(cat)
    return result


def build_category_standings_table(
    needs: dict[str, Any],
    *,
    categories: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """One row per category with current league rank."""
    ranks = needs.get("category_ranks") or {}
    if not ranks:
        return pd.DataFrame()
    n_teams = int(needs.get("n_teams") or 0) or max(ranks.values())
    rows = []
    for cat in (categories or WAIVER_HITTER_CATEGORIES):
        if cat not in ranks:
            continue
        rank = int(ranks[cat])
        rank_label = f"{rank}{_ordinal_suffix(rank)}"
        if n_teams > 1:
            rank_label = f"{rank_label} of {n_teams}"
        rows.append(
            {
                "Category": cat,
                "Rank": rank_label,
                "Status": (
                    "Strength" if cat in (needs.get("strengths") or [])
                    else "Weakness" if cat in (needs.get("weaknesses") or [])
                    else "Middle"
                ),
            }
        )
    return pd.DataFrame(rows)


def format_league_rank_lines(
    needs: dict[str, Any],
    *,
    categories: tuple[str, ...] | None = None,
) -> list[str]:
    """Compact rank lines: HR: 6th, RBI: 5th."""
    ranks = needs.get("category_ranks") or {}
    lines: list[str] = []
    for cat in (categories or WAIVER_HITTER_CATEGORIES):
        if cat not in ranks:
            continue
        rank = int(ranks[cat])
        lines.append(f"**{cat}:** {rank}{_ordinal_suffix(rank)}")
    return lines


def merge_current_season_stats(
    hitter_df: pd.DataFrame | None,
    pitcher_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """Combine hitter and pitcher current-season rows on Player Key."""
    hitters = hitter_df.copy() if hitter_df is not None and not hitter_df.empty else pd.DataFrame()
    pitchers = pitcher_df.copy() if pitcher_df is not None and not pitcher_df.empty else pd.DataFrame()
    if hitters.empty and pitchers.empty:
        return pd.DataFrame()
    if hitters.empty:
        return pitchers.reset_index(drop=True)
    if pitchers.empty:
        return hitters.reset_index(drop=True)
    if "Player Key" not in hitters.columns and "Player" in hitters.columns:
        hitters["Player Key"] = hitters["Player"].astype(str).str.strip().str.lower()
    if "Player Key" not in pitchers.columns and "Player" in pitchers.columns:
        pitchers["Player Key"] = pitchers["Player"].astype(str).str.strip().str.lower()
    pitcher_cols = [c for c in pitchers.columns if c not in hitters.columns or c in ("Player Key", "Player")]
    merged = hitters.merge(
        pitchers[pitcher_cols],
        on="Player Key",
        how="outer",
        suffixes=("", "_pit"),
    )
    for col in ("Player", "MLB Team", "Primary Position"):
        pit_col = f"{col}_pit"
        if col in merged.columns and pit_col in merged.columns:
            merged[col] = merged[col].fillna(merged[pit_col])
            merged = merged.drop(columns=[pit_col])
    if "Player" not in merged.columns and "Player_pit" in merged.columns:
        merged["Player"] = merged["Player_pit"]
    return merged.reset_index(drop=True)


def _is_pitcher_row(row: pd.Series) -> bool:
    pos = str(row.get("Primary Position") or row.get("Position") or "").upper()
    if pos in ("P", "SP", "RP"):
        return True
    for col in ("W", "SV", "ERA", "WHIP"):
        if col in row.index and pd.notna(row.get(col)):
            if col in ("ERA", "WHIP") or float(pd.to_numeric(row.get(col), errors="coerce") or 0) > 0:
                return True
    return False


def format_current_stat_line(row: pd.Series) -> str:
    """One-line current stats for waiver cards (hitter or pitcher)."""
    if _is_pitcher_row(row):
        parts: list[str] = []
        for label, col in (("W", "W"), ("SV", "SV"), ("K", "K"), ("ERA", "ERA"), ("WHIP", "WHIP")):
            if col in row.index and pd.notna(row.get(col)):
                val = pd.to_numeric(row.get(col), errors="coerce")
                if pd.notna(val):
                    parts.append(f"{label} {float(val):.2f}" if label in ("ERA", "WHIP") else f"{label} {int(val)}")
        return " · ".join(parts) if parts else "Pitcher — current stats loaded"
    parts: list[str] = []
    for label, cols in (
        ("AVG", ("BA", "AVG")),
        ("OBP", ("OBP",)),
        ("OPS", ("OPS",)),
        ("HR", ("HR",)),
        ("RBI", ("RBI",)),
        ("R", ("R",)),
        ("SB", ("SB",)),
    ):
        for col in cols:
            if col in row.index and pd.notna(row.get(col)):
                val = row.get(col)
                if label in ("AVG", "OBP", "OPS"):
                    parts.append(f"{label} {float(val):.3f}")
                elif isinstance(val, float):
                    parts.append(f"{label} {val:.0f}")
                else:
                    parts.append(f"{label} {val}")
                break
    return " · ".join(parts) if parts else "Current stats loaded"


def format_projected_stat_line(row: pd.Series) -> str:
    """One-line projected stats for waiver cards when projection columns exist."""
    if _is_pitcher_row(row):
        parts: list[str] = []
        for label, cols in (
            ("W", ("proj_W", "Projected W")),
            ("SV", ("proj_SV", "Projected SV")),
            ("K", ("proj_K", "Projected K")),
            ("ERA", ("proj_ERA", "Projected ERA")),
            ("WHIP", ("proj_WHIP", "Projected WHIP")),
        ):
            for col in cols:
                if col in row.index and pd.notna(row.get(col)):
                    val = pd.to_numeric(row.get(col), errors="coerce")
                    if pd.notna(val):
                        parts.append(f"{label} {float(val):.2f}" if label in ("ERA", "WHIP") else f"{label} {int(val)}")
                    break
        return " · ".join(parts) if parts else ""
    parts: list[str] = []
    for label, cols in (
        ("AVG", ("proj_BA", "proj_AVG", "Projected AVG")),
        ("OBP", ("proj_OBP", "Projected OBP")),
        ("OPS", ("proj_OPS", "Projected OPS")),
        ("HR", ("proj_HR", "Projected HR")),
        ("RBI", ("proj_RBI", "Projected RBI")),
        ("R", ("proj_R", "Projected R")),
        ("SB", ("proj_SB", "Projected SB")),
    ):
        for col in cols:
            if col in row.index and pd.notna(row.get(col)):
                val = pd.to_numeric(row.get(col), errors="coerce")
                if pd.notna(val):
                    if label in ("AVG", "OBP", "OPS"):
                        parts.append(f"{label} {float(val):.3f}")
                    else:
                        parts.append(f"{label} {int(round(float(val)))}")
                break
    return " · ".join(parts) if parts else ""


def build_add_recommendation_explanation(player_row: pd.Series, needs: dict[str, Any]) -> str:
    """Waiver-specific explanation with league rank context — not draft metrics."""
    targets = list(needs.get("targets") or needs.get("weaknesses") or [])
    ranks = needs.get("category_ranks") or {}
    helped = categories_helped_by_player(player_row, targets)
    if helped and ranks:
        rank_bits = [
            f"{cat} {int(ranks[cat])}{_ordinal_suffix(int(ranks[cat]))}"
            for cat in helped[:4]
            if cat in ranks
        ]
        cats_text = ", ".join(helped[:4])
        if rank_bits:
            return f"Helps: **{cats_text}**. Current team ranks: **{' • '.join(rank_bits)}**."
        return f"Helps: **{cats_text}**."
    if helped:
        return f"Helps: **{', '.join(helped[:4])}** based on current-season production."
    return "Solid current-season upgrade for roster balance."


def build_weakness_narrative(needs: dict[str, Any]) -> list[str]:
    """Plain-language team weakness lines for waiver planning."""
    ranks = needs.get("category_ranks") or {}
    n_teams = int(needs.get("n_teams") or 0)
    if not ranks or n_teams < 2:
        return ["Load current-season stats and a multi-team league context to rank category needs."]

    lines: list[str] = []
    weaknesses = list(needs.get("weaknesses") or [])
    strengths = list(needs.get("strengths") or [])
    targets = list(needs.get("targets") or weaknesses)

    if weaknesses:
        weak_bits = [f"{cat} ({ranks.get(cat, '?')}/{n_teams})" for cat in weaknesses[:4]]
        lines.append(
            f"Your biggest category gaps are **{', '.join(weak_bits)}** — prioritize adds that improve these areas."
        )
    if targets:
        top = targets[0]
        rank = ranks.get(top)
        if top in ("HR", "RBI") and rank:
            lines.append(
                f"You are **{rank}{_ordinal_suffix(rank)} in {top}** — power bats are a top waiver target."
            )
        elif top == "SB" and rank:
            lines.append(
                f"You are **{rank}{_ordinal_suffix(rank)} in SB** — prioritize speed and stolen-base upside."
            )
        elif top == "SV" and rank:
            lines.append("Your pitching is competitive, but **saves are your biggest gap**.")
        elif top == "AVG" and strengths and "SB" in weaknesses:
            lines.append("You are strong in **AVG** but weak in **SB** — prioritize speed without tanking average.")
        elif rank:
            lines.append(f"**{top}** is your top upgrade category (currently {rank}{_ordinal_suffix(rank)} in the league).")

    if not lines:
        lines.append("Your roster profile is balanced — target best-available current-season upgrades.")
    return lines


def _ordinal_suffix(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def categories_helped_by_player(player_row: pd.Series, targets: list[str]) -> list[str]:
    helped: list[str] = []
    for cat in targets:
        col = _resolve_current_stat_col(player_row.to_frame().T, cat)
        if col and pd.notna(player_row.get(col)):
            helped.append(cat)
    return helped


def _current_need_explanation(player_row: pd.Series, needs: dict[str, Any]) -> str:
    targets = list(needs.get("targets") or needs.get("weaknesses") or [])
    parts: list[str] = []
    for cat in targets[:3]:
        col = _resolve_current_stat_col(player_row.to_frame().T, cat)
        if col and col in player_row.index:
            val = player_row.get(col)
            if pd.notna(val):
                if cat == "AVG":
                    parts.append(f"AVG {float(val):.3f}")
                elif cat in LOWER_IS_BETTER_CATEGORIES:
                    parts.append(f"{cat} {float(val):.2f}")
                elif isinstance(val, float):
                    parts.append(f"{cat} {val:.0f}")
                else:
                    parts.append(f"helps {cat}")
    if not parts:
        return "Solid current-season upgrade for roster balance."
    return " · ".join(parts)


def recommend_adds_current(
    waiver_pool: pd.DataFrame,
    needs: dict[str, Any],
    *,
    limit: int = 8,
) -> pd.DataFrame:
    if waiver_pool is None or waiver_pool.empty:
        return pd.DataFrame()
    pool = waiver_pool.copy()
    targets = list(needs.get("targets") or needs.get("weaknesses") or [])
    score = pd.Series(0.0, index=pool.index)
    for cat in targets:
        col = _resolve_current_stat_col(pool, cat)
        if not col:
            continue
        vals = pd.to_numeric(pool[col], errors="coerce").fillna(0)
        if cat in LOWER_IS_BETTER_CATEGORIES:
            score += (1.0 / (vals + 0.01)) * 0.15
        elif cat == "AVG":
            score += vals * 0.2
        else:
            score += vals * 0.08
    if not targets and "OPS" in pool.columns:
        score += pd.to_numeric(pool["OPS"], errors="coerce").fillna(0) * 0.1
    pool["_waiver_add_score"] = score
    pool = pool.sort_values("_waiver_add_score", ascending=False)
    top = pool.head(limit).copy()
    top["Why Add"] = [build_add_recommendation_explanation(row, needs) for _, row in top.iterrows()]
    top["Categories Helped"] = [
        ", ".join(categories_helped_by_player(row, targets)) or "Balance"
        for _, row in top.iterrows()
    ]
    name_col = _player_name_col(top)
    if name_col != "Player" and "Player" not in top.columns:
        top["Player"] = top[name_col]
    return top.drop(columns=["_waiver_add_score"], errors="ignore")


def recommend_drops_current(
    my_roster: pd.DataFrame,
    *,
    limit: int = 6,
    categories: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    if my_roster is None or my_roster.empty:
        return pd.DataFrame()
    roster = my_roster.copy()
    score = pd.Series(0.0, index=roster.index)
    drop_weights: tuple[tuple[str, float], ...] = (
        ("HR", 0.16),
        ("RBI", 0.14),
        ("R", 0.1),
        ("SB", 0.08),
        ("AVG", 0.12),
        ("OPS", 0.1),
        ("OBP", 0.08),
        ("W", 0.1),
        ("SV", 0.12),
        ("K", 0.08),
        ("ERA", 0.05),
        ("WHIP", 0.05),
    )
    active_cats = set(categories or WAIVER_HITTER_CATEGORIES)
    for cat, weight in drop_weights:
        if cat not in active_cats:
            continue
        col = _resolve_current_stat_col(roster, cat)
        if col:
            vals = pd.to_numeric(roster[col], errors="coerce").fillna(0)
            if cat in LOWER_IS_BETTER_CATEGORIES:
                score += (1.0 / (vals + 0.01)) * weight
            else:
                score += vals * weight
    roster["_drop_score"] = score
    roster = roster.sort_values("_drop_score", ascending=True)
    top = roster.head(limit).copy()
    top["Why Drop"] = [_drop_explanation_current(row, my_roster) for _, row in top.iterrows()]
    name_col = _player_name_col(top)
    if name_col != "Player":
        top["Player"] = top[name_col]
    return top.drop(columns=["_drop_score"], errors="ignore")


def _drop_explanation_current(player_row: pd.Series, my_roster: pd.DataFrame) -> str:
    parts: list[str] = []
    for cat in ("HR", "RBI", "R", "SB", "AVG"):
        col = _resolve_current_stat_col(player_row.to_frame().T, cat)
        if not col or col not in my_roster.columns:
            continue
        val = pd.to_numeric(player_row.get(col), errors="coerce")
        med = pd.to_numeric(my_roster[col], errors="coerce").median()
        if pd.notna(val) and pd.notna(med) and val < med * 0.75:
            parts.append(f"low current {cat}")
    pos = str(player_row.get("Primary Position") or player_row.get("position") or "").strip()
    if pos and "Primary Position" in my_roster.columns:
        same = my_roster[my_roster["Primary Position"].astype(str) == pos]
        if len(same) > 2:
            parts.append(f"redundant {pos}")
    if not parts:
        return "Weakest current-season production on roster."
    return " · ".join(parts)


def compute_add_drop_category_impact(
    add_row: pd.Series | None,
    drop_row: pd.Series | None,
    *,
    categories: list[str] | None = None,
) -> list[str]:
    cats = list(categories or WAIVER_HITTER_CATEGORIES)
    impacts: list[str] = []
    for cat in cats:
        probe = add_row if add_row is not None else drop_row
        if probe is None:
            continue
        col = _resolve_current_stat_col(probe.to_frame().T, cat)
        if not col:
            continue
        add_val = pd.to_numeric(add_row.get(col), errors="coerce") if add_row is not None and col in add_row.index else pd.NA
        drop_val = pd.to_numeric(drop_row.get(col), errors="coerce") if drop_row is not None and col in drop_row.index else pd.NA
        if pd.isna(add_val) and pd.isna(drop_val):
            continue
        add_num = float(add_val) if pd.notna(add_val) else 0.0
        drop_num = float(drop_val) if pd.notna(drop_val) else 0.0
        delta = add_num - drop_num
        threshold = 0.005 if cat == "AVG" else 0.5
        if cat in LOWER_IS_BETTER_CATEGORIES:
            if delta < -threshold:
                impacts.append(f"+{cat}")
            elif delta > threshold:
                impacts.append(f"-{cat}")
        elif delta > threshold:
            impacts.append(f"+{cat}")
        elif delta < -threshold:
            impacts.append(f"-{cat}")
    return impacts


def get_pending_move_pairs(session: dict[str, Any]) -> list[dict[str, Any]]:
    raw = session.get(WAIVER_PENDING_PAIRS_KEY)
    if not isinstance(raw, list):
        return []
    return [dict(x) for x in raw if isinstance(x, dict)]


def add_pending_move_pair(
    session: dict[str, Any],
    *,
    add_player: str,
    drop_player: str,
    category_impact: list[str] | None = None,
) -> bool:
    add_name = str(add_player or "").strip()
    drop_name = str(drop_player or "").strip()
    if not add_name or not drop_name:
        return False
    pairs = get_pending_move_pairs(session)
    pairs.append(
        {
            "add_player": add_name,
            "drop_player": drop_name,
            "category_impact": list(category_impact or []),
            "recorded_at": _utc_now_iso(),
        }
    )
    session[WAIVER_PENDING_PAIRS_KEY] = pairs[-20:]
    add_pending_move(session, TRADE_MODE_ADD, add_name)
    add_pending_move(session, TRADE_MODE_DROP, drop_name)
    try:
        import streamlit as st
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="waiver_pending_pair")
    except Exception:
        pass
    return True


def remove_pending_move_pair(session: dict[str, Any], index: int) -> bool:
    pairs = get_pending_move_pairs(session)
    if index < 0 or index >= len(pairs):
        return False
    pair = pairs.pop(index)
    session[WAIVER_PENDING_PAIRS_KEY] = pairs
    remove_pending_move(session, TRADE_MODE_ADD, str(pair.get("add_player") or ""))
    remove_pending_move(session, TRADE_MODE_DROP, str(pair.get("drop_player") or ""))
    return True


def filter_waiver_names_by_search(names: list[str], query: str) -> list[str]:
    """Case-insensitive substring filter for searchable waiver picker."""
    q = str(query or "").strip().lower()
    if not q:
        return list(names)
    return [n for n in names if q in str(n).lower()]


def waiver_display_stat_columns(df: pd.DataFrame, *, pitcher: bool = False) -> list[str]:
    base = ["Player", "MLB Team", "Team", "Primary Position", "Position"]
    if pitcher:
        current = ["W", "SV", "K", "ERA", "WHIP"]
        projected = ["proj_W", "proj_SV", "proj_K", "proj_ERA", "proj_WHIP"]
    else:
        current = ["AVG", "BA", "OBP", "OPS", "HR", "RBI", "R", "SB"]
        projected = [
            "proj_BA",
            "proj_AVG",
            "proj_OBP",
            "proj_OPS",
            "proj_HR",
            "proj_RBI",
            "proj_R",
            "proj_SB",
        ]
    score_cols = ["Why Add", "Why Drop", "Categories Helped", "_waiver_add_score"]
    ordered = base + current + projected + score_cols
    return [c for c in ordered if c in df.columns]


def analyze_team_needs(
    my_roster: pd.DataFrame,
    league_rosters_df: pd.DataFrame,
    *,
    fantasy_format: str = "5x5 Roto",
) -> dict[str, Any]:
    """Identify category strengths, weaknesses, and targets."""
    result: dict[str, Any] = {
        "strengths": [],
        "weaknesses": [],
        "targets": [],
        "category_ranks": {},
    }
    if my_roster is None or my_roster.empty:
        return result
    if league_rosters_df is None or league_rosters_df.empty or "Team" not in league_rosters_df.columns:
        return result

    team_totals: dict[str, dict[str, float]] = {}
    for team, subset in league_rosters_df.groupby(league_rosters_df["Team"].astype(str), sort=False):
        totals: dict[str, float] = {}
        for cat, (_, proj_col, _) in ROTO_STAT_MAP.items():
            if proj_col in subset.columns:
                vals = pd.to_numeric(subset[proj_col], errors="coerce")
                if cat in ("AVG", "ERA", "WHIP"):
                    totals[cat] = float(vals.mean()) if vals.notna().any() else 0.0
                else:
                    totals[cat] = float(vals.sum()) if vals.notna().any() else 0.0
        team_totals[str(team)] = totals

    my_team_name = str(my_roster.get("Team").iloc[0]) if "Team" in my_roster.columns and not my_roster.empty else ""
    if not my_team_name and len(team_totals) == 1:
        my_team_name = next(iter(team_totals.keys()))
    my_totals = team_totals.get(my_team_name) or {}
    if not my_totals:
        my_subset = my_roster
        for cat, (_, proj_col, _) in ROTO_STAT_MAP.items():
            if proj_col in my_subset.columns:
                vals = pd.to_numeric(my_subset[proj_col], errors="coerce")
                if cat in ("AVG", "ERA", "WHIP"):
                    my_totals[cat] = float(vals.mean()) if vals.notna().any() else 0.0
                else:
                    my_totals[cat] = float(vals.sum()) if vals.notna().any() else 0.0

    for cat in ROTO_CATEGORIES:
        if cat not in my_totals:
            continue
        values = [team_totals[t].get(cat, 0.0) for t in team_totals if cat in team_totals.get(t, {})]
        if not values:
            continue
        my_val = my_totals.get(cat, 0.0)
        lower_is_better = cat in ("ERA", "WHIP")
        if lower_is_better:
            rank = sum(1 for v in values if v < my_val) + 1
            league_best = min(values)
            weakness = my_val > league_best * 1.08 if league_best else False
            strength = my_val <= league_best * 1.02 if league_best else False
        else:
            rank = sum(1 for v in values if v > my_val) + 1
            league_best = max(values)
            weakness = my_val < league_best * 0.85 if league_best else False
            strength = my_val >= league_best * 0.95 if league_best else False
        result["category_ranks"][cat] = rank
        if strength:
            result["strengths"].append(cat)
        if weakness:
            result["weaknesses"].append(cat)
            result["targets"].append(cat)
    return result


def _need_explanation(player_row: pd.Series, needs: dict[str, Any]) -> str:
    targets = list(needs.get("targets") or needs.get("weaknesses") or [])
    parts: list[str] = []
    for cat in targets[:3]:
        _, proj_col, _ = ROTO_STAT_MAP.get(cat, ("", "", ""))
        if proj_col and proj_col in player_row.index:
            val = player_row.get(proj_col)
            if pd.notna(val):
                parts.append(f"helps {cat} ({val:.2f})" if isinstance(val, float) else f"helps {cat}")
    if not parts:
        return "Solid waiver fit for roster depth."
    return " · ".join(parts)


def recommend_adds(
    waiver_pool: pd.DataFrame,
    needs: dict[str, Any],
    *,
    limit: int = 8,
) -> pd.DataFrame:
    if waiver_pool is None or waiver_pool.empty:
        return pd.DataFrame()
    pool = waiver_pool.copy()
    targets = list(needs.get("targets") or needs.get("weaknesses") or [])
    score = pd.Series(0.0, index=pool.index)
    for cat in targets:
        _, proj_col, _ = ROTO_STAT_MAP.get(cat, ("", "", ""))
        if proj_col in pool.columns:
            vals = pd.to_numeric(pool[proj_col], errors="coerce").fillna(0)
            if cat in ("ERA", "WHIP"):
                score += (1.0 / (vals + 0.01)) * 0.15
            elif cat == "AVG":
                score += vals * 0.2
            else:
                score += vals * 0.08
    if "proj_OPS" in pool.columns and not targets:
        score += pd.to_numeric(pool["proj_OPS"], errors="coerce").fillna(0) * 0.1
    pool["_waiver_add_score"] = score
    pool = pool.sort_values("_waiver_add_score", ascending=False)
    top = pool.head(limit).copy()
    explanations = []
    for _, row in top.iterrows():
        explanations.append(_need_explanation(row, needs))
    top["Why Add"] = explanations
    return top.drop(columns=["_waiver_add_score"], errors="ignore")


def _drop_explanation(player_row: pd.Series, my_roster: pd.DataFrame) -> str:
    parts: list[str] = []
    for col in ("proj_OPS", "proj_HR", "proj_RBI"):
        if col not in player_row.index or col not in my_roster.columns:
            continue
        val = pd.to_numeric(player_row.get(col), errors="coerce")
        med = pd.to_numeric(my_roster[col], errors="coerce").median()
        if pd.notna(val) and pd.notna(med) and val < med * 0.75:
            parts.append(f"below-roster {col.replace('proj_', '')}")
    pos = str(player_row.get("Primary Position") or player_row.get("position") or "").strip()
    if pos and "Primary Position" in my_roster.columns:
        same = my_roster[my_roster["Primary Position"].astype(str) == pos]
        if len(same) > 2:
            parts.append(f"redundant {pos}")
    if not parts:
        return "Weakest projected value on roster."
    return " · ".join(parts)


def recommend_drops(
    my_roster: pd.DataFrame,
    *,
    limit: int = 6,
) -> pd.DataFrame:
    if my_roster is None or my_roster.empty:
        return pd.DataFrame()
    roster = my_roster.copy()
    score = pd.Series(0.0, index=roster.index)
    for col, weight in (("proj_OPS", 0.35), ("proj_HR", 0.15), ("proj_RBI", 0.12), ("proj_SB", 0.1), ("proj_BA", 0.15)):
        if col in roster.columns:
            vals = pd.to_numeric(roster[col], errors="coerce").fillna(0)
            score += vals * weight
    roster["_drop_score"] = score
    roster = roster.sort_values("_drop_score", ascending=True)
    top = roster.head(limit).copy()
    explanations = []
    for _, row in top.iterrows():
        explanations.append(_drop_explanation(row, my_roster))
    top["Why Drop"] = explanations
    name_col = _player_name_col(top)
    if name_col != "Player":
        top["Player"] = top[name_col]
    return top.drop(columns=["_drop_score"], errors="ignore")


def get_pending_add_targets(session: dict[str, Any]) -> list[dict[str, Any]]:
    context = get_active_league_context(session)
    if not context:
        return []
    return get_workflow_targets(context, TRADE_MODE_ADD)


def get_pending_drop_candidates(session: dict[str, Any]) -> list[dict[str, Any]]:
    context = get_active_league_context(session)
    if not context:
        return []
    return get_workflow_targets(context, TRADE_MODE_DROP)


def add_pending_move(
    session: dict[str, Any],
    mode: str,
    player_name: str,
    *,
    owner_team: str = "",
) -> bool:
    context = get_active_league_context(session)
    if not context:
        return False
    league_context_id = str(context.get("league_context_id") or "").strip()
    if not league_context_id:
        return False
    my_team = str(context.get("my_team_name") or owner_team or "").strip()
    owner = my_team if mode == TRADE_MODE_DROP else owner_team
    add_workflow_target(session, league_context_id, mode, player_name, owner_team=owner)
    return True


def remove_pending_move(session: dict[str, Any], mode: str, player_name: str) -> bool:
    context = get_active_league_context(session)
    if not context:
        return False
    league_context_id = str(context.get("league_context_id") or "").strip()
    if not league_context_id:
        return False
    remove_workflow_target(session, league_context_id, mode, player_name)
    return True


def _remove_player_from_team_roster(context: dict[str, Any], team_name: str, player_name: str) -> bool:
    league_rosters = context.get("league_rosters") or {}
    if not isinstance(league_rosters, dict):
        return False
    entry = league_rosters.get(team_name)
    if not isinstance(entry, dict):
        return False
    remove_key = normalize_player_key(player_name)
    players = [dict(p) for p in (entry.get("players") or []) if isinstance(p, dict)]
    kept = [p for p in players if str(p.get("player_key") or normalize_player_key(p.get("player_name"))) != remove_key]
    if len(kept) == len(players):
        return False
    entry["players"] = kept
    league_rosters[team_name] = entry
    context["league_rosters"] = league_rosters
    return True


def _add_player_to_team_roster(
    context: dict[str, Any],
    team_name: str,
    player_name: str,
    *,
    positions: list[str] | None = None,
) -> bool:
    league_rosters = context.get("league_rosters") or {}
    if not isinstance(league_rosters, dict):
        return False
    entry = league_rosters.setdefault(
        team_name,
        {"team_name": team_name, "is_user_team": team_name == str(context.get("my_team_name") or ""), "players": []},
    )
    players = [dict(p) for p in (entry.get("players") or []) if isinstance(p, dict)]
    player_key = normalize_player_key(player_name)
    if any(str(p.get("player_key") or "") == player_key for p in players):
        return False
    players.append(
        {
            "player_name": player_name,
            "player_key": player_key,
            "positions": list(positions or []),
            "team_name": team_name,
        }
    )
    entry["players"] = players
    league_rosters[team_name] = entry
    context["league_rosters"] = league_rosters
    return True


def record_league_activity(
    session: dict[str, Any],
    *,
    team_name: str,
    action: str,
    player_name: str,
) -> dict[str, Any] | None:
    """Record a league add/drop and update ownership map (planner — no claim rules)."""
    context = get_active_league_context(session)
    if not context:
        return None
    league_context_id = str(context.get("league_context_id") or "").strip()
    if not league_context_id:
        return None
    context = get_league_context(session, league_context_id)
    if not context:
        return None
    team = str(team_name or "").strip()
    player = str(player_name or "").strip()
    action_norm = str(action or "").strip().lower()
    if not team or not player or action_norm not in ("add", "drop"):
        return None

    changed = False
    if action_norm == "drop":
        changed = _remove_player_from_team_roster(context, team, player)
    else:
        changed = _add_player_to_team_roster(context, team, player)

    workflow = context.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        workflow = {}
        context["workflow"] = workflow
    activity = list(workflow.get(WORKFLOW_KEY_LEAGUE_ACTIVITY) or [])
    activity.append(
        {
            "team_name": team,
            "action": action_norm,
            "player_name": player,
            "recorded_at": _utc_now_iso(),
        }
    )
    workflow[WORKFLOW_KEY_LEAGUE_ACTIVITY] = activity[-50:]
    context["workflow"] = workflow
    if changed or activity:
        return upsert_league_context(session, context)
    return context


def get_league_activity(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not context:
        return []
    workflow = context.get("workflow") or {}
    raw = workflow.get(WORKFLOW_KEY_LEAGUE_ACTIVITY) or []
    return [dict(x) for x in raw if isinstance(x, dict)]
