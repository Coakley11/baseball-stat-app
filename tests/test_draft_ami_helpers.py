"""Tests for draft AMI helper utilities."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_ami_helpers import (
    compact_fantasy_market_rows,
    compact_recommendation_rows,
    detect_positions_from_question,
    draft_ami_guidance,
)


class TestDraftAmiHelpers(unittest.TestCase):
    def test_compact_recommendation_rows(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "fullName": "Corbin Carroll",
                    "Primary Position": "OF",
                    "Model Rank": 10,
                    "Reason": "Strong fit",
                }
            ]
        )
        rows = compact_recommendation_rows(df)
        self.assertEqual(rows[0]["player"], "Corbin Carroll")
        self.assertEqual(rows[0]["Primary Position"], "OF")
        self.assertEqual(rows[0]["reason"], "Strong fit")

    def test_compact_fantasy_market_rows(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "fullName": "Junior Caminero",
                    "Fantasy Edge": 40,
                    "Reason": "Undervalued",
                }
            ]
        )
        rows = compact_fantasy_market_rows(df)
        self.assertEqual(rows[0]["player"], "Junior Caminero")
        self.assertEqual(rows[0]["Fantasy Edge"], 40)

    def test_draft_ami_guidance_per_page(self) -> None:
        self.assertIn("sleeper", draft_ami_guidance("Fantasy Sleepers & Busts").lower())
        self.assertIn("my_next_pick", draft_ami_guidance("Live Draft Room"))
        self.assertIn("canonical", draft_ami_guidance("Draft Assistant Simulator").lower())
        self.assertIn("valuation", draft_ami_guidance("Valuation").lower())

    def test_detect_positions_from_question_aliases(self) -> None:
        self.assertEqual(detect_positions_from_question("next catcher drafted"), ["C"])
        self.assertIn("SS", detect_positions_from_question("wait on shortstop"))
        self.assertIn("RP", detect_positions_from_question("relief pitcher run"))


if __name__ == "__main__":
    unittest.main()
