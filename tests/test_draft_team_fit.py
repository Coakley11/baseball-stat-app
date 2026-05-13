"""Unit tests for draft_team_fit roster-context narratives."""

import unittest

from draft_team_fit import team_fit_summary_line


class TestTeamFitSummaryLine(unittest.TestCase):
    def test_no_roster_prompts_sync(self):
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
        self.assertIn("Sync your Draft Room roster", s)

    def test_positional_need_names_slot(self):
        row = {
            "Primary Position": "SS",
            "proj_SB": 5.0,
            "proj_HR": 15.0,
            "proj_BA": 0.25,
            "proj_R": 70.0,
            "proj_RBI": 65.0,
            "proj_OBP": 0.32,
            "proj_OPS": 0.75,
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
            roster_means={"proj_SB": 8.0},
            pool_means={"proj_SB": 10.0},
            current_position_counts={"SS": 0},
            target_position_counts={"SS": 1},
        )
        self.assertIn("shortstop", s.lower())
        self.assertIn("positional gap", s.lower())

    def test_dual_weak_categories_lift(self):
        row = {
            "Primary Position": "OF",
            "proj_SB": 25.0,
            "proj_BA": 0.285,
            "proj_HR": 18.0,
            "proj_RBI": 70.0,
            "proj_R": 75.0,
            "proj_OBP": 0.35,
            "proj_OPS": 0.8,
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
            category_needs=["SB", "BA"],
            roster_means={
                "proj_SB": 5.0,
                "proj_BA": 0.248,
                "proj_HR": 20.0,
                "proj_RBI": 72.0,
                "proj_R": 72.0,
                "proj_OBP": 0.31,
                "proj_OPS": 0.76,
            },
            pool_means={
                "proj_SB": 12.0,
                "proj_BA": 0.262,
                "proj_HR": 20.0,
                "proj_RBI": 72.0,
                "proj_R": 72.0,
                "proj_OBP": 0.32,
                "proj_OPS": 0.76,
            },
            current_position_counts={"OF": 3},
            target_position_counts={"OF": 3},
        )
        self.assertIn("stolen bases", s.lower())
        self.assertIn("batting average", s.lower())
        self.assertIn("pool", s.lower())

    def test_power_stack_obp_lift(self):
        row = {
            "Primary Position": "1B",
            "proj_HR": 32.0,
            "proj_OBP": 0.38,
            "proj_SB": 2.0,
            "proj_BA": 0.27,
            "proj_RBI": 95.0,
            "proj_R": 80.0,
            "proj_OPS": 0.9,
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
            category_needs=[],
            roster_means={
                "proj_HR": 28.0,
                "proj_OBP": 0.30,
                "proj_SB": 8.0,
                "proj_BA": 0.265,
                "proj_RBI": 85.0,
                "proj_R": 78.0,
                "proj_OPS": 0.82,
            },
            pool_means={
                "proj_HR": 20.0,
                "proj_OBP": 0.33,
                "proj_SB": 10.0,
                "proj_BA": 0.26,
                "proj_RBI": 72.0,
                "proj_R": 72.0,
                "proj_OPS": 0.76,
            },
            current_position_counts={"1B": 1},
            target_position_counts={"1B": 1},
        )
        self.assertIn("OBP", s)
        self.assertIn("power", s.lower())

    def test_at_most_two_sentence_breaks(self):
        row = {
            "Primary Position": "SS",
            "proj_SB": 30.0,
            "proj_HR": 30.0,
            "proj_BA": 0.29,
            "proj_R": 90.0,
            "proj_RBI": 95.0,
            "proj_OBP": 0.36,
            "proj_OPS": 0.88,
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
            roster_means={
                "proj_SB": 4.0,
                "proj_HR": 10.0,
                "proj_BA": 0.25,
                "proj_R": 65.0,
                "proj_RBI": 60.0,
                "proj_OBP": 0.31,
                "proj_OPS": 0.74,
            },
            pool_means={
                "proj_SB": 12.0,
                "proj_HR": 22.0,
                "proj_BA": 0.26,
                "proj_R": 72.0,
                "proj_RBI": 72.0,
                "proj_OBP": 0.32,
                "proj_OPS": 0.76,
            },
            current_position_counts={"SS": 0},
            target_position_counts={"SS": 1},
            roster_expert_std_mean=18.0,
            pool_expert_std_mean=12.0,
        )
        self.assertLessEqual(s.count(". "), 1)


if __name__ == "__main__":
    unittest.main()
