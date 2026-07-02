"""Regression tests for Projection Breakdown canonical alignment."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

import projection_breakdown as pb
from canonical_projections import CANONICAL_PROJ_STAT_COLUMNS, merge_canonical_projections

_REPO = Path(__file__).resolve().parents[1]


class ProjectionBreakdownCanonicalTests(unittest.TestCase):
    def test_snapshot_matches_canonical_proj_columns(self) -> None:
        row = pd.Series(
            {
                "proj_HR": 43,
                "proj_RBI": 100,
                "proj_R": 95,
                "proj_SB": 12,
                "proj_BA": 0.285,
                "proj_OPS": 0.980,
                "Expected Fantasy Value": 0.9626,
                "Projection Confidence Score": 0.8,
                "proj_G": 145,
                "Realistic Base Projection Score": 0.91,
            }
        )
        snap = pb.build_projection_snapshot(row)
        self.assertEqual(snap["projections"]["HR"], 43)
        self.assertEqual(snap["projections"]["OPS"], 0.98)
        self.assertEqual(snap["efv_raw"], 0.9626)
        self.assertEqual(snap["player_grade"], "96.26")

    def test_breakdown_bundle_uses_same_row_projections(self) -> None:
        row = pd.Series(
            {
                "proj_HR": 43,
                "proj_OPS": 0.980,
                "Expected Fantasy Value": 0.9626,
                "Projection Confidence Score": 0.8,
                "proj_G": 145,
            }
        )
        bundle = pb.build_projection_breakdown_bundle(
            "Aaron Judge",
            row,
            data_source="unified_stabilized_pool",
            projection_system=pb.PROJECTION_SYSTEM_LABEL,
            window_years=3,
            projection_style="Balanced",
        )
        self.assertEqual(bundle["snapshot"]["projections"]["HR"], 43)
        self.assertEqual(bundle["snapshot"]["player_grade"], "96.26")

    def test_merge_canonical_projections_aligns_page_with_pool(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "j1",
                    "fullName": "Aaron Judge",
                    "proj_HR": 43,
                    "proj_OPS": 0.98,
                    "Expected Fantasy Value": 0.9626,
                }
            ]
        )
        page = pd.DataFrame(
            [
                {
                    "playerID": "j1",
                    "fullName": "Aaron Judge",
                    "proj_HR": 48,
                    "proj_OPS": 0.92,
                }
            ]
        )
        merged = merge_canonical_projections(page, pool)
        self.assertEqual(int(merged.iloc[0]["proj_HR"]), 43)

    def test_breakdown_pool_uses_live_unified_pool(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertNotIn("PROJECTION_BREAKDOWN_PROFILE", text)
        self.assertNotIn("def get_projection_breakdown_pool(", text)
        start = text.find("def get_projection_breakdown_pool_live")
        chunk = text[start : start + 250]
        self.assertIn("get_cached_unified_projection_pool_live()", chunk)

    def test_trend_only_diagnostic_differs_from_canonical(self) -> None:
        season = pd.DataFrame(
            {
                "yearID": [2023, 2024, 2025],
                "G": [150, 150, 150],
                "HR": [30, 35, 40],
                "RBI": [90, 95, 100],
                "R": [100, 105, 110],
                "SB": [5, 6, 7],
                "BA": [0.280, 0.285, 0.290],
                "OPS": [0.900, 0.920, 0.940],
            }
        )
        row = pd.Series(
            {
                "proj_HR": 43,
                "proj_RBI": 100,
                "proj_R": 95,
                "proj_SB": 12,
                "proj_BA": 0.285,
                "proj_OPS": 0.980,
                "Expected Fantasy Value": 0.9626,
                "Projection Confidence Score": 0.8,
                "proj_G": 145,
            }
        )
        bundle = pb.build_projection_breakdown_bundle(
            "Aaron Judge",
            row,
            data_source="unified_stabilized_pool",
            projection_system=pb.PROJECTION_SYSTEM_LABEL,
            window_years=3,
            projection_style="Aggressive / Upside",
            season_history=season,
        )
        self.assertEqual(bundle["snapshot"]["projections"]["HR"], 43)
        self.assertIn("HR", bundle["diagnostic_trend_only"])
        self.assertNotEqual(
            int(round(bundle["diagnostic_trend_only"]["HR"])),
            int(round(bundle["snapshot"]["projections"]["HR"])),
        )

    def test_sleepers_market_merge_includes_player_key(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        marker = '_market_merge_cols = ["Player Key"]'
        self.assertIn(marker, text)

    def test_canonical_proj_stat_columns_cover_breakdown(self) -> None:
        for col in ("proj_HR", "proj_RBI", "proj_R", "proj_SB", "proj_BA", "proj_OPS"):
            self.assertIn(col, CANONICAL_PROJ_STAT_COLUMNS)


if __name__ == "__main__":
    unittest.main()
