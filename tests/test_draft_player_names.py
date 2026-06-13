"""Tests for draft player name resolution."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_player_names import (
    build_draft_player_name_index,
    resolve_draft_player_name,
    search_draft_pool_names,
    validate_draft_player_lines,
)


class TestDraftPlayerNames(unittest.TestCase):
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
        self.names = list(self.index.values())

    def test_search_prefix_fran(self) -> None:
        hits = search_draft_pool_names("FRAN", self.names)
        self.assertIn("Francisco Lindor", hits)
        self.assertIn("Framber Valdez", hits)

    def test_resolve_exact_case_insensitive(self) -> None:
        canonical, suggestions = resolve_draft_player_name("aaron judge", self.index, all_names=self.names)
        self.assertEqual(canonical, "Aaron Judge")
        self.assertEqual(suggestions, [])

    def test_validate_paste_fuzzy_correction(self) -> None:
        report = validate_draft_player_lines(
            ["Júan Sotto", "Aaron Judge"],
            self.index,
            all_names=self.names,
        )
        self.assertEqual(len(report["unmatched"]), 0)
        players = report["canonical_names"]
        self.assertIn("Aaron Judge", players)
        self.assertTrue(any("Juan Soto" == p for p in players))

    def test_validate_board_players(self) -> None:
        from draft_player_names import validate_draft_board_players

        board = pd.DataFrame(
            {
                "Round": [1, 1, 1],
                "Pick": [1, 2, 3],
                "Team": ["A", "B", "C"],
                "Player": ["Aaron Judge", "Fake Guy", ""],
            }
        )
        report = validate_draft_board_players(board, self.index, all_names=self.names)
        self.assertEqual(report["valid_count"], 1)
        self.assertEqual(len(report["invalid"]), 1)
        self.assertEqual(report["invalid"][0]["input"], "Fake Guy")


if __name__ == "__main__":
    unittest.main()
