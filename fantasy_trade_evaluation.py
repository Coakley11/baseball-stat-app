"""Trade value evaluation — category give/receive comparison and verdict.

Moved verbatim from streamlit_app.py (evaluate_trade, build_trade_verdict_text) so the
Trade Center and AMI share one implementation. This module scores *value only*; it does
not check legality or permissions:

* who may propose/execute: ``fantasy_team_control.resolve_team_control``,
  ``fantasy_league_team_ownership.trades_enabled``;
* ownership/size rules: ``fantasy_trade_proposals.validate_proposal_players``;
* roster/lineup consequences: ``fantasy_trade_legality.trade_roster_warnings``.

Note on rates: BA and OPS here are the plain average of the players' rates on each side
(not hit/at-bat weighted). That is the existing page behavior, kept unchanged.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fantasy_standings_snapshot import summarize_team_category_needs
from stat_helpers import safe_numeric_series


def evaluate_trade(my_give, my_get, my_roster, all_rosters, standings, my_team):
    """Evaluate a proposed fantasy trade from the user's perspective."""
    give_df = all_rosters[all_rosters["Player"].isin(my_give)].copy()
    get_df = all_rosters[all_rosters["Player"].isin(my_get)].copy()

    cats = ["HR", "RBI", "R", "SB", "BA", "OPS"]
    rows = []
    for cat in cats:
        give_series = safe_numeric_series(give_df, cat, np.nan)
        get_series = safe_numeric_series(get_df, cat, np.nan)
        give_val = give_series.mean() if cat in ["BA", "OPS"] else give_series.sum()
        get_val = get_series.mean() if cat in ["BA", "OPS"] else get_series.sum()
        rows.append({"Category": cat, "Give Away": give_val, "Receive": get_val, "Net Gain": get_val - give_val})

    trade_df = pd.DataFrame(rows)
    needs = summarize_team_category_needs(standings, my_team)
    weighted_gain = 0
    for _, r in trade_df.iterrows():
        weight = 1.5 if needs.get(r["Category"], False) else 1.0
        weighted_gain += r["Net Gain"] * weight

    verdict = "Neutral"
    if weighted_gain > 2:
        verdict = "Good for your team"
    elif weighted_gain < -2:
        verdict = "Bad for your team"

    return trade_df, verdict, weighted_gain


def build_trade_verdict_text(trade_eval, weighted_gain):
    """Plain-English trade verdict for Fantasy Lineup Assistant."""
    try:
        wg = float(weighted_gain)
    except Exception:
        wg = 0.0

    if wg >= 5:
        verdict = "Strong accept"
        reason = "The trade appears to improve your roster in important need areas."
    elif wg >= 1:
        verdict = "Slight accept"
        reason = "The trade looks modestly helpful, especially if it addresses a weak category or roster need."
    elif wg > -1:
        verdict = "Fair / neutral"
        reason = "The trade is close enough that team context, injury risk, and category needs should decide it."
    elif wg > -5:
        verdict = "Slight decline"
        reason = "The trade appears slightly unfavorable unless it solves a specific roster problem."
    else:
        verdict = "Decline"
        reason = "The trade appears to cost too much projected value or category balance."

    return f"{verdict}: {reason} Team-need weighted score: {wg:.2f}."
