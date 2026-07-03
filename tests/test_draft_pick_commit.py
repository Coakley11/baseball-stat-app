"""Pick commit path — validate before make_pick, fresh revision on save."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from draft_actions import _draft_live
from draft_room_context import commit_shared_room_state, create_and_host_shared_room, join_shared_draft_room
from draft_room_shared_state import LocalFileSharedRoomStore, bump_revision
from live_draft_state import LIVE_DRAFT_ROOM_KEY


def _sample_live_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Jose Ramirez", "Primary Position": "3B"},
        ]
    )
    return {
        "draft_room_id": "MULTI1",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "your_team": "Team 1", "timer_seconds": 60, "allow_free_pool_drafting": True},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team 1"},
            {"Pick": 2, "Round": 1, "Team": "Team 2"},
        ],
        "draft_board": [],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
        "timer_started_at": 1_700_000_000.0,
        "timer_handled_index": -1,
    }


class DraftPickCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host = {"draft_room_participant_id": "host-user", "room_your_team": "Team 1"}
        self.guest = {"draft_room_participant_id": "guest-user", "room_your_team": "Team 2"}
        self._patch = patch("draft_room_shared_state.get_shared_room_store", return_value=self.store)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_manual_pick_commits_with_fresh_revision(self, _auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host, _sample_live_room(), store=self.store)
        ok, msg, _ = join_shared_draft_room(self.guest, code, requested_team="Team 2", store=self.store)
        self.assertTrue(ok, msg)
        room = self.guest[LIVE_DRAFT_ROOM_KEY]
        self.guest["draft_room_participant_team"] = "Team 2"
        self.guest["room_your_team"] = "Team 2"
        before = int(room.get("current_pick_index") or 0)
        result = _draft_live(self.host, "Aaron Judge", source="test")
        self.assertTrue(result.get("ok"), result.get("message"))
        room = self.host[LIVE_DRAFT_ROOM_KEY]
        self.assertEqual(int(room.get("current_pick_index") or 0), before + 1)
        self.assertEqual(len(room.get("draft_board") or []), 1)
        saved = self.store.load(code)
        self.assertIsNotNone(saved)
        self.assertEqual(len((saved.get("room") or {}).get("draft_board") or []), 1)

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_post_pick_validation_not_reapplied(self, _auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host, _sample_live_room(), store=self.store)
        join_shared_draft_room(self.guest, code, requested_team="Team 2", store=self.store)
        room = self.host[LIVE_DRAFT_ROOM_KEY]
        self.host["draft_room_participant_team"] = "Team 1"
        self.host["room_your_team"] = "Team 1"
        ok, msg, saved = commit_shared_room_state(
            self.host,
            room,
            player_name="Aaron Judge",
            pick_already_applied=False,
            store=self.store,
        )
        self.assertTrue(ok, msg)
        self.assertIsNotNone(saved)


if __name__ == "__main__":
    unittest.main()
