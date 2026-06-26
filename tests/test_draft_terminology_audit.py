"""Audit generated insight/reason text for legacy draft score terminology."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_lab_analysis import _explain_best_pick, _explain_good_pick, _questionable_reasons
from draft_score_display import FORBIDDEN_USER_SCORE_TERMS, sanitize_draft_terminology_text
from draft_strategy_intel import draft_strategy_line


def _assert_no_legacy_terms(text: str) -> None:
    cleaned = sanitize_draft_terminology_text(text)
    for term in FORBIDDEN_USER_SCORE_TERMS:
        assert term not in cleaned, f"legacy term {term!r} in: {text!r}"


class DraftTerminologyAuditTests(unittest.TestCase):
    def test_draft_lab_pick_reason_generators(self) -> None:
        row = pd.Series(
            {
                "fullName": "Test Player",
                "Primary Position": "OF",
                "Model Rank": 40,
                "Market Rank": 80,
                "Fantasy Edge": 12,
                "Decision Score": 0.84,
                "Draft Fit Score": 0.72,
                "Pick": 5,
            }
        )
        for text in (
            _explain_best_pick(row, gaps_before=["OF"]),
            _explain_good_pick(row, gaps_before=["OF"]),
            "; ".join(
                _questionable_reasons(
                    row,
                    gaps_before=["C"],
                    team_median_decision=0.9,
                    better_alternatives=4,
                )
            ),
        ):
            _assert_no_legacy_terms(text)

    def test_draft_strategy_line_generated_copy(self) -> None:
        row = pd.Series(
            {
                "Primary Position": "SS",
                "Fantasy Edge": 18,
                "Market Rank": 55,
                "Model Rank": 37,
                "Availability Probability": 0.35,
                "proj_HR": 28,
                "proj_BA": 0.285,
                "proj_SB": 16,
                "Risk Penalty": 0.018,
            }
        )
        text = draft_strategy_line(
            row,
            draft_format="5x5 Roto",
            needed_positions=["SS"],
            category_needs=[],
            current_position_counts={"SS": 0},
            target_position_counts={"SS": 1},
            position_meta_by_pos={"SS": {"dropoff": 0.12, "available": 14}},
            median_scarcity_dropoff=0.08,
            remaining_high_sb_count=10,
            remaining_high_hr_count=15,
            current_pick=12,
            roster_means={"proj_HR": 210},
            pool_means={"proj_HR": 205, "proj_BA": 0.265},
        )
        _assert_no_legacy_terms(text)


if __name__ == "__main__":
    unittest.main()
