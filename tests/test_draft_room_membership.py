"""Tests for auth-based shared draft room membership (PR 5)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from draft_room_context import (
    create_and_host_shared_room,
    join_shared_draft_room,
    prepare_global_draft_context,
)
from draft_room_membership import (
    ERR_CANNOT_DRAFT_OTHER_TEAM,
    ERR_HOST_ONLY_RESET,
    ERR_LOGIN_REQUIRED,
    ERR_TEAM_ALREADY_ASSIGNED,
    close_shared_draft_room,
    is_room_host,
    resolve_join_team_assignment,
    reset_live_draft_with_membership_guard,
)
from draft_room_participant_state import ACTIVE_PARTICIPANT_ID_KEY, MEMBERSHIP_KEY
from draft_room_shared_state import LocalFileSharedRoomStore, sanitize_shared_room_document
from draft_source_validation import validate_shared_pick_commit
from suite_auth import AUTH_USER_EMAIL_KEY, AUTH_USER_ID_KEY


def _sample_live_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF"},
        ]
    )
    return {
        "draft_room_id": "MULTI1",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "your_team": "Team 2"},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team 1"},
            {"Pick": 2, "Round": 1, "Team": "Team 2"},
        ],
        "draft_board": [
            {"Pick": 1, "Round": 1, "Team": "Team 1", "Player": ""},
            {"Pick": 2, "Round": 1, "Team": "Team 2", "Player": ""},
        ],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


class DraftRoomMembershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host_session = {
            ACTIVE_PARTICIPANT_ID_KEY: "auth-host-uuid",
            AUTH_USER_ID_KEY: "auth-host-uuid",
            AUTH_USER_EMAIL_KEY: "Daniel.cohen11@yahoo.com",
        }
        self.guest_session = {
            ACTIVE_PARTICIPANT_ID_KEY: "auth-guest-uuid",
            AUTH_USER_ID_KEY: "auth-guest-uuid",
            AUTH_USER_EMAIL_KEY: "Coakley11@aol.com",
        }
        self._store_patch = patch(
            "draft_room_shared_state.get_shared_room_store",
            return_value=self.store,
        )
        self._store_patch.start()

    def tearDown(self) -> None:
        self._store_patch.stop()
        self._tmpdir.cleanup()

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_host_gets_team_1_by_default(self, _mock_auth: object) -> None:
        code, doc = create_and_host_shared_room(
            self.host_session,
            _sample_live_room(),
            store=self.store,
        )
        self.assertTrue(code)
        self.assertEqual(doc["participants"]["auth-host-uuid"]["assigned_team"], "Team 1")
        self.assertTrue(is_room_host(self.host_session, doc))

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_second_user_joins_team_2(self, _mock_auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        ok, msg, _ = join_shared_draft_room(self.guest_session, code, store=self.store)
        self.assertTrue(ok, msg)
        self.assertEqual(self.guest_session.get("draft_room_participant_team"), "Team 2")

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_different_auth_users_receive_different_teams(self, _mock_auth: object) -> None:
        code, doc = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        ok, msg, joined = join_shared_draft_room(self.guest_session, code, store=self.store)
        self.assertTrue(ok, msg)
        self.assertIsInstance(joined, dict)
        participants = dict(joined.get("participants") or {})
        host_team = participants["auth-host-uuid"]["assigned_team"]
        guest_team = participants["auth-guest-uuid"]["assigned_team"]
        self.assertNotEqual(host_team, guest_team)
        self.assertEqual(self.host_session.get("draft_room_participant_team"), host_team)
        self.assertEqual(self.guest_session.get("draft_room_participant_team"), guest_team)

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_guest_team_survives_shared_workspace_host_membership_blob(self, _mock_auth: object) -> None:
        """Regression: shared daniel workspace must not overwrite guest team with host team."""
        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        join_shared_draft_room(self.guest_session, code, store=self.store)
        self.guest_session.pop("draft_room_participant_team", None)
        self.guest_session["room_your_team"] = "Team 1"
        self.guest_session[MEMBERSHIP_KEY] = {
            code: {
                "auth-host-uuid": {
                    "participant_id": "auth-host-uuid",
                    "assigned_team": "Team 1",
                },
                "auth-guest-uuid": {
                    "participant_id": "auth-guest-uuid",
                    "assigned_team": "Team 2",
                },
            }
        }
        prepare_global_draft_context(self.guest_session)
        self.assertEqual(self.guest_session.get("draft_room_participant_team"), "Team 2")
        self.assertNotEqual(self.guest_session.get("draft_room_participant_team"), "Team 1")
        self.assertIsNone(self.guest_session.get("room_your_team"))

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_legacy_host_only_membership_does_not_assign_guest_host_team(self, _mock_auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        join_shared_draft_room(self.guest_session, code, store=self.store)
        self.guest_session.pop("draft_room_participant_team", None)
        self.guest_session[MEMBERSHIP_KEY] = {
            code: {
                "participant_id": "auth-host-uuid",
                "assigned_team": "Team 1",
            }
        }
        prepare_global_draft_context(self.guest_session)
        self.assertEqual(self.guest_session.get("draft_room_participant_team"), "Team 2")

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_new_guest_join_does_not_inherit_host_queue_from_globals(self, _mock_auth: object) -> None:
        from draft_state import DRAFT_QUEUE_KEY

        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        self.guest_session[DRAFT_QUEUE_KEY] = ["Aaron Judge", "Juan Soto"]
        ok, msg, _ = join_shared_draft_room(self.guest_session, code, store=self.store)
        self.assertTrue(ok, msg)
        self.assertEqual(self.guest_session.get(DRAFT_QUEUE_KEY), [])

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_rejoin_restores_same_team(self, _mock_auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        join_shared_draft_room(self.guest_session, code, store=self.store)
        self.guest_session["draft_room_participant_team"] = "Team 99"
        ok, _, _ = join_shared_draft_room(self.guest_session, code, store=self.store)
        self.assertTrue(ok)
        self.assertEqual(self.guest_session.get("draft_room_participant_team"), "Team 2")

    @patch("draft_room_membership.shared_room_requires_auth", return_value=True)
    def test_join_requires_login_when_supabase(self, _mock_auth: object) -> None:
        with patch("draft_room_membership.is_auth_session", return_value=False):
            ok, msg, _ = join_shared_draft_room({}, "ABC123", store=self.store)
        self.assertFalse(ok)
        self.assertEqual(msg, ERR_LOGIN_REQUIRED)

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_team_already_assigned_error(self, _mock_auth: object) -> None:
        code, doc = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        team, err = resolve_join_team_assignment(doc, "other-user", requested_team="Team 1")
        self.assertIsNone(team)
        self.assertEqual(err, ERR_TEAM_ALREADY_ASSIGNED)

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_guest_cannot_reset_room(self, _mock_auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        join_shared_draft_room(self.guest_session, code, store=self.store)
        self.guest_session["active_shared_draft_room_code"] = code
        ok, msg = close_shared_draft_room(self.guest_session, store=self.store)
        self.assertFalse(ok)
        self.assertEqual(msg, ERR_HOST_ONLY_RESET)

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_host_can_close_room(self, _mock_auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        self.host_session["active_shared_draft_room_code"] = code
        ok, msg = close_shared_draft_room(self.host_session, store=self.store)
        self.assertTrue(ok, msg)
        self.assertNotIn("active_shared_draft_room_code", self.host_session)

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_cannot_draft_for_other_team(self, _mock_auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        join_shared_draft_room(self.guest_session, code, store=self.store)
        prepare_global_draft_context(self.guest_session)
        room = self.guest_session["live_draft_room"]
        ok, msg = validate_shared_pick_commit(self.guest_session, room, "Aaron Judge")
        self.assertFalse(ok)
        self.assertIn("Not your pick", msg)

    @patch("draft_room_membership.shared_room_requires_auth", return_value=True)
    def test_stale_participant_id_cleared_for_authenticated_guest(self, _mock_auth: object) -> None:
        from suite_auth import AUTH_SESSION_KEY
        from draft_room_participant_state import (
            ACTIVE_PARTICIPANT_ID_KEY,
            ACTIVE_PARTICIPANT_TEAM_KEY,
            active_participant_team,
            resolve_participant_id,
        )

        guest = {
            ACTIVE_PARTICIPANT_ID_KEY: "auth-host-uuid",
            ACTIVE_PARTICIPANT_TEAM_KEY: "Team Daniel",
            AUTH_USER_ID_KEY: "auth-guest-uuid",
            AUTH_USER_EMAIL_KEY: "Coakley11@aol.com",
            AUTH_SESSION_KEY: True,
        }
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth.is_authenticated", return_value=True
        ):
            self.assertEqual(resolve_participant_id(guest), "auth-guest-uuid")
            self.assertNotIn(ACTIVE_PARTICIPANT_ID_KEY, guest)
            code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
            ok, msg, _ = join_shared_draft_room(guest, code, store=self.store)
            self.assertTrue(ok, msg)
        guest["active_shared_draft_room_code"] = code
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth.is_authenticated", return_value=True
        ):
            team = active_participant_team(guest)
        self.assertEqual(team, "Team 2")
        self.assertNotEqual(team, "Team Daniel")

    def test_private_fields_not_in_shared_document(self) -> None:
        doc = {
            "room_code": "X",
            "queue": ["Aaron Judge"],
            "participants": {"u1": {"assigned_team": "Team 1", "workflow": {"queue": ["x"]}}},
            "room": {"draft_board": []},
        }
        cleaned = sanitize_shared_room_document(doc)
        self.assertNotIn("queue", cleaned)
        self.assertNotIn("workflow", cleaned["participants"]["u1"])


if __name__ == "__main__":
    unittest.main()
