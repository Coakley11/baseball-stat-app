"""Team assignment restore from shared participant registry."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typing import Any

import pandas as pd

from draft_room_context import create_and_host_shared_room, join_shared_draft_room, prepare_global_draft_context
from draft_room_participant_state import (
    ACTIVE_PARTICIPANT_TEAM_KEY,
    MEMBERSHIP_KEY,
    active_participant_team,
    build_participant_assignment_diagnostics,
    ensure_participant_team_assigned,
)
from draft_room_shared_state import LocalFileSharedRoomStore
from suite_auth import AUTH_SESSION_KEY, AUTH_USER_ID_KEY


def _sample_live_room() -> dict:
    pool = pd.DataFrame([{"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"}])
    return {
        "draft_room_id": "MULTI1",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "your_team": "Team 1"},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team 1"}],
        "draft_board": [{"Pick": 1, "Round": 1, "Team": "Team 1", "Player": ""}],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


class ParticipantTeamAssignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host_session = {
            AUTH_USER_ID_KEY: "auth-host-uuid",
            AUTH_SESSION_KEY: True,
        }
        self.guest_session = {
            AUTH_USER_ID_KEY: "auth-guest-uuid",
            AUTH_SESSION_KEY: True,
        }
        self._store_patch = patch(
            "draft_room_shared_state.get_shared_room_store",
            return_value=self.store,
        )
        self._store_patch.start()

    def tearDown(self) -> None:
        self._store_patch.stop()
        self._tmpdir.cleanup()

    def _simulate_cloud_restore_skipping_mp_scoped(self, session: dict[str, Any]) -> None:
        """Cloud restore skips membership + team globals but keeps auth user id."""
        session.pop(MEMBERSHIP_KEY, None)
        session.pop(ACTIVE_PARTICIPANT_TEAM_KEY, None)
        session.pop("draft_room_participant_id", None)
        session.pop("room_your_team", None)

    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("draft_room_membership.shared_room_requires_auth", return_value=True)
    def test_ensure_restores_team_from_registry(self, _mock_auth: object, _mock_enabled: object) -> None:
        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        ok, msg, doc = join_shared_draft_room(self.guest_session, code, requested_team="Team 2", store=self.store)
        self.assertTrue(ok, msg)
        self._simulate_cloud_restore_skipping_mp_scoped(self.guest_session)
        team, fail = ensure_participant_team_assigned(self.guest_session, room_code=code, document=doc)
        self.assertEqual(team, "Team 2")
        self.assertEqual(fail, "")
        self.assertEqual(active_participant_team(self.guest_session), "Team 2")

    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("draft_room_membership.shared_room_requires_auth", return_value=True)
    def test_assignment_diagnostics_fields(self, _mock_auth: object, _mock_enabled: object) -> None:
        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        join_shared_draft_room(self.guest_session, code, requested_team="Team 2", store=self.store)
        diag = build_participant_assignment_diagnostics(self.guest_session, source="test")
        self.assertEqual(diag.get("room_code"), code)
        self.assertEqual(diag.get("participant_id"), "auth-guest-uuid")
        self.assertTrue(diag.get("participant_registry_found"))
        self.assertEqual(diag.get("registry_assigned_team"), "Team 2")
        self.assertEqual(diag.get("displayed_team"), "Team 2")

    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("draft_room_membership.shared_room_requires_auth", return_value=True)
    def test_prepare_global_restores_guest_team_after_restore(self, _mock_auth: object, _mock_enabled: object) -> None:
        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        ok, msg, _ = join_shared_draft_room(self.guest_session, code, requested_team="Team 2", store=self.store)
        self.assertTrue(ok, msg)
        self._simulate_cloud_restore_skipping_mp_scoped(self.guest_session)
        self.assertEqual(self.guest_session.get("active_shared_draft_room_code"), code)
        prepare_global_draft_context(self.guest_session)
        self.assertEqual(active_participant_team(self.guest_session), "Team 2")


if __name__ == "__main__":
    unittest.main()
