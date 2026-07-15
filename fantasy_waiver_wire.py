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
RATE_CATEGORIES = frozenset({"AVG", "OBP", "SLG", "OPS", "BA"})
WAIVER_PENDING_PAIRS_KEY = "_waiver_pending_move_pairs"
WAIVER_PLANNER_ADD_KEY = "waiver_planner_add_pick"
WAIVER_PLANNER_DROP_KEY = "waiver_planner_drop_pick"
WAIVER_TX_FLASH_KEY = "_waiver_tx_ui_flash"
MAX_WAIVER_MOVE_PAIRS = 2
WAIVER_TX_MODE_ADD_ONLY = "add_only"
WAIVER_TX_MODE_ADD_DROP = "add_drop"
WAIVER_TX_MODE_CLEANUP = "cleanup_required"
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


def set_waiver_tx_flash(session: dict[str, Any], *, level: str, message: str) -> None:
    session[WAIVER_TX_FLASH_KEY] = {"level": str(level or "info"), "message": str(message or "")}
    try:
        import streamlit as st
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="waiver_tx_flash")
    except Exception:
        pass


def pop_waiver_tx_flash(session: dict[str, Any]) -> dict[str, str] | None:
    flash = session.pop(WAIVER_TX_FLASH_KEY, None)
    return flash if isinstance(flash, dict) else None


def _is_player_rostered(context: dict[str, Any], player_name: str) -> bool:
    """True when player_name matches an owned roster slot (display or normalized key)."""
    name = str(player_name or "").strip()
    if not name:
        return False
    if name in rostered_player_names(context):
        return True
    target_key = normalize_player_key(name)
    ownership = context.get("ownership_map") or build_ownership_map(context)
    return target_key in ownership


def _find_roster_player_index(players: list[dict[str, Any]], player_name: str) -> int | None:
    """Match roster entry by display name or normalized player key."""
    target = str(player_name or "").strip()
    if not target:
        return None
    target_key = normalize_player_key(target)
    for i, player in enumerate(players):
        if not isinstance(player, dict):
            continue
        pname = str(player.get("player_name") or "").strip()
        if pname == target:
            return i
        pkey = str(player.get("player_key") or normalize_player_key(pname)).strip()
        if pkey and pkey == target_key:
            return i
    return None


def sync_waiver_roster_views(
    session: dict[str, Any],
    *,
    stats_pool: pd.DataFrame | None = None,
    normalize_name_fn=None,
) -> None:
    """Refresh cached league roster dataframe after waiver transactions."""
    context = get_active_league_context(session)
    if not context:
        return
    _clear_waiver_transaction_caches(session)
    if stats_pool is None or getattr(stats_pool, "empty", True):
        return
    name_fn = normalize_name_fn or normalize_player_key
    try:
        from fantasy_league_context import build_roster_stats_from_league_context, has_full_league_rosters

        if has_full_league_rosters(context):
            session["fantasy_current_roster_stats"] = build_roster_stats_from_league_context(
                context,
                stats_pool,
                normalize_name_fn=name_fn,
            )
    except Exception:
        pass


def research_league_sync_enabled(session: dict[str, Any]) -> bool:
    """When ON, research pages exclude active-league rostered players."""
    return bool(session.get(FANTASY_RESEARCH_SYNC_KEY))


def waiver_filter_enabled(session: dict[str, Any]) -> bool:
    return research_league_sync_enabled(session)


def rostered_player_keys(context: dict[str, Any] | None) -> set[str]:
    if not context:
        return set()
    # Always rebuild from league_rosters — stale ownership_map can keep traded players "available".
    ownership = build_ownership_map(context)
    return {str(k).strip() for k in ownership.keys() if str(k).strip()}


def rostered_player_names(context: dict[str, Any] | None) -> set[str]:
    if not context:
        return set()
    ownership = build_ownership_map(context)
    names: set[str] = set()
    for rec in ownership.values():
        if not isinstance(rec, dict):
            continue
        name = str(rec.get("player_name") or "").strip()
        if name:
            names.add(name)
    return names


def _player_identity_keys(name: Any) -> set[str]:
    """Matching keys that absorb accent / spacing differences (José vs Jose)."""
    raw = str(name or "").strip()
    if not raw:
        return set()
    keys = {raw.lower(), normalize_player_key(raw)}
    try:
        from player_name_normalization import normalize_player_name_for_merge

        folded = str(normalize_player_name_for_merge(raw) or "").strip().lower()
        if folded:
            keys.add(folded)
    except ImportError:
        pass
    return {k for k in keys if k}


def rostered_identity_keys(context: dict[str, Any] | None) -> set[str]:
    """All identity keys for every rostered player across every league team."""
    if not context:
        return set()
    ownership = build_ownership_map(context)
    keys: set[str] = set()
    for player_key, rec in ownership.items():
        pk = str(player_key or "").strip().lower()
        if pk:
            keys.add(pk)
            keys |= _player_identity_keys(pk)
        if isinstance(rec, dict):
            keys |= _player_identity_keys(rec.get("player_name"))
    return keys


def _player_name_col(df: pd.DataFrame) -> str:
    for col in ("fullName", "Player", "player_name", "name"):
        if col in df.columns:
            return col
    return "fullName"


def _filter_pool_to_league_positions(pool: pd.DataFrame, context: dict[str, Any] | None) -> pd.DataFrame:
    """Drop players who cannot fill any configured roster slot (e.g. OF when league is 1B/3B only)."""
    if pool is None or getattr(pool, "empty", True) or not context:
        return pool if isinstance(pool, pd.DataFrame) else pd.DataFrame()
    try:
        from fantasy_league_context import resolve_context_draft_slot_config
        from live_draft_roster_slots import filter_candidates_to_legal_roster_positions

        cfg = resolve_context_draft_slot_config(context)
        if not (cfg.get("slots") or cfg.get("slot_instances")):
            return pool
        return filter_candidates_to_legal_roster_positions(
            pool,
            config=cfg,
            respect_league_remaining_demand=False,
        )
    except Exception:
        return pool


def build_waiver_pool(
    player_pool: pd.DataFrame,
    context: dict[str, Any] | None,
) -> pd.DataFrame:
    """Available players = active pool minus anyone rostered on ANY team in the league."""
    if player_pool is None or getattr(player_pool, "empty", True):
        return pd.DataFrame()
    if not context:
        return pd.DataFrame()
    league_rosters = context.get("league_rosters") or {}
    if not isinstance(league_rosters, dict) or len(league_rosters) < 1:
        return pd.DataFrame()
    pool = player_pool.copy()
    name_col = _player_name_col(pool)
    if name_col not in pool.columns:
        return pool
    rostered = rostered_identity_keys(context)
    if rostered:
        mask = pool[name_col].astype(str).map(lambda n: bool(_player_identity_keys(n) & rostered))
        pool = pool.loc[~mask].copy()
    pool = _exclude_pitchers_for_context(pool, context)
    pool = _filter_pool_to_league_positions(pool, context)
    return pool.reset_index(drop=True)


def _exclude_pitchers_for_context(pool: pd.DataFrame, context: dict[str, Any] | None) -> pd.DataFrame:
    try:
        from live_draft_roster_slots import exclude_pitchers_when_no_pitcher_slots

        fmt = str((context or {}).get("fantasy_format") or "5x5 Roto")
        return exclude_pitchers_when_no_pitcher_slots(pool, context=context, fantasy_format=fmt)
    except ImportError:
        return pool


def filter_unrostered_players(
    session: dict[str, Any],
    df: pd.DataFrame,
    *,
    name_col: str | None = None,
    page_name: str | None = None,
) -> pd.DataFrame:
    """Exclude already-drafted players when fantasy context routing applies to this page.

    Uses the unified active-team context so the correct source is applied:
    Active League when one is selected, otherwise the Draft Assistant Simulator
    draft board. Rows for any drafted/rostered player are removed so downstream
    ranking and recommendation code recalculates on the remaining pool.

    When ``page_name`` is omitted, only Research Mode Sync gates filtering (legacy).
    """
    try:
        from fantasy_context_source import fantasy_drafted_pool_filter_applies

        if page_name:
            if not fantasy_drafted_pool_filter_applies(session, page_name):
                return df
        elif not research_league_sync_enabled(session):
            return df
    except ImportError:
        if not research_league_sync_enabled(session):
            return df
    if df is None or getattr(df, "empty", True):
        return df
    col = name_col or _player_name_col(df)
    if col not in df.columns:
        return df
    try:
        from active_team_context import resolve_active_team_context

        ctx = resolve_active_team_context(session)
        if ctx.drafted_keys:
            return ctx.available_pool(df, name_col=col)
    except Exception:
        pass
    # Fallback to Active League only (legacy behavior).
    context = get_active_league_context(session)
    if context is None:
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
    if category in LOWER_IS_BETTER_CATEGORIES or category in RATE_CATEGORIES:
        return float(vals.mean())
    return float(vals.sum())


def _clamp_league_rank(rank: int | float | None, n_teams: int) -> int | None:
    if rank is None:
        return None
    try:
        rank_i = int(rank)
    except (TypeError, ValueError):
        return None
    n = max(1, int(n_teams or 1))
    return max(1, min(rank_i, n))


def _category_rank_from_values(
    values: list[float],
    my_val: float,
    *,
    lower_is_better: bool,
    n_teams: int,
) -> int:
    if not values:
        return 1
    if lower_is_better:
        rank = sum(1 for v in values if float(v) < float(my_val)) + 1
    else:
        rank = sum(1 for v in values if float(v) > float(my_val)) + 1
    return int(_clamp_league_rank(rank, n_teams) or 1)


def _projected_league_values_after_trade(
    team_totals: dict[str, dict[str, float]],
    my_team_name: str,
    category: str,
    after_val: float,
) -> list[float]:
    if not team_totals:
        return []
    my_team = str(my_team_name or "").strip()
    values: list[float] = []
    for team, totals in team_totals.items():
        if category not in totals:
            continue
        if my_team and str(team) == my_team:
            values.append(float(after_val))
        else:
            values.append(float(totals.get(category, 0.0)))
    return values


def analyze_current_team_needs(
    my_roster: pd.DataFrame,
    league_rosters_df: pd.DataFrame,
    *,
    categories: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """
    In-season category strengths/weaknesses from current-season stat columns.

    Shared source of truth for Waiver Wire, Lineup Assistant, and future Start/Sit,
    trade, and lineup-optimization recommendations. Draft-time category logic lives
    in ``draft_needs.infer_hitter_category_needs``; keep both aligned when changing
    weakness thresholds or category sets.
    """
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
    result["category_values"] = dict(my_totals)
    result["my_team_name"] = my_team_name
    result["team_category_totals"] = {str(t): dict(vals) for t, vals in team_totals.items()}
    league_values_by_cat: dict[str, list[float]] = {}
    for cat in available:
        league_values_by_cat[cat] = [
            team_totals[t].get(cat, 0.0) for t in team_totals if cat in team_totals.get(t, {})
        ]
    result["team_totals_by_category"] = league_values_by_cat

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
        rank = _clamp_league_rank(rank, result["n_teams"])
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


def build_category_action_table(
    needs: dict[str, Any],
    *,
    categories: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Lineup diagnosis table: team value, league rank, best team, gap to improve."""
    ranks = dict(needs.get("category_ranks") or {})
    values = dict(needs.get("category_values") or {})
    team_totals = dict(needs.get("team_totals_by_category") or {})
    if not ranks:
        return pd.DataFrame()
    n_teams = int(needs.get("n_teams") or 0) or max(ranks.values(), default=0)
    rows: list[dict[str, Any]] = []
    for cat in (categories or WAIVER_HITTER_CATEGORIES):
        if cat not in ranks:
            continue
        rank = int(ranks[cat])
        my_val = values.get(cat)
        league_vals = team_totals.get(cat) or []
        league_best = None
        gap = None
        if league_vals:
            nums = [float(v) for v in league_vals if v is not None]
            if nums:
                lower_better = cat in LOWER_IS_BETTER_CATEGORIES
                league_best = min(nums) if lower_better else max(nums)
                if my_val is not None:
                    gap = (float(my_val) - league_best) if lower_better else (league_best - float(my_val))
        rank_label = f"{rank}{_ordinal_suffix(rank)}"
        if n_teams > 1:
            rank_label = f"{rank_label} of {n_teams} teams"
        val_display = format_category_display_value(cat, my_val) if my_val is not None else "—"
        best_display = format_category_display_value(cat, league_best) if league_best is not None else "—"
        gap_display = format_category_display_value(cat, gap) if gap is not None else "—"
        rows.append(
            {
                "Category": cat,
                "Your Team": val_display,
                "League Rank": rank_label,
                "League Best": best_display if best_display is not None else "—",
                "Gap To Improve": gap_display if gap_display is not None else "—",
                "Status": (
                    "Strength" if cat in (needs.get("strengths") or [])
                    else "Weakness" if cat in (needs.get("weaknesses") or [])
                    else "Middle"
                ),
            }
        )
    return pd.DataFrame(rows)


def style_category_action_table(df: pd.DataFrame):
    """Green strengths / red weaknesses for lineup category table."""
    if df is None or getattr(df, "empty", True) or "Status" not in df.columns:
        return df

    def _row_style(row: pd.Series):
        status = str(row.get("Status") or "")
        if status == "Strength":
            return ["background-color: #dcfce7"] * len(row)
        if status == "Weakness":
            return ["background-color: #fee2e2"] * len(row)
        return [""] * len(row)

    styled = df.style.apply(_row_style, axis=1)
    try:
        styled = styled.hide(subset=["Status"], axis="columns")
    except Exception:
        pass
    return styled


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
    """Waiver-specific explanation — emphasize why the add helps a team weakness."""
    targets = list(needs.get("targets") or needs.get("weaknesses") or [])
    helped = categories_helped_by_player(player_row, targets)
    pos = str(player_row.get("Primary Position") or player_row.get("Position") or "").strip()
    if helped:
        primary = helped[0]
        if primary == "SB":
            return "Improves SB weakness"
        if primary in ("AVG", "OBP", "OPS"):
            return f"Improves {primary}"
        if primary in ("HR", "RBI", "R"):
            return f"Improves {primary} production"
        if pos:
            return f"Improves {pos} depth"
        return f"Improves {primary} weakness"
    if pos:
        return f"Improves {pos} depth"
    return "Solid upgrade for roster balance"


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
        weak_bits = [
            format_weakness_rank_phrase(cat, int(ranks[cat]), n_teams=n_teams)
            for cat in weaknesses[:4]
            if cat in ranks
        ]
        lines.append(
            f"Your biggest improvement opportunities: **{', '.join(weak_bits)}** — prioritize adds in these areas."
        )
    if targets:
        top = targets[0]
        rank = ranks.get(top)
        if top in ("HR", "RBI") and rank:
            lines.append(
                f"**{top}** is your weakest category ({int(rank)}{_ordinal_suffix(int(rank))} of {n_teams}) — target power production."
            )
        elif top == "SB" and rank:
            lines.append(
                f"**SB** is your weakest category ({int(rank)}{_ordinal_suffix(int(rank))} of {n_teams}) — prioritize speed."
            )
        elif top == "SV" and rank:
            lines.append("Saves are your biggest improvement opportunity.")
        elif top == "AVG" and strengths and "SB" in weaknesses:
            lines.append("Strong average, but speed is your lowest-ranked category — target SB without sacrificing contact.")
        elif rank:
            lines.append(
                f"**{top}** is your top upgrade target ({int(rank)}{_ordinal_suffix(int(rank))} of {n_teams})."
            )

    if not lines:
        lines.append("Roster profile is balanced — target best-available upgrades.")
    return lines


def _ordinal_suffix(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def format_category_display_value(cat: str, val: Any) -> str:
    """Format counting stats as integers; rate stats with decimals."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    if cat in RATE_CATEGORIES:
        fval = float(val)
        return f"{fval:.3f}".lstrip("0") if fval < 1 else f"{fval:.3f}"
    if cat in LOWER_IS_BETTER_CATEGORIES:
        return f"{float(val):.2f}"
    return str(int(round(float(val))))


def format_weakness_rank_phrase(cat: str, rank: int | None, *, n_teams: int = 0) -> str:
    """Small-league-friendly rank phrase — avoids dramatic wording."""
    if not rank:
        return str(cat)
    suffix = _ordinal_suffix(int(rank))
    if n_teams > 1:
        return f"{cat}: {int(rank)}{suffix} of {n_teams} teams"
    return f"{cat}: {int(rank)}{suffix}"


def _player_grade_display(row: pd.Series) -> float | None:
    """Normalize Player Grade / EFV to 0–100 display scale."""
    for col in ("Player Grade", "Expected Fantasy Value", "ML Fantasy Value"):
        if col not in row.index:
            continue
        val = pd.to_numeric(row.get(col), errors="coerce")
        if pd.notna(val):
            fval = float(val)
            return fval * 100.0 if 0 < fval <= 1.5 else fval
    return None


def _roster_grade_median(roster: pd.DataFrame) -> float | None:
    for col in ("Player Grade", "Expected Fantasy Value", "ML Fantasy Value"):
        if col not in roster.columns:
            continue
        vals = pd.to_numeric(roster[col], errors="coerce")
        if vals.notna().any():
            med = float(vals.median())
            return med * 100.0 if 0 < med <= 1.5 else med
    return None


def _drop_value_score(roster: pd.DataFrame) -> pd.Series:
    """Higher score = more valuable — sort ascending for drop candidates."""
    score = pd.Series(0.0, index=roster.index)
    for col in ("Player Grade", "Expected Fantasy Value", "ML Fantasy Value"):
        if col in roster.columns:
            vals = pd.to_numeric(roster[col], errors="coerce").fillna(0)
            if vals.max() <= 1.5:
                vals = vals * 100.0
            score += vals * 0.45
            break
    for col, weight in (("proj_OPS", 0.20), ("proj_HR", 0.12), ("proj_RBI", 0.10), ("proj_SB", 0.08)):
        if col in roster.columns:
            score += pd.to_numeric(roster[col], errors="coerce").fillna(0) * weight
    if "Fantasy Edge" in roster.columns:
        score += pd.to_numeric(roster["Fantasy Edge"], errors="coerce").fillna(0) * 0.08
    for cat, weight in (("HR", 0.03), ("RBI", 0.02), ("SB", 0.02), ("OPS", 0.02)):
        col = _resolve_current_stat_col(roster, cat)
        if col:
            score += pd.to_numeric(roster[col], errors="coerce").fillna(0) * weight
    return score


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


_WAIVER_POSITION_ALIASES: dict[str, tuple[str, ...]] = {
    "C": ("C",),
    "1B": ("1B",),
    "2B": ("2B",),
    "3B": ("3B",),
    "SS": ("SS",),
    "OF": ("OF", "LF", "CF", "RF"),
    "DH": ("DH", "UTIL"),
    "P": ("P", "SP", "RP"),
}
# Missing positions dominate; weak/thin positions rank up; filled positions get little weight.
_POSITION_WEIGHT_MISSING = 1.0
_POSITION_WEIGHT_THIN = 0.55
_POSITION_WEIGHT_FILLED = 0.05
_CATEGORY_WEIGHTS = {
    "HR": 1.0,
    "RBI": 1.0,
    "R": 0.85,
    "Power": 1.0,
    "Run Production": 0.95,
    "SB": 1.0,
    "Speed": 1.0,
    "AVG": 0.95,
    "BA": 0.95,
    "OBP": 0.85,
    "OPS": 0.85,
    "Walks/OPS": 0.85,
}


def _row_positions(row: pd.Series) -> set[str]:
    tokens: set[str] = set()
    for col in ("positions", "Primary Position", "Position", "primaryPos", "Pos"):
        if col not in row.index:
            continue
        val = row.get(col)
        if val is None:
            continue
        if isinstance(val, (list, tuple, set)):
            raw = [str(v) for v in val]
        else:
            raw = str(val).replace("/", ",").replace(";", ",").split(",")
        for tok in raw:
            s = tok.strip().upper()
            if s:
                tokens.add(s)
    return tokens


def _player_eligible_at(row: pd.Series, position: str) -> bool:
    aliases = _WAIVER_POSITION_ALIASES.get(str(position).strip().upper(), (str(position).strip().upper(),))
    return bool(_row_positions(row) & set(aliases))


def _required_position_counts(context: dict[str, Any] | None) -> dict[str, int]:
    if not context:
        return {}
    try:
        from fantasy_league_context import resolve_context_draft_slot_config
        from live_draft_roster_slots import get_required_position_counts

        cfg = resolve_context_draft_slot_config(context)
        if cfg.get("slots"):
            return {str(k).strip().upper(): int(v or 0) for k, v in get_required_position_counts(cfg).items()}
    except Exception:
        pass
    return {}


def _filled_position_counts(my_roster: pd.DataFrame) -> dict[str, int]:
    counts: dict[str, int] = {}
    if my_roster is None or getattr(my_roster, "empty", True):
        return counts
    for _, row in my_roster.iterrows():
        for pos in _row_positions(row):
            for base, aliases in _WAIVER_POSITION_ALIASES.items():
                if pos in aliases:
                    counts[base] = counts.get(base, 0) + 1
                    break
    return counts


def compute_position_need_weights(
    context: dict[str, Any] | None,
    my_roster: pd.DataFrame,
) -> dict[str, float]:
    """Per-position recommendation weight for the active team's waiver needs.

    - Missing positions (0 filled where required) receive the highest weight so
      catchers/first-basemen dominate when the roster has none.
    - Thin positions (filled < required) receive an elevated weight.
    - Fully filled / strong positions receive a small weight so quality still
      matters but they no longer dominate.

    When the context has no slot rules, falls back to relative scarcity by how many
    of each position the roster already carries.
    """
    required = _required_position_counts(context)
    filled = _filled_position_counts(my_roster)
    weights: dict[str, float] = {}
    if required:
        for pos, need in required.items():
            if need <= 0:
                continue
            have = filled.get(pos, 0)
            if have <= 0:
                weights[pos] = _POSITION_WEIGHT_MISSING
            elif have < need:
                shortfall = (need - have) / max(1, need)
                weights[pos] = _POSITION_WEIGHT_THIN + shortfall * (_POSITION_WEIGHT_MISSING - _POSITION_WEIGHT_THIN)
            else:
                weights[pos] = _POSITION_WEIGHT_FILLED
        return weights
    # No slot rules: weight inversely to how deep the roster already is at a spot.
    if not filled:
        return {}
    max_have = max(filled.values())
    for base in _WAIVER_POSITION_ALIASES:
        have = filled.get(base, 0)
        if have <= 0:
            weights[base] = _POSITION_WEIGHT_MISSING
        else:
            weights[base] = max(
                _POSITION_WEIGHT_FILLED,
                _POSITION_WEIGHT_MISSING * (1.0 - have / (max_have + 1)),
            )
    return weights


def _player_position_weight(row: pd.Series, position_weights: dict[str, float]) -> float:
    if not position_weights:
        return 0.0
    best = 0.0
    for pos, weight in position_weights.items():
        if _player_eligible_at(row, pos):
            best = max(best, float(weight))
    return best


def recommend_adds_personalized(
    waiver_pool: pd.DataFrame,
    needs: dict[str, Any],
    *,
    context: dict[str, Any] | None,
    my_roster: pd.DataFrame,
    limit: int = 15,
) -> pd.DataFrame:
    """Personalized waiver adds: which available players help THIS roster the most.

    Blends four signals so the ranking answers the roster's actual needs rather
    than "best available in general":

    1. **Positional need** (dominant) — missing positions first, then thin ones.
    2. **Category help** — players who help weak categories move up.
    3. **Overall quality** — Player Grade / EFV keeps elite talent relevant.
    4. **Upgrade opportunity** — quality above the roster's median at that spot.
    """
    if waiver_pool is None or getattr(waiver_pool, "empty", True):
        return pd.DataFrame()
    pool = _exclude_pitchers_for_context(waiver_pool.copy(), context)
    pool = _filter_pool_to_league_positions(pool, context)
    if pool.empty:
        return pd.DataFrame()
    targets = list(needs.get("targets") or needs.get("weaknesses") or [])
    position_weights = compute_position_need_weights(context, my_roster)
    roster_grade_med = _roster_grade_median(my_roster) if my_roster is not None else None

    # When the league has explicit slots, do not rank players who can't fill any of them.
    if position_weights:
        eligible_mask = pool.apply(lambda r: _player_position_weight(r, position_weights) > 0, axis=1)
        if eligible_mask.any():
            pool = pool.loc[eligible_mask].copy()
        if pool.empty:
            return pd.DataFrame()

    pos_component = pd.Series(0.0, index=pool.index)
    cat_component = pd.Series(0.0, index=pool.index)
    quality_component = pd.Series(0.0, index=pool.index)

    if position_weights:
        pos_component = pool.apply(lambda r: _player_position_weight(r, position_weights), axis=1)

    for cat in targets:
        vals = _category_value_series_for_waiver(pool, cat)
        if vals is None:
            continue
        vmax = float(vals.max()) or 1.0
        normalized = vals.fillna(0) / vmax
        if cat in LOWER_IS_BETTER_CATEGORIES:
            normalized = 1.0 - normalized
        cat_weight = float(_CATEGORY_WEIGHTS.get(str(cat).strip(), 0.85))
        cat_component = cat_component + (normalized * cat_weight)

    grade = pool.apply(lambda r: _player_grade_display(r) or 0.0, axis=1)
    gmax = float(grade.max()) or 1.0
    quality_component = grade / gmax

    has_missing_positions = any(weight >= _POSITION_WEIGHT_MISSING for weight in position_weights.values())
    pos_multiplier = 12.0 if has_missing_positions else 3.5
    cat_multiplier = 2.5
    quality_multiplier = 0.2 if has_missing_positions else 1.0

    # Positional need dominates when roster holes exist; category needs follow.
    score = (
        pos_component * pos_multiplier
        + cat_component * cat_multiplier
        + quality_component * quality_multiplier
    )

    if roster_grade_med:
        upgrade = grade.apply(lambda g: 0.4 if g and g > roster_grade_med else 0.0)
        score = score + upgrade

    pool["_waiver_add_score"] = score
    pool["_position_need_weight"] = pos_component
    pool = pool.sort_values(["_position_need_weight", "_waiver_add_score"], ascending=[False, False])
    top = pool.head(limit).copy()
    top["Why Add"] = [
        _personalized_add_explanation(row, needs, position_weights)
        for _, row in top.iterrows()
    ]
    top["Categories Helped"] = [
        ", ".join(categories_helped_by_player(row, targets)) or "Balance"
        for _, row in top.iterrows()
    ]
    name_col = _player_name_col(top)
    if name_col != "Player" and "Player" not in top.columns:
        top["Player"] = top[name_col]
    return top.drop(columns=["_waiver_add_score", "_position_need_weight"], errors="ignore")


def _category_value_series_for_waiver(pool: pd.DataFrame, category: str) -> pd.Series | None:
    """Current-season stats first, then projected columns for waiver scoring."""
    col = _resolve_current_stat_col(pool, category)
    if col:
        vals = pd.to_numeric(pool[col], errors="coerce")
        if vals.notna().any():
            return vals
    try:
        from active_team_context import _category_value_series

        return _category_value_series(pool, category)
    except Exception:
        return None


def _personalized_add_explanation(
    player_row: pd.Series,
    needs: dict[str, Any],
    position_weights: dict[str, float],
) -> str:
    """Explain the add, leading with the strongest personalized reason."""
    targets = list(needs.get("targets") or needs.get("weaknesses") or [])
    helped_cats = categories_helped_by_player(player_row, targets)
    if helped_cats:
        primary = helped_cats[0]
        if primary in ("HR", "RBI", "R"):
            return f"Improves {primary} production (team weakness)"
        if primary == "SB":
            return "Improves SB weakness — speed upgrade"
        if primary in ("AVG", "OBP", "OPS"):
            return f"Improves {primary} (team weakness)"
    eligible_needed = [
        pos
        for pos, weight in sorted(position_weights.items(), key=lambda kv: kv[1], reverse=True)
        if weight >= _POSITION_WEIGHT_THIN and _player_eligible_at(player_row, pos)
    ]
    if eligible_needed:
        top_pos = eligible_needed[0]
        weight = position_weights.get(top_pos, 0.0)
        if weight >= _POSITION_WEIGHT_MISSING:
            return f"Fills an empty {top_pos} spot on your roster"
        return f"Upgrades your thin {top_pos} depth"
    return build_add_recommendation_explanation(player_row, needs)


def _is_roster_star(player_row: pd.Series, roster: pd.DataFrame) -> bool:
    """Protect elite roster anchors from drop recommendations."""
    grade = _player_grade_display(player_row)
    grades = [_player_grade_display(row) for _, row in roster.iterrows()]
    grades = [g for g in grades if g is not None]
    if grade is not None and grades:
        sorted_grades = sorted(grades, reverse=True)
        top_cutoff = sorted_grades[max(0, min(len(sorted_grades) - 1, max(1, len(sorted_grades) // 4)))]
        if grade >= top_cutoff:
            return True
    for cat in ("HR", "RBI", "R", "SB"):
        col = _resolve_current_stat_col(roster, cat)
        if not col or col not in player_row.index:
            continue
        val = pd.to_numeric(player_row.get(col), errors="coerce")
        roster_vals = pd.to_numeric(roster[col], errors="coerce")
        if pd.notna(val) and roster_vals.notna().any() and float(val) >= float(roster_vals.max()) * 0.88:
            return True
    if "proj_OPS" in player_row.index and "proj_OPS" in roster.columns:
        val = pd.to_numeric(player_row.get("proj_OPS"), errors="coerce")
        med = pd.to_numeric(roster["proj_OPS"], errors="coerce").median()
        if pd.notna(val) and pd.notna(med) and float(val) >= float(med) * 1.12:
            return True
    return False


def _is_bench_or_replacement(player_row: pd.Series, roster: pd.DataFrame) -> bool:
    """Prefer dropping bench-level or blocked roster spots."""
    scores = _drop_value_score(roster)
    if scores.empty:
        return False
    player_score = float(_drop_value_score(player_row.to_frame().T).iloc[0])
    if player_score <= float(scores.quantile(0.35)):
        return True
    pos = str(player_row.get("Primary Position") or player_row.get("position") or "").strip()
    if pos and "Primary Position" in roster.columns:
        same = roster[roster["Primary Position"].astype(str) == pos]
        if len(same) > 1:
            pos_scores = _drop_value_score(same)
            if player_score <= float(pos_scores.min()) * 1.05:
                return True
    if "Fantasy Edge" in player_row.index:
        edge = pd.to_numeric(player_row.get("Fantasy Edge"), errors="coerce")
        if pd.notna(edge) and float(edge) < -2:
            return True
    return False


def recommend_drops_current(
    my_roster: pd.DataFrame,
    *,
    limit: int = 6,
    categories: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    if my_roster is None or my_roster.empty:
        return pd.DataFrame()
    roster = my_roster.copy()
    roster["_drop_score"] = _drop_value_score(roster)
    roster["_is_star"] = [_is_roster_star(row, my_roster) for _, row in roster.iterrows()]
    roster["_is_bench"] = [_is_bench_or_replacement(row, my_roster) for _, row in roster.iterrows()]
    candidates = roster[~roster["_is_star"]].copy()
    if candidates.empty:
        candidates = roster.copy()
    candidates["_bench_sort"] = (~candidates["_is_bench"]).astype(int)
    candidates = candidates.sort_values(["_bench_sort", "_drop_score"], ascending=[True, True])
    top = candidates.head(limit).copy()
    top["Why Drop"] = [_build_drop_explanation(row, my_roster) for _, row in top.iterrows()]
    name_col = _player_name_col(top)
    if name_col != "Player":
        top["Player"] = top[name_col]
    return top.drop(columns=["_drop_score", "_is_star", "_is_bench", "_bench_sort"], errors="ignore")


def _build_drop_explanation(player_row: pd.Series, my_roster: pd.DataFrame) -> str:
    """One concise fantasy-analyst drop reason — prefer bench, injured, replacement-level."""
    pos = str(player_row.get("Primary Position") or player_row.get("position") or "").strip()
    for col in ("Injury", "injury_status", "Status", "IL Status"):
        if col in player_row.index:
            status = str(player_row.get(col) or "").strip().lower()
            if status and any(token in status for token in ("il", "inj", "out", "dtd", "disabled")):
                return "Injured or limited — lowest immediate roster value."

    if _is_bench_or_replacement(player_row, my_roster):
        if pos and "Primary Position" in my_roster.columns:
            same = my_roster[my_roster["Primary Position"].astype(str) == pos]
            if len(same) > 1:
                return f"Bench-level {pos} with stronger starters available."
        return "Replacement-level bench option."

    grade = _player_grade_display(player_row)
    med_grade = _roster_grade_median(my_roster)

    if grade is not None and med_grade is not None and grade < med_grade * 0.85:
        if pos:
            same_pos = my_roster[my_roster["Primary Position"].astype(str) == pos] if "Primary Position" in my_roster.columns else my_roster
            if len(same_pos) > 1:
                pos_grades = [_player_grade_display(r) for _, r in same_pos.iterrows()]
                pos_grades = [g for g in pos_grades if g is not None]
                if pos_grades and grade <= min(pos_grades):
                    return f"Lowest Player Grade among active {pos} options."
        return "Lowest Player Grade on roster."

    if "proj_OPS" in player_row.index and "proj_OPS" in my_roster.columns:
        val = pd.to_numeric(player_row.get("proj_OPS"), errors="coerce")
        med = pd.to_numeric(my_roster["proj_OPS"], errors="coerce").median()
        if pd.notna(val) and pd.notna(med) and float(val) < float(med) * 0.80:
            if pos:
                return f"Lowest projected rest-of-season value among active {pos}."
            return "Lowest projected rest-of-season value on roster."

    if pos and "Primary Position" in my_roster.columns:
        same = my_roster[my_roster["Primary Position"].astype(str) == pos]
        if len(same) > 2:
            return f"Blocked by stronger players at {pos}."

    weak_cats: list[str] = []
    for cat in ("HR", "RBI", "R", "SB"):
        col = _resolve_current_stat_col(player_row.to_frame().T, cat)
        if not col or col not in my_roster.columns:
            continue
        val = pd.to_numeric(player_row.get(col), errors="coerce")
        med = pd.to_numeric(my_roster[col], errors="coerce").median()
        if pd.notna(val) and pd.notna(med) and float(val) < float(med) * 0.65:
            weak_cats.append(cat)
    if weak_cats:
        return f"Limited {'/'.join(weak_cats[:2])} contribution relative to alternatives."

    if "Fantasy Edge" in player_row.index:
        edge = pd.to_numeric(player_row.get("Fantasy Edge"), errors="coerce")
        if pd.notna(edge) and float(edge) < -3:
            return "Replacement-level value vs market."

    return "Replacement-level alternatives provide more category value."


def _drop_explanation_current(player_row: pd.Series, my_roster: pd.DataFrame) -> str:
    """Backward-compatible alias."""
    return _build_drop_explanation(player_row, my_roster)


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


def _apply_names_to_roster_df(
    roster: pd.DataFrame,
    add_names: list[str],
    drop_names: list[str],
    *,
    stats_pool: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if roster is None or getattr(roster, "empty", True):
        return pd.DataFrame()
    working = roster.copy()
    name_col = _player_name_col(working)
    if not name_col:
        return working
    drop_set = {str(n).strip() for n in drop_names if str(n).strip()}
    working = working[~working[name_col].astype(str).str.strip().isin(drop_set)]
    add_rows: list[dict[str, Any]] = []
    for add_name in add_names:
        add_name = str(add_name or "").strip()
        if not add_name:
            continue
        row = _row_for_player_name(stats_pool, add_name) if stats_pool is not None else None
        if row is not None:
            add_rows.append(row.to_dict())
        else:
            add_rows.append({"Player": add_name, "fullName": add_name})
    if add_rows:
        working = pd.concat([working, pd.DataFrame(add_rows)], ignore_index=True)
    return working


def _team_category_totals(
    roster: pd.DataFrame,
    categories: tuple[str, ...] | None = None,
) -> dict[str, float]:
    cats = list(categories or WAIVER_HITTER_CATEGORIES)
    totals: dict[str, float] = {}
    if roster is None or getattr(roster, "empty", True):
        return totals
    for cat in cats:
        val = _category_value_for_team(roster, cat)
        if val is not None:
            totals[cat] = float(val)
    return totals


def _format_impact_delta(cat: str, before: float, after: float) -> str:
    delta = after - before
    if cat in RATE_CATEGORIES:
        sign = "+" if delta >= 0 else ""
        return f"{sign}{delta:.3f}"
    if cat in LOWER_IS_BETTER_CATEGORIES:
        sign = "+" if delta <= 0 else ""
        return f"{sign}{delta:.2f}"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{int(round(delta))}"


def compute_waiver_transaction_impact(
    my_roster: pd.DataFrame,
    add_names: list[str],
    drop_names: list[str],
    *,
    stats_pool: pd.DataFrame | None = None,
    needs: dict[str, Any] | None = None,
    categories: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Project category totals and ranks before/after a waiver transaction."""
    needs = needs or {}
    cats = tuple(categories or needs.get("available_categories") or WAIVER_HITTER_CATEGORIES)
    before_totals = dict(needs.get("category_values") or _team_category_totals(my_roster, cats))
    after_roster = _apply_names_to_roster_df(my_roster, add_names, drop_names, stats_pool=stats_pool)
    after_totals = _team_category_totals(after_roster, cats)
    ranks_before = dict(needs.get("category_ranks") or {})
    league_values = dict(needs.get("team_totals_by_category") or {})
    team_totals = dict(needs.get("team_category_totals") or {})
    my_team_name = str(needs.get("my_team_name") or "").strip()
    if not my_team_name and my_roster is not None and not getattr(my_roster, "empty", True):
        if "Team" in my_roster.columns:
            my_team_name = str(my_roster["Team"].iloc[0])
    n_teams = int(needs.get("n_teams") or 0)
    if not n_teams and team_totals:
        n_teams = len(team_totals)
    if not n_teams and league_values:
        n_teams = max(len(v) for v in league_values.values() if v)

    rows: list[dict[str, str]] = []
    gain_scores: list[tuple[str, float]] = []
    loss_scores: list[tuple[str, float]] = []

    for cat in cats:
        before = before_totals.get(cat)
        after = after_totals.get(cat)
        if before is None and after is None:
            continue
        before_val = float(before if before is not None else 0.0)
        after_val = float(after if after is not None else 0.0)
        delta = after_val - before_val
        lower_is_better = cat in LOWER_IS_BETTER_CATEGORIES
        rank_before = ranks_before.get(cat)
        if rank_before is not None:
            rank_before = _clamp_league_rank(rank_before, n_teams)
        rank_after = rank_before
        if team_totals and my_team_name:
            proj_values = _projected_league_values_after_trade(
                team_totals,
                my_team_name,
                cat,
                after_val,
            )
            if proj_values:
                rank_after = _category_rank_from_values(
                    proj_values,
                    after_val,
                    lower_is_better=lower_is_better,
                    n_teams=n_teams or len(proj_values),
                )
        else:
            values = list(league_values.get(cat) or [])
            if values:
                adjusted = list(values)
                if before is not None:
                    for idx, val in enumerate(adjusted):
                        if abs(float(val) - before_val) < 1e-9:
                            adjusted[idx] = after_val
                            break
                    else:
                        adjusted.append(after_val)
                rank_after = _category_rank_from_values(
                    adjusted,
                    after_val,
                    lower_is_better=lower_is_better,
                    n_teams=n_teams or len(adjusted),
                )
        rows.append(
            {
                "Category": cat,
                "Before": format_category_display_value(cat, before_val),
                "After": format_category_display_value(cat, after_val),
                "Change": _format_impact_delta(cat, before_val, after_val),
                "Rank Before": str(rank_before) if rank_before else "—",
                "Rank After": str(rank_after) if rank_after else "—",
            }
        )
        if lower_is_better:
            score = before_val - after_val
        else:
            score = delta
        if score > 0.001 or (cat in RATE_CATEGORIES and score > 0.0005):
            gain_scores.append((cat, score))
        elif score < -0.001 or (cat in RATE_CATEGORIES and score < -0.0005):
            loss_scores.append((cat, abs(score)))

    biggest_gain = ""
    if gain_scores:
        gain_scores.sort(key=lambda item: item[1], reverse=True)
        biggest_gain = gain_scores[0][0]
    biggest_loss = ""
    if loss_scores:
        loss_scores.sort(key=lambda item: item[1], reverse=True)
        biggest_loss = loss_scores[0][0]

    return {
        "rows": rows,
        "before_totals": before_totals,
        "after_totals": after_totals,
        "biggest_gain": biggest_gain,
        "biggest_loss": biggest_loss,
    }


def _clear_waiver_transaction_caches(session: dict[str, Any]) -> None:
    try:
        from fantasy_perf_cache import (
            LINEUP_DIAGNOSIS_CACHE_KEY,
            LINEUP_SCORES_CACHE_KEY,
            STANDINGS_ROSTER_CACHE_KEY,
            WAIVER_ANALYSIS_CACHE_KEY,
        )

        session.pop(STANDINGS_ROSTER_CACHE_KEY, None)
        session.pop(LINEUP_SCORES_CACHE_KEY, None)
        session.pop(WAIVER_ANALYSIS_CACHE_KEY, None)
        session.pop(LINEUP_DIAGNOSIS_CACHE_KEY, None)
    except ImportError:
        pass


def _row_for_player_name(df: pd.DataFrame, name: str) -> pd.Series | None:
    target = str(name or "").strip()
    if not target or df is None or getattr(df, "empty", True):
        return None
    for col in ("Player", "fullName", "player_name"):
        if col not in df.columns:
            continue
        match = df[df[col].astype(str).str.strip() == target]
        if not match.empty:
            return match.iloc[0]
    return None


def _player_entry_from_name(
    player_name: str,
    *,
    team_name: str,
    stats_pool: pd.DataFrame | None = None,
) -> dict[str, Any]:
    from fantasy_league_context import _normalize_player_entry

    row = _row_for_player_name(stats_pool, player_name) if stats_pool is not None else None
    if row is not None:
        return _normalize_player_entry(row.to_dict(), team_name=team_name)
    return _normalize_player_entry({"fullName": player_name, "Player": player_name}, team_name=team_name)


def waiver_roster_transaction_mode(context: dict[str, Any] | None, roster_size: int) -> str:
    """Whether waiver moves need add-only, matched add/drop, or roster cleanup."""
    try:
        from fantasy_league_lineup_format import roster_capacity_from_format
        from fantasy_weekly_lineup import resolve_weekly_lineup_slots

        capacity = roster_capacity_from_format(context)
        if capacity is None:
            slots = resolve_weekly_lineup_slots(context)
            capacity = len(slots) if slots else roster_size
    except ImportError:
        capacity = roster_size
    if roster_size < capacity:
        return WAIVER_TX_MODE_ADD_ONLY
    if roster_size == capacity:
        return WAIVER_TX_MODE_ADD_DROP
    return WAIVER_TX_MODE_CLEANUP


def apply_waiver_move_pairs(
    session: dict[str, Any],
    pairs: list[dict[str, Any]],
    *,
    stats_pool: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Execute matched add/drop pairs on the active league context roster."""
    result: dict[str, Any] = {
        "ok": False,
        "applied": 0,
        "errors": [],
        "position_warnings": [],
        "moves": [],
    }
    context = get_active_league_context(session)
    if not context:
        result["errors"].append("No active league context.")
        return result
    if not pairs:
        result["errors"].append("Select at least one add/drop pair.")
        return result
    if len(pairs) > MAX_WAIVER_MOVE_PAIRS:
        result["errors"].append(
            f"At most {MAX_WAIVER_MOVE_PAIRS} add/drop pairs per transaction (Add 1/Drop 1 or Add 2/Drop 2)."
        )
        return result

    my_team = str(context.get("my_team_name") or "").strip()
    league_rosters = copy.deepcopy(context.get("league_rosters") or {})
    if not isinstance(league_rosters, dict):
        league_rosters = {}
    team_entry = league_rosters.get(my_team)
    if not isinstance(team_entry, dict):
        result["errors"].append(f"Roster not found for {my_team or 'your team'}.")
        return result

    players = [dict(p) for p in (team_entry.get("players") or []) if isinstance(p, dict)]
    working_context = copy.deepcopy(context)
    working_context["league_rosters"] = league_rosters
    tx_mode = waiver_roster_transaction_mode(context, len(players))
    if tx_mode == WAIVER_TX_MODE_CLEANUP:
        result["errors"].append("Roster is over capacity. Drop players before adding more.")
        return result

    for pair in pairs:
        add_name = str(pair.get("add_player") or "").strip()
        drop_name = str(pair.get("drop_player") or "").strip()
        if not add_name:
            result["errors"].append("Each move needs a player to add.")
            continue
        if tx_mode == WAIVER_TX_MODE_ADD_DROP and not drop_name:
            result["errors"].append("Roster is full. Each add needs a matching drop.")
            continue
        if add_name == drop_name:
            result["errors"].append(f"Add and drop cannot be the same player: {add_name}")
            continue
        if _is_player_rostered(working_context, add_name):
            result["errors"].append(f"{add_name} is already rostered.")
            continue
        drop_idx = None
        if drop_name:
            drop_idx = _find_roster_player_index(players, drop_name)
            if drop_idx is None:
                result["errors"].append(f"{drop_name} is not on your roster.")
                continue
        new_player = _player_entry_from_name(add_name, team_name=my_team, stats_pool=stats_pool)
        if drop_idx is not None:
            players.pop(drop_idx)
        players.append(new_player)
        team_entry["players"] = players
        league_rosters[my_team] = team_entry
        working_context["league_rosters"] = league_rosters
        working_context["ownership_map"] = build_ownership_map(working_context)
        result["moves"].append({"add_player": add_name, "drop_player": drop_name})
        result["applied"] += 1

    if result["applied"] <= 0:
        return result

    workflow = context.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        workflow = {}
    activity = list(workflow.get(WORKFLOW_KEY_LEAGUE_ACTIVITY) or [])
    now = _utc_now_iso()
    for move in result["moves"]:
        activity.append(
            {
                "team_name": my_team,
                "action": "add",
                "player_name": move["add_player"],
                "paired_drop": move["drop_player"],
                "recorded_at": now,
            }
        )
        activity.append(
            {
                "team_name": my_team,
                "action": "drop",
                "player_name": move["drop_player"],
                "paired_add": move["add_player"],
                "recorded_at": now,
            }
        )
    workflow[WORKFLOW_KEY_LEAGUE_ACTIVITY] = activity[-50:]
    context["workflow"] = workflow
    context["league_rosters"] = league_rosters
    context = upsert_league_context(session, context)

    draft_id = str(context.get("source_draft_id") or "").strip()
    if not draft_id:
        try:
            from draft_archive_state import get_active_draft_archive

            active = get_active_draft_archive(session)
            if isinstance(active, dict):
                draft_id = str(active.get("draft_id") or "").strip()
        except ImportError:
            pass
    if draft_id:
        try:
            from fantasy_league_context import save_draft_archive_with_league_context

            save_draft_archive_with_league_context(
                session,
                draft_id=draft_id,
                league_rosters=league_rosters,
                league_context_id=str(context.get("league_context_id") or ""),
            )
        except ImportError:
            pass

    my_roster_df = my_team_roster_dataframe(context)
    try:
        from fantasy_league_context import context_has_roster_slots, resolve_context_open_position_needs

        if context_has_roster_slots(context):
            open_slots = resolve_context_open_position_needs(context, my_roster_df)
            if open_slots:
                result["position_warnings"].append(
                    f"Roster has open required slots: {', '.join(open_slots)}"
                )
    except ImportError:
        pass

    session.pop(WAIVER_PENDING_PAIRS_KEY, None)
    session.pop(WAIVER_PLANNER_ADD_KEY, None)
    session.pop(WAIVER_PLANNER_DROP_KEY, None)
    _clear_waiver_transaction_caches(session)

    try:
        import streamlit as st
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="waiver_transaction")
    except Exception:
        pass
    try:
        import streamlit as st
        from suite_user_persistence import force_autosave

        force_autosave(st, reason="waiver_transaction")
    except Exception:
        pass

    result["ok"] = True
    result["added_players"] = [str(m.get("add_player") or "") for m in result["moves"]]
    result["dropped_players"] = [str(m.get("drop_player") or "") for m in result["moves"]]
    return result


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
