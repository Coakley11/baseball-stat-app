"""Tests for live draft required pool columns and scoring safety."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_scoring_pool import (
    LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS,
    POOL_KIND_FAST_MARKET_FALLBACK,
    POOL_KIND_VALID_PROJECTION,
    POOL_VALUE_KIND_KEY,
    analyze_compact_pool,
    ensure_draft_scoring_pool_columns,
    ensure_draft_scoring_pool_columns_with_report,
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

    def test_ensure_derives_primary_position_from_adp_when_util(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Jose Ramirez",
                    "Primary Position": "UTIL",
                    "ADP Position": "3B,DH",
                    "FantasyPros Position": "3B1",
                    "Expected Fantasy Value": 90.0,
                    "Market Rank": 5,
                    "Model Rank": 4,
                }
            ]
        )
        out = ensure_draft_scoring_pool_columns(pool)
        self.assertEqual(str(out.loc[0, "Primary Position"]), "3B")

    def test_zero_efv_column_rebuilds_market_proxy_and_ranks(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Early Star",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.0,
                    "Market Rank": 5,
                    "Model Rank": 9999,
                    "Fantasy Edge": 0.0,
                },
                {
                    "playerID": "p2",
                    "fullName": "Deep Fringe",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.0,
                    "Market Rank": 350,
                    "Model Rank": 9999,
                    "Fantasy Edge": 349.0,
                },
                {
                    "playerID": "p3",
                    "fullName": "Mid Tier",
                    "Primary Position": "SS",
                    "Expected Fantasy Value": 0.0,
                    "Market Rank": 40,
                    "Model Rank": 9999,
                    "Fantasy Edge": 39.0,
                },
            ]
        )
        out, report = ensure_draft_scoring_pool_columns_with_report(pool)
        self.assertEqual(report.get("pool_value_kind"), POOL_KIND_FAST_MARKET_FALLBACK)
        efv = pd.to_numeric(out["Expected Fantasy Value"], errors="coerce")
        # Temporary proxy must stay on Player Grade 0–1 scale (not ADP counts).
        self.assertLessEqual(float(efv.max()), 1.0)
        self.assertGreater(float(efv.max()), 0.0)
        self.assertGreater(int(efv.nunique()), 1)
        early = out.loc[out["fullName"] == "Early Star"].iloc[0]
        fringe = out.loc[out["fullName"] == "Deep Fringe"].iloc[0]
        self.assertGreater(float(early["Expected Fantasy Value"]), float(fringe["Expected Fantasy Value"]))
        model = pd.to_numeric(out["Model Rank"], errors="coerce")
        self.assertGreater(int(model.nunique()), 1)
        self.assertLess(abs(float(fringe["Fantasy Edge"])), 50.0)

    def test_adp_count_scale_efv_coerced_to_player_grade_0_1(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Aaron Judge",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 739.0,
                    "Market Rank": 2,
                    "Model Rank": 2,
                    "Fantasy Edge": 0.0,
                },
                {
                    "playerID": "p2",
                    "fullName": "Ben Williamson",
                    "Primary Position": "3B",
                    "Expected Fantasy Value": 381.0,
                    "Market Rank": 359,
                    "Model Rank": 359,
                    "Fantasy Edge": 0.0,
                },
            ]
        )
        out, report = ensure_draft_scoring_pool_columns_with_report(pool)
        efv = pd.to_numeric(out["Expected Fantasy Value"], errors="coerce")
        self.assertLessEqual(float(efv.max()), 1.0)
        self.assertEqual(report.get("efv_repair"), "coerced_adp_count_scale_to_player_grade_0_1")
        judge = out.loc[out["fullName"] == "Aaron Judge"].iloc[0]
        fringe = out.loc[out["fullName"] == "Ben Williamson"].iloc[0]
        self.assertGreater(float(judge["Expected Fantasy Value"]), float(fringe["Expected Fantasy Value"]))

    def test_valid_projection_player_grade_preserved_on_0_1_scale(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Aaron Judge",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.95,
                    "Market Rank": 15,
                    "Model Rank": 8,
                    "Fantasy Edge": 7,
                },
                {
                    "playerID": "p2",
                    "fullName": "Bench Bat",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.40,
                    "Market Rank": 120,
                    "Model Rank": 140,
                    "Fantasy Edge": -20,
                },
            ]
        )
        out, report = ensure_draft_scoring_pool_columns_with_report(pool)
        self.assertEqual(report.get("pool_value_kind"), POOL_KIND_VALID_PROJECTION)
        judge = out.loc[out["fullName"] == "Aaron Judge"].iloc[0]
        self.assertAlmostEqual(float(judge["Expected Fantasy Value"]), 0.95, places=5)
        from draft_score_display import fmt_player_grade, fmt_pick_score

        self.assertEqual(fmt_player_grade(0.95), "95")
        # Decision Score display uses 0–100 contract for internal 0–1 values.
        self.assertEqual(fmt_pick_score(0.91), "91")

    def test_sentinel_model_rank_recomputed_not_collapsed(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "A",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 95.0,
                    "Market Rank": 10,
                    "Model Rank": 9999,
                },
                {
                    "playerID": "p2",
                    "fullName": "B",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 80.0,
                    "Market Rank": 25,
                    "Model Rank": 9999,
                },
                {
                    "playerID": "p3",
                    "fullName": "C",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 50.0,
                    "Market Rank": 100,
                    "Model Rank": 9999,
                },
            ]
        )
        out = ensure_draft_scoring_pool_columns(pool)
        ranks = pd.to_numeric(out["Model Rank"], errors="coerce")
        self.assertTrue((ranks < 9000).all())
        self.assertGreater(int(ranks.nunique()), 1)
        self.assertEqual(float(out.loc[out["fullName"] == "A", "Model Rank"].iloc[0]), 1.0)

    def test_collapsed_model_rank_does_not_create_fake_edge(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Elite",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.0,
                    "Market Rank": 8,
                    "Model Rank": 1,
                    "Fantasy Edge": 7.0,
                },
                {
                    "playerID": "p2",
                    "fullName": "Ben Fringe",
                    "Primary Position": "3B",
                    "Expected Fantasy Value": 0.0,
                    "Market Rank": 359,
                    "Model Rank": 1,
                    "Fantasy Edge": 358.0,
                },
            ]
        )
        out = ensure_draft_scoring_pool_columns(pool)
        fringe = out.loc[out["fullName"] == "Ben Fringe"].iloc[0]
        self.assertLess(abs(float(fringe["Fantasy Edge"])), 5.0)
        self.assertNotEqual(float(fringe["Model Rank"]), 1.0)
        model = pd.to_numeric(out["Model Rank"], errors="coerce")
        self.assertGreater(int(model.nunique()), 1)

    def test_valid_projection_pool_preserved(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Aaron Judge",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.95,
                    "Market Rank": 15,
                    "Model Rank": 8,
                    "Fantasy Edge": 7,
                },
                {
                    "playerID": "p2",
                    "fullName": "Bench Bat",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.40,
                    "Market Rank": 120,
                    "Model Rank": 140,
                    "Fantasy Edge": -20,
                },
            ]
        )
        out, report = ensure_draft_scoring_pool_columns_with_report(pool)
        self.assertEqual(report.get("pool_value_kind"), POOL_KIND_VALID_PROJECTION)
        judge = out.loc[out["fullName"] == "Aaron Judge"].iloc[0]
        self.assertAlmostEqual(float(judge["Expected Fantasy Value"]), 0.95, places=5)
        self.assertEqual(float(judge["Model Rank"]), 8.0)
        self.assertEqual(float(judge["Fantasy Edge"]), 7.0)

    def test_decision_score_weights_match_baseline_contract(self) -> None:
        """Decision Score still uses established 0.55 value / 0.20 rank / … weights."""
        import inspect

        from live_draft_pick_scoring import apply_draft_pick_scoring

        src = inspect.getsource(apply_draft_pick_scoring)
        self.assertIn("value_dec * 0.55", src)
        self.assertIn("* 0.20", src)
        self.assertIn("* 0.10", src)
        self.assertIn("pool_scarcity * 0.05", src)
        self.assertNotIn("market_rank_proxy", src)

    def test_strong_market_outranks_deep_adp_when_fit_equal(self) -> None:
        """Generic ranking sanity: early market beat deep ADP when value signal repaired."""
        pool = pd.DataFrame(
            [
                {
                    "playerID": "early",
                    "fullName": "Early Market",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.0,
                    "Market Rank": 12,
                    "Model Rank": 9999,
                    "Fantasy Edge": 0.0,
                },
                {
                    "playerID": "deep",
                    "fullName": "Deep Adp",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.0,
                    "Market Rank": 340,
                    "Model Rank": 9999,
                    "Fantasy Edge": 339.0,
                },
            ]
        )
        repaired = ensure_draft_scoring_pool_columns(pool)
        early = repaired.loc[repaired["fullName"] == "Early Market"].iloc[0]
        deep = repaired.loc[repaired["fullName"] == "Deep Adp"].iloc[0]
        self.assertLessEqual(float(early["Expected Fantasy Value"]), 1.0)
        self.assertGreater(float(early["Expected Fantasy Value"]), float(deep["Expected Fantasy Value"]))
        self.assertLess(float(early["Model Rank"]), float(deep["Model Rank"]))
        self.assertLess(abs(float(deep["Fantasy Edge"])), 20.0)
        by_efv = repaired.sort_values("Expected Fantasy Value", ascending=False)
        self.assertEqual(str(by_efv.iloc[0]["fullName"]), "Early Market")


if __name__ == "__main__":
    unittest.main()
