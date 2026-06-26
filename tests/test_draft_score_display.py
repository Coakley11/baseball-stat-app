"""Tests for draft score display naming and formatting (no formula changes)."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_score_display import (
    DISPLAY_PICK_SCORE,
    DISPLAY_PLAYER_GRADE,
    DISPLAY_RELATIVE_GRADE,
    DISPLAY_ROSTER_FIT,
    fmt_pick_score,
    fmt_player_grade,
    fmt_relative_draft_grade,
    fmt_roster_fit_score,
    prepare_draft_scores_for_display,
    style_cols_for_display,
)


class DraftScoreDisplayTests(unittest.TestCase):
    def test_player_grade_scales_to_100(self) -> None:
        self.assertEqual(fmt_player_grade(0.9012), "90.12")
        self.assertEqual(fmt_player_grade(0.7834), "78.34")

    def test_pick_score_scales_to_100(self) -> None:
        self.assertEqual(fmt_pick_score(0.9123), "91.23")
        self.assertEqual(fmt_pick_score(0.7421), "74.21")

    def test_roster_fit_not_scaled(self) -> None:
        self.assertEqual(fmt_roster_fit_score(1.70), "1.70")
        self.assertEqual(fmt_roster_fit_score(0.88), "0.88")

    def test_relative_draft_grade_two_decimals(self) -> None:
        self.assertEqual(fmt_relative_draft_grade(0.8214), "82.14")
        self.assertEqual(fmt_relative_draft_grade(0.2785), "27.85")

    def test_prepare_renames_and_scales_columns(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "Expected Fantasy Value": 0.9,
                    "Decision Score": 0.85,
                    "Draft Fit Score": 1.42,
                    "Overall Draft Grade Score": 0.73,
                }
            ]
        )
        out = prepare_draft_scores_for_display(df)
        self.assertIn(DISPLAY_PLAYER_GRADE, out.columns)
        self.assertIn(DISPLAY_PICK_SCORE, out.columns)
        self.assertIn(DISPLAY_ROSTER_FIT, out.columns)
        self.assertIn(DISPLAY_RELATIVE_GRADE, out.columns)
        self.assertEqual(float(out.iloc[0][DISPLAY_PLAYER_GRADE]), 90.0)
        self.assertEqual(float(out.iloc[0][DISPLAY_PICK_SCORE]), 85.0)
        self.assertEqual(float(out.iloc[0][DISPLAY_ROSTER_FIT]), 1.42)
        self.assertEqual(float(out.iloc[0][DISPLAY_RELATIVE_GRADE]), 73.0)

    def test_style_cols_map_to_display_names(self) -> None:
        mapped = style_cols_for_display(["Fantasy Edge", "Draft Fit Score", "Expected Fantasy Value"])
        self.assertEqual(mapped, ["Fantasy Edge", DISPLAY_ROSTER_FIT, DISPLAY_PLAYER_GRADE])


if __name__ == "__main__":
    unittest.main()
