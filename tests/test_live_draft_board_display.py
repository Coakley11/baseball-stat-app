"""Live Draft board display formatting."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_score_display import prepare_draft_scores_for_display


class LiveDraftBoardDisplayTests(unittest.TestCase):
    def test_board_uses_player_grade_and_integer_ranks(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "Round": 1,
                    "Pick": 1,
                    "Player": "Test Player",
                    "Expected Fantasy Value": 0.913,
                    "Model Rank": 2.0,
                    "Market Rank": 5.0,
                    "Fantasy Edge": 12.4,
                }
            ]
        )
        out = prepare_draft_scores_for_display(df)
        self.assertIn("Player Grade", out.columns)
        self.assertNotIn("Expected Fantasy Value", out.columns)
        grade = float(str(out.iloc[0]["Player Grade"]).replace(",", ""))
        self.assertGreaterEqual(grade, 90.0)
        self.assertLessEqual(grade, 92.0)
        self.assertEqual(int(out.iloc[0]["Model Rank"]), 2)
        self.assertEqual(int(out.iloc[0]["Market Rank"]), 5)


if __name__ == "__main__":
    unittest.main()
