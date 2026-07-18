"""Host lobby and guest join must share one room identity / team / claim source."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import get_global_draft_context, join_shared_draft_room
from draft_room_membership import is_room_host
from draft_room_shared_state import LocalFileSharedRoomStore, reset_shared_room_store_for_tests
from live_draft_presence import canonical_participant_user_id, mark_participant_present
from live_draft_setup_mode import SETUP_MODE_SHARED, finalize_shared_room_create, set_live_draft_setup_mode
from live_draft_team_ownership import (
    format_team_claim_status,
    list_document_teams,
    lookup_open_teams_for_code,
    open_teams_for_join,
    team_claim_rows,
)
from live_draft_ux import format_participant_identity
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY


def _sample_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF"},
        ]
    )
    return {
        "draft_room_id": "SYNC1",
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


def _daniel() -> dict:
    return {
        AUTH_USER_ID_KEY: "uuid-daniel",
        AUTH_EXTERNAL_ID_KEY: "daniel",
        "_suite_cloud_user_id": "cloud-daniel-alias",
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
        "_suite_cloud_user_id": "cloud-coakley-alias",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "coakley11",
        "_suite_owned_workspace_id": "coakley11",
        "draft_room_participant_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


class RoomSyncConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
        self._auth.start()
        self._auth_enabled = mock.patch("suite_auth.is_auth_enabled", return_value=True)
        self._auth_enabled.start()
        self._authenticated = mock.patch("suite_auth.is_authenticated", return_value=True)
        self._authenticated.start()

    def tearDown(self) -> None:
        self._authenticated.stop()
        self._auth_enabled.stop()
        self._auth.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_commissioner_not_guest_when_host_aliases_differ(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        doc = self.store.load(code)
        assert isinstance(doc, dict)
        # Simulate create-time host_user_id diverging from participant map key.
        doc["host_user_id"] = "cloud-daniel-alias"
        doc["host_participant_id"] = "uuid-daniel"
        self.store.save(doc)

        self.assertTrue(is_room_host(host, doc))
        ctx = get_global_draft_context(host)
        self.assertTrue(ctx.get("is_room_host"))
        rows = team_claim_rows(host, host["live_draft_room"], document=doc)
        host_row = next(r for r in rows if r["team"] == "Team A")
        self.assertTrue(host_row.get("is_host"))
        line = format_team_claim_status(host, host_row)
        self.assertIn("Commissioner", line)
        self.assertNotIn("Guest", line)

    def test_presence_does_not_double_claim_via_cloud_alias(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        # Presence previously used _suite_cloud_user_id and registered a second seat.
        self.assertEqual(canonical_participant_user_id(host), "uuid-daniel")
        mark_participant_present(host, force_save=True, store=self.store)
        doc = self.store.load(code)
        assert isinstance(doc, dict)
        participants = dict(doc.get("participants") or {})
        claimed_teams = {
            str(v.get("assigned_team") or "")
            for v in participants.values()
            if isinstance(v, dict) and v.get("assigned_team")
        }
        self.assertEqual(claimed_teams, {"Team A"})
        open_teams = open_teams_for_join(doc)
        self.assertEqual(open_teams, ["Team B"])

        guest = _coakley()
        teams, lookup_err = lookup_open_teams_for_code(code, store=self.store)
        self.assertFalse(lookup_err, lookup_err)
        self.assertEqual(teams, ["Team B"])
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)

        # Host refresh sees the same revision / claims as guest.
        host_doc = self.store.load(code)
        guest_doc = self.store.load(code)
        assert isinstance(host_doc, dict) and isinstance(guest_doc, dict)
        self.assertEqual(host_doc.get("revision"), guest_doc.get("revision"))
        self.assertEqual(host_doc.get("draft_room_id"), guest_doc.get("draft_room_id"))
        host_rows = team_claim_rows(host, host.get("live_draft_room") or {}, document=host_doc)
        claimed = {r["team"]: r for r in host_rows if r.get("claimed")}
        self.assertIn("Team A", claimed)
        self.assertIn("Team B", claimed)
        self.assertTrue(claimed["Team A"].get("is_host"))
        self.assertFalse(claimed["Team B"].get("is_host"))

    def test_empty_document_teams_still_recover_from_pick_order(self) -> None:
        doc = {
            "room_code": "ABCDEF",
            "status": "not_started",
            "revision": 1,
            "host_participant_id": "uuid-daniel",
            "participants": {
                "uuid-daniel": {"assigned_team": "Team A", "display_name": "Daniel"},
            },
            "room": {
                "draft_room_id": "SYNC2",
                "status": "not_started",
                "teams": [],
                "config": {"num_teams": 2},
                "pick_order": [
                    {"Pick": 1, "Team": "Team A"},
                    {"Pick": 2, "Team": "Team B"},
                ],
            },
        }
        self.assertEqual(list_document_teams(doc), ["Team A", "Team B"])
        self.assertEqual(open_teams_for_join(doc), ["Team B"])

    def test_format_commissioner_identity(self) -> None:
        text = format_participant_identity("You", role="Commissioner", team="Team A")
        self.assertEqual(text, "You (Commissioner) — Team A")


if __name__ == "__main__":
    unittest.main()
