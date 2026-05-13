"""Unit tests for draft projection style factor tables."""

import unittest

from projection_style import PROJECTION_STYLE_OPTIONS, get_draft_projection_factors


class TestProjectionStyleFactors(unittest.TestCase):
    def test_projection_style_options_include_balanced(self):
        self.assertIn("Balanced", PROJECTION_STYLE_OPTIONS)
        self.assertIn("Conservative", PROJECTION_STYLE_OPTIONS)
        self.assertIn("Aggressive / Upside", PROJECTION_STYLE_OPTIONS)

    def test_balanced_matches_legacy_defaults(self):
        f = get_draft_projection_factors("Balanced")
        self.assertEqual(f["regression_strength_multiplier"], 1.0)
        self.assertEqual(f["youth_bump"], 0.05)
        self.assertEqual(f["reg_strength_min"], 0.10)
        self.assertEqual(f["reg_strength_max"], 0.42)
        self.assertEqual(f["trend_clip_hr"], (-5.0, 5.0))
        self.assertEqual(f["trend_clip_sb"], (-5.0, 5.0))
        self.assertEqual(f["trend_clip_ops"], (-0.060, 0.060))
        self.assertEqual(f["trend_clip_ba"], (-0.030, 0.030))
        self.assertEqual(f["anchor_player_weight"], 0.84)
        self.assertEqual(f["breakout_weights"], (0.35, 0.20, 0.15, 0.20, 0.10))
        self.assertEqual(sum(f["breakout_weights"]), 1.0)
        self.assertEqual(f["context_weights"], (0.70, 0.15, 0.10, 0.05))
        self.assertEqual(f["raw_adj_clip"], 0.10)
        self.assertEqual(f["ml_adj_clip"], 0.06)
        self.assertEqual(f["recency_weight_latest"], 0.0)

    def test_conservative_stronger_shrinkage_and_tighter_caps(self):
        b = get_draft_projection_factors("Balanced")
        c = get_draft_projection_factors("Conservative")
        self.assertGreater(c["regression_strength_multiplier"], b["regression_strength_multiplier"])
        self.assertLess(c["anchor_player_weight"], b["anchor_player_weight"])
        self.assertLess(abs(c["trend_clip_hr"][1]), abs(b["trend_clip_hr"][1]))
        self.assertLess(c["raw_adj_clip"], b["raw_adj_clip"])
        self.assertLess(c["ml_adj_clip"], b["ml_adj_clip"])

    def test_aggressive_reduces_regression_and_adds_recency(self):
        b = get_draft_projection_factors("Balanced")
        a = get_draft_projection_factors("Aggressive / Upside")
        self.assertLess(a["regression_strength_multiplier"], b["regression_strength_multiplier"])
        self.assertGreater(a["anchor_player_weight"], b["anchor_player_weight"])
        self.assertGreater(a["recency_weight_latest"], 0)
        self.assertGreater(a["raw_adj_clip"], b["raw_adj_clip"])

    def test_unknown_mode_falls_back_to_balanced_numeric_profile(self):
        f = get_draft_projection_factors("not-a-real-mode")
        self.assertEqual(f["anchor_player_weight"], 0.84)
        self.assertEqual(f["ml_adj_clip"], 0.06)


if __name__ == "__main__":
    unittest.main()
