"""Tests for live draft required pool columns and scoring safety."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_scoring_pool import (
    LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS,
    analyze_compact_pool,
    ensure_draft_scoring_pool_columns,
    prepare_pool_for_compact_serialization,
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
        self.assertIn("Market Rank", diag["missing_required"])
        derived = diag.get("derived_columns") or []
        self.assertTrue("Model Rank" in derived or "Fantasy Edge" in derived)

    def test_prepare_compact_derives_ranks_from_adp_and_efv(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Aaron Judge",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.95,
                    "ADP Rank": 12,
                }
            ]
        )
        prepared, report = prepare_pool_for_compact_serialization(pool)
        self.assertIn("Model Rank", prepared.columns)
        self.assertIn("Market Rank", prepared.columns)
        self.assertIn("Fantasy Edge", prepared.columns)
        self.assertEqual(float(prepared.loc[0, "Market Rank"]), 12.0)
        self.assertLess(float(prepared.loc[0, "Model Rank"]), 9000)
        self.assertNotEqual(float(prepared.loc[0, "Fantasy Edge"]), 0.0)
        quality = report.get("scoring_quality") or {}
        self.assertGreaterEqual(quality.get("Market Rank", {}).get("real", 0), 1)

    def test_repairs_baked_9999_ranks_from_efv_and_adp_on_restore(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Aaron Judge",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.95,
                    "ADP Rank": 8,
                    "Model Rank": 9999.0,
                    "Market Rank": 9999.0,
                    "Fantasy Edge": 0.0,
                },
                {
                    "playerID": "p2",
                    "fullName": "Juan Soto",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.90,
                    "ADP Rank": 5,
                    "Model Rank": 9999.0,
                    "Market Rank": 9999.0,
                    "Fantasy Edge": 0.0,
                },
            ]
        )
        out = ensure_draft_scoring_pool_columns(pool)
        judge = out.loc[out["fullName"] == "Aaron Judge"].iloc[0]
        self.assertLess(float(judge["Model Rank"]), 9000)
        self.assertEqual(float(judge["Market Rank"]), 8.0)
        self.assertNotEqual(float(judge["Fantasy Edge"]), 0.0)

    def test_trace_player_scoring_reads_real_values(self) -> None:
        from draft_scoring_pool import trace_player_scoring

        pool = pd.DataFrame(
            [
                {
                    "fullName": "Aaron Judge",
                    "Expected Fantasy Value": 0.95,
                    "Model Rank": 3,
                    "Market Rank": 8,
                    "Fantasy Edge": 5,
                    "ADP Rank": 8,
                    "Sleeper Score": 0.7,
                }
            ]
        )
        trace = trace_player_scoring(pool)
        judge = trace["Aaron Judge"]
        self.assertTrue(judge.get("found"))
        self.assertLess(float(judge["Model Rank"]), 9000)
        self.assertEqual(float(judge["Fantasy Edge"]), 5.0)

    def test_compact_round_trip_repairs_defaults(self) -> None:
        from live_draft_state import room_from_persist_dict, room_to_persist_dict

        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Aaron Judge",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.95,
                    "ADP Rank": 12,
                }
            ]
        )
        room = {"status": "in_progress", "pool": pool}
        blob = room_to_persist_dict(room, compact_pool=True)
        restored = room_from_persist_dict(blob)
        assert isinstance(restored, dict)
        frame = restored["pool"]
        self.assertLess(float(frame.loc[0, "Model Rank"]), 9000)
        self.assertEqual(float(frame.loc[0, "Market Rank"]), 12.0)


if __name__ == "__main__":
    unittest.main()
