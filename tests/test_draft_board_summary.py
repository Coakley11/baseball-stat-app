"""Tests for plain-language draft board summary helpers."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_room_state import draft_board_summary_for_team, next_board_pick_for_team, round_one_draft_slot


class TestDraftBoardSummary(unittest.TestCase):
    def test_summary_counts_and_pick(self) -> None:
        table = pd.DataFrame(
            [
                {"Round": 1, "Pick": 1, "Team": "Daniel", "Player": "A"},
                {"Round": 1, "Pick": 2, "Team": "Team 2", "Player": "B"},
                {"Round": 1, "Pick": 3, "Team": "Daniel", "Player": "C"},
                {"Round": 1, "Pick": 4, "Team": "Team 2", "Player": "D"},
                {"Round": 1, "Pick": 5, "Team": "Daniel", "Player": "E"},
                {"Round": 1, "Pick": 6, "Team": "Team 2", "Player": "F"},
                {"Round": 1, "Pick": 7, "Team": "Daniel", "Player": ""},
                {"Round": 1, "Pick": 8, "Team": "Team 2", "Player": ""},
            ]
        )
        teams = ["Daniel", "Team 2"]
        summary = draft_board_summary_for_team(
            table,
            your_team="Daniel",
            team_names=teams,
            num_teams=2,
        )
        self.assertEqual(summary["players_you_drafted"], 3)
        self.assertEqual(summary["players_league_drafted"], 3)
        self.assertEqual(summary["current_pick"], 7)
        self.assertEqual(summary["current_round"], 4)
        self.assertEqual(summary["draft_slot"], 1)
        self.assertEqual(next_board_pick_for_team(table, "Daniel", min_pick=7), 7)

    def test_round_one_slot_missing_team(self) -> None:
        self.assertIsNone(round_one_draft_slot(["A", "B"], "C"))


if __name__ == "__main__":
    unittest.main()
