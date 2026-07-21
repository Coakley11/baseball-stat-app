"""Tests for fast Solo start pool deferral."""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_fast_solo_start import build_fast_market_pool, should_use_fast_solo_pool


class TestFastSoloStart(unittest.TestCase):
    def test_should_use_fast_solo_pool(self) -> None:
        session = {"live_draft_setup_mode": "solo"}
        self.assertTrue(
            should_use_fast_solo_pool(
                session, solo_mode=True, from_simulator=False, prepare_shared=False
            )
        )
        self.assertFalse(
            should_use_fast_solo_pool(
                session, solo_mode=False, from_simulator=False, prepare_shared=False
            )
        )

    def test_build_fast_market_pool(self) -> None:
        market = pd.DataFrame(
            {
                "Player": [f"P{i}" for i in range(10)],
                "Market Rank": list(range(1, 11)),
                "Position": ["1B", "C", "OF", "P", "SS", "2B", "3B", "OF", "C", "1B"],
            }
        )
        pool = build_fast_market_pool(market, min_rows=5)
        self.assertEqual(len(pool), 5)
        self.assertIn("fullName", pool.columns)
        self.assertIn("Expected Fantasy Value", pool.columns)


if __name__ == "__main__":
    unittest.main()
