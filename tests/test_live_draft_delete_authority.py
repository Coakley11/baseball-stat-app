"""Authoritative End/Delete for Everyone — backend receipt required."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from draft_room_context import create_and_host_shared_room, join_shared_draft_room
from draft_room_shared_state import LocalFileSharedRoomStore, load_shared_room
from live_draft_completion import LIFECYCLE_SETUP, resolve_live_draft_lifecycle
from live_draft_delete_authority import (
    DELETE_RECEIPT_KEY,
    delete_shared_live_draft_for_everyone,
    note_delete_trace,
)


def _room() -> dict:
    return {
        "draft_room_id": "DELTEST1",
        "status": "in_progress",
        "teams": ["Team A", "Team B"],
        "config": {"num_teams": 2, "picks_per_team": 2, "timer_seconds": 30},
        "pick_order": [
            {"Pick": 1, "Team": "Team A"},
            {"Pick": 2, "Team": "Team B"},
        ],
        "draft_board": [],
        "current_pick_index": 0,
        "pool": [],
    }


class DeleteAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self._patch = mock.patch(
            "draft_room_shared_state.get_shared_room_store", return_value=self.store
        )
        self._patch.start()
        self.host = {
            "draft_room_participant_id": "host-pid",
            "auth_user_id": "host-auth",
        }
        self.guest = {
            "draft_room_participant_id": "guest-pid",
            "auth_user_id": "guest-auth",
        }

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    @mock.patch("draft_room_membership.ensure_authenticated_for_shared_room", return_value=(True, ""))
    def test_delete_requires_backend_receipt_and_exits(self, *_m: object) -> None:
        code, _ = create_and_host_shared_room(self.host, _room(), host_team="Team A", store=self.store)
        join_shared_draft_room(self.guest, code, store=self.store)
        self.host["live_draft_room"] = dict(self.host.get("live_draft_room") or _room())
        self.host["live_draft_room"]["status"] = "in_progress"
        self.host["active_shared_draft_room_code"] = code

        note_delete_trace(self.host, "test_start")
        receipt = delete_shared_live_draft_for_everyone(
            self.host, st=None, room_code=code, reason="unit_test"
        )
        self.assertTrue(receipt.get("ok"), receipt)
        self.assertTrue(receipt.get("backend_ok"), receipt)
        self.assertTrue(receipt.get("auth_ok"), receipt)
        self.assertEqual(receipt.get("room_code"), code)
        self.assertTrue(receipt.get("deletion_generation"))
        self.assertEqual(self.host.get(DELETE_RECEIPT_KEY), receipt)
        self.assertEqual(self.host.get("_live_draft_deleting"), "done")
        self.assertIsNone(self.host.get("live_draft_room"))
        self.assertEqual(resolve_live_draft_lifecycle(self.host), LIFECYCLE_SETUP)

        doc = load_shared_room(code)
        self.assertEqual(str((doc or {}).get("status") or "").lower(), "deleted")
        self.assertEqual((doc or {}).get("participants") or {}, {})

        # Guest poll path clears via terminal handler.
        from live_draft_termination import handle_shared_document_terminal

        self.guest["live_draft_room"] = dict(_room())
        self.guest["active_shared_draft_room_code"] = code
        self.assertTrue(handle_shared_document_terminal(self.guest, doc))
        self.assertIsNone(self.guest.get("live_draft_room"))
        self.assertEqual(resolve_live_draft_lifecycle(self.guest), LIFECYCLE_SETUP)

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    @mock.patch("draft_room_membership.ensure_authenticated_for_shared_room", return_value=(True, ""))
    def test_guest_cannot_delete(self, *_m: object) -> None:
        code, _ = create_and_host_shared_room(self.host, _room(), host_team="Team A", store=self.store)
        join_shared_draft_room(self.guest, code, store=self.store)
        self.guest["live_draft_room"] = dict(self.guest.get("live_draft_room") or _room())
        self.guest["active_shared_draft_room_code"] = code
        receipt = delete_shared_live_draft_for_everyone(
            self.guest, st=None, room_code=code, reason="guest_attempt"
        )
        self.assertFalse(receipt.get("ok"))
        self.assertEqual(receipt.get("error"), "not_commissioner")
        self.assertIsNotNone(self.guest.get("live_draft_room"))
        doc = load_shared_room(code)
        self.assertNotEqual(str((doc or {}).get("status") or "").lower(), "deleted")


if __name__ == "__main__":
    unittest.main()
