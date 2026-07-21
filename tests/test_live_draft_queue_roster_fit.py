"""Queue Roster Fit must score against the on-clock team (paint), not a stale team."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from draft_ui import format_queue_player_metrics_line, score_queue_player_for_on_clock_team
from live_draft_canonical_snapshot import begin_live_draft_paint, invalidate_live_draft_paint
from live_draft_timer_logic import live_draft_reset_timer


def _pool_row() -> pd.Series:
    return pd.Series(
        {
            "playerID": "p-of",
            "fullName": "Test Outfielder",
            "Primary Position": "OF",
            "Decision Score": 0.88,
            "Draft Fit Score": 7.5,
            "Positional Fit": 0.5,
            "Expected Fantasy Value": 0.75,
        }
    )


def _room(*, pick_index: int) -> dict:
    teams = ["Team A", "Team B"]
    pick_order = [
        {"Pick": 1, "Round": 1, "Team": "Team A"},
        {"Pick": 2, "Round": 1, "Team": "Team B"},
        {"Pick": 3, "Round": 2, "Team": "Team B"},
        {"Pick": 4, "Round": 2, "Team": "Team A"},
    ]
    board: list[dict] = []
    drafted: list[str] = []
    if pick_index >= 1:
        board = [{"Pick": 1, "Round": 1, "Team": "Team A", "playerID": "x1", "fullName": "A Pick"}]
        drafted = ["x1"]
    return {
        "status": "in_progress",
        "current_pick_index": pick_index,
        "config": {
            "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 0, "P": 0, "BN": 0},
            "auto_pick_rule": "balanced recommendation",
        },
        "teams": teams,
        "pick_order": pick_order,
        "draft_board": board,
        "rosters": {
            "Team A": [{"Primary Position": "OF", "fullName": "A1"} for _ in range(3)],
            "Team B": [],
        },
        "drafted_player_ids": drafted,
        "pool": pd.DataFrame([_pool_row().to_dict()]),
    }
    live_draft_reset_timer(room)
    return room


class QueueRosterFitOnClockTests(unittest.TestCase):
    def test_roster_fit_changes_with_on_clock_team(self) -> None:
        session: dict = {}
        row = _pool_row()

        def _score(available, roster_df, rule_key, target_counts, config=None):
            scored = available.copy()
            need_bonus = 0.9 if len(roster_df) == 0 else 0.2
            scored["Positional Fit"] = need_bonus
            scored["Draft Fit Score"] = need_bonus * 10.0
            return scored, []

        with patch("live_draft_pick_scoring.score_available_for_rule", side_effect=_score):
            room_a = _room(pick_index=0)
            session["live_draft_room"] = room_a
            begin_live_draft_paint(session, room_a, state_source="team_a_clock")
            scored_a = score_queue_player_for_on_clock_team(session, row, room=room_a)
            assert scored_a is not None
            self.assertAlmostEqual(float(scored_a.get("Positional Fit") or 0), 0.2, places=2)

            room_b = _room(pick_index=1)
            session["live_draft_room"] = room_b
            invalidate_live_draft_paint(session)
            begin_live_draft_paint(session, room_b, state_source="team_b_clock")
            scored_b = score_queue_player_for_on_clock_team(session, row, room=room_b)
            assert scored_b is not None
            self.assertAlmostEqual(float(scored_b.get("Positional Fit") or 0), 0.9, places=2)

            line = format_queue_player_metrics_line(row, session=session, room=room_b)
            self.assertIn("Roster Fit", line)
            self.assertNotIn("Roster Fit 0.00", line)

    def test_paint_team_is_scoring_target(self) -> None:
        session: dict = {}
        room = _room(pick_index=1)
        session["live_draft_room"] = room
        begin_live_draft_paint(session, room, state_source="paint_team_check")
        paint = session.get("_live_draft_paint_snapshot") or {}
        self.assertEqual(str(paint.get("team_on_clock") or ""), "Team B")

        captured: dict = {}

        def _score(available, roster_df, rule_key, target_counts, config=None):
            captured["roster_len"] = len(roster_df)
            scored = available.copy()
            scored["Positional Fit"] = 0.77
            return scored, []

        with patch("live_draft_pick_scoring.score_available_for_rule", side_effect=_score):
            score_queue_player_for_on_clock_team(session, _pool_row(), room=room)
        self.assertEqual(captured.get("roster_len"), 0)


if __name__ == "__main__":
    unittest.main()
