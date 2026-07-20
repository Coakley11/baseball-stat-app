"""Membership soft-miss must not kick valid Shared Multiplayer participants."""

from __future__ import annotations

import unittest
from unittest import mock

from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY
from shared_room_membership_gate import assert_or_repair_before_shared_render


class SoftMissMembershipTests(unittest.TestCase):
    def test_room_missing_keeps_active_guest(self) -> None:
        session = {
            "auth_user_id": "coakley-id",
            "draft_room_participant_id": "coakley-id",
            ACTIVE_SHARED_ROOM_CODE_KEY: "ABC123",
            "draft_room_participant_team": "Team B",
            "live_draft_room": {
                "draft_room_id": "DR1",
                "status": "in_progress",
                "current_pick_index": 2,
            },
        }
        with mock.patch(
            "shared_room_membership_gate.load_authoritative_shared_document",
            return_value=None,
        ):
            ok, reason = assert_or_repair_before_shared_render(session)
        self.assertTrue(ok, reason)
        self.assertIn("soft_miss", reason)
        self.assertEqual(session.get(ACTIVE_SHARED_ROOM_CODE_KEY), "ABC123")
        self.assertEqual(session.get("draft_room_participant_team"), "Team B")
        self.assertIsInstance(session.get("live_draft_room"), dict)

    def test_confirmed_not_member_fails_closed(self) -> None:
        session = {
            "auth_user_id": "coakley-id",
            "draft_room_participant_id": "coakley-id",
            ACTIVE_SHARED_ROOM_CODE_KEY: "ABC123",
            "draft_room_participant_team": "Team B",
            "live_draft_room": {"draft_room_id": "DR1", "status": "in_progress"},
        }
        doc = {
            "room_code": "ABC123",
            "status": "in_progress",
            "participants": {"daniel-id": {"team": "Team A"}},
            "room": {"draft_room_id": "DR1", "status": "in_progress"},
        }
        with mock.patch(
            "shared_room_membership_gate.load_authoritative_shared_document",
            return_value=doc,
        ):
            ok, reason = assert_or_repair_before_shared_render(session)
        self.assertFalse(ok)
        self.assertEqual(reason, "not_in_document_participants")
        self.assertNotIn(ACTIVE_SHARED_ROOM_CODE_KEY, session)


if __name__ == "__main__":
    unittest.main()
