"""End Draft exclusive lifecycle + drafted-player queue prune + preferred mode."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import join_shared_draft_room
from draft_room_participant_state import (
    load_participant_workflow_into_session,
    save_participant_workflow_from_session,
)
from draft_room_shared_state import LocalFileSharedRoomStore, reset_shared_room_store_for_tests
from draft_state import DRAFT_QUEUE_KEY, add_player_to_draft_queue, remove_drafted_player_from_active_queues
from live_draft_completion import (
    END_DRAFT_CLEAR_KEYS,
    LIFECYCLE_SETUP,
    end_live_draft_session,
    is_live_draft_ended_tombstoned,
    resolve_live_draft_lifecycle,
)
from live_draft_setup_mode import (
    LIVE_DRAFT_SETUP_MODE_KEY,
    PREFERRED_NEXT_DRAFT_MODE_KEY,
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    finalize_shared_room_create,
    get_preferred_next_draft_mode,
    set_live_draft_setup_mode,
    should_show_full_draft_setup,
)
from live_draft_timer_logic import live_draft_reset_timer, live_draft_seconds_remaining
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY


def _sample_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
        ]
    )
    return {
        "draft_room_id": "END1",
        "status": "not_started",
        "current_pick_index": 0,
        "config": {
            "num_teams": 2,
            "your_team": "Team A",
            "teams": ["Team A", "Team B"],
            "draft_setup_mode": SETUP_MODE_SHARED,
            "timer_seconds": 30,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
        ],
        "draft_board": [],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


def _daniel() -> dict:
    return {
        AUTH_USER_ID_KEY: "uuid-daniel",
        AUTH_EXTERNAL_ID_KEY: "daniel",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "daniel",
        "draft_room_participant_id": "uuid-daniel",
        LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SOLO,
    }


def _coakley() -> dict:
    return {
        AUTH_USER_ID_KEY: "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        AUTH_EXTERNAL_ID_KEY: "coakley11",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "coakley11",
        "draft_room_participant_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED,
    }


class PreferredNextModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
        self._auth.start()

    def tearDown(self) -> None:
        self._auth.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_create_shared_updates_preferred_next_mode(self) -> None:
        host = _daniel()
        self.assertEqual(get_preferred_next_draft_mode(host), SETUP_MODE_SOLO)
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        self.assertTrue(code)
        self.assertEqual(get_preferred_next_draft_mode(host), SETUP_MODE_SHARED)
        self.assertEqual(host.get(PREFERRED_NEXT_DRAFT_MODE_KEY), SETUP_MODE_SHARED)


class EndDraftLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
        self._auth.start()

    def tearDown(self) -> None:
        self._auth.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_end_draft_clears_room_and_tombstones(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)

        result = end_live_draft_session(host, st=None, reason="test_end")
        self.assertTrue(result["ok"])
        self.assertIsNone(host.get("live_draft_room"))
        self.assertTrue(should_show_full_draft_setup(host))
        self.assertEqual(resolve_live_draft_lifecycle(host), LIFECYCLE_SETUP)
        self.assertTrue(
            is_live_draft_ended_tombstoned(host, room_code=code, draft_room_id="END1")
        )
        # Preferred next mode remains Shared (last actual draft).
        self.assertEqual(get_preferred_next_draft_mode(host), SETUP_MODE_SHARED)
        for key in ("_shared_lobby_authority_doc", "_shared_room_doc_soft_cache", "active_shared_draft_room_code"):
            self.assertIn(key, END_DRAFT_CLEAR_KEYS)


class DraftedQueuePruneTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
        self._auth.start()

    def tearDown(self) -> None:
        self._auth.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_drafted_player_removed_locally_and_prune_clears_others(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)

        add_player_to_draft_queue(host, "Juan Soto")
        add_player_to_draft_queue(host, "Aaron Judge")
        add_player_to_draft_queue(guest, "Juan Soto")
        add_player_to_draft_queue(guest, "Aaron Judge")
        save_participant_workflow_from_session(guest, code)

        remove_drafted_player_from_active_queues(host, "Juan Soto", room_or_draft_id=code)
        self.assertEqual(host.get(DRAFT_QUEUE_KEY), ["Aaron Judge"])

        # Guest still has Soto until their board syncs; paint-time prune clears it.
        from draft_actions import _prune_drafted_from_queue

        guest["live_draft_room"] = {
            "status": "in_progress",
            "drafted_player_ids": ["p1"],
            "draft_board": [{"fullName": "Juan Soto", "playerID": "p1"}],
            "config": {},
        }
        with mock.patch(
            "draft_room_state.get_all_drafted_player_names",
            return_value=["Juan Soto"],
        ):
            pruned = _prune_drafted_from_queue(guest)
        self.assertEqual(pruned, ["Aaron Judge"])
        self.assertEqual(guest.get(DRAFT_QUEUE_KEY), ["Aaron Judge"])


class TimerDeadlineFreshnessTests(unittest.TestCase):
    def test_reset_timer_uses_now_plus_duration(self) -> None:
        import time

        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 30},
            "timer_deadline": time.time() - 20,
            "timer_started_at": time.time() - 50,
            "current_pick_index": 1,
        }
        before = time.time()
        live_draft_reset_timer(room)
        after = time.time()
        remaining = live_draft_seconds_remaining(room)
        self.assertGreaterEqual(remaining, 29)
        self.assertLessEqual(remaining, 30)
        self.assertGreaterEqual(float(room["timer_deadline"]), before + 29)
        self.assertLessEqual(float(room["timer_deadline"]), after + 31)


if __name__ == "__main__":
    unittest.main()
