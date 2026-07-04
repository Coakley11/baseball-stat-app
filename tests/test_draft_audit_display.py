"""Tests for post-draft audit table formatting and pick verdicts."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_lab_analysis import draft_lab_table_readme_markdown, enrich_draft_board_pick_verdicts
from draft_score_display import (
    fmt_confidence_score,
    fmt_roster_fit_score,
    normalize_projection_confidence_column,
    normalize_projection_warning_column,
    prepare_draft_scores_for_display,
)
from live_draft_pick_engine import build_pick_verdict


class DraftAuditFormattingTests(unittest.TestCase):
    def test_prepare_draft_scores_idempotent_for_already_scaled_decision(self) -> None:
        df = pd.DataFrame([{"Decision Score": 96.09, "Draft Fit Score": 1.4838}])
        once = prepare_draft_scores_for_display(df)
        twice = prepare_draft_scores_for_display(once)
        self.assertEqual(float(once.iloc[0]["Decision Score"]), 96.09)
        self.assertEqual(float(twice.iloc[0]["Decision Score"]), 96.09)
        self.assertEqual(float(once.iloc[0]["Roster Fit Score"]), 1.48)

    def test_roster_fit_always_two_decimals(self) -> None:
        self.assertEqual(fmt_roster_fit_score(1.4838), "1.48")
        self.assertEqual(fmt_roster_fit_score(1.45), "1.45")

    def test_confidence_numeric_format(self) -> None:
        self.assertEqual(fmt_confidence_score(0.985167), "0.99")
        self.assertEqual(fmt_confidence_score("High Confidence"), "—")

    def test_normalize_projection_confidence_from_text_and_score(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "Projection Confidence": "High Confidence",
                    "Projection Confidence Score": 0.985,
                },
                {"Projection Confidence": 0.91, "Projection Confidence Score": None},
            ]
        )
        out = normalize_projection_confidence_column(df)
        self.assertAlmostEqual(float(out.iloc[0]["Projection Confidence"]), 0.985, places=3)
        self.assertAlmostEqual(float(out.iloc[1]["Projection Confidence"]), 0.91, places=2)

    def test_normalize_projection_warning_short_labels(self) -> None:
        df = pd.DataFrame(
            [{"Projection Warning": "Volatile profile: projection confidence reduced"}]
        )
        out = normalize_projection_warning_column(df)
        self.assertEqual(out.iloc[0]["Projection Warning"], "High Volatility")

    def test_empty_warning_displays_dash(self) -> None:
        df = pd.DataFrame([{"Projection Warning": ""}])
        out = normalize_projection_warning_column(df)
        self.assertEqual(out.iloc[0]["Projection Warning"], "—")

    def test_audit_score_pipeline_double_prepare_keeps_decision_score(self) -> None:
        """Avoid importing streamlit_app — only test display-prep idempotency."""
        from draft_score_display import (
            fmt_confidence_score,
            normalize_projection_confidence_column,
            normalize_projection_warning_column,
            prepare_draft_scores_for_display,
        )

        df = pd.DataFrame(
            [
                {
                    "Decision Score": 0.9609,
                    "Draft Fit Score": 1.4838,
                    "Projection Confidence Score": 0.985,
                    "Projection Warning": "",
                }
            ]
        )
        once = prepare_draft_scores_for_display(
            normalize_projection_warning_column(normalize_projection_confidence_column(df.copy()))
        )
        twice = prepare_draft_scores_for_display(once.copy())
        self.assertEqual(float(once.iloc[0]["Decision Score"]), 96.09)
        self.assertEqual(float(twice.iloc[0]["Decision Score"]), 96.09)
        self.assertEqual(float(once.iloc[0]["Roster Fit Score"]), 1.48)
        self.assertEqual(fmt_confidence_score(once.iloc[0]["Projection Confidence"]), "0.99")


class PickVerdictTests(unittest.TestCase):
    def test_value_vs_adp_verdict(self) -> None:
        row = {
            "Pick": 50,
            "Market Rank": 145,
            "Fantasy Edge": 31,
            "Primary Position": "OF",
        }
        text = build_pick_verdict(row, pick_no=50)
        self.assertIn("95 spots after ADP", text)
        self.assertIn("+31 Fantasy Edge", text)

    def test_position_need_with_roster_fit(self) -> None:
        row = {
            "Pick": 8,
            "Primary Position": "OF",
            "Draft Fit Score": 1.72,
            "Scarcity Score": 0.55,
        }
        text = build_pick_verdict(row, gaps=["OF"], pick_no=8)
        self.assertIn("Filled OF need with 1.72 roster-fit score", text)

    def test_no_generic_strong_decision_prefix(self) -> None:
        row = {
            "Pick": 3,
            "Decision Score": 0.82,
            "Fantasy Edge": 4,
            "Primary Position": "SS",
        }
        text = build_pick_verdict(row, pick_no=3)
        self.assertNotIn("Strong decision", text)
        self.assertNotIn("Manual Pick", text)

    def test_enrich_draft_board_pick_verdicts(self) -> None:
        draft = pd.DataFrame(
            [
                {
                    "Pick": 1,
                    "Fantasy Team": "Daniel",
                    "fullName": "Player A",
                    "Primary Position": "OF",
                    "Market Rank": 120,
                    "Fantasy Edge": 25,
                    "Decision Score": 0.88,
                    "Draft Fit Score": 1.4,
                }
            ]
        )
        out = enrich_draft_board_pick_verdicts(draft)
        self.assertIn("Pick Verdict", out.columns)
        self.assertTrue(str(out.iloc[0]["Pick Verdict"]).strip())

    def test_readme_contains_confidence_and_scarcity(self) -> None:
        md = draft_lab_table_readme_markdown()
        self.assertIn("Projection Confidence", md)
        self.assertIn("Scarcity Score", md)
        self.assertIn("0.95", md)


if __name__ == "__main__":
    unittest.main()
