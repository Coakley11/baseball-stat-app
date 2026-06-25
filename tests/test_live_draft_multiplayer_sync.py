"""Tests for canonical timer_deadline sync and pick notice deduplication."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_commit_diagnostics import (
    render_live_draft_pick_notice,
    set_live_draft_pick_notice,
)
from draft_room_context import create_and_host_shared_room, join_shared_draft_room
from draft_room_shared_state import LocalFileSharedRoomStore, SHARED_ROOM_META_KEY, bump_revision
from live_draft_expired_pick import _multiplayer_autopick_allowed, should_fragment_trigger_full_rerun
from live_draft_pick_commit import sync_expected_revision
from live_draft_state import LIVE_DRAFT_ROOM_KEY, room_from_persist_dict, room_to_persist_dict
from live_draft_timer_logic import live_draft_reset_timer, live_draft_seconds_remaining


def _sample_live_room(**overrides: object) -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Jose Ramirez", "Primary Position": "3B"},
        ]
    )
    base = {
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
    base.update(overrides)
    return base


class TimerDeadlineSyncTests(unittest.TestCase):
    def test_reset_timer_sets_shared_deadline(self) -> None:
        room = {"status": "in_progress", "config": {"timer_seconds": 90}, "timer_handled_index": -1}
        before = time.time()
        live_draft_reset_timer(room)
        self.assertIsNotNone(room.get("timer_deadline"))
        self.assertGreaterEqual(float(room["timer_deadline"]), before + 89)
        self.assertLessEqual(float(room["timer_deadline"]), before + 91)

    def test_seconds_remaining_uses_deadline_not_local_start(self) -> None:
        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 60},
            "timer_deadline": time.time() + 42,
            "timer_started_at": time.time() - 999,
        }
        remaining = live_draft_seconds_remaining(room)
        self.assertGreaterEqual(remaining, 40)
        self.assertLessEqual(remaining, 43)

    def test_deadline_roundtrips_through_persist(self) -> None:
        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 60},
            "current_pick_index": 1,
            "timer_handled_index": -1,
        }
        live_draft_reset_timer(room)
        blob = room_to_persist_dict(room)
        self.assertIn("timer_deadline", blob)
        self.assertIsNone(blob.get("timer_started_at"))
        restored = room_from_persist_dict(blob)
        assert restored is not None
        self.assertIsNotNone(restored.get("timer_deadline"))
        self.assertGreater(live_draft_seconds_remaining(restored), 0)


class PickNoticeDedupTests(unittest.TestCase):
    def test_success_notice_renders_once(self) -> None:
        session: dict = {}
        set_live_draft_pick_notice(session, "success", "Drafted Julio Rodriguez.", pick_key="2:julior01")
        st = mock.MagicMock()
        render_live_draft_pick_notice(st, session)
        st.success.assert_called_once_with("Drafted Julio Rodriguez.")
        set_live_draft_pick_notice(session, "success", "Drafted Julio Rodriguez.", pick_key="2:julior01")
        render_live_draft_pick_notice(st, session)
        st.success.assert_called_once()


class SyncExpectedRevisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host = {"draft_room_participant_id": "host-user", "room_your_team": "Team 1"}
        self._patch = mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_sync_does_not_overwrite_local_ahead_room(self, _auth: object) -> None:
        code, doc = create_and_host_shared_room(self.host, _sample_live_room(), store=self.store)
        stale_rev = int(doc.get("revision") or 1)
        remote = self.store.load(code)
        assert remote is not None
        self.store.save(bump_revision(remote, live_room=_sample_live_room()))
        self.host[SHARED_ROOM_META_KEY] = {"revision": stale_rev}

        local = _sample_live_room()
        local["draft_board"] = [{"playerID": "p1", "fullName": "Local Pick"}]
        local["current_pick_index"] = 1
        self.host[LIVE_DRAFT_ROOM_KEY] = local

        sync_expected_revision(self.host)
        room = self.host[LIVE_DRAFT_ROOM_KEY]
        self.assertEqual(len(room.get("draft_board") or []), 1)
        self.assertEqual(int(room.get("current_pick_index") or 0), 1)


class HostOnlyAutopickTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host = {"draft_room_participant_id": "host-user", "room_your_team": "Team 1"}
        self.guest = {"draft_room_participant_id": "guest-user", "room_your_team": "Team 2"}
        self._patch = mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_guest_does_not_run_timer_autopick(self, _auth: object) -> None:
        room = _sample_live_room(timer_deadline=time.time() - 5)
        code, _ = create_and_host_shared_room(self.host, room, store=self.store)
        ok, msg, _ = join_shared_draft_room(self.guest, code, store=self.store)
        self.assertTrue(ok, msg)
        expired_room = self.guest[LIVE_DRAFT_ROOM_KEY]
        expired_room["timer_deadline"] = time.time() - 5
        self.assertFalse(_multiplayer_autopick_allowed(self.guest))
        self.assertTrue(_multiplayer_autopick_allowed(self.host))
        self.assertFalse(should_fragment_trigger_full_rerun(self.guest, expired_room))


if __name__ == "__main__":
    unittest.main()
