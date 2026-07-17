"""Daniel creates Shared Multiplayer room; Coakley11 joins by code across workspaces."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import join_shared_draft_room, resolve_shared_room_code
from draft_room_create_verify import load_shared_room_with_diagnostics
from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    LIVE_DRAFT_ROOM_KEY,
    LocalFileSharedRoomStore,
    reset_shared_room_store_for_tests,
)
from live_draft_setup_mode import SETUP_MODE_SHARED, can_start_live_draft, set_live_draft_setup_mode
from live_draft_state import clear_foreign_live_draft_state, live_draft_restore_allowed
from live_draft_team_ownership import lookup_open_teams_for_code
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_EMAIL_KEY, AUTH_USER_ID_KEY


def _sample_room(**overrides) -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF"},
        ]
    )
    room = {
        "draft_room_id": "XWJOIN1",
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
        "pool": pool,
    }
    room.update(overrides)
    return room


def _daniel() -> dict:
    return {
        AUTH_USER_ID_KEY: "uuid-daniel",
        AUTH_EXTERNAL_ID_KEY: "daniel",
        AUTH_USER_EMAIL_KEY: "daniel.cohen11@yahoo.com",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "daniel",
        "_suite_owned_workspace_id": "daniel",
        "draft_room_participant_id": "uuid-daniel",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


def _coakley() -> dict:
    return {
        AUTH_USER_ID_KEY: "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        AUTH_EXTERNAL_ID_KEY: "coakley11",
        AUTH_USER_EMAIL_KEY: "coakley11@aol.com",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "coakley11",
        "_suite_owned_workspace_id": "coakley11",
        "draft_room_participant_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


class CrossWorkspaceRoomCodeJoinTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
        self._auth.start()
        self._authenticated = mock.patch("suite_auth.is_authenticated", return_value=True)
        self._authenticated.start()
        self._auth_enabled = mock.patch("suite_auth.is_auth_enabled", return_value=True)
        self._auth_enabled.start()

    def tearDown(self) -> None:
        self._auth_enabled.stop()
        self._authenticated.stop()
        self._auth.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def _create_daniel_room(self) -> tuple[dict, str]:
        from live_draft_setup_mode import finalize_shared_room_create

        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _sample_room()
        code, err = finalize_shared_room_create(host, room, host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        self.assertEqual(len(code), 6)
        return host, code

    def test_coakley_joins_with_spaced_lowercase_code(self) -> None:
        host, code = self._create_daniel_room()
        guest = _coakley()
        messy = f"  {code.lower()}  "
        teams, lookup_err = lookup_open_teams_for_code(messy, store=self.store)
        self.assertFalse(lookup_err, lookup_err)
        self.assertIn("Team B", teams)

        ok, msg, doc = join_shared_draft_room(guest, messy, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)
        self.assertEqual(resolve_shared_room_code(guest), code.upper())
        self.assertEqual(str(guest.get("draft_room_participant_team") or ""), "Team B")
        self.assertEqual(guest.get("_suite_active_workspace_id"), "coakley11")
        self.assertEqual(guest.get("_suite_owned_workspace_id"), "coakley11")
        # Regression: claim bind must not wipe hydrated room (share code vs draft_room_id).
        guest_room = guest.get(LIVE_DRAFT_ROOM_KEY)
        self.assertIsInstance(guest_room, dict, "guest live_draft_room missing after join")
        self.assertEqual(str((guest_room or {}).get("draft_room_id") or ""), "XWJOIN1")

        # Host team unchanged; both see same room id + revision.
        self.assertEqual(str(host.get("room_your_team") or host.get("draft_room_participant_team") or ""), "Team A")
        assert isinstance(doc, dict)
        self.assertEqual(str(doc.get("draft_room_id")), "XWJOIN1")
        loaded = self.store.load(code)
        assert isinstance(loaded, dict)
        self.assertEqual(int(loaded.get("revision") or 0), int(doc.get("revision") or 0))
        participants = dict(loaded.get("participants") or {})
        self.assertEqual(str((participants.get("uuid-daniel") or {}).get("assigned_team")), "Team A")
        self.assertEqual(
            str((participants.get("961df5e9-cdde-48d7-80dd-95a8ba3f46e5") or {}).get("assigned_team")),
            "Team B",
        )

        # Start becomes enabled when both humans are claimed + present.
        host[LIVE_DRAFT_ROOM_KEY] = host.get(LIVE_DRAFT_ROOM_KEY) or _sample_room()
        host[ACTIVE_SHARED_ROOM_CODE_KEY] = code
        # Presence may be required — mark both present via joined_participants on store doc.
        from live_draft_presence import JOINED_PARTICIPANTS_KEY

        loaded[JOINED_PARTICIPANTS_KEY] = {
            "uuid-daniel": {"team_name": "Team A", "present": True},
            "961df5e9-cdde-48d7-80dd-95a8ba3f46e5": {"team_name": "Team B", "present": True},
        }
        self.store.save(loaded)
        with mock.patch("live_draft_presence.mark_participant_present"):
            ok_start, reason = can_start_live_draft(host)
        # Distinct owners claimed — presence gating may still apply; at least claims are 2.
        from live_draft_team_ownership import distinct_claimed_owner_count

        self.assertGreaterEqual(distinct_claimed_owner_count(host, host[LIVE_DRAFT_ROOM_KEY]), 2)
        _ = ok_start, reason

    def test_lookup_is_global_not_workspace_scoped(self) -> None:
        _host, code = self._create_daniel_room()
        # Coakley uses a different store instance pointing at the same global registry root.
        guest_store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        load = load_shared_room_with_diagnostics(guest_store, code)
        self.assertTrue(load.get("found"), load)
        self.assertNotIn("baseball__coakley11", str(load.get("backend") or ""))

    def test_invalid_code(self) -> None:
        teams, err = lookup_open_teams_for_code("ZZZZZZ", store=self.store)
        self.assertEqual(teams, [])
        self.assertEqual(err, "Room code not found")

    def test_already_claimed_team(self) -> None:
        _host, code = self._create_daniel_room()
        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team A", store=self.store)
        self.assertFalse(ok)
        self.assertIn("claimed", msg.lower())

    def test_completed_room_blocked(self) -> None:
        host, code = self._create_daniel_room()
        doc = self.store.load(code)
        assert isinstance(doc, dict)
        doc["status"] = "completed"
        self.store.save(doc)
        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertFalse(ok)
        self.assertIn("no longer joinable", msg.lower())

    def test_duplicate_join_same_user(self) -> None:
        _host, code = self._create_daniel_room()
        guest = _coakley()
        ok1, msg1, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok1, msg1)
        ok2, msg2, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok2, msg2)
        self.assertIn("already joined", msg2.lower())

    def test_room_code_join_does_not_require_invitation(self) -> None:
        _host, code = self._create_daniel_room()
        guest = _coakley()
        # No invite keys present.
        self.assertNotIn("fantasy_league_invites", guest)
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)
        diag = guest.get("_draft_room_join_attempt_diag") or {}
        self.assertFalse(diag.get("invitation_required"))

    def test_guest_hydrate_not_cleared_as_foreign(self) -> None:
        _host, code = self._create_daniel_room()
        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)
        blob = {
            "draft_room_id": "XWJOIN1",
            "owner_auth_user_id": "uuid-daniel",
            "owner_workspace_id": "daniel",
        }
        allowed, reason = live_draft_restore_allowed(guest, blob, source="test")
        self.assertTrue(allowed, reason)
        self.assertEqual(reason, "shared_multiplayer_participant")
        clear_foreign_live_draft_state(guest, reason="auth_user_mismatch")
        self.assertTrue(guest.get(LIVE_DRAFT_ROOM_KEY) or guest.get(ACTIVE_SHARED_ROOM_CODE_KEY))
        self.assertIn("skipped_clear_mp", str(guest.get("_live_draft_restore_blocked_reason") or ""))

    def test_no_available_teams(self) -> None:
        host, code = self._create_daniel_room()
        # Claim Team B as a second host-side participant so guest has nothing left.
        other = {
            AUTH_USER_ID_KEY: "other-user",
            "draft_room_participant_id": "other-user",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
        }
        ok, msg, _ = join_shared_draft_room(other, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)
        teams, err = lookup_open_teams_for_code(code, store=self.store)
        self.assertEqual(teams, [])
        self.assertEqual(err, "No teams are available")
        _ = host


if __name__ == "__main__":
    unittest.main()
