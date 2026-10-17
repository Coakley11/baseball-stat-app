"""Roto category points split ties; team rate stats come from summed hits and at-bats."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from fantasy_team_rates import roto_points, team_rate

ROOT = Path(__file__).resolve().parents[1]


class RotoTiePointsTests(unittest.TestCase):
    def test_two_way_tie_for_first_splits_four_and_three(self):
        pts = roto_points(pd.Series([30, 30, 20, 10], index=list("ABCD")))
        self.assertEqual(pts.to_dict(), {"A": 3.5, "B": 3.5, "C": 2.0, "D": 1.0})

    def test_three_way_tie_and_tie_for_last(self):
        pts = roto_points(pd.Series([5, 5, 5, 1, 1], index=list("ABCDE")))
        self.assertEqual(pts.to_dict(), {"A": 4.0, "B": 4.0, "C": 4.0, "D": 1.5, "E": 1.5})

    def test_points_always_sum_to_the_full_pool(self):
        for values in ([1, 2, 3, 4], [7, 7, 7, 7], [3, 3, 1, 9, 9, 2]):
            n = len(values)
            self.assertEqual(roto_points(pd.Series(values)).sum(), n * (n + 1) / 2)

    def test_lower_is_better_categories(self):
        pts = roto_points(pd.Series([3.10, 4.50, 3.10]), higher_is_better=False)
        self.assertEqual(pts.tolist(), [2.5, 1.0, 2.5])


class TeamRateTests(unittest.TestCase):
    def test_team_ba_is_hits_over_at_bats_not_mean_of_players(self):
        team = pd.DataFrame([{"H": 180, "AB": 600, "BA": 0.300}, {"H": 10, "AB": 20, "BA": 0.500}])
        self.assertAlmostEqual(team_rate(team, "BA"), 190 / 620)  # .306, not the .400 mean
        self.assertAlmostEqual(team_rate(team, "AVG"), 190 / 620)

    def test_obp_slg_ops_from_components(self):
        team = pd.DataFrame([{"AB": 500, "H": 150, "2B": 30, "3B": 2, "HR": 25, "BB": 60, "HBP": 5, "SF": 5}])
        obp = (150 + 60 + 5) / (500 + 60 + 5 + 5)
        slg = (150 + 30 + 2 * 2 + 3 * 25) / 500
        self.assertAlmostEqual(team_rate(team, "OBP"), obp)
        self.assertAlmostEqual(team_rate(team, "SLG"), slg)
        self.assertAlmostEqual(team_rate(team, "OPS"), obp + slg)

    def test_falls_back_to_mean_without_components(self):
        team = pd.DataFrame([{"BA": 0.300, "OPS": 0.900}, {"BA": 0.250, "OPS": 0.700}])
        self.assertAlmostEqual(team_rate(team, "BA"), 0.275)
        self.assertAlmostEqual(team_rate(team, "OPS"), 0.800)

    def test_waiver_team_values_use_the_same_rule(self):
        from fantasy_waiver_wire import _category_value_for_team

        team = pd.DataFrame([{"Player": "A", "H": 180, "AB": 600, "BA": 0.300}, {"Player": "B", "H": 10, "AB": 20, "BA": 0.500}])
        self.assertAlmostEqual(_category_value_for_team(team, "AVG"), 190 / 620)


class StandingsWiringTests(unittest.TestCase):
    def setUp(self):
        self.src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        snapshot = (ROOT / "fantasy_standings_snapshot.py").read_text(encoding="utf-8")
        start = snapshot.index("def score_current_roster_standings")
        self.body = snapshot[start:snapshot.index("def summarize_team_category_needs")]

    def test_standings_use_split_points_and_team_rates(self):
        self.assertIn("roto_points(standings[cat])", self.body)
        self.assertIn('"Team BA": team_rate(g, "BA")', self.body)
        self.assertNotIn('method="min")\n', self.body.split("League Rank")[0])
        self.assertNotIn('g["BA"].mean()', self.body)

    def test_half_points_are_not_rounded_away(self):
        fmt = self.src[self.src.index("def format_fantasy_standings_table"):self.src.index("def score_fantasy_rosters_from_stats")]
        self.assertIn("(vals.dropna() % 1 != 0).any()", fmt)


if __name__ == "__main__":
    unittest.main()
