"""Tests for shared room create verification."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from draft_room_context import abort_shared_room_create, create_and_host_shared_room, join_shared_draft_room
from draft_room_create_verify import validate_shared_room_document, verify_shared_room_persisted
from draft_room_participant_state import ACTIVE_PARTICIPANT_ID_KEY
from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, LocalFileSharedRoomStore, shared_room_document
from live_draft_state import LIVE_DRAFT_ROOM_KEY


def _sample_live_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF", "Expected Fantasy Value": 95.0},
        ]
    )
    return {
        "draft_room_id": "MULTI1",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "picks_per_team": 1, "your_team": "Team 1"},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team 1"}],
        "draft_board": [{"Pick": 1, "Round": 1, "Team": "Team 1", "Player": ""}],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


class DraftRoomCreateVerifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_validate_rejects_empty_room_blob(self) -> None:
        ok, msg = validate_shared_room_document({"room_code": "ABC123", "room": {}})
        self.assertFalse(ok)
        self.assertIn("empty", msg.lower())

    def test_verify_shared_room_persisted_after_save(self) -> None:
        session: dict = {ACTIVE_PARTICIPANT_ID_KEY: "host-user"}
        code, _ = create_and_host_shared_room(session, _sample_live_room(), store=self.store)
        self.assertTrue(code)
        ok, msg, diag = verify_shared_room_persisted(self.store, code)
        self.assertTrue(ok, msg)
        self.assertTrue(diag["immediate_load"]["valid_runtime"])

    def test_abort_shared_room_create_restores_local_room(self) -> None:
        room = _sample_live_room()
        session = {
            ACTIVE_PARTICIPANT_ID_KEY: "host-user",
            ACTIVE_SHARED_ROOM_CODE_KEY: "GHOST1",
            LIVE_DRAFT_ROOM_KEY: {"status": "broken"},
        }
        abort_shared_room_create(session, backup_room=room)
        self.assertNotIn(ACTIVE_SHARED_ROOM_CODE_KEY, session)
        self.assertEqual(session[LIVE_DRAFT_ROOM_KEY]["draft_room_id"], "MULTI1")

    def test_join_reports_not_found_with_backend(self) -> None:
        guest: dict = {ACTIVE_PARTICIPANT_ID_KEY: "guest-user"}
        ok, msg, _ = join_shared_draft_room(guest, "ZZZZZZ", store=self.store)
        self.assertFalse(ok)
        self.assertIn("no active shared draft room was found", msg.lower())
        self.assertEqual(guest["_draft_room_join_load_diag"]["reason"], "not_found")


if __name__ == "__main__":
    unittest.main()
