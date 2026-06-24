"""Tests for live draft required pool columns and scoring safety."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_scoring_pool import (
    LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS,
    analyze_compact_pool,
    ensure_draft_scoring_pool_columns,
    select_live_draft_compact_columns,
)


def _full_scoring_row() -> dict:
    return {
        "playerID": "p1",
        "fullName": "Aaron Judge",
        "Primary Position": "OF",
        "Team": "NYY",
        "Expected Fantasy Value": 0.91,
        "Model Rank": 8,
        "Market Rank": 15,
        "Fantasy Edge": 7,
        "ADP": 15,
        "Expert Std Dev": 4.0,
        "Sleeper Score": 0.62,
        "Scarcity Score": 0.44,
        "Projection Confidence Score": 0.8,
        "Trend Signal": 0.12,
        "proj_HR": 42,
        "proj_RBI": 98,
        "proj_R": 88,
        "proj_SB": 8,
        "proj_BA": 0.285,
        "proj_OPS": 0.920,
        "G": 140,
        "AB": 520,
        "HR_trend": 0.1,
        "RBI_trend": 0.05,
        "SB_trend": 0.0,
        "OPS_trend": 0.02,
        "Blended Projection Score": 0.91,
        "Projected Production Score": 0.89,
        "Realistic Base Projection Score": 0.88,
        "Current Production Score": 0.87,
        "extra_lahman_col": 999,
    }


class DraftScoringPoolTests(unittest.TestCase):
    def test_select_compact_keeps_required_present_columns(self) -> None:
        pool = pd.DataFrame([_full_scoring_row()])
        cols = select_live_draft_compact_columns(pool)
        self.assertIn("Model Rank", cols)
        self.assertIn("Fantasy Edge", cols)
        self.assertIn("Sleeper Score", cols)
        self.assertNotIn("extra_lahman_col", cols)

    def test_ensure_preserves_real_rank_values(self) -> None:
        pool = pd.DataFrame([_full_scoring_row()])
        out = ensure_draft_scoring_pool_columns(pool)
        self.assertEqual(float(out.loc[0, "Model Rank"]), 8.0)
        self.assertEqual(float(out.loc[0, "Market Rank"]), 15.0)
        self.assertEqual(float(out.loc[0, "Fantasy Edge"]), 7.0)

    def test_ensure_derives_edge_from_ranks_without_overwriting(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Star",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 90.0,
                    "Market Rank": 20,
                    "Model Rank": 12,
                }
            ]
        )
        out = ensure_draft_scoring_pool_columns(pool)
        self.assertEqual(float(out.loc[0, "Fantasy Edge"]), 8.0)

    def test_analyze_reports_missing_and_defaults(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Star",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 90.0,
                }
            ]
        )
        diag = analyze_compact_pool(pool)
        self.assertIn("Model Rank", diag["missing_required"])
        self.assertIn("Model Rank", diag["default_filled_counts"])

    def test_compact_column_list_is_stable(self) -> None:
        self.assertIn("Fantasy Edge", LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS)
        self.assertIn("proj_HR", LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS)


if __name__ == "__main__":
    unittest.main()
