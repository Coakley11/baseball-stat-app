"""Tests for saved draft team archive."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_archive_state import (
    DRAFT_ARCHIVE_KEY,
    DRAFT_TYPE_LIVE,
    archive_roster_dataframe,
    get_active_draft_archive,
    list_draft_archives,
    save_live_draft_team_archive,
    save_simulator_team_archive,
    set_active_draft_archive,
)


class DraftArchiveTests(unittest.TestCase):
    def test_save_live_draft_team_persists_in_session(self) -> None:
        session: dict = {}
        room = {
            "config": {
                "league_name": "Test League",
                "slots": {"C": 1, "SS": 1, "OF": 1, "1B": 0, "2B": 0, "3B": 0, "DH": 0, "P": 0, "BN": 0},
                "fantasy_format": "5x5 Roto",
            },
            "rosters": {
                "Team A": [{"fullName": "Player One", "Primary Position": "SS", "Expected Fantasy Value": 0.8}],
            },
            "draft_board": [
                {"Fantasy Team": "Team A", "fullName": "Player One", "Pick": 1, "Round": 1},
            ],
        }
        entry = save_live_draft_team_archive(session, room, team_name="Team A", draft_name="My Live Draft")
        self.assertEqual(entry["draft_type"], DRAFT_TYPE_LIVE)
        self.assertEqual(len(session[DRAFT_ARCHIVE_KEY]), 1)
        self.assertEqual(list_draft_archives(session)[0]["draft_name"], "My Live Draft")

    def test_simulator_save_and_active_selection(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Team A", "Player": "Player X", "Pick": 1, "Round": 1, "Primary Position": "OF"},
            ]
        )
        entry = save_simulator_team_archive(session, board, team_name="Team A", draft_name="Mock 2026")
        set_active_draft_archive(session, entry["draft_id"])
        active = get_active_draft_archive(session)
        assert active is not None
        self.assertEqual(active["draft_id"], entry["draft_id"])
        df = archive_roster_dataframe(active)
        self.assertFalse(df.empty)
        self.assertIn("Player", df.columns)


if __name__ == "__main__":
    unittest.main()
