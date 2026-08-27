"""Shared Draft create/join/reconnect keeps identity and private queues after refresh."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from draft_room_context import join_shared_draft_room, sync_shared_draft_room
from draft_room_create_verify import is_plausible_share_code
from draft_room_participant_state import (
    MEMBERSHIP_KEY,
    PARTICIPANT_STATE_KEY,
    live_draft_room_share_code,
    load_participant_workflow_into_session,
    restore_persisted_shared_room_membership,
    save_participant_workflow_from_session,
)
from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    LocalFileSharedRoomStore,
    load_shared_room,
    reset_shared_room_store_for_tests,
    shared_room_document_private_leaks,
)
from draft_state import DRAFT_QUEUE_KEY, add_player_to_draft_queue
from live_draft_queue_survival import QUEUE_SCOPE_KEY
from live_draft_setup_mode import SETUP_MODE_SHARED, finalize_shared_room_create, set_live_draft_setup_mode


def _room() -> dict:
    return {
        "draft_room_id": "PREDRAFT1",
        "status": "not_started",
        "current_pick_index": 0,
        "config": {
            "num_teams": 2,
            "your_team": "Team A",
            "user_team": "Team A",
            "teams": ["Team A", "Team B"],
            "draft_setup_mode": SETUP_MODE_SHARED,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
        ],
        "draft_board": [],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": [],
        "pool": [],
    }


def _host() -> dict:
    return {
        "draft_room_participant_id": "daniel",
        "auth_user_id": "daniel",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


def _guest() -> dict:
    return {
        "draft_room_participant_id": "coakley11",
        "auth_user_id": "coakley11",
    }


class SharedDraftRefreshQueueIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._patches = [
            mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_context.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_internal_draft_id_is_not_a_share_code(self) -> None:
        self.assertFalse(is_plausible_share_code("PREDRAFT1"))
        self.assertEqual(live_draft_room_share_code({"draft_room_id": "PREDRAFT1"}), "")
        self.assertEqual(
            live_draft_room_share_code(
                {"draft_room_id": "PREDRAFT1", "room_code": "ABC123", "sync": {"room_code": "ABC123"}}
            ),
            "ABC123",
        )

    def test_create_join_reconnect_refresh_keeps_identity_and_private_queues(self) -> None:
        host = _host()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        self.assertTrue(is_plausible_share_code(code))
        self.assertEqual(host.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        host_room = host.get("live_draft_room") or {}
        self.assertEqual(str(host_room.get("draft_room_id") or ""), "PREDRAFT1")
        self.assertEqual(live_draft_room_share_code(host_room), code)
        self.assertNotEqual(str(host_room.get("draft_room_id") or ""), code)

        guest = _guest()
        ok, msg, doc = join_shared_draft_room(
            guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok, msg)
        self.assertEqual(guest.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        self.assertEqual(guest.get("draft_room_participant_team"), "Team B")
        guest_room = guest.get("live_draft_room") or {}
        self.assertEqual(str(guest_room.get("draft_room_id") or ""), "PREDRAFT1")
        self.assertEqual(live_draft_room_share_code(guest_room), code)

        add_player_to_draft_queue(host, "Francisco Lindor")
        save_participant_workflow_from_session(host, code)
        add_player_to_draft_queue(guest, "Aaron Judge")
        save_participant_workflow_from_session(guest, code)
        self.assertEqual(host.get(DRAFT_QUEUE_KEY), ["Francisco Lindor"])
        self.assertEqual(guest.get(DRAFT_QUEUE_KEY), ["Aaron Judge"])
        self.assertNotEqual(host.get(QUEUE_SCOPE_KEY), guest.get(QUEUE_SCOPE_KEY))

        ok2, msg2, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok2, msg2)
        self.assertEqual(guest.get("draft_room_participant_team"), "Team B")
        self.assertEqual(guest.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        load_participant_workflow_into_session(guest, code)
        self.assertEqual(guest.get(DRAFT_QUEUE_KEY), ["Aaron Judge"])

        stored = load_shared_room(code, store=self.store)
        self.assertIsInstance(stored, dict)
        self.assertEqual(shared_room_document_private_leaks(stored), [])
        stored_room = stored.get("room") if isinstance(stored.get("room"), dict) else {}
        stored_room["status"] = "in_progress"
        stored_room["draft_board"] = [
            {"Pick": 1, "fullName": "Shohei Ohtani", "playerID": "ohtani", "Team": "Team A"}
        ]
        stored_room["current_pick_index"] = 1
        stored["room"] = stored_room
        stored["room_code"] = code
        stored["revision"] = int(stored.get("revision") or 0) + 1
        self.store.save(stored)

        changed = sync_shared_draft_room(guest, force=True, store=self.store)
        self.assertTrue(changed)
        self.assertEqual(guest.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        self.assertEqual(str((guest.get("live_draft_room") or {}).get("draft_room_id") or ""), "PREDRAFT1")
        self.assertEqual(guest.get(DRAFT_QUEUE_KEY), ["Aaron Judge"])
        load_participant_workflow_into_session(host, code)
        self.assertEqual(host.get(DRAFT_QUEUE_KEY), ["Francisco Lindor"])

        refreshed = {
            "draft_room_participant_id": "coakley11",
            "auth_user_id": "coakley11",
            ACTIVE_SHARED_ROOM_CODE_KEY: code,
            MEMBERSHIP_KEY: dict(guest.get(MEMBERSHIP_KEY) or {}),
            PARTICIPANT_STATE_KEY: dict(guest.get(PARTICIPANT_STATE_KEY) or {}),
        }
        restored = restore_persisted_shared_room_membership(refreshed)
        self.assertEqual(restored, code)
        load_participant_workflow_into_session(refreshed, code)
        self.assertEqual(refreshed.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        self.assertEqual(refreshed.get(DRAFT_QUEUE_KEY), ["Aaron Judge"])
        self.assertNotIn("Francisco Lindor", refreshed.get(DRAFT_QUEUE_KEY) or [])


if __name__ == "__main__":
    unittest.main()
