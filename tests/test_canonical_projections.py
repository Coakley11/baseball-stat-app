"""Regression tests for canonical projection stat lines across pages."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from canonical_projections import (
    CANONICAL_PROJ_STAT_COLUMNS,
    apply_ml_blend_to_projection_stats,
    merge_canonical_projections,
    projection_consistency_signature,
)


def _sample_pool(*, ml_adj: float = 0.05) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "playerID": "judge01",
                "fullName": "Aaron Judge",
                "Primary Position": "OF",
                "ML Adjustment": ml_adj,
                "proj_HR": 40.0,
                "proj_RBI": 100.0,
                "proj_R": 95.0,
                "proj_SB": 8.0,
                "proj_BA": 0.285,
                "proj_OPS": 0.980,
            },
            {
                "playerID": "trout01",
                "fullName": "Mike Trout",
                "Primary Position": "OF",
                "ML Adjustment": 0.02,
                "proj_HR": 35.0,
                "proj_RBI": 85.0,
                "proj_R": 90.0,
                "proj_SB": 12.0,
                "proj_BA": 0.275,
                "proj_OPS": 0.920,
            },
        ]
    )


class CanonicalProjectionTests(unittest.TestCase):
    def test_ml_blend_scales_proj_stats_when_enabled(self) -> None:
        pool = _sample_pool(ml_adj=0.10)
        blended = apply_ml_blend_to_projection_stats(pool, use_ml_blend=True, ml_blend_weight=0.12)
        baseline = apply_ml_blend_to_projection_stats(pool, use_ml_blend=False, ml_blend_weight=0.12)
        self.assertEqual(blended.iloc[0]["Projection Source"], "ml_blended")
        self.assertEqual(baseline.iloc[0]["Projection Source"], "baseline")
        self.assertGreater(float(blended.iloc[0]["proj_HR"]), float(baseline.iloc[0]["proj_HR"]))

    def test_merge_canonical_projections_overwrites_page_proj_columns(self) -> None:
        canonical = apply_ml_blend_to_projection_stats(
            _sample_pool(), use_ml_blend=True, ml_blend_weight=0.12
        )
        page_df = pd.DataFrame(
            [
                {
                    "playerID": "judge01",
                    "fullName": "Aaron Judge",
                    "proj_HR": 22.0,
                    "proj_RBI": 55.0,
                    "HR": 58,
                    "RBI": 144,
                }
            ]
        )
        merged = merge_canonical_projections(page_df, canonical)
        self.assertAlmostEqual(float(merged.iloc[0]["proj_HR"]), float(canonical.iloc[0]["proj_HR"]))
        self.assertAlmostEqual(float(merged.iloc[0]["proj_RBI"]), float(canonical.iloc[0]["proj_RBI"]))
        self.assertEqual(int(merged.iloc[0]["HR"]), 58)

    def test_same_player_same_signature_across_merged_pages(self) -> None:
        canonical = apply_ml_blend_to_projection_stats(
            _sample_pool(), use_ml_blend=True, ml_blend_weight=0.12
        )
        trends = merge_canonical_projections(
            pd.DataFrame([{"playerID": "judge01", "fullName": "Aaron Judge", "proj_HR": 1.0}]),
            canonical,
        )
        sleepers = merge_canonical_projections(
            pd.DataFrame([{"playerID": "judge01", "fullName": "Aaron Judge", "proj_HR": 99.0}]),
            canonical,
        )
        sig_t = projection_consistency_signature(trends.iloc[0])
        sig_s = projection_consistency_signature(sleepers.iloc[0])
        self.assertEqual(sig_t, sig_s)

    def test_ml_blend_off_keeps_baseline_proj_stats(self) -> None:
        pool = _sample_pool()
        out = apply_ml_blend_to_projection_stats(pool, use_ml_blend=False, ml_blend_weight=0.12)
        self.assertAlmostEqual(float(out.iloc[0]["proj_HR"]), 40.0)
        self.assertEqual(out.iloc[0]["Projection Source"], "baseline")

    def test_canonical_columns_present(self) -> None:
        self.assertIn("proj_HR", CANONICAL_PROJ_STAT_COLUMNS)
        self.assertIn("proj_OPS", CANONICAL_PROJ_STAT_COLUMNS)

    def test_projection_signature_handles_nan(self) -> None:
        row = {"proj_HR": np.nan, "proj_RBI": 80.0}
        sig = projection_consistency_signature(row, proj_cols=("proj_HR", "proj_RBI"))
        self.assertIsNone(sig[0])
        self.assertEqual(sig[1], 80.0)


if __name__ == "__main__":
    unittest.main()
