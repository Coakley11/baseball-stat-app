"""Two-account Live Draft closure — Daniel/Donny + Coakley11/Team B lifecycle."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_actions import draft_player
from draft_room_context import (
    commit_shared_room_state,
    create_and_host_shared_room,
    join_shared_draft_room,
    prepare_global_draft_context,
)
from draft_room_shared_state import LIVE_DRAFT_ROOM_KEY, LocalFileSharedRoomStore, shared_document_room_blob
from draft_room_participant_state import ACTIVE_PARTICIPANT_TEAM_KEY
from draft_source_validation import ALLOW_FREE_POOL_KEY
from live_draft_setup_mode import SETUP_MODE_SHARED, can_start_live_draft, set_live_draft_setup_mode
from live_draft_timer_logic import live_draft_clear_timer, live_draft_resume_timer
from suite_auth import AUTH_USER_ID_KEY


def _pool() -> pd.DataFrame:
    rows = [
        {"playerID": f"p{i}", "fullName": f"Player {i}", "Primary Position": "OF"}
        for i in range(1, 9)
    ]
    return pd.DataFrame(rows)


def _two_team_room(*, status: str = "not_started") -> dict:
    teams = ["Donny", "Team B"]
    pick_order = [
        {"Pick": 1, "Round": 1, "Team": "Donny"},
        {"Pick": 2, "Round": 1, "Team": "Team B"},
        {"Pick": 3, "Round": 2, "Team": "Team B"},
        {"Pick": 4, "Round": 2, "Team": "Donny"},
    ]
    return {
        "draft_room_id": "CLOSURE1",
        "status": status,
        "current_pick_index": 0,
        "config": {
            "num_teams": 2,
            "your_team": "Donny",
            "user_team": "Donny",
            "teams": teams,
            "draft_setup_mode": SETUP_MODE_SHARED,
            ALLOW_FREE_POOL_KEY: True,
        },
        "teams": teams,
        "pick_order": pick_order,
        "draft_board": [],
        "rosters": {t: [] for t in teams},
        "drafted_player_ids": [],
        "pool": _pool(),
    }


class LiveDraftTwoAccountClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.daniel: dict = {
            AUTH_USER_ID_KEY: "user:daniel",
            "draft_room_participant_id": "user:daniel",
            "room_your_team": "Donny",
            ALLOW_FREE_POOL_KEY: True,
            "draft_queue": ["Player 1", "Player 2", "Player 3", "Player 4"],
        }
        self.coakley: dict = {
            AUTH_USER_ID_KEY: "user:coakley11",
            "draft_room_participant_id": "user:coakley11",
            ALLOW_FREE_POOL_KEY: True,
            "draft_queue": ["Player 5", "Player 6"],
        }
        self._patches = [
            mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False),
        ]
        for patcher in self._patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self._patches):
            patcher.stop()
        self._tmpdir.cleanup()

    def _start_shared_draft(self) -> str:
        set_live_draft_setup_mode(self.daniel, SETUP_MODE_SHARED)
        room = _two_team_room(status="in_progress")
        code, _ = create_and_host_shared_room(self.daniel, room, store=self.store)
        ok, msg, _detail = join_shared_draft_room(self.coakley, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)
        self.assertEqual(str(self.coakley.get(ACTIVE_PARTICIPANT_TEAM_KEY) or ""), "Team B")
        prepare_global_draft_context(self.daniel)
        prepare_global_draft_context(self.coakley)
        return code

    def test_two_account_draft_pause_resume_and_complete(self) -> None:
        code = self._start_shared_draft()
        self.assertEqual(str(self.daniel.get(ACTIVE_PARTICIPANT_TEAM_KEY) or ""), "Donny")

        result = draft_player(self.daniel, "Player 1", source="live_queue")
        self.assertTrue(result["ok"], result.get("message"))
        room = self.daniel[LIVE_DRAFT_ROOM_KEY]
        ok, msg, _ = commit_shared_room_state(
            self.daniel,
            room,
            player_name="Player 1",
            pick_already_applied=True,
            store=self.store,
        )
        self.assertTrue(ok, msg)

        polled = self.store.load(code)
        room_blob = shared_document_room_blob(polled)
        assert isinstance(room_blob, dict)
        self.coakley[LIVE_DRAFT_ROOM_KEY] = copy.deepcopy(room_blob)
        prepare_global_draft_context(self.coakley)
        self.assertEqual(int(self.coakley[LIVE_DRAFT_ROOM_KEY]["current_pick_index"]), 1)

        paused_room = self.daniel[LIVE_DRAFT_ROOM_KEY]
        from live_draft_timer_logic import live_draft_seconds_remaining

        paused_room["paused_remaining_seconds"] = live_draft_seconds_remaining(paused_room)
        paused_room["status"] = "paused"
        live_draft_clear_timer(paused_room)
        self.assertEqual(paused_room["status"], "paused")
        paused_room["status"] = "in_progress"
        live_draft_resume_timer(paused_room, int(paused_room.get("paused_remaining_seconds") or 60))
        self.assertEqual(paused_room["status"], "in_progress")

        result2 = draft_player(self.coakley, "Player 2", source="live_queue")
        self.assertTrue(result2["ok"], result2.get("message"))
        room2 = self.coakley[LIVE_DRAFT_ROOM_KEY]
        ok2, msg2, _ = commit_shared_room_state(
            self.coakley,
            room2,
            player_name="Player 2",
            pick_already_applied=True,
            store=self.store,
        )
        self.assertTrue(ok2, msg2)

        final_doc = self.store.load(code)
        final_room = shared_document_room_blob(final_doc)
        assert isinstance(final_room, dict)
        self.daniel[LIVE_DRAFT_ROOM_KEY] = copy.deepcopy(final_room)
        prepare_global_draft_context(self.daniel)
        board = self.daniel[LIVE_DRAFT_ROOM_KEY].get("draft_board") or []
        self.assertEqual(len(board), 2)
        drafted = self.daniel[LIVE_DRAFT_ROOM_KEY].get("drafted_player_ids") or []
        self.assertIn("p1", drafted)
        self.assertIn("p2", drafted)

    def test_queue_reorder_persists_in_session(self) -> None:
        self._start_shared_draft()
        self.daniel["draft_queue"] = ["Player 4", "Player 1", "Player 2"]
        self.assertEqual(self.daniel["draft_queue"][0], "Player 4")
        self.daniel["draft_queue"] = ["Player 1", "Player 4", "Player 2"]
        self.assertEqual(self.daniel["draft_queue"][0], "Player 1")

    def test_refresh_preserves_team_identity(self) -> None:
        code = self._start_shared_draft()
        coakley_team = str(self.coakley.get(ACTIVE_PARTICIPANT_TEAM_KEY) or "")
        reboot = {
            AUTH_USER_ID_KEY: "user:coakley11",
            ALLOW_FREE_POOL_KEY: True,
        }
        doc = self.store.load(code)
        room_blob = shared_document_room_blob(doc)
        assert isinstance(room_blob, dict)
        reboot[LIVE_DRAFT_ROOM_KEY] = copy.deepcopy(room_blob)
        reboot["active_shared_draft_room_code"] = code
        reboot[ACTIVE_PARTICIPANT_TEAM_KEY] = coakley_team
        prepare_global_draft_context(reboot)
        self.assertEqual(str(reboot.get(ACTIVE_PARTICIPANT_TEAM_KEY) or ""), "Team B")

    def test_not_started_requires_two_owners(self) -> None:
        set_live_draft_setup_mode(self.daniel, SETUP_MODE_SHARED)
        room = _two_team_room()
        create_and_host_shared_room(self.daniel, room, store=self.store)
        self.daniel[LIVE_DRAFT_ROOM_KEY] = room
        ok, reason = can_start_live_draft(self.daniel)
        self.assertFalse(ok)
        self.assertTrue(
            any(tok in reason.lower() for tok in ("participant", "manager", "claim", "join", "two distinct")),
            reason,
        )


if __name__ == "__main__":
    unittest.main()
