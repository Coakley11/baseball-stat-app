"""Host lobby must apply guest Team B claims and count required human seats."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import (
    join_shared_draft_room,
    poll_shared_draft_room,
    refresh_shared_lobby_authority,
    reset_shared_draft_sync_gate,
)
from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    SHARED_ROOM_META_KEY,
    LocalFileSharedRoomStore,
    reset_shared_room_store_for_tests,
)
from live_draft_presence import (
    JOINED_PARTICIPANTS_KEY,
    count_required_joined,
    format_participant_status_line,
    required_human_participant_rows,
)
from live_draft_setup_mode import SETUP_MODE_SHARED, can_start_live_draft, set_live_draft_setup_mode
from live_draft_setup_mode import finalize_shared_room_create
from live_draft_team_ownership import (
    list_available_shared_room_teams,
    list_required_human_teams,
    team_claim_rows,
)
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY


def _sample_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF"},
        ]
    )
    return {
        "draft_room_id": "LOBBY1",
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
        "participant_display_name": "daniel.cohen11",
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
        "participant_display_name": "coakley11",
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


class LobbyParticipantSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._patches = [
            mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False),
            mock.patch("suite_auth.is_auth_enabled", return_value=True),
            mock.patch("suite_auth.is_authenticated", return_value=True),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_required_denominator_is_configured_teams_not_visible_participants(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        doc = self.store.load(code)
        assert isinstance(doc, dict)
        room = host["live_draft_room"]
        joined, total, rows = count_required_joined(host, room, document=doc)
        self.assertEqual(total, 2)
        self.assertEqual(joined, 1)
        labels = [format_participant_status_line(r) for r in rows]
        self.assertTrue(any("Team A" in x and "Joined" in x for x in labels))
        self.assertTrue(any(x == "Team B — Waiting" for x in labels))
        self.assertEqual(list_required_human_teams(room, document=doc), ["Team A", "Team B"])

    def test_duplicate_host_aliases_do_not_change_denominator_or_take_team_b(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        doc = self.store.load(code)
        assert isinstance(doc, dict)
        parts = dict(doc.get("participants") or {})
        parts["cloud-daniel-alias"] = {
            "assigned_team": "Team B",
            "display_name": "Daniel",
            "user_id": "uuid-daniel",
        }
        doc["host_user_id"] = "cloud-daniel-alias"
        doc["participants"] = parts
        self.store.save(doc)
        doc = self.store.load(code)
        assert isinstance(doc, dict)
        available, diag = list_available_shared_room_teams(doc, "guest")
        self.assertEqual(available, ["Team B"], diag)
        joined, total, rows = count_required_joined(host, host["live_draft_room"], document=doc)
        self.assertEqual(total, 2)
        self.assertEqual(joined, 1)
        self.assertTrue(any(r.get("waiting") and r.get("team_name") == "Team B" for r in rows))

    def test_host_poll_discards_stale_revision_and_shows_coakley_team_b(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(host, _sample_room(), host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        doc = self.store.load(code)
        assert isinstance(doc, dict)
        create_rev = int(doc.get("revision") or 0)
        self.assertGreaterEqual(create_rev, 1)

        joined, total, _ = count_required_joined(host, host["live_draft_room"], document=doc)
        self.assertEqual((joined, total), (1, 2))

        # Host is stuck on the create-time revision while guest claims Team B.
        host[SHARED_ROOM_META_KEY] = {
            "room_code": code,
            "revision": create_rev,
            "draft_room_id": "LOBBY1",
        }
        host[ACTIVE_SHARED_ROOM_CODE_KEY] = code

        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)
        guest_doc = self.store.load(code)
        assert isinstance(guest_doc, dict)
        guest_rev = int(guest_doc.get("revision") or 0)
        self.assertGreater(guest_rev, create_rev)
        parts = dict(guest_doc.get("participants") or {})
        guest_pid = "961df5e9-cdde-48d7-80dd-95a8ba3f46e5"
        self.assertEqual(str((parts.get(guest_pid) or {}).get("assigned_team") or ""), "Team B")
        self.assertIn(guest_pid, dict(guest_doc.get(JOINED_PARTICIPANTS_KEY) or {}) | parts)

        # Daniel still thinks create_rev until poll.
        self.assertEqual(int((host.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0), create_rev)
        reset_shared_draft_sync_gate(host)
        changed = poll_shared_draft_room(host, force=False, store=self.store)
        self.assertTrue(changed)
        self.assertGreaterEqual(int((host.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0), guest_rev)

        authority = refresh_shared_lobby_authority(host, store=self.store, force_poll=True)
        assert isinstance(authority, dict)
        rows = team_claim_rows(host, host.get("live_draft_room") or {}, document=authority)
        claimed = {r["team"]: r for r in rows if r.get("claimed")}
        self.assertIn("Team A", claimed)
        self.assertIn("Team B", claimed)
        self.assertFalse(claimed["Team B"].get("is_host"))

        joined2, total2, prow = count_required_joined(
            host, host.get("live_draft_room") or {}, document=authority
        )
        self.assertEqual((joined2, total2), (2, 2))
        labels = [format_participant_status_line(r) for r in prow]
        self.assertTrue(any("Team B" in x and "Joined" in x for x in labels))
        self.assertFalse(any(x == "Team B — Waiting" for x in labels))

        ok_start, reason = can_start_live_draft(host)
        self.assertTrue(ok_start, reason)


if __name__ == "__main__":
    unittest.main()
