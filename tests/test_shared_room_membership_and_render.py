"""Release-blocking: page completion, membership gate, leave vs end-all."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from draft_room_participant_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    MEMBERSHIP_KEY,
    restore_persisted_shared_room_membership,
)
from draft_room_shared_state import LocalFileSharedRoomStore, reset_shared_room_store_for_tests
from live_draft_queue_fragment import QUEUE_FRAGMENT_PICK_KEY, _pick_escalation_needed
from shared_room_membership_gate import (
    can_render_shared_live_draft,
    clear_stale_shared_room_local_state,
    repair_stale_shared_room_session,
)


class QueueMidPassRerunTests(unittest.TestCase):
    def test_sticky_pick_flag_does_not_escalate(self) -> None:
        session = {QUEUE_FRAGMENT_PICK_KEY: True, "live_draft_room": {"draft_board": [1, 2]}}
        self.assertFalse(_pick_escalation_needed(session, board_before=2))

    def test_dirty_persist_does_not_escalate(self) -> None:
        session = {
            "_live_draft_pick_persist_dirty": True,
            "live_draft_room": {"draft_board": [1]},
        }
        self.assertFalse(_pick_escalation_needed(session, board_before=1))

    def test_board_growth_does_escalate(self) -> None:
        session = {"live_draft_room": {"draft_board": [1, 2, 3]}}
        self.assertTrue(_pick_escalation_needed(session, board_before=1))


class MembershipGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)

    def tearDown(self) -> None:
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_guest_without_document_membership_cannot_render(self) -> None:
        code = "NEWRM1"
        doc = {
            "room_code": code,
            "status": "waiting",
            "revision": 1,
            "draft_room_id": "DR-NEW",
            "host_participant_id": "daniel-id",
            "participants": {
                "daniel-id": {"assigned_team": "Team A"},
            },
            "room": {"status": "waiting", "draft_room_id": "DR-NEW", "teams": ["Team A", "Team B"]},
        }
        self.store.save(doc)
        guest = {
            "auth_user_id": "clp11-id",
            "draft_room_participant_id": "clp11-id",
            ACTIVE_SHARED_ROOM_CODE_KEY: code,
            "live_draft_room": {"draft_room_id": "DR-NEW", "status": "waiting"},
        }
        ok, reason = can_render_shared_live_draft(guest, document=doc, require_team_claim=False)
        self.assertFalse(ok)
        self.assertEqual(reason, "not_in_document_participants")

    def test_joined_guest_can_render(self) -> None:
        code = "JOIN01"
        doc = {
            "room_code": code,
            "status": "in_progress",
            "revision": 2,
            "draft_room_id": "DR-J",
            "host_participant_id": "daniel-id",
            "participants": {
                "daniel-id": {"assigned_team": "Team A"},
                "clp11-id": {"assigned_team": "Team B"},
            },
            "room": {"status": "in_progress", "draft_room_id": "DR-J"},
        }
        guest = {
            "auth_user_id": "clp11-id",
            "draft_room_participant_id": "clp11-id",
            ACTIVE_SHARED_ROOM_CODE_KEY: code,
            "live_draft_room": {"draft_room_id": "DR-J", "status": "in_progress"},
        }
        ok, reason = can_render_shared_live_draft(guest, document=doc, require_team_claim=True)
        self.assertTrue(ok, reason)

    def test_stale_repair_clears_local_pointer(self) -> None:
        session = {
            "auth_user_id": "clp11-id",
            "draft_room_participant_id": "clp11-id",
            ACTIVE_SHARED_ROOM_CODE_KEY: "GONE99",
            "live_draft_room": {"draft_room_id": "old", "status": "in_progress"},
            "draft_room_participant_team": "Team B",
        }
        with mock.patch(
            "shared_room_membership_gate.load_authoritative_shared_document",
            return_value=None,
        ):
            diag = repair_stale_shared_room_session(session)
        self.assertTrue(diag.get("repaired"))
        self.assertNotIn(ACTIVE_SHARED_ROOM_CODE_KEY, session)
        self.assertIsNone(session.get("live_draft_room"))

    def test_restore_does_not_auto_bind_unverified_newest(self) -> None:
        """Local membership map alone must not attach CLP11 to a room they never joined."""
        guest = {
            "auth_user_id": "clp11-id",
            "draft_room_participant_id": "clp11-id",
            MEMBERSHIP_KEY: {
                "OLDAAA": {"clp11-id": {"team": "Team B", "joined_at": "2020-01-01T00:00:00Z"}},
                "NEWBBB": {"clp11-id": {"team": "Team B", "joined_at": "2099-01-01T00:00:00Z"}},
            },
        }
        with mock.patch(
            "shared_room_membership_gate.load_authoritative_shared_document",
            return_value=None,
        ), mock.patch(
            "suite_auth.is_auth_enabled", return_value=False
        ):
            code = restore_persisted_shared_room_membership(guest)
        self.assertEqual(code, "")
        self.assertNotIn(ACTIVE_SHARED_ROOM_CODE_KEY, guest)


class LeaveVsEndSemanticsTests(unittest.TestCase):
    def test_clear_stale_keeps_setup_ready(self) -> None:
        session = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "X",
            "live_draft_room": {"status": "in_progress"},
            "live_draft_setup_mode": "shared_multiplayer",
        }
        clear_stale_shared_room_local_state(session, reason="test")
        self.assertNotIn(ACTIVE_SHARED_ROOM_CODE_KEY, session)
        self.assertEqual(session.get("live_draft_setup_mode"), "shared_multiplayer")


if __name__ == "__main__":
    unittest.main()
