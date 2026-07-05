"""Tests for Draft Room roster-view team selector."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_room_state import simulator_roster_view_team_options


class DraftRoomRosterTeamOptionsTests(unittest.TestCase):
    def test_includes_all_board_teams_beyond_configured_count(self) -> None:
        session = {
            "room_team_count": 2,
            "room_team_names": "Daniel\nCoakley11",
            "room_rounds": 5,
        }
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "P1"},
                {"Team": "Coakley11", "Player": "P2"},
                {"Team": "Team 3", "Player": "P3"},
                {"Team": "Team 4", "Player": "P4"},
            ]
        )
        opts = simulator_roster_view_team_options(session, board)
        self.assertEqual(opts, ["Daniel", "Coakley11", "Team 3", "Team 4"])


if __name__ == "__main__":
    unittest.main()
