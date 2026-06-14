"""Tests for unified draft_player action (Phase 1)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_actions import can_draft_player, draft_action_context, draft_player
from draft_room_state import build_snake_board
from draft_state import DRAFT_QUEUE_KEY, add_player_to_draft_queue


def _four_team_board(*, filled_through_pick: int = 0) -> pd.DataFrame:
    teams = ["Team A", "Team B", "Team C", "Team D"]
    board = build_snake_board(teams, rounds=2)
    if filled_through_pick > 0:
        board = board.sort_values("Pick", kind="stable").reset_index(drop=True)
        for idx, row in board.iterrows():
            if int(row["Pick"]) <= filled_through_pick:
                board.at[idx, "Player"] = f"Player {row['Pick']}"
    return board


class TestDraftActionContext(unittest.TestCase):
    def test_simulator_user_on_clock(self) -> None:
        board = _four_team_board(filled_through_pick=4)
        session = {
            "room_your_team": "Team D",
            "draft_room_table": board.copy(),
            "draft_room_board_editor_cache": board.copy(),
        }
        ctx = draft_action_context(session)
        self.assertEqual(ctx["on_clock_team"], "Team D")
        self.assertEqual(ctx["current_pick"], 5)
        self.assertTrue(ctx["is_your_pick"])

    def test_simulator_user_not_on_clock(self) -> None:
        board = _four_team_board(filled_through_pick=4)
        session = {
            "room_your_team": "Team A",
            "draft_room_table": board.copy(),
            "draft_room_board_editor_cache": board.copy(),
        }
        ctx = draft_action_context(session)
        self.assertEqual(ctx["on_clock_team"], "Team D")
        self.assertFalse(ctx["is_your_pick"])


class TestCanDraftPlayer(unittest.TestCase):
    def test_allows_when_on_clock(self) -> None:
        board = _four_team_board(filled_through_pick=4)
        session = {
            "room_your_team": "Team D",
            "draft_room_table": board.copy(),
        }
        ok, reason = can_draft_player(session, "Kyle Tucker")
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_blocks_when_not_on_clock(self) -> None:
        board = _four_team_board(filled_through_pick=4)
        session = {
            "room_your_team": "Team A",
            "draft_room_table": board.copy(),
        }
        ok, reason = can_draft_player(session, "Kyle Tucker")
        self.assertFalse(ok)
        self.assertIn("Not your pick", reason)

    def test_blocks_already_drafted(self) -> None:
        board = _four_team_board(filled_through_pick=1)
        session = {
            "room_your_team": "Team B",
            "draft_room_table": board.copy(),
        }
        ok, reason = can_draft_player(session, "Player 1")
        self.assertFalse(ok)
        self.assertIn("already drafted", reason.lower())


class TestDraftPlayerSimulator(unittest.TestCase):
    def test_drafts_to_on_clock_pick_not_blind_next_open(self) -> None:
        """After round 1, pick 5 belongs to Team D — Team A must not draft."""
        board = _four_team_board(filled_through_pick=4)
        session: dict = {
            "room_your_team": "Team A",
            "draft_room_table": board.copy(),
            "draft_room_board_editor_cache": board.copy(),
        }
        result = draft_player(session, "Kyle Tucker", source="queue")
        self.assertFalse(result["ok"])
        self.assertIn("Not your pick", result["message"])

    def test_user_on_clock_writes_correct_pick_row(self) -> None:
        board = _four_team_board(filled_through_pick=4)
        session: dict = {
            "room_your_team": "Team D",
            "draft_room_table": board.copy(),
            "draft_room_board_editor_cache": board.copy(),
        }
        result = draft_player(session, "Kyle Tucker", source="queue")
        self.assertTrue(result["ok"], result.get("message"))
        self.assertEqual(result["target_pick"], 5)
        self.assertEqual(result["on_clock_team"], "Team D")

        from draft_room_state import get_canonical_draft_board

        updated = get_canonical_draft_board(session)
        row = updated[updated["Pick"] == 5].iloc[0]
        self.assertEqual(str(row["Team"]), "Team D")
        self.assertEqual(str(row["Player"]), "Kyle Tucker")

    def test_removes_player_from_queue_after_success(self) -> None:
        board = _four_team_board(filled_through_pick=0)
        session: dict = {
            "room_your_team": "Team A",
            "draft_room_table": board.copy(),
            "draft_room_board_editor_cache": board.copy(),
        }
        add_player_to_draft_queue(session, "Kyle Tucker")
        self.assertIn("Kyle Tucker", session[DRAFT_QUEUE_KEY])

        result = draft_player(session, "Kyle Tucker", source="queue")
        self.assertTrue(result["ok"], result.get("message"))
        self.assertNotIn("Kyle Tucker", session.get(DRAFT_QUEUE_KEY) or [])
        self.assertNotIn("Kyle Tucker", result.get("queue_after") or [])

    def test_clears_ami_cache_after_success(self) -> None:
        board = _four_team_board(filled_through_pick=0)
        session: dict = {
            "room_your_team": "Team A",
            "draft_room_table": board.copy(),
            "_ami_draft_projection": {"available_players": [{"player": "X"}]},
            "_ami_draft_snapshot": {"current_pick": 1},
        }
        draft_player(session, "Kyle Tucker", source="draft_room")
        self.assertNotIn("_ami_draft_projection", session)
        self.assertNotIn("_ami_draft_snapshot", session)


class TestDraftPlayerLive(unittest.TestCase):
    def _live_session(self, *, your_team: str, pick_index: int) -> dict:
        pool = pd.DataFrame(
            [
                {"playerID": "1", "fullName": "Kyle Tucker", "Primary Position": "OF"},
                {"playerID": "2", "fullName": "Mike Trout", "Primary Position": "OF"},
            ]
        )
        room = {
            "status": "in_progress",
            "current_pick_index": pick_index,
            "pick_order": [
                {"Round": 1, "Pick": 1, "Team": "Team A"},
                {"Round": 1, "Pick": 2, "Team": "Team B"},
            ],
            "config": {"your_team": your_team, "num_teams": 2},
            "draft_board": [],
            "drafted_player_ids": [],
            "rosters": {"Team A": [], "Team B": []},
            "pool": pool,
        }
        return {
            "room_your_team": your_team,
            "live_draft_room": room,
            "canonical_draft_meta": {"active_mode": "live_draft_room"},
        }

    def test_live_blocks_when_not_on_clock(self) -> None:
        session = self._live_session(your_team="Team B", pick_index=0)
        ok, reason = can_draft_player(session, "Kyle Tucker")
        self.assertFalse(ok)
        self.assertIn("Not your pick", reason)

    @patch("draft_actions._import_baseball_app")
    def test_live_drafts_when_on_clock(self, mock_import: MagicMock) -> None:
        session = self._live_session(your_team="Team B", pick_index=1)
        app = MagicMock()

        def _slot(room):
            idx = int(room.get("current_pick_index", 0))
            return room["pick_order"][idx]

        def _make_pick(room, player_row, verdict="Manual pick"):
            room["draft_board"].append(player_row)
            room["drafted_player_ids"].append(str(player_row.get("playerID")))
            room["current_pick_index"] = int(room.get("current_pick_index", 0)) + 1
            return True, f"Drafted {player_row.get('fullName')}."

        app.live_draft_current_slot.side_effect = _slot
        app.live_draft_make_pick.side_effect = _make_pick
        app.live_draft_get_available.side_effect = lambda room: room["pool"].copy()
        mock_import.return_value = app

        result = draft_player(session, "Kyle Tucker", source="live_queue")
        self.assertTrue(result["ok"], result.get("message"))
        self.assertEqual(result["on_clock_team"], "Team B")
        self.assertEqual(result["target_pick"], 2)
        app.live_draft_make_pick.assert_called_once()

    @patch("draft_actions._import_baseball_app")
    def test_live_validates_on_clock_before_make_pick(self, mock_import: MagicMock) -> None:
        session = self._live_session(your_team="Team B", pick_index=0)
        app = MagicMock()
        app.live_draft_current_slot.return_value = session["live_draft_room"]["pick_order"][0]
        app.live_draft_get_available.return_value = session["live_draft_room"]["pool"].copy()
        mock_import.return_value = app

        result = draft_player(session, "Kyle Tucker", source="live_queue")
        self.assertFalse(result["ok"])
        self.assertIn("Not your pick", result["message"])
        app.live_draft_make_pick.assert_not_called()


class TestImportFallback(unittest.TestCase):
    @patch("importlib.import_module")
    def test_import_baseball_app_tries_both_casings(self, mock_import: MagicMock) -> None:
        from draft_actions import _import_baseball_app

        sentinel = object()
        mock_import.side_effect = [ImportError("no lower"), sentinel]
        self.assertIs(_import_baseball_app(), sentinel)
        self.assertEqual(mock_import.call_args_list[0].args[0], "streamlit_app")
        self.assertEqual(mock_import.call_args_list[1].args[0], "Streamlit_app")


if __name__ == "__main__":
    unittest.main()
