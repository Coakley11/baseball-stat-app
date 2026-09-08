"""Tests for fast Solo start pool deferral."""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_fast_solo_start import (
    build_fast_market_pool,
    clear_defer_heavy_first_paint,
    ensure_solo_player_pool_for_recs,
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

    def test_build_fast_market_pool_derives_util_from_adp(self) -> None:
        market = pd.DataFrame(
            {
                "Player": ["Jose Ramirez", "Aaron Judge"],
                "Primary Position": ["UTIL", "UTIL"],
                "ADP Position": ["3B,DH", "LF,CF,RF"],
                "FantasyPros Position": ["3B1", "OF1"],
                "Market Rank": [1, 2],
            }
        )
        pool = build_fast_market_pool(market, min_rows=10)
        by_name = {str(r["fullName"]): str(r["Primary Position"]) for _, r in pool.iterrows()}
        self.assertEqual(by_name["Jose Ramirez"], "3B")
        self.assertEqual(by_name["Aaron Judge"], "OF")

    def test_build_fast_market_pool_repairs_all_zero_efv(self) -> None:
        market = pd.DataFrame(
            {
                "Player": [f"P{i}" for i in range(20)],
                "Market Rank": list(range(1, 21)),
                "Position": ["OF"] * 20,
                "Expected Fantasy Value": [0.0] * 20,
                "Model Rank": [9999] * 20,
                "Fantasy Edge": [float(i) for i in range(20)],
            }
        )
        pool = build_fast_market_pool(market, min_rows=20)
        efv = pd.to_numeric(pool["Expected Fantasy Value"], errors="coerce")
        model = pd.to_numeric(pool["Model Rank"], errors="coerce")
        edge = pd.to_numeric(pool["Fantasy Edge"], errors="coerce")
        self.assertGreater(float(efv.max()), 0.0)
        self.assertGreater(int(efv.nunique()), 1)
        self.assertGreater(int(model.nunique()), 1)
        self.assertLess(float(edge.max()), 50.0)
        self.assertGreater(
            float(pool.loc[pool["Market Rank"] == 1, "Expected Fantasy Value"].iloc[0]),
            float(pool.loc[pool["Market Rank"] == 20, "Expected Fantasy Value"].iloc[0]),
        )

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

    def test_ensure_solo_player_pool_attaches_fast_market_when_empty(self) -> None:
        from unittest.mock import patch

        market = pd.DataFrame(
            {
                "Player": [f"P{i}" for i in range(20)],
                "Market Rank": list(range(1, 21)),
                "Position": ["OF"] * 20,
            }
        )
        room = {
            "status": "in_progress",
            "pool": pd.DataFrame(),
            "config": {
                "draft_mode": "solo",
                "num_teams": 2,
                "picks_per_team": 4,
                "user_team": "Team A",
            },
        }
        session = {
            "live_draft_setup_mode": "solo",
            "live_draft_room": room,
        }

        class _App:
            @staticmethod
            def load_fantasypros_market_data():
                return market

        with patch("live_draft_solo_timer.is_solo_live_draft", return_value=True), patch(
            "importlib.import_module", return_value=_App
        ):
            ok = ensure_solo_player_pool_for_recs(session, room)
        self.assertTrue(ok)
        attached = session["live_draft_room"]["pool"]
        self.assertFalse(attached.empty)
        self.assertGreaterEqual(len(attached), 20)


if __name__ == "__main__":
    unittest.main()
