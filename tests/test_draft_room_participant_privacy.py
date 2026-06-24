"""Tests for private vs shared draft room participant state."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from draft_room_context import create_and_host_shared_room, join_shared_draft_room, prepare_global_draft_context
from draft_room_participant_state import (
    ACTIVE_PARTICIPANT_ID_KEY,
    PARTICIPANT_STATE_KEY,
    load_participant_workflow_into_session,
    participant_workflow_slot,
    resolve_participant_id,
    save_participant_workflow_from_session,
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


if __name__ == "__main__":
    unittest.main()
