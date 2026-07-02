"""Tests for draft score display naming and formatting (no formula changes)."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_score_display import (
    DISPLAY_PICK_SCORE,
    DISPLAY_PLAYER_GRADE,
    DISPLAY_RELATIVE_GRADE,
    DISPLAY_ROSTER_FIT,
    FORBIDDEN_USER_SCORE_TERMS,
    coerce_sleeper_min_player_grade,
    compact_context_row_for_display,
    fmt_pick_score,
    fmt_player_grade,
    fmt_relative_draft_grade,
    fmt_roster_fit_score,
    prepare_draft_scores_for_display,
    sanitize_draft_terminology_text,
    sleeper_min_player_grade_to_internal,
    style_cols_for_display,
)


class DraftScoreDisplayTests(unittest.TestCase):
    def test_player_grade_scales_to_100(self) -> None:
        self.assertEqual(fmt_player_grade(0.9012), "90.12")
        self.assertEqual(fmt_player_grade(0.7834), "78.34")

    def test_sleeper_min_player_grade_migrates_legacy_efv_scale(self) -> None:
        self.assertEqual(coerce_sleeper_min_player_grade(0.10), 10.0)
        self.assertEqual(coerce_sleeper_min_player_grade(50), 50.0)
        self.assertEqual(sleeper_min_player_grade_to_internal(50), 0.5)
        self.assertEqual(sleeper_min_player_grade_to_internal(0.10), 0.1)

    def test_sleeper_min_player_grade_filters_internal_scores(self) -> None:
        scores = pd.Series([0.45, 0.55, 0.72])
        threshold = sleeper_min_player_grade_to_internal(60)
        kept = scores[scores >= threshold]
        self.assertEqual(kept.tolist(), [0.72])

    def test_pick_score_scales_to_100(self) -> None:
        self.assertEqual(fmt_pick_score(0.9123), "91.23")
        self.assertEqual(fmt_pick_score(0.7421), "74.21")

    def test_pick_score_exact_two_decimals_from_long_values(self) -> None:
        self.assertEqual(fmt_pick_score(0.94756234), "94.76")
        self.assertEqual(fmt_pick_score(0.8907), "89.07")
        self.assertEqual(fmt_pick_score(0.92), "92")
        self.assertEqual(fmt_pick_score(1.0), "100")
        self.assertEqual(fmt_pick_score(94.756234), "94.76")

    def test_ml_projection_score_trim_trailing_zeros(self) -> None:
        from draft_score_display import fmt_ml_projection_score

        self.assertEqual(fmt_ml_projection_score(0.94756234), "94.76")
        self.assertEqual(fmt_ml_projection_score(0.8907), "89.07")
        self.assertEqual(fmt_ml_projection_score(0.92), "92")
        self.assertEqual(fmt_ml_projection_score(1.0), "100")
        self.assertEqual(fmt_ml_projection_score(0.885), "88.5")
        self.assertEqual(fmt_ml_projection_score(89.07), "89.07")

    def test_roster_fit_not_scaled(self) -> None:
        self.assertEqual(fmt_roster_fit_score(1.70), "1.70")
        self.assertEqual(fmt_roster_fit_score(0.88), "0.88")

    def test_ml_projection_score_scales_to_100(self) -> None:
        from draft_score_display import fmt_ml_projection_score

        self.assertEqual(fmt_ml_projection_score(0.9475), "94.75")
        self.assertEqual(fmt_ml_projection_score(0.8907), "89.07")

    def test_valuation_score_scales_to_100(self) -> None:
        from draft_score_display import fmt_valuation_score

        self.assertEqual(fmt_valuation_score(1), "100.00")
        self.assertEqual(fmt_valuation_score(0.9583), "95.83")
        self.assertEqual(fmt_valuation_score(0.9204), "92.04")

    def test_prepare_scales_ml_projection_score(self) -> None:
        df = pd.DataFrame([{"ML Projection Score": 0.9475}])
        out = prepare_draft_scores_for_display(df)
        self.assertEqual(float(out.iloc[0]["ML Projection Score"]), 94.75)

    def test_relative_draft_grade_two_decimals(self) -> None:
        self.assertEqual(fmt_relative_draft_grade(0.8214), "82.14")
        self.assertEqual(fmt_relative_draft_grade(0.2785), "27.85")

    def test_prepare_renames_and_scales_columns(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "Expected Fantasy Value": 0.9,
                    "Decision Score": 0.85,
                    "Draft Fit Score": 1.42,
                    "Overall Draft Grade Score": 0.73,
                }
            ]
        )
        out = prepare_draft_scores_for_display(df)
        self.assertIn(DISPLAY_PLAYER_GRADE, out.columns)
        self.assertIn(DISPLAY_PICK_SCORE, out.columns)
        self.assertIn(DISPLAY_ROSTER_FIT, out.columns)
        self.assertIn(DISPLAY_RELATIVE_GRADE, out.columns)
        self.assertEqual(float(out.iloc[0][DISPLAY_PLAYER_GRADE]), 90.0)
        self.assertEqual(float(out.iloc[0][DISPLAY_PICK_SCORE]), 85.0)
        self.assertEqual(float(out.iloc[0][DISPLAY_ROSTER_FIT]), 1.42)
        self.assertEqual(float(out.iloc[0][DISPLAY_RELATIVE_GRADE]), 73.0)

    def test_style_cols_map_to_display_names(self) -> None:
        mapped = style_cols_for_display(["Fantasy Edge", "Draft Fit Score", "Expected Fantasy Value"])
        self.assertEqual(mapped, ["Fantasy Edge", DISPLAY_ROSTER_FIT, DISPLAY_PLAYER_GRADE])

    def test_sanitize_legacy_score_terms_in_prose(self) -> None:
        raw = "Decision Score 0.91 beats Draft Fit Score; EFV is high vs Expected Fantasy Value."
        cleaned = sanitize_draft_terminology_text(raw)
        for term in FORBIDDEN_USER_SCORE_TERMS:
            self.assertNotIn(term, cleaned)
        self.assertIn(DISPLAY_PICK_SCORE, cleaned)
        self.assertIn(DISPLAY_ROSTER_FIT, cleaned)
        self.assertIn(DISPLAY_PLAYER_GRADE, cleaned)

    def test_compact_context_row_renames_ami_keys(self) -> None:
        row = compact_context_row_for_display(
            {
                "player": "Aaron Judge",
                "Expected Fantasy Value": 0.91,
                "Decision Score": 0.88,
                "Draft Fit Score": 1.42,
                "reason": "Strong Decision Score with elite EFV.",
            }
        )
        self.assertIn(DISPLAY_PLAYER_GRADE, row)
        self.assertIn(DISPLAY_PICK_SCORE, row)
        self.assertIn(DISPLAY_ROSTER_FIT, row)
        self.assertEqual(row[DISPLAY_PLAYER_GRADE], 91.0)
        self.assertEqual(row[DISPLAY_PICK_SCORE], 88.0)
        self.assertNotIn("Decision Score", row["reason"])
        self.assertNotIn("EFV", row["reason"])


if __name__ == "__main__":
    unittest.main()
