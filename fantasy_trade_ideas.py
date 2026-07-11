"""Generate fair trade ideas across opposing teams in the active league."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

TRADE_IDEA_CATEGORIES: tuple[str, ...] = ("HR", "RBI", "R", "SB", "BA", "OPS")
LINEUP_TRADE_IDEAS_RESULTS_KEY = "_lineup_trade_ideas_results"
LINEUP_TRADE_IDEAS_DIAG_KEY = "_lineup_trade_ideas_diag"
LINEUP_ASSISTANT_TAB_KEY = "lineup_assistant_tab"
LINEUP_ASSISTANT_TAB_OPTIONS: tuple[str, ...] = (
    "Lineup & Weekly Stats",
    "Trade Analyzer",
    "Trade Ideas",
    "Offers & Activity",
)

_EMPTY_SUGGESTIONS_MESSAGE = (
    "No suitable trade ideas were found with the current players and filters. "
    "Try selecting another player or widening the value range."
)


def _normalize_team(value: Any) -> str:
    return str(value or "").strip()


def _player_value(row: pd.Series) -> float:
    efv = pd.to_numeric(row.get("Expected Fantasy Value"), errors="coerce")
    if pd.notna(efv):
        return float(efv)
    parts: list[float] = []
    for col, weight in (("OPS", 3.0), ("BA", 2.0), ("HR", 1.5), ("RBI", 1.0), ("R", 1.0), ("SB", 1.0)):
        val = pd.to_numeric(row.get(col), errors="coerce")
        if pd.notna(val):
            parts.append(float(val) * weight)
    if parts:
        return float(sum(parts) / len(parts))
    return 0.0


def derive_category_needs(
    standings: pd.DataFrame | None,
    my_team: str,
    all_rosters: pd.DataFrame,
    *,
    summarize_team_category_needs_fn,
) -> dict[str, bool]:
    """Standings-first category needs with league-roster fallback."""
    my_team = _normalize_team(my_team)
    needs = summarize_team_category_needs_fn(standings, my_team) if callable(summarize_team_category_needs_fn) else {}
    if needs:
        return {str(k): bool(v) for k, v in needs.items()}

    try:
        from fantasy_waiver_wire import analyze_current_team_needs
    except ImportError:
        return {}

    if all_rosters is None or all_rosters.empty or "Team" not in all_rosters.columns:
        return {}

    my_roster = all_rosters[all_rosters["Team"].astype(str) == my_team]
    if my_roster.empty:
        return {}

    analysis = analyze_current_team_needs(my_roster, all_rosters)
    out: dict[str, bool] = {}
    for cat in analysis.get("weaknesses") or []:
        label = str(cat or "").strip().upper()
        if label == "AVG":
            label = "BA"
        if label in TRADE_IDEA_CATEGORIES:
            out[label] = True
    return out


def _score_one_for_one(
    mine: pd.Series,
    theirs: pd.Series,
    *,
    target_team: str,
    needs: dict[str, bool],
) -> dict[str, Any] | None:
    need_gain = 0.0
    surplus_penalty = 0.0
    reason_parts: list[str] = []
    for cat in TRADE_IDEA_CATEGORIES:
        mv = pd.to_numeric(mine.get(cat), errors="coerce")
        tv = pd.to_numeric(theirs.get(cat), errors="coerce")
        if pd.isna(mv) or pd.isna(tv):
            continue
        diff = float(tv - mv)
        rate_weight = 12.0 if cat in {"BA", "OPS"} else 1.0
        if needs.get(cat) and diff > 0:
            need_gain += diff * rate_weight
            reason_parts.append(f"helps {cat}")
        elif diff < 0:
            surplus_penalty += abs(diff) * (0.4 if needs.get(cat) else 0.02)

    if need_gain <= 0:
        return None

    mine_val = _player_value(mine)
    theirs_val = _player_value(theirs)
    fairness_gap = theirs_val - mine_val
    fit_gain = need_gain - (surplus_penalty * 0.35) - (max(0.0, abs(fairness_gap) - 6.0) * 0.05)

    mine_val = _player_value(mine)
    theirs_val = _player_value(theirs)
    fairness_gap = theirs_val - mine_val
    if fit_gain <= 0:
        return None

    fairness_note = "balanced value" if abs(fairness_gap) <= 2 else (
        "slightly favors you" if fairness_gap > 0 else "slightly favors them"
    )
    return {
        "Give": mine.get("Player"),
        "Receive": theirs.get("Player"),
        "Other Team": target_team,
        "Trade Fit Score": round(fit_gain, 2),
        "Fairness Gap": round(fairness_gap, 2) if pd.notna(fairness_gap) else np.nan,
        "Why It Helps": ", ".join(reason_parts[:4]) if reason_parts else "improves category balance",
        "Value Explanation": fairness_note,
    }


def suggest_trade_targets_for_team(
    my_team: str,
    target_team: str,
    all_rosters: pd.DataFrame,
    needs: dict[str, bool],
    *,
    max_suggestions: int = 20,
) -> pd.DataFrame:
    """Suggest one-for-one trades against a single opposing team."""
    my_team = _normalize_team(my_team)
    target_team = _normalize_team(target_team)
    if all_rosters is None or all_rosters.empty or my_team == target_team:
        return pd.DataFrame()

    my_players = all_rosters[all_rosters["Team"].astype(str) == my_team].copy()
    other_players = all_rosters[all_rosters["Team"].astype(str) == target_team].copy()
    if my_players.empty or other_players.empty:
        return pd.DataFrame()

    suggestions: list[dict[str, Any]] = []
    for _, mine in my_players.iterrows():
        for _, theirs in other_players.iterrows():
            row = _score_one_for_one(mine, theirs, target_team=target_team, needs=needs)
            if row:
                suggestions.append(row)

    out = pd.DataFrame(suggestions)
    if out.empty:
        return out
    return out.sort_values("Trade Fit Score", ascending=False).head(max_suggestions)


def filter_trade_suggestions_by_requested_players(
    suggestions: pd.DataFrame | None,
    *,
    forced_give: list[str] | None = None,
    forced_get: list[str] | None = None,
) -> pd.DataFrame:
    """Filter trade suggestions using optional user-desired give/acquire players."""
    if suggestions is None or suggestions.empty:
        return suggestions if suggestions is not None else pd.DataFrame()
    out = suggestions.copy()
    give_list = [_normalize_team(x) for x in (forced_give or []) if _normalize_team(x)]
    get_list = [_normalize_team(x) for x in (forced_get or []) if _normalize_team(x)]
    if give_list and "Give" in out.columns:
        out = out[out["Give"].astype(str).isin(give_list)]
    if get_list and "Receive" in out.columns:
        out = out[out["Receive"].astype(str).isin(get_list)]
    return out


def generate_trade_ideas(
    my_team: str,
    all_rosters: pd.DataFrame,
    standings: pd.DataFrame | None,
    *,
    forced_give: list[str] | None = None,
    forced_get: list[str] | None = None,
    target_team: str | None = None,
    summarize_team_category_needs_fn=None,
    league_context_id: str = "",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Search all opposing teams (or one target team) and return trade suggestions plus diagnostics.
    """
    my_team = _normalize_team(my_team)
    diag: dict[str, Any] = {
        "button_clicked": True,
        "selected_give_players": list(forced_give or []),
        "selected_get_players": list(forced_get or []),
        "active_league_id": str(league_context_id or "").strip() or None,
        "user_team": my_team or None,
        "opposing_teams_searched": [],
        "candidate_count_before_filters": 0,
        "candidate_count_after_filters": 0,
        "final_idea_count": 0,
        "failure_reason": None,
    }

    if all_rosters is None or all_rosters.empty:
        diag["failure_reason"] = "roster_stats_empty"
        return pd.DataFrame(), diag
    if not my_team:
        diag["failure_reason"] = "user_team_missing"
        return pd.DataFrame(), diag

    teams = sorted(all_rosters["Team"].dropna().astype(str).unique().tolist())
    if my_team not in teams:
        diag["failure_reason"] = "user_team_not_in_rosters"
        return pd.DataFrame(), diag

    opposing = [t for t in teams if t != my_team]
    if target_team:
        target_team = _normalize_team(target_team)
        if target_team and target_team != my_team:
            opposing = [t for t in opposing if t == target_team]
    diag["opposing_teams_searched"] = opposing
    if not opposing:
        diag["failure_reason"] = "no_opposing_teams"
        return pd.DataFrame(), diag

    needs = derive_category_needs(
        standings,
        my_team,
        all_rosters,
        summarize_team_category_needs_fn=summarize_team_category_needs_fn,
    )
    diag["category_needs"] = {k: v for k, v in needs.items() if v}

    chunks: list[pd.DataFrame] = []
    raw_count = 0
    for other_team in opposing:
        chunk = suggest_trade_targets_for_team(my_team, other_team, all_rosters, needs)
        if not chunk.empty:
            raw_count += len(chunk)
            chunks.append(chunk)
    diag["candidate_count_before_filters"] = raw_count

    if not chunks:
        diag["failure_reason"] = "no_positive_fit_trades" if needs else "no_category_needs_detected"
        return pd.DataFrame(), diag

    combined = pd.concat(chunks, ignore_index=True)
    combined = combined.sort_values("Trade Fit Score", ascending=False)
    filtered = filter_trade_suggestions_by_requested_players(
        combined,
        forced_give=forced_give,
        forced_get=forced_get,
    )
    diag["candidate_count_after_filters"] = len(filtered)
    if filtered.empty:
        diag["failure_reason"] = "filtered_out_by_selected_players"
        return pd.DataFrame(), diag

    final = filtered.head(20).reset_index(drop=True)
    diag["final_idea_count"] = len(final)
    return final, diag


def empty_trade_ideas_message() -> str:
    return _EMPTY_SUGGESTIONS_MESSAGE


def resolve_lineup_assistant_tab(session: dict[str, Any]) -> str:
    """Return active tab, honoring trade handoff focus flags."""
    if session.pop("_lineup_focus_trade_analyzer", False):
        session[LINEUP_ASSISTANT_TAB_KEY] = "Trade Analyzer"
    if session.pop("_lineup_focus_trade_ideas", False):
        session[LINEUP_ASSISTANT_TAB_KEY] = "Trade Ideas"
    tab = str(session.get(LINEUP_ASSISTANT_TAB_KEY) or LINEUP_ASSISTANT_TAB_OPTIONS[0]).strip()
    if tab not in LINEUP_ASSISTANT_TAB_OPTIONS:
        tab = LINEUP_ASSISTANT_TAB_OPTIONS[0]
    session[LINEUP_ASSISTANT_TAB_KEY] = tab
    return tab
