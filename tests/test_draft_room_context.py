"""Tests for multi-user draft room context (Phase 1 foundation)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from draft_room_context import (
    create_and_host_shared_room,
    get_global_draft_context,
    join_shared_draft_room,
    prepare_global_draft_context,
    recommendation_team,
    sync_shared_draft_room,
)
from draft_room_participant_state import (
    ACTIVE_PARTICIPANT_ID_KEY,
    participant_state_for_room,
    save_participant_workflow_from_session,
    set_active_participant,
)
from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    LocalFileSharedRoomStore,
    bump_revision,
)
from live_draft_state import LIVE_DRAFT_ROOM_KEY


def _sample_live_room(*, team_a_roster: list | None = None) -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF", "Expected Fantasy Value": 95.0},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF", "Expected Fantasy Value": 92.0},
        ]
    )
    return {
        "draft_room_id": "MULTI1",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {
            "num_teams": 3,
            "picks_per_team": 2,
            "your_team": "Team 1",
            "scoring_type": "Roto (5x5)",
        },
        "teams": ["Team 1", "Team 2", "Team 3"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team 1"},
            {"Pick": 2, "Round": 1, "Team": "Team 2"},
            {"Pick": 3, "Round": 1, "Team": "Team 3"},
        ],
        "draft_board": [
            {"Pick": 1, "Round": 1, "Team": "Team 1", "Player": ""},
            {"Pick": 2, "Round": 1, "Team": "Team 2", "Player": ""},
            {"Pick": 3, "Round": 1, "Team": "Team 3", "Player": ""},
        ],
        "rosters": {
            "Team 1": team_a_roster or [],
            "Team 2": [],
            "Team 3": [],
        },
        "drafted_player_ids": [],
        "pool": pool,
    }


class DraftRoomContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_create_and_join_assigns_distinct_teams(self) -> None:
        host_session: dict = {ACTIVE_PARTICIPANT_ID_KEY: "host-user"}
        guest_session: dict = {ACTIVE_PARTICIPANT_ID_KEY: "guest-user"}

        room_code, _document = create_and_host_shared_room(
            host_session,
            _sample_live_room(),
            host_team="Team 1",
            store=self.store,
        )

        ok, msg, joined = join_shared_draft_room(guest_session, room_code, store=self.store)
        self.assertTrue(ok, msg)
        self.assertIsNotNone(joined)
        self.assertEqual(guest_session.get("draft_room_participant_team"), "Team 2")

        ctx_host = get_global_draft_context(host_session)
        ctx_guest = get_global_draft_context(guest_session)
        self.assertEqual(ctx_host["room_code"], ctx_guest["room_code"])
        self.assertNotEqual(ctx_host["participant_team"], ctx_guest["participant_team"])
        self.assertEqual(recommendation_team(host_session, on_clock_team="Team 1"), "Team 1")
        self.assertEqual(recommendation_team(guest_session, on_clock_team="Team 1"), "Team 2")

    def test_private_queue_isolated_per_participant(self) -> None:
        host: dict = {ACTIVE_PARTICIPANT_ID_KEY: "host-user"}
        guest: dict = {ACTIVE_PARTICIPANT_ID_KEY: "guest-user"}

        room_code, _ = create_and_host_shared_room(
            host,
            _sample_live_room(),
            host_team="Team 1",
            store=self.store,
        )
        host["draft_queue"] = ["Aaron Judge"]
        save_participant_workflow_from_session(host, room_code)

        join_shared_draft_room(guest, room_code, store=self.store)
        guest["draft_queue"] = ["Juan Soto"]
        save_participant_workflow_from_session(guest, room_code)

        prepare_global_draft_context(host)
        prepare_global_draft_context(guest)
        self.assertEqual(host.get("draft_queue"), ["Aaron Judge"])
        self.assertEqual(guest.get("draft_queue"), ["Juan Soto"])

        host_state = participant_state_for_room(host, room_code)
        guest_state = participant_state_for_room(guest, room_code)
        self.assertEqual(host_state["workflow"]["queue"], ["Aaron Judge"])
        self.assertEqual(guest_state["workflow"]["queue"], ["Juan Soto"])

    def test_sync_shared_room_refreshes_runtime(self) -> None:
        session: dict = {ACTIVE_PARTICIPANT_ID_KEY: "host-user"}
        room_code, document = create_and_host_shared_room(
            session,
            _sample_live_room(),
            host_team="Team 1",
            store=self.store,
        )

        room = session[LIVE_DRAFT_ROOM_KEY]
        self.assertIsInstance(room, dict)
        room["current_pick_index"] = 1
        board = list(room.get("draft_board") or [])
        if board:
            board[0] = {**board[0], "Player": "Aaron Judge", "fullName": "Aaron Judge"}
        room["draft_board"] = board

        from draft_room_shared_state import bump_revision

        updated = bump_revision(document, live_room=room)
        self.store.save(updated)

        self.assertTrue(sync_shared_draft_room(session, store=self.store))
        refreshed = session[LIVE_DRAFT_ROOM_KEY]
        self.assertEqual(int(refreshed.get("current_pick_index") or 0), 1)

    def test_sync_skips_full_load_when_revision_unchanged(self) -> None:
        session: dict = {ACTIVE_PARTICIPANT_ID_KEY: "host-user"}
        room_code, _document = create_and_host_shared_room(
            session,
            _sample_live_room(),
            host_team="Team 1",
            store=self.store,
        )
        loads: list[str] = []
        original_load = self.store.load
        original_head = self.store.load_head

        def _tracked_load(code: str):
            loads.append("load")
            return original_load(code)

        def _tracked_head(code: str):
            loads.append("head")
            return original_head(code)

        self.store.load = _tracked_load  # type: ignore[method-assign]
        self.store.load_head = _tracked_head  # type: ignore[method-assign]

        self.assertFalse(sync_shared_draft_room(session, store=self.store))
        self.assertIn("head", loads)
        self.assertNotIn("load", loads)

        session.pop("_shared_draft_sync_run", None)
        loads.clear()
        self.assertFalse(sync_shared_draft_room(session, store=self.store))
        self.assertEqual(loads, ["head"])


if __name__ == "__main__":
    unittest.main()
