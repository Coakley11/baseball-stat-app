"""Tests for draft import validation."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_import_validation import (
    build_validated_import_dataframe,
    import_review_ready,
    import_review_ready_for_league,
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

    def test_francsco_lindor_close_match(self) -> None:
        info = classify_draft_player_import_name("Francsco Lindor", self.index, all_names=self.pool["fullName"].tolist())
        self.assertEqual(info["status"], "close")
        self.assertIsNone(info["canonical"])
        self.assertIn("Francisco Lindor", info["candidates"])

    def test_a_judge_close_match(self) -> None:
        info = classify_draft_player_import_name("A Judge", self.index, all_names=self.pool["fullName"].tolist())
        self.assertEqual(info["status"], "close")
        self.assertIn("Aaron Judge", info["candidates"])

    def test_retired_name_invalid(self) -> None:
        info = classify_draft_player_import_name("Mike Piazza", self.index, all_names=self.pool["fullName"].tolist())
        self.assertEqual(info["status"], "invalid")
        self.assertIsNone(info["canonical"])

    def test_exact_match_auto_accept(self) -> None:
        info = classify_draft_player_import_name("Aaron Judge", self.index, all_names=self.pool["fullName"].tolist())
        self.assertEqual(info["status"], "exact")
        self.assertEqual(info["canonical"], "Aaron Judge")

    def test_validate_import_summary(self) -> None:
        import_df = pd.DataFrame(
            {
                "Round": [1, 1, 1],
                "Pick": [1, 2, 3],
                "Team": ["A", "B", "C"],
                "Player": ["Aaron Judge", "Francsco Lindor", "Mike Piazza"],
            }
        )
        review = validate_imported_draft_df(import_df, self.pool)
        self.assertEqual(review["summary"]["exact"], 1)
        self.assertEqual(review["summary"]["close"], 1)
        self.assertEqual(review["summary"]["invalid"], 1)
        self.assertFalse(import_review_ready(review))

    def test_build_validated_board_only_pool_names(self) -> None:
        import_df = pd.DataFrame(
            {
                "Round": [1, 1],
                "Pick": [1, 2],
                "Team": ["A", "B"],
                "Player": ["Aaron Judge", "Mike Piazza"],
            }
        )
        review = validate_imported_draft_df(import_df, self.pool)
        review["rows"][1]["skip"] = True
        self.assertTrue(import_review_ready(review))
        out = build_validated_import_dataframe(review)
        players = out["Player"].astype(str).str.strip().tolist()
        self.assertEqual(players[0], "Aaron Judge")
        self.assertEqual(players[1], "")

    def test_close_match_requires_user_resolution(self) -> None:
        import_df = pd.DataFrame(
            {
                "Round": [1],
                "Pick": [1],
                "Team": ["A"],
                "Player": ["Francsco Lindor"],
            }
        )
        review = validate_imported_draft_df(import_df, self.pool)
        self.assertFalse(import_review_ready(review))
        review["rows"][0]["resolved_canonical"] = "Francisco Lindor"
        self.assertTrue(import_review_ready(review))

    def test_league_ready_requires_all_resolved_no_skip(self) -> None:
        import_df = pd.DataFrame(
            {
                "Round": [1, 1],
                "Pick": [1, 2],
                "Team": ["A", "B"],
                "Player": ["Aaron Judge", "Mike Piazza"],
            }
        )
        review = validate_imported_draft_df(import_df, self.pool)
        self.assertFalse(import_review_ready_for_league(review, self.pool))
        review["rows"][1]["skip"] = True
        self.assertFalse(import_review_ready_for_league(review, self.pool))
        review["rows"][1]["skip"] = False
        review["rows"][1]["resolved_canonical"] = "Juan Soto"
        self.assertTrue(import_review_ready_for_league(review, self.pool))


if __name__ == "__main__":
    unittest.main()
