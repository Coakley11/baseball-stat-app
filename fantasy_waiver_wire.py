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
WORKFLOW_KEY_ADD_TARGETS = "add_targets"
WORKFLOW_KEY_DROP_CANDIDATES = "drop_candidates"
WORKFLOW_KEY_LEAGUE_ACTIVITY = "league_activity"
TRADE_MODE_ADD = "add"
TRADE_MODE_DROP = "drop"

ROTO_CATEGORIES = ("HR", "RBI", "SB", "AVG", "R", "S", "K", "ERA", "WHIP")
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


def waiver_filter_enabled(session: dict[str, Any]) -> bool:
    return bool(session.get(GLOBAL_WAIVER_FILTER_KEY))


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
    """Exclude active-league rostered players when global waiver filter is ON."""
    if not waiver_filter_enabled(session):
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
