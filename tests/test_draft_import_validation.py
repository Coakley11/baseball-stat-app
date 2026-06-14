"""Tests for draft import validation."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_import_validation import (
    build_validated_import_dataframe,
    import_review_ready,
    validate_imported_draft_df,
)
from draft_player_names import classify_draft_player_import_name, build_draft_player_name_index


class TestDraftImportValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = pd.DataFrame(
            {
                "fullName": [
                    "Francisco Lindor",
                    "Framber Valdez",
                    "Aaron Judge",
                    "Juan Soto",
                ]
            }
        )
        self.index = build_draft_player_name_index(self.pool)

    def test_francsco_lindor_corrected(self) -> None:
        info = classify_draft_player_import_name("Francsco Lindor", self.index, all_names=self.pool["fullName"].tolist())
        self.assertEqual(info["status"], "corrected")
        self.assertEqual(info["canonical"], "Francisco Lindor")

    def test_a_judge_corrected(self) -> None:
        info = classify_draft_player_import_name("A Judge", self.index, all_names=self.pool["fullName"].tolist())
        self.assertEqual(info["status"], "corrected")
        self.assertEqual(info["canonical"], "Aaron Judge")

    def test_retired_name_unresolved(self) -> None:
        info = classify_draft_player_import_name("Babe Ruth", self.index, all_names=self.pool["fullName"].tolist())
        self.assertEqual(info["status"], "unresolved")
        self.assertIsNone(info["canonical"])

    def test_validate_import_summary(self) -> None:
        import_df = pd.DataFrame(
            {
                "Round": [1, 1, 1],
                "Pick": [1, 2, 3],
                "Team": ["A", "B", "C"],
                "Player": ["Aaron Judge", "Francsco Lindor", "Babe Ruth"],
            }
        )
        review = validate_imported_draft_df(import_df, self.pool)
        self.assertEqual(review["summary"]["exact"], 1)
        self.assertEqual(review["summary"]["corrected"], 1)
        self.assertEqual(review["summary"]["unresolved"], 1)
        self.assertFalse(import_review_ready(review))

    def test_build_validated_board_only_pool_names(self) -> None:
        import_df = pd.DataFrame(
            {
                "Round": [1, 1],
                "Pick": [1, 2],
                "Team": ["A", "B"],
                "Player": ["Aaron Judge", "Babe Ruth"],
            }
        )
        review = validate_imported_draft_df(import_df, self.pool)
        review["rows"][1]["skip"] = True
        self.assertTrue(import_review_ready(review))
        out = build_validated_import_dataframe(review)
        players = out["Player"].astype(str).str.strip().tolist()
        self.assertEqual(players[0], "Aaron Judge")
        self.assertEqual(players[1], "")


if __name__ == "__main__":
    unittest.main()
