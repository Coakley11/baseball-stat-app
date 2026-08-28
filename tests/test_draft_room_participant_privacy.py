"""Tests for private vs shared draft room participant state."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from draft_room_context import create_and_host_shared_room, join_shared_draft_room, prepare_global_draft_context
from draft_room_participant_state import (
    ACTIVE_PARTICIPANT_ID_KEY,
    AUTH_WORKFLOW_USER_KEY,
    PARTICIPANT_STATE_KEY,
    load_participant_workflow_into_session,
    load_workflow_for_participant_id,
    on_auth_user_switch,
    participant_workflow_slot,
    reconcile_auth_scoped_draft_workflow,
    resolve_participant_id,
    save_participant_workflow_from_session,
    save_workflow_for_participant_id,
)
from draft_room_shared_state import (
    LocalFileSharedRoomStore,
    sanitize_shared_room_document,
    shared_room_document_private_leaks,
)
from draft_state import DRAFT_QUEUE_KEY, DRAFT_WATCHLIST_FOCUS_KEY
from suite_auth import AUTH_SESSION_KEY, AUTH_USER_ID_KEY


def _sample_live_room() -> dict:
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
        "config": {"num_teams": 2, "picks_per_team": 1, "your_team": "Team 1"},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team 1"}],
        "draft_board": [{"Pick": 1, "Round": 1, "Team": "Team 1", "Player": ""}],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


def _simulate_cloud_private_state_handoff(source: dict, target: dict) -> None:
    """Copy participant-private blobs the way workspace cloud sync would."""
    private = copy.deepcopy(source.get(PARTICIPANT_STATE_KEY) or {})
    if private:
        target[PARTICIPANT_STATE_KEY] = private
    for key in (
        "draft_room_participant_membership",
        "active_shared_draft_room_code",
        "draft_room_participant_team",
        "draft_room_participant_id",
    ):
        if key in source:
            target[key] = copy.deepcopy(source[key])


class DraftRoomParticipantPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_resolve_participant_id_prefers_auth_user_when_enabled(self) -> None:
        session = {
            ACTIVE_PARTICIPANT_ID_KEY: "legacy-id",
            AUTH_USER_ID_KEY: "auth-uuid-123",
            AUTH_SESSION_KEY: {"access_token": "x"},
        }
        with patch("suite_auth.is_auth_enabled", return_value=True):
            self.assertEqual(resolve_participant_id(session), "auth-uuid-123")

    def test_same_auth_account_two_devices_share_private_queue(self) -> None:
        shared_auth = "auth-same-user-uuid"
        device_a: dict = {ACTIVE_PARTICIPANT_ID_KEY: shared_auth, AUTH_USER_ID_KEY: shared_auth}
        device_b: dict = {ACTIVE_PARTICIPANT_ID_KEY: shared_auth, AUTH_USER_ID_KEY: shared_auth}

        room_code, _ = create_and_host_shared_room(device_a, _sample_live_room(), store=self.store)
        device_a[DRAFT_QUEUE_KEY] = ["Aaron Judge", "Juan Soto"]
        device_a[DRAFT_WATCHLIST_FOCUS_KEY] = ["Mike Trout"]
        save_participant_workflow_from_session(device_a, room_code)

        _simulate_cloud_private_state_handoff(device_a, device_b)
        load_participant_workflow_into_session(device_b, room_code)

        self.assertEqual(device_b.get(DRAFT_QUEUE_KEY), ["Aaron Judge", "Juan Soto"])
        self.assertEqual(device_b.get(DRAFT_WATCHLIST_FOCUS_KEY), ["Mike Trout"])
        slot = participant_workflow_slot(device_b, room_code)
        self.assertEqual(slot.get("participant_id"), shared_auth)

    def test_different_auth_accounts_isolated_in_same_room(self) -> None:
        host: dict = {ACTIVE_PARTICIPANT_ID_KEY: "auth-host-uuid", AUTH_USER_ID_KEY: "auth-host-uuid"}
        guest: dict = {ACTIVE_PARTICIPANT_ID_KEY: "auth-guest-uuid", AUTH_USER_ID_KEY: "auth-guest-uuid"}

        room_code, document = create_and_host_shared_room(host, _sample_live_room(), store=self.store)
        host[DRAFT_QUEUE_KEY] = ["Aaron Judge"]
        save_participant_workflow_from_session(host, room_code)

        join_shared_draft_room(guest, room_code, store=self.store)
        guest[DRAFT_QUEUE_KEY] = ["Juan Soto"]
        save_participant_workflow_from_session(guest, room_code)

        prepare_global_draft_context(host)
        prepare_global_draft_context(guest)
        self.assertEqual(host.get(DRAFT_QUEUE_KEY), ["Aaron Judge"])
        self.assertEqual(guest.get(DRAFT_QUEUE_KEY), ["Juan Soto"])

        room_private_host = host[PARTICIPANT_STATE_KEY][room_code]["by_participant"]
        room_private_guest = guest[PARTICIPANT_STATE_KEY][room_code]["by_participant"]
        self.assertIn("auth-host-uuid", room_private_host)
        self.assertIn("auth-guest-uuid", room_private_guest)
        self.assertEqual(room_private_host["auth-host-uuid"]["workflow"]["queue"], ["Aaron Judge"])
        self.assertEqual(room_private_guest["auth-guest-uuid"]["workflow"]["queue"], ["Juan Soto"])

    def test_shared_room_json_never_contains_private_queue_or_watchlist(self) -> None:
        session: dict = {
            ACTIVE_PARTICIPANT_ID_KEY: "auth-host-uuid",
            AUTH_USER_ID_KEY: "auth-host-uuid",
            DRAFT_QUEUE_KEY: ["Aaron Judge"],
            DRAFT_WATCHLIST_FOCUS_KEY: ["Juan Soto"],
        }
        room_code, document = create_and_host_shared_room(session, _sample_live_room(), store=self.store)
        save_participant_workflow_from_session(session, room_code)

        sanitized = sanitize_shared_room_document(document)
        leaks = shared_room_document_private_leaks(sanitized)
        self.assertEqual(leaks, [], f"private fields leaked: {leaks}")

        raw = json.dumps(sanitized)
        self.assertNotIn('"draft_queue"', raw)
        self.assertNotIn('"watchlist_focus"', raw)
        self.assertNotIn('"watchlist_favorites"', raw)
        self.assertNotIn('"by_participant"', raw)

    def test_load_participant_workflow_clears_inherited_host_queue(self) -> None:
        room_code = "ROOM01"
        guest_pid = "auth-guest-uuid"
        guest: dict = {
            ACTIVE_PARTICIPANT_ID_KEY: guest_pid,
            AUTH_USER_ID_KEY: guest_pid,
            DRAFT_QUEUE_KEY: ["Aaron Judge"],
            "active_shared_draft_room_code": room_code,
        }
        guest[PARTICIPANT_STATE_KEY] = {
            room_code: {
                "participant_id": "auth-host-uuid",
                "assigned_team": "Team 1",
                "workflow": {"queue": ["Aaron Judge"]},
                "by_participant": {},
            }
        }
        load_participant_workflow_into_session(guest, room_code)
        self.assertEqual(guest.get(DRAFT_QUEUE_KEY), [])

    def test_leave_shared_draft_room_clears_runtime_state(self) -> None:
        from draft_room_context import leave_shared_draft_room
        from draft_room_participant_state import ACTIVE_PARTICIPANT_ID_KEY, participant_has_left_room
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        session: dict = {
            "active_shared_draft_room_code": "ABC123",
            ACTIVE_PARTICIPANT_ID_KEY: "auth-guest-uuid",
            "draft_room_shared_meta": {"revision": 2},
            "draft_room_participant_team": "Team 2",
            "draft_room_participant_id": "auth-guest-uuid",
            LIVE_DRAFT_ROOM_KEY: {"status": "in_progress"},
            DRAFT_QUEUE_KEY: ["Juan Soto"],
        }
        leave_shared_draft_room(session)
        self.assertNotIn("active_shared_draft_room_code", session)
        self.assertNotIn(LIVE_DRAFT_ROOM_KEY, session)
        self.assertEqual(session.get(DRAFT_QUEUE_KEY), [])
        self.assertTrue(participant_has_left_room(session, "ABC123"))

    def test_restore_skips_room_user_explicitly_left(self) -> None:
        from draft_room_context import prepare_global_draft_context
        from draft_room_participant_state import mark_participant_left_room, restore_persisted_shared_room_membership

        session: dict = {
            AUTH_USER_ID_KEY: "auth-guest-uuid",
            "draft_room_participant_membership": {
                "ABC123": {
                    "auth-guest-uuid": {
                        "participant_id": "auth-guest-uuid",
                        "assigned_team": "Team 2",
                    }
                }
            },
        }
        mark_participant_left_room(session, "ABC123")
        self.assertEqual(restore_persisted_shared_room_membership(session), "")
        session["active_shared_draft_room_code"] = "ABC123"
        self.assertEqual(restore_persisted_shared_room_membership(session), "")
        prepare_global_draft_context(session)
        self.assertNotIn("active_shared_draft_room_code", session)

    def test_auth_account_switch_isolates_solo_queue(self) -> None:
        daniel_id = "auth-daniel-cohen11"
        ari_id = "auth-coakley11"
        session: dict = {
            AUTH_USER_ID_KEY: daniel_id,
            AUTH_WORKFLOW_USER_KEY: daniel_id,
            DRAFT_QUEUE_KEY: ["Aaron Judge", "Juan Soto"],
        }
        with patch("suite_auth.is_auth_enabled", return_value=True):
            on_auth_user_switch(session, from_user_id=daniel_id, to_user_id=ari_id)
            session[AUTH_USER_ID_KEY] = ari_id
            self.assertEqual(session.get(DRAFT_QUEUE_KEY), [])
            session[DRAFT_QUEUE_KEY] = ["Mike Trout"]
            save_workflow_for_participant_id(
                session,
                ari_id,
                {"queue": ["Mike Trout"], "watchlist_focus": [], "watchlist_favorites": []},
            )
            on_auth_user_switch(session, from_user_id=ari_id, to_user_id=daniel_id)
            session[AUTH_USER_ID_KEY] = daniel_id
            self.assertEqual(session.get(DRAFT_QUEUE_KEY), ["Aaron Judge", "Juan Soto"])

    def test_auth_switch_in_shared_room_keeps_separate_queues(self) -> None:
        daniel_id = "auth-daniel-cohen11"
        ari_id = "auth-coakley11"
        host: dict = {ACTIVE_PARTICIPANT_ID_KEY: daniel_id, AUTH_USER_ID_KEY: daniel_id}
        guest: dict = {ACTIVE_PARTICIPANT_ID_KEY: ari_id, AUTH_USER_ID_KEY: ari_id}

        room_code, _ = create_and_host_shared_room(host, _sample_live_room(), store=self.store)
        host[DRAFT_QUEUE_KEY] = ["Aaron Judge"]
        save_participant_workflow_from_session(host, room_code)

        join_shared_draft_room(guest, room_code, store=self.store)
        guest[DRAFT_QUEUE_KEY] = ["Juan Soto"]
        save_participant_workflow_from_session(guest, room_code)

        # Same Streamlit session retains room-private blobs for all participants.
        guest[PARTICIPANT_STATE_KEY] = copy.deepcopy(host.get(PARTICIPANT_STATE_KEY) or {})
        room_private = guest[PARTICIPANT_STATE_KEY][room_code]["by_participant"]
        room_private[ari_id] = copy.deepcopy(
            participant_workflow_slot(guest, room_code)
        )
        guest["active_shared_draft_room_code"] = room_code

        with patch("suite_auth.is_auth_enabled", return_value=True):
            on_auth_user_switch(guest, from_user_id=ari_id, to_user_id=daniel_id)
            guest[AUTH_USER_ID_KEY] = daniel_id
            load_participant_workflow_into_session(guest, room_code)
            self.assertEqual(guest.get(DRAFT_QUEUE_KEY), ["Aaron Judge"])

            on_auth_user_switch(guest, from_user_id=daniel_id, to_user_id=ari_id)
            guest[AUTH_USER_ID_KEY] = ari_id
            load_participant_workflow_into_session(guest, room_code)
            self.assertEqual(guest.get(DRAFT_QUEUE_KEY), ["Juan Soto"])

    def test_reconcile_auth_scoped_workflow_after_refresh(self) -> None:
        daniel_id = "auth-daniel-cohen11"
        ari_id = "auth-coakley11"
        session: dict = {
            AUTH_USER_ID_KEY: ari_id,
            AUTH_WORKFLOW_USER_KEY: daniel_id,
            DRAFT_QUEUE_KEY: ["Aaron Judge"],
        }
        save_workflow_for_participant_id(
            session,
            ari_id,
            {"queue": ["Mike Trout"], "watchlist_focus": [], "watchlist_favorites": []},
        )
        with patch("suite_auth.is_auth_enabled", return_value=True):
            self.assertTrue(reconcile_auth_scoped_draft_workflow(session))
            self.assertEqual(session.get(DRAFT_QUEUE_KEY), ["Mike Trout"])
            self.assertEqual(load_workflow_for_participant_id(session, daniel_id)["queue"], ["Aaron Judge"])


class TestParticipantIdEnvOverride(unittest.TestCase):
    def test_env_wins_when_auth_off_and_is_inert_when_unset(self) -> None:
        session = {ACTIVE_PARTICIPANT_ID_KEY: "stale-session"}
        with (
            patch("suite_auth.is_auth_enabled", return_value=False),
            patch.dict(os.environ, {"BASEBALL_PARTICIPANT_ID": "qa-guest"}, clear=False),
        ):
            self.assertEqual(resolve_participant_id(session), "qa-guest")
            self.assertEqual(session.get(ACTIVE_PARTICIPANT_ID_KEY), "qa-guest")

        leftover = {k: v for k, v in os.environ.items() if k != "BASEBALL_PARTICIPANT_ID"}
        session_unset = {ACTIVE_PARTICIPANT_ID_KEY: "session-id"}
        with (
            patch("suite_auth.is_auth_enabled", return_value=False),
            patch.dict(os.environ, leftover, clear=True),
        ):
            self.assertEqual(resolve_participant_id(session_unset), "session-id")

    def test_env_does_not_override_authenticated_user(self) -> None:
        session = {
            ACTIVE_PARTICIPANT_ID_KEY: "legacy-id",
            AUTH_USER_ID_KEY: "auth-uuid-123",
            AUTH_SESSION_KEY: {"access_token": "x"},
        }
        with (
            patch("suite_auth.is_auth_enabled", return_value=True),
            patch.dict(os.environ, {"BASEBALL_PARTICIPANT_ID": "qa-guest"}, clear=False),
        ):
            self.assertEqual(resolve_participant_id(session), "auth-uuid-123")


if __name__ == "__main__":
    unittest.main()
