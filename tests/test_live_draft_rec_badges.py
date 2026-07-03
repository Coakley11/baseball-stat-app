"""Tests for smart Live Draft recommendation badges."""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_rec_badges import build_smart_recommendation_badges, primary_recommendation_reason


def _rec_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fullName": "Player A",
                "Primary Position": "SS",
                "Decision Score": 0.88,
                "Fantasy Edge": 14,
                "Scarcity Score": 0.82,
                "Positional Fit": 0.9,
                "Category Need Bonus": 0.08,
                "Expected Fantasy Value": 0.84,
                "Projection Confidence": 0.7,
                "Risk Penalty": 0.2,
            },
            {
                "fullName": "Player B",
                "Primary Position": "OF",
                "Decision Score": 0.75,
                "Fantasy Edge": 4,
                "Scarcity Score": 0.4,
                "Positional Fit": 0.55,
                "Category Need Bonus": 0.0,
                "Expected Fantasy Value": 0.7,
            },
            {
                "fullName": "Player C",
                "Primary Position": "SS",
                "Decision Score": 0.71,
                "Fantasy Edge": 2,
                "Scarcity Score": 0.35,
                "Positional Fit": 0.6,
            },
        ]
    )


class SmartRecommendationBadgeTests(unittest.TestCase):
    def test_top_pick_gets_specific_badges_not_generic_position_need(self) -> None:
        row = _rec_df().iloc[0]
        badges = build_smart_recommendation_badges(
            1,
            row,
            _rec_df(),
            gaps=["SS", "OF"],
            category_needs=["HR"],
            strengths=["HR", "RBI"],
        )
        labels = [b[0] for b in badges]
        self.assertIn("Best Remaining SS", labels)
        self.assertTrue(any("Power" in lb or "Category" in lb or "HR" in lb for lb in labels))
        self.assertNotIn("Position Need", labels)
        if "Best Overall" in labels:
            self.assertEqual(labels[-1], "Best Overall")

    def test_second_ss_gets_different_badges_than_first(self) -> None:
        row_c = _rec_df().iloc[2]
        badges = build_smart_recommendation_badges(3, row_c, _rec_df(), gaps=["SS"])
        labels = [b[0] for b in badges]
        self.assertNotIn("Best Remaining SS", labels)

    def test_primary_reason_is_prose_not_badge_duplicate(self) -> None:
        row = _rec_df().iloc[0]
        badges = build_smart_recommendation_badges(1, row, _rec_df(), gaps=["SS"], strengths=["HR"])
        reason = primary_recommendation_reason(1, row, badges=badges, strengths=["HR"], gaps=["SS"])
        badge_labels = {b[0] for b in badges}
        self.assertNotIn(reason, badge_labels)
        self.assertIn("SS", reason)


if __name__ == "__main__":
    unittest.main()
