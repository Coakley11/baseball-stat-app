"""Tests for Trend / Valuation analytics profile cards and valuation score display."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from player_photos import (
    build_trend_summary_text,
    build_valuation_market_summary,
    merge_profile_row,
    render_analytics_profile_card,
    valuation_score_display,
)


class TrendValuationProfileTests(unittest.TestCase):
    def test_build_trend_summary_from_existing_slopes(self) -> None:
        row = pd.Series({"OPS_trend": 0.04, "HR_trend": 8, "SB_trend": 0.1, "BA_trend": -0.001})
        text = build_trend_summary_text(row, window_years=3)
        self.assertIn("3-year trend", text)
        self.assertIn("OPS", text)
        self.assertIn("HR", text)

    def test_build_trend_summary_unavailable_without_data(self) -> None:
        self.assertEqual(build_trend_summary_text(pd.Series(dtype=object)), "Trend data unavailable")

    def test_valuation_score_display_scales_to_100(self) -> None:
        row = pd.Series({"Valuation_Score": 0.9583})
        self.assertEqual(valuation_score_display(row), "95.83")

    def test_merge_profile_row_prefers_draft_pool_metrics(self) -> None:
        base = pd.Series({"fullName": "Aaron Judge", "OPS_trend": 0.03, "playerID": "judgeaa01"})
        pool = pd.DataFrame(
            [
                {
                    "fullName": "Aaron Judge",
                    "Expected Fantasy Value": 0.91,
                    "Draft Fit Score": 1.42,
                    "Market Rank": 12,
                    "Model Rank": 3,
                    "proj_HR": 48,
                }
            ]
        )
        merged = merge_profile_row(base, pool)
        self.assertEqual(float(merged["Expected Fantasy Value"]), 0.91)
        self.assertEqual(float(merged["OPS_trend"]), 0.03)

    @patch("player_photos.render_draft_player_profile_card")
    def test_analytics_profile_historical_player(self, mock_card: MagicMock) -> None:
        yearly = pd.DataFrame(
            [
                {"playerID": "ruthba01", "yearID": 1927},
                {"playerID": "judgeaa01", "yearID": 2025},
            ]
        )
        row = pd.Series({"fullName": "Babe Ruth", "playerID": "ruthba01"})
        st = MagicMock()
        render_analytics_profile_card(
            st,
            row,
            player_id="ruthba01",
            yearly_df=yearly,
            draft_pool_df=pd.DataFrame(),
            trend_summary="Trend: OPS ↑",
            show_valuation_score=True,
        )
        self.assertTrue(mock_card.called)
        kwargs = mock_card.call_args.kwargs
        self.assertFalse(kwargs["show_projection"])
        self.assertIn("Historical player", kwargs["historical_note"])

    @patch("player_photos.render_draft_player_profile_card")
    def test_analytics_profile_active_player_shows_metrics(self, mock_card: MagicMock) -> None:
        yearly = pd.DataFrame([{"playerID": "judgeaa01", "yearID": 2025}])
        row = pd.Series(
            {
                "fullName": "Aaron Judge",
                "playerID": "judgeaa01",
                "proj_HR": 48,
                "Expected Fantasy Value": 0.91,
                "Draft Fit Score": 1.42,
                "Market Rank": 12,
                "Model Rank": 3,
            }
        )
        st = MagicMock()
        render_analytics_profile_card(
            st,
            row,
            player_id="judgeaa01",
            yearly_df=yearly,
            trend_summary="3-year trend: HR ↑",
            show_valuation_score=True,
        )
        kwargs = mock_card.call_args.kwargs
        self.assertTrue(kwargs["show_projection"])
        self.assertTrue(kwargs["show_grade"])
        self.assertIn("Valuation Score", kwargs["reason"])

    def test_valuation_market_summary(self) -> None:
        row = pd.Series({"Market Rank": 67, "Model Rank": 42, "Fantasy Edge": 25})
        text = build_valuation_market_summary(row)
        self.assertIn("model rank 42", text)
        self.assertIn("market rank 67", text)
        self.assertIn("undervalued", text)


if __name__ == "__main__":
    unittest.main()
