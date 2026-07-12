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
    "Trade Center",
)
TRADE_CENTER_INTERNAL_TAB_KEY = "trade_center_internal_tab"
TRADE_CENTER_INTERNAL_TABS: tuple[str, ...] = (
    "Build & Analyze",
    "Offers",
    "History",
)
LINEUP_TRADE_CENTER_STATE_KEY = "_lineup_trade_center_state"
FAIRNESS_MAX_GAP = 18.0

_EMPTY_SUGGESTIONS_MESSAGE = (
    "No suitable trade ideas were found. Try widening the fairness range or selecting another player."
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


def resolve_player_owner_team(
    player_name: str,
    all_rosters: pd.DataFrame,
    *,
    my_team: str,
) -> str | None:
    """Find which opposing team owns a player on the active league roster."""
    name = _normalize_team(player_name)
    my_team = _normalize_team(my_team)
    if not name or all_rosters is None or all_rosters.empty or "Player" not in all_rosters.columns:
        return None
    if "Team" not in all_rosters.columns:
        return None
    matches = all_rosters[all_rosters["Player"].astype(str).str.strip() == name]
    if matches.empty:
        return None
    for team in matches["Team"].dropna().astype(str).unique().tolist():
        team = str(team).strip()
        if team and team != my_team:
            return team
    return None


def resolve_receive_target_teams(
    forced_get: list[str] | None,
    all_rosters: pd.DataFrame,
    *,
    my_team: str,
) -> dict[str, str]:
    """Map each acquisition target to its owning team."""
    out: dict[str, str] = {}
    for player in forced_get or []:
        owner = resolve_player_owner_team(player, all_rosters, my_team=my_team)
        if owner:
            out[str(player)] = owner
    return out


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


def _category_impact(
    mine: pd.Series,
    theirs: pd.Series,
    *,
    needs: dict[str, bool],
) -> tuple[float, list[str], list[str], list[str]]:
    need_gain = 0.0
    helps: list[str] = []
    hurts: list[str] = []
    neutral: list[str] = []
    for cat in TRADE_IDEA_CATEGORIES:
        mv = pd.to_numeric(mine.get(cat), errors="coerce")
        tv = pd.to_numeric(theirs.get(cat), errors="coerce")
        if pd.isna(mv) or pd.isna(tv):
            continue
        diff = float(tv - mv)
        rate_weight = 12.0 if cat in {"BA", "OPS"} else 1.0
        if diff > 0:
            if needs.get(cat):
                need_gain += diff * rate_weight
                helps.append(cat)
            else:
                neutral.append(cat)
        elif diff < 0:
            hurts.append(cat)
    return need_gain, helps, hurts, neutral


def _score_one_for_one(
    mine: pd.Series,
    theirs: pd.Series,
    *,
    target_team: str,
    needs: dict[str, bool],
) -> dict[str, Any] | None:
    mine_val = _player_value(mine)
    theirs_val = _player_value(theirs)
    fairness_gap = theirs_val - mine_val
    if abs(fairness_gap) > FAIRNESS_MAX_GAP:
        return None

    need_gain, helps, hurts, neutral = _category_impact(mine, theirs, needs=needs)
    fairness_score = max(0.0, 100.0 - abs(fairness_gap) * 4.5)
    fit_gain = need_gain
    overall = fairness_score * 0.55 + max(0.0, fit_gain) * 0.25 + max(-5.0, min(5.0, fairness_gap)) * 2.0

    if fairness_score < 35:
        return None

    if fairness_gap > 2:
        fairness_note = "slight advantage to you"
    elif fairness_gap < -2:
        fairness_note = "slight advantage to them"
    else:
        fairness_note = "balanced value"

    explanation_parts: list[str] = []
    if helps:
        explanation_parts.append(f"helps {', '.join(helps[:3])}")
    if hurts:
        explanation_parts.append(f"may weaken {', '.join(hurts[:3])}")
    if not helps and not hurts and neutral:
        explanation_parts.append("neutral category shift")
    if not explanation_parts:
        explanation_parts.append("fair value with limited category movement")

    risk = ""
    if hurts:
        risk = f"May weaken {hurts[0]}" + (f" and {hurts[1]}" if len(hurts) > 1 else "")

    return {
        "Give": mine.get("Player"),
        "Receive": theirs.get("Player"),
        "Other Team": target_team,
        "Trade Fit Score": round(fit_gain, 2),
        "Fairness Score": round(fairness_score, 1),
        "Overall Score": round(overall, 2),
        "Fairness Gap": round(fairness_gap, 2) if pd.notna(fairness_gap) else np.nan,
        "Why It Helps": ", ".join(explanation_parts[:4]),
        "Value Explanation": fairness_note,
        "Category Gains": ", ".join(helps[:4]) if helps else "—",
        "Category Losses": ", ".join(hurts[:4]) if hurts else "—",
        "Main Risk": risk or "Moderate roster churn",
        "Recommendation": "Fair" if fairness_score >= 70 else "Slight risk",
    }


def suggest_trade_targets_for_team(
    my_team: str,
    target_team: str,
    all_rosters: pd.DataFrame,
    needs: dict[str, bool],
    *,
    max_suggestions: int = 40,
    forced_give: list[str] | None = None,
    forced_get: list[str] | None = None,
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

    give_filter = {_normalize_team(x) for x in (forced_give or []) if _normalize_team(x)}
    get_filter = {_normalize_team(x) for x in (forced_get or []) if _normalize_team(x)}
    if give_filter:
        my_players = my_players[my_players["Player"].astype(str).isin(give_filter)]
    if get_filter:
        other_players = other_players[other_players["Player"].astype(str).isin(get_filter)]

    suggestions: list[dict[str, Any]] = []
    for _, mine in my_players.iterrows():
        for _, theirs in other_players.iterrows():
            row = _score_one_for_one(mine, theirs, target_team=target_team, needs=needs)
            if row:
                suggestions.append(row)

    out = pd.DataFrame(suggestions)
    if out.empty:
        return out
    sort_col = "Overall Score" if "Overall Score" in out.columns else "Trade Fit Score"
    return out.sort_values(sort_col, ascending=False).head(max_suggestions)


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
    target_owner_teams: dict[str, str] | None = None,
    summarize_team_category_needs_fn=None,
    league_context_id: str = "",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Search all opposing teams (or one target team) and return trade suggestions plus diagnostics.
    """
    my_team = _normalize_team(my_team)
    give_list = [_normalize_team(x) for x in (forced_give or []) if _normalize_team(x)]
    get_list = [_normalize_team(x) for x in (forced_get or []) if _normalize_team(x)]

    diag: dict[str, Any] = {
        "button_clicked": True,
        "button_action": "find_trade_ideas",
        "selected_give_players": give_list,
        "selected_get_players": get_list,
        "active_league_id": str(league_context_id or "").strip() or None,
        "user_team": my_team or None,
        "target_owner_teams": dict(target_owner_teams or {}),
        "opposing_teams_searched": [],
        "candidate_count_raw": 0,
        "candidate_count_after_fairness": 0,
        "candidate_count_after_filters": 0,
        "final_idea_count": 0,
        "rejection_counts": {},
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

    if give_list:
        on_roster = set(all_rosters[all_rosters["Team"].astype(str) == my_team]["Player"].astype(str))
        missing = [p for p in give_list if p not in on_roster]
        if missing:
            diag["failure_reason"] = "selected_player_not_on_roster"
            diag["missing_give_players"] = missing
            return pd.DataFrame(), diag

    opposing = [t for t in teams if t != my_team]
    owner_map = dict(target_owner_teams or {})
    if get_list and owner_map:
        opposing = sorted(set(owner_map.values()) - {my_team})
    elif target_team:
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

    raw_count = 0
    fair_count = 0
    chunks: list[pd.DataFrame] = []
    for other_team in opposing:
        chunk = suggest_trade_targets_for_team(
            my_team,
            other_team,
            all_rosters,
            needs,
            forced_give=give_list or None,
            forced_get=get_list or None,
        )
        opp_my = all_rosters[all_rosters["Team"].astype(str) == my_team]
        opp_other = all_rosters[all_rosters["Team"].astype(str) == other_team]
        raw_count += max(0, len(opp_my) * len(opp_other))
        if not chunk.empty:
            fair_count += len(chunk)
            chunks.append(chunk)

    diag["candidate_count_raw"] = raw_count
    diag["candidate_count_after_fairness"] = fair_count
    diag["candidate_count_before_filters"] = fair_count

    if not chunks:
        if give_list and not get_list:
            diag["failure_reason"] = "all_candidates_exceeded_fairness_threshold"
        elif not needs:
            diag["failure_reason"] = "all_candidates_exceeded_fairness_threshold"
        else:
            diag["failure_reason"] = "no_fair_candidates"
        return pd.DataFrame(), diag

    combined = pd.concat(chunks, ignore_index=True)
    sort_col = "Overall Score" if "Overall Score" in combined.columns else "Trade Fit Score"
    combined = combined.sort_values(sort_col, ascending=False)
    filtered = filter_trade_suggestions_by_requested_players(
        combined,
        forced_give=give_list or None,
        forced_get=get_list or None,
    )
    diag["candidate_count_after_filters"] = len(filtered)
    if filtered.empty:
        diag["failure_reason"] = "filtered_out_by_selected_players"
        return pd.DataFrame(), diag

    final = filtered.head(10).reset_index(drop=True)
    diag["final_idea_count"] = len(final)
    return final, diag


def empty_trade_ideas_message(diag: dict[str, Any] | None = None) -> str:
    reason = str((diag or {}).get("failure_reason") or "").strip()
    if reason == "selected_player_not_on_roster":
        return "Selected player was not found on your roster."
    if reason == "roster_stats_empty":
        return "No opposing roster loaded. Load league stats first."
    if reason == "no_opposing_teams":
        return "No other claimed team is available for trades."
    return _EMPTY_SUGGESTIONS_MESSAGE


def resolve_lineup_assistant_tab(session: dict[str, Any]) -> str:
    """Return active tab, honoring trade handoff focus flags."""
    if session.pop("_lineup_focus_trade_center", False) or session.pop("_lineup_focus_trade_analyzer", False):
        session[LINEUP_ASSISTANT_TAB_KEY] = "Trade Center"
        session[TRADE_CENTER_INTERNAL_TAB_KEY] = "Build & Analyze"
    if session.pop("_lineup_focus_trade_ideas", False):
        session[LINEUP_ASSISTANT_TAB_KEY] = "Trade Center"
        session[TRADE_CENTER_INTERNAL_TAB_KEY] = "Build & Analyze"
    if session.pop("_lineup_focus_trade_offers", False):
        session[LINEUP_ASSISTANT_TAB_KEY] = "Trade Center"
        session[TRADE_CENTER_INTERNAL_TAB_KEY] = "Offers"
    tab = str(session.get(LINEUP_ASSISTANT_TAB_KEY) or LINEUP_ASSISTANT_TAB_OPTIONS[0]).strip()
    if tab == "Offers & Activity":
        tab = "Trade Center"
        session[TRADE_CENTER_INTERNAL_TAB_KEY] = "Offers"
    if tab not in LINEUP_ASSISTANT_TAB_OPTIONS:
        tab = LINEUP_ASSISTANT_TAB_OPTIONS[0]
    session[LINEUP_ASSISTANT_TAB_KEY] = tab
    return tab


def resolve_trade_center_internal_tab(session: dict[str, Any]) -> str:
    tab = str(session.get(TRADE_CENTER_INTERNAL_TAB_KEY) or TRADE_CENTER_INTERNAL_TABS[0]).strip()
    if tab not in TRADE_CENTER_INTERNAL_TABS:
        tab = TRADE_CENTER_INTERNAL_TABS[0]
    session[TRADE_CENTER_INTERNAL_TAB_KEY] = tab
    return tab
