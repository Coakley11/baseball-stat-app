"""Live Draft Room team rosters panel (2026-11-06): every team's picks, the viewer's team first."""

from __future__ import annotations

import copy
import unittest

from streamlit.testing.v1 import AppTest

from live_draft_team_rosters import team_rosters

TEAMS = ["Danny", "Barry", "Cara"]


def room() -> dict:
    board = [
        {"Pick": 1, "Round": 1, "Team": "Danny", "fullName": "Player 1", "Primary Position": "SS"},
        {"Pick": 2, "Round": 1, "Team": "Barry", "fullName": "Player 2", "Primary Position": "C"},
        {"Pick": 4, "Round": 2, "Team": "Barry", "fullName": "Player 4", "Primary Position": "OF"},
        {"Pick": 3, "Round": 1, "Team": "Cara", "fullName": "Player 3", "Primary Position": "1B"},
    ]
    return {"teams": list(TEAMS), "draft_board": board}


def _script() -> None:
    import streamlit as st

    from live_draft_team_rosters import render_team_rosters
    from tests.test_live_draft_team_rosters import room

    render_team_rosters(st, room(), viewer_team="Barry")


class TeamRostersTests(unittest.TestCase):
    def test_every_team_in_pick_order_and_the_room_is_never_changed(self) -> None:
        r = room()
        before = copy.deepcopy(r)
        rosters = team_rosters(r)
        self.assertEqual(list(rosters), TEAMS)
        self.assertEqual([p["Pick"] for p in rosters["Barry"]], [2, 4])
        self.assertEqual(rosters["Cara"][0]["Pos"], "1B")
        self.assertEqual(r, before)

    def test_a_team_without_picks_is_listed(self) -> None:
        r = room()
        r["teams"].append("Dora")
        self.assertEqual(team_rosters(r)["Dora"], [])

    def test_the_viewer_team_comes_first_and_is_marked(self) -> None:
        at = AppTest.from_function(_script, default_timeout=30)
        at.run()
        self.assertFalse(at.exception)
        box = at.selectbox[0]
        self.assertEqual(box.options[0], "Barry (you)")
        self.assertEqual(box.value, "Barry")
        self.assertEqual(len(at.dataframe[0].value), 2)


if __name__ == "__main__":
    unittest.main()
