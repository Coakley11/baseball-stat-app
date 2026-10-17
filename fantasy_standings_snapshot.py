"""Current-roster standings snapshot — NOT the official league standings.

Scores every team's *current* roster on season-to-date stats: a player counts for whoever
owns him today, for every game he played this season, whichever team he played them for.
Useful for analysis ("how do our rosters stack up right now?"); never the standings.

Official standings are the sum of finalized scoring periods:
``fantasy_season_results.official_standings``. Anything that shows or explains this
table must label it ``SNAPSHOT_LABEL``.

Moved verbatim from streamlit_app.py (score_fantasy_rosters_from_stats,
summarize_team_category_needs); the page keeps a cached wrapper under the old name.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SNAPSHOT_KIND = "current_roster_snapshot"
SNAPSHOT_LABEL = "Current Roster Snapshot (not official standings)"


def score_current_roster_standings(roster_df, scoring_format="5x5 Roto"):
    """Score drafted teams using uploaded/current stats."""
    df = roster_df.copy()
    for c in ["HR", "RBI", "R", "SB", "BA", "OPS", "OBP", "SLG"]:
        if c not in df.columns:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")

    from fantasy_team_rates import roto_points, team_rate

    team_rows = []
    for team, g in df.groupby("Team"):
        row = {
            "Fantasy Team": team,
            "Players": g["Player"].nunique(),
            "Total HR": g["HR"].sum(),
            "Total RBI": g["RBI"].sum(),
            "Total R": g["R"].sum(),
            "Total SB": g["SB"].sum(),
            # Team rates from summed hits/at-bats when the stats carry them (roto convention).
            "Team BA": team_rate(g, "BA"),
            "Team OPS": team_rate(g, "OPS"),
        }
        team_rows.append(row)

    standings = pd.DataFrame(team_rows)
    if standings.empty:
        return standings

    if scoring_format == "5x5 Roto":
        categories = ["Total HR", "Total RBI", "Total R", "Total SB", "Team BA"]
        for cat in categories:
            standings[f"{cat} Points"] = roto_points(standings[cat])  # ties split points
        standings["Total Roto Points"] = standings[[f"{c} Points" for c in categories]].sum(axis=1)
        standings["League Rank"] = standings["Total Roto Points"].rank(ascending=False, method="min")
        standings = standings.sort_values(["League Rank", "Fantasy Team"])
    else:
        standings["Estimated Points"] = (
            standings["Total HR"] * 4 +
            standings["Total RBI"] +
            standings["Total R"] +
            standings["Total SB"] * 2 +
            standings["Team OPS"].fillna(0) * 25
        )
        standings["League Rank"] = standings["Estimated Points"].rank(ascending=False, method="min")
        standings = standings.sort_values(["League Rank", "Fantasy Team"])

    return standings


def summarize_team_category_needs(standings, team_name):
    if standings is None or standings.empty or team_name not in standings["Fantasy Team"].values:
        return {}
    row = standings[standings["Fantasy Team"] == team_name].iloc[0]
    needs = {}
    category_map = {
        "HR": "Total HR",
        "RBI": "Total RBI",
        "R": "Total R",
        "SB": "Total SB",
        "BA": "Team BA",
        "OPS": "Team OPS",
    }
    for label, col in category_map.items():
        if col in standings.columns:
            rank = standings[col].rank(ascending=False, method="min")[row.name]
            if rank > max(1, len(standings) / 2):
                needs[label] = True
    return needs
