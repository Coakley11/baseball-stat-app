"""Regression tests for Fantasy Lineup actionable summary helpers."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_actionable_recommendations import build_team_actionable_summary
from fantasy_waiver_wire import analyze_current_team_needs


class FantasyActionableRecommendationsTests(unittest.TestCase):
    def test_build_team_actionable_summary_accepts_league_rosters_and_my_team(self) -> None:
        league = pd.DataFrame(
            [
                {"Team": "A", "Player": "P1", "HR": 30, "RBI": 100, "R": 80, "SB": 10, "OBP": 0.340},
                {"Team": "A", "Player": "P2", "HR": 25, "RBI": 90, "R": 70, "SB": 5, "OBP": 0.330},
                {"Team": "B", "Player": "P3", "HR": 40, "RBI": 120, "R": 90, "SB": 15, "OBP": 0.360},
                {"Team": "B", "Player": "P4", "HR": 35, "RBI": 110, "R": 85, "SB": 8, "OBP": 0.350},
            ]
        )
        my_team = league[league["Team"] == "A"]
        needs = analyze_current_team_needs(my_team, league)
        lines = build_team_actionable_summary(
            strong_cats=list(needs.get("strengths") or [])[:2],
            weak_cats=list(needs.get("weaknesses") or [])[:2],
            needs=needs,
            waiver_pool=pd.DataFrame(),
            league_rosters=league,
            my_team="A",
        )
        self.assertIsInstance(lines, list)

    def test_obp_category_value_is_team_average_not_sum(self) -> None:
        league = pd.DataFrame(
            [
                {"Team": "A", "Player": "P1", "OBP": 0.340},
                {"Team": "A", "Player": "P2", "OBP": 0.320},
                {"Team": "B", "Player": "P3", "OBP": 0.360},
            ]
        )
        my_team = league[league["Team"] == "A"]
        needs = analyze_current_team_needs(my_team, league, categories=("OBP",))
        obp_val = float((needs.get("category_values") or {}).get("OBP") or 0)
        self.assertLess(obp_val, 1.0)
        self.assertAlmostEqual(obp_val, 0.330, places=3)

    def test_build_team_actionable_summary_no_waiver_pool_shows_unavailable(self) -> None:
        lines = build_team_actionable_summary(
            strong_cats=["OBP"],
            weak_cats=["HR"],
            needs={"weaknesses": ["HR"]},
            waiver_pool=pd.DataFrame(),
        )
        self.assertTrue(any("No strong waiver upgrades" in line for line in lines))

    def test_team_outlook_explanation_lists_strengths_and_concerns(self) -> None:
        from fantasy_actionable_recommendations import team_outlook_explanation

        lines = team_outlook_explanation(
            strong_cats=["OBP", "SB"],
            weak_cats=["HR", "RBI"],
            category_ranks={"OBP": 2, "SB": 2, "HR": 4, "RBI": 4},
            n_teams=4,
        )
        self.assertTrue(any("Strengths driving outlook" in line for line in lines))
        self.assertTrue(any("Concerns" in line for line in lines))
