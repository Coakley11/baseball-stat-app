"""Tests for fast Solo start pool deferral."""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_fast_solo_start import (
    build_fast_market_pool,
    clear_defer_heavy_first_paint,
    get_start_stage_report,
    mark_defer_heavy_first_paint,
    note_start_stage,
    should_defer_heavy_first_paint,
    should_use_fast_solo_pool,
)


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

    def test_defer_heavy_first_paint_lifecycle(self) -> None:
        session: dict = {}
        self.assertFalse(should_defer_heavy_first_paint(session))
        mark_defer_heavy_first_paint(session)
        self.assertTrue(should_defer_heavy_first_paint(session))
        clear_defer_heavy_first_paint(session)
        self.assertFalse(should_defer_heavy_first_paint(session))

    def test_note_start_stage_records_elapsed_ms(self) -> None:
        session: dict = {}
        note_start_stage(session, "start_button_received")
        note_start_stage(session, "validation_completed")
        report = get_start_stage_report(session)
        self.assertIn("start_button_received", report)
        self.assertIn("validation_completed", report)
        self.assertIn("elapsed_ms", report["start_button_received"])


if __name__ == "__main__":
    unittest.main()
