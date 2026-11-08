"""Queued players are marked as taken only by an ACTIVE draft, and the mark says who took them
(D4J review 2026-11-08: Salvador Perez and Cal Raleigh showed "drafted" from a completed Simulator
board while no draft was in progress)."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

import draft_queue_contract as dqc

QUEUE = ["Cal Raleigh", "Salvador Perez", "Matt Olson", "Aaron Judge"]


def _live(status="in_progress"):
    return {"live_draft_room": {"draft_room_id": "ROOM1", "status": status, "draft_board": [
        {"Pick": 1, "Team": "Team B", "fullName": "Cal Raleigh"},
        {"Pick": 2, "Team": "My Team", "fullName": "Matt Olson"},
    ]}, "draft_queue": list(QUEUE)}


def _sim(rows):
    return {"draft_room_table": pd.DataFrame(rows), "draft_queue": list(QUEUE), "_simulator_board_epoch": 3}


def _patch(source, ctx):
    return (mock.patch("draft_room_state.resolve_active_draft_source", return_value=source),
            mock.patch("draft_actions.draft_action_context", return_value=ctx))


class DraftStatusTests(unittest.TestCase):
    def run_with(self, session, source, ctx):
        p1, p2 = _patch(source, ctx)
        with p1, p2:
            return dqc.queue_draft_status(session), dqc.drafted_in_active_draft(session)

    def test_live_in_progress_marks_who_took_each_player(self) -> None:
        status, names = self.run_with(_live(), "live", {"your_team": "My Team", "draft_complete": False})
        self.assertEqual(set(status), {"cal raleigh", "matt olson"})
        self.assertFalse(status["cal raleigh"]["mine"])
        self.assertTrue(status["matt olson"]["mine"])
        self.assertEqual(dqc.draft_status_label(status["matt olson"]), "you drafted in this Live Draft (pick 2)")
        self.assertEqual(dqc.draft_status_label(status["cal raleigh"]), "taken by Team B in this Live Draft (pick 1)")
        self.assertEqual(names, {"cal raleigh", "matt olson"})

    def test_finished_live_draft_marks_nothing(self) -> None:
        for st_ in ("complete", "deleted"):
            status, names = self.run_with(_live(st_), "live", {"your_team": "My Team", "draft_complete": False})
            self.assertEqual((status, names), ({}, set()), st_)
        status, names = self.run_with(_live(), "live", {"your_team": "My Team", "draft_complete": True})
        self.assertEqual((status, names), ({}, set()))

    def test_completed_simulator_board_marks_nothing(self) -> None:
        rows = [{"Pick": 1, "Team": "Sim A", "Player": "Salvador Perez"}, {"Pick": 2, "Team": "Sim B", "Player": "Cal Raleigh"}]
        status, names = self.run_with(_sim(rows), "simulator", {"your_team": "Sim A", "draft_complete": True, "board_full": True})
        self.assertEqual((status, names), ({}, set()))

    def test_simulator_in_progress_says_it_is_the_simulator(self) -> None:
        rows = [{"Pick": 1, "Team": "Sim A", "Player": "Salvador Perez"}, {"Pick": 2, "Team": "Sim B", "Player": None}]
        status, _names = self.run_with(_sim(rows), "simulator", {"your_team": "Sim A", "draft_complete": False})
        self.assertEqual(set(status), {"salvador perez"})
        self.assertEqual(dqc.draft_status_label(status["salvador perez"]), "you drafted in your Simulator draft (pick 1)")

    def test_empty_simulator_board_is_no_draft(self) -> None:
        status, names = self.run_with(_sim([{"Pick": 1, "Team": "Sim A", "Player": None}]), "simulator",
                                      {"your_team": "Sim A", "draft_complete": False})
        self.assertEqual((status, names), ({}, set()))

    def test_queue_itself_never_changes(self) -> None:
        s = _live()
        self.run_with(s, "live", {"your_team": "My Team", "draft_complete": False})
        self.assertEqual(s["draft_queue"], QUEUE)


if __name__ == "__main__":
    unittest.main()
