"""Tests for compact pool scoring column defaults."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_scoring_pool import ensure_draft_scoring_pool_columns


class DraftScoringPoolTests(unittest.TestCase):
    def test_fills_fantasy_edge_when_missing(self) -> None:
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
        out = ensure_draft_scoring_pool_columns(pool)
        self.assertIn("Fantasy Edge", out.columns)
        self.assertEqual(float(out.loc[0, "Fantasy Edge"]), 0.0)

    def test_derives_fantasy_edge_from_ranks(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
