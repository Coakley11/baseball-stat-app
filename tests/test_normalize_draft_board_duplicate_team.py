"""Regression: normalize_draft_board_df must not crash on duplicate Team columns."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_assistant_board import normalize_draft_board_df, validate_canonical_board_schema


class DuplicateTeamColumnRegressionTests(unittest.TestCase):
    def test_live_draft_row_with_mlb_and_fantasy_team_normalizes(self) -> None:
        """Exact failure shape: Team + Fantasy Team both renamed to Team → DataFrame.str crash."""
        raw = pd.DataFrame(
            [
                {
                    "Round": 1,
                    "Pick": 1,
                    "Team": "NYY",  # MLB franchise
                    "Fantasy Team": "Team 1",
                    "fullName": "Aaron Judge",
                    "Primary Position": "OF",
                },
                {
                    "Round": 1,
                    "Pick": 2,
                    "Team": "LAD",
                    "Fantasy Team": "Team 2",
                    "fullName": "Shohei Ohtani",
                    "Primary Position": "DH",
                },
            ]
        )
        # Reproduce pre-fix rename collision without the new mapper.
        collided = raw.rename(
            columns={"fullName": "Player", "Team": "Team", "Fantasy Team": "Team"}
        )
        self.assertIsInstance(collided["Team"], pd.DataFrame)
        with self.assertRaises(AttributeError):
            collided["Team"].astype(str).str.strip()

        normalized, diag = normalize_draft_board_df(raw)
        self.assertFalse(normalized.empty)
        self.assertIsInstance(normalized["Team"], pd.Series)
        self.assertEqual(list(normalized["Team"]), ["Team 1", "Team 2"])
        self.assertIn("MLB Team", normalized.columns)
        self.assertEqual(list(normalized["MLB Team"]), ["NYY", "LAD"])
        self.assertEqual(list(normalized["Player"]), ["Aaron Judge", "Shohei Ohtani"])
        self.assertTrue(diag["schema"]["ok"])
        self.assertTrue(diag["schema"]["team_is_series"])
        self.assertEqual(diag["schema"]["duplicate_columns"], [])

    def test_simulator_board_team_only_stays_team(self) -> None:
        raw = pd.DataFrame(
            {
                "Round": [1, 1],
                "Pick": [1, 2],
                "Team": ["Daniel", "Rivals"],
                "Player": ["Aaron Judge", "Juan Soto"],
            }
        )
        normalized, diag = normalize_draft_board_df(raw)
        self.assertEqual(list(normalized["Team"]), ["Daniel", "Rivals"])
        self.assertTrue(diag["schema"]["ok"])

    def test_validate_schema_flags_duplicate_team(self) -> None:
        bad = pd.DataFrame([["A", "B", "P"]], columns=["Team", "Team", "Player"])
        schema = validate_canonical_board_schema(bad)
        self.assertFalse(schema["ok"])
        self.assertIn("Team", schema["duplicate_columns"])
        self.assertFalse(schema["team_is_series"])


if __name__ == "__main__":
    unittest.main()
