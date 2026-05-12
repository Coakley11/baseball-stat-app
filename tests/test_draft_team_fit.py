"""Unit tests for draft_team_fit roster-context labels."""

import unittest

from draft_team_fit import team_fit_summary_line


class TestTeamFitSummaryLine(unittest.TestCase):
    def test_balanced_when_no_signals(self):
        row = {
            "Primary Position": "1B",
            "proj_SB": 5.0,
            "Position Scarcity Bonus": 0.0,
            "Category Need Bonus": 0.0,
            "Risk Penalty": 0.01,
            "Breakout Probability": 0.2,
            "Fantasy Edge": 0.0,
            "Expected Fantasy Value": -0.5,
        }
        s = team_fit_summary_line(
            row,
            draft_format="5x5 Roto",
            needed_positions=[],
            category_needs=[],
            roster_means={},
            pool_means={"proj_SB": 10.0},
            current_position_counts={"1B": 0},
            target_position_counts={"1B": 1},
        )
        self.assertEqual(s, "Balanced roster fit")

    def test_fills_positional_need(self):
        row = {
            "Primary Position": "SS",
            "proj_SB": 5.0,
            "Position Scarcity Bonus": 0.0,
            "Category Need Bonus": 0.0,
            "Risk Penalty": 0.01,
            "Breakout Probability": 0.2,
            "Fantasy Edge": 0.0,
            "Expected Fantasy Value": 0.5,
        }
        s = team_fit_summary_line(
            row,
            draft_format="5x5 Roto",
            needed_positions=["SS"],
            category_needs=[],
            roster_means={},
            pool_means={},
            current_position_counts={},
            target_position_counts={"SS": 1},
        )
        self.assertIn("Fills positional need", s)

    def test_boosts_weak_category_vs_roster(self):
        row = {
            "Primary Position": "OF",
            "proj_SB": 25.0,
            "Position Scarcity Bonus": 0.0,
            "Category Need Bonus": 0.0,
            "Risk Penalty": 0.01,
            "Breakout Probability": 0.2,
            "Fantasy Edge": 0.0,
            "Expected Fantasy Value": 0.5,
        }
        s = team_fit_summary_line(
            row,
            draft_format="5x5 Roto",
            needed_positions=[],
            category_needs=["SB"],
            roster_means={"proj_SB": 5.0},
            pool_means={"proj_SB": 12.0},
            current_position_counts={"OF": 3},
            target_position_counts={"OF": 3},
        )
        self.assertIn("Boosts SB vs roster", s)

    def test_caps_at_four_distinct_tags(self):
        row = {
            "Primary Position": "SS",
            "proj_SB": 30.0,
            "proj_HR": 30.0,
            "Position Scarcity Bonus": 0.06,
            "Category Need Bonus": 0.05,
            "Risk Penalty": 0.06,
            "Breakout Probability": 0.56,
            "Fantasy Edge": 30.0,
            "Expected Fantasy Value": 0.8,
        }
        s = team_fit_summary_line(
            row,
            draft_format="5x5 Roto",
            needed_positions=["SS"],
            category_needs=["SB", "HR"],
            roster_means={"proj_SB": 4.0, "proj_HR": 10.0},
            pool_means={"proj_SB": 12.0, "proj_HR": 22.0},
            current_position_counts={},
            target_position_counts={"SS": 1},
        )
        parts = [p.strip() for p in s.split(" · ")]
        self.assertLessEqual(len(parts), 4)


if __name__ == "__main__":
    unittest.main()
