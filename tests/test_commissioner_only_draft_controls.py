"""Commissioner-only Save / Continue / Delete — exact participant id check."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_shared_state import LocalFileSharedRoomStore, reset_shared_room_store_for_tests
from live_draft_resumable_slot import (
    RESUMABLE_LIVE_DRAFT_SLOT_KEY,
    continue_saved_draft,
    save_and_continue_later,
)
from live_draft_setup_mode import (
    LIVE_DRAFT_SETUP_MODE_KEY,
    SETUP_MODE_SHARED,
    finalize_shared_room_create,
    set_live_draft_setup_mode,
)
from shared_draft_permissions import (
    can_continue_saved_draft_slot,
    is_canonical_commissioner,
    session_may_use_commissioner_draft_controls,
)
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY


def _room() -> dict:
    return {
        "draft_room_id": "COMM1",
        "status": "in_progress",
        "current_pick_index": 1,
        "config": {
            "num_teams": 2,
            "num_rounds": 10,
            "your_team": "Team A",
            "teams": ["Team A", "Team B"],
            "draft_setup_mode": SETUP_MODE_SHARED,
            "timer_seconds": 60,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": i + 1, "Round": 1, "Team": "Team A" if i % 2 == 0 else "Team B"}
            for i in range(20)
        ],
        "draft_board": [{"Pick": 1, "Team": "Team A", "fullName": "P1", "playerID": "p1"}],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": ["p1"],
        "pool": pd.DataFrame(
            [{"playerID": "p1", "fullName": "P1", "Primary Position": "OF"}]
        ),
    }


def _daniel() -> dict:
    return {
        AUTH_USER_ID_KEY: "uuid-daniel",
        AUTH_EXTERNAL_ID_KEY: "daniel",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "daniel",
        "draft_room_participant_id": "uuid-daniel",
        LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED,
    }


def _coakley() -> dict:
    return {
        AUTH_USER_ID_KEY: "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        AUTH_EXTERNAL_ID_KEY: "coakley11",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "coakley11",
        "draft_room_participant_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED,
    }


class CommissionerOnlyControlsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
        self._auth.start()

    def tearDown(self) -> None:
        self._auth.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_daniel_is_commissioner_coakley_is_not(self) -> None:
        host = _daniel()
        guest = _coakley()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _room()
        code, err = finalize_shared_room_create(host, room, host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        from draft_room_shared_state import load_shared_room

        doc = load_shared_room(code)
        self.assertTrue(is_canonical_commissioner(host, doc))
        self.assertFalse(is_canonical_commissioner(guest, doc))
        host["active_shared_draft_room_code"] = code
        host["live_draft_room"] = room
        guest["active_shared_draft_room_code"] = code
        guest["live_draft_room"] = dict(room)
        self.assertTrue(session_may_use_commissioner_draft_controls(host, document=doc))
        self.assertFalse(session_may_use_commissioner_draft_controls(guest, document=doc))

    def test_guest_cannot_save_or_continue(self) -> None:
        host = _daniel()
        guest = _coakley()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _room()
        code, err = finalize_shared_room_create(host, room, host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        host["live_draft_room"] = room
        host["active_shared_draft_room_code"] = code

        guest["live_draft_room"] = dict(room)
        guest["active_shared_draft_room_code"] = code
        blocked_save = save_and_continue_later(guest, st=None, replace_existing=True)
        self.assertFalse(blocked_save.get("ok"))
        self.assertEqual(blocked_save.get("error"), "not_commissioner")

        saved = save_and_continue_later(host, st=None, replace_existing=True)
        self.assertTrue(saved.get("ok"), saved)

        guest[RESUMABLE_LIVE_DRAFT_SLOT_KEY] = dict(host[RESUMABLE_LIVE_DRAFT_SLOT_KEY])
        self.assertFalse(can_continue_saved_draft_slot(guest))
        blocked_cont = continue_saved_draft(guest, st=None)
        self.assertFalse(blocked_cont.get("ok"))
        self.assertEqual(blocked_cont.get("error"), "not_commissioner")

        self.assertTrue(can_continue_saved_draft_slot(host))
        cont = continue_saved_draft(host, st=None)
        self.assertTrue(cont.get("ok"), cont)
        self.assertEqual(str(host.get("active_shared_draft_room_code") or "").upper(), code)

    def test_team_a_alone_does_not_grant_commissioner(self) -> None:
        guest = _coakley()
        doc = {
            "commissioner_participant_id": "uuid-daniel",
            "host_participant_id": "uuid-daniel",
        }
        guest["draft_room_participant_team"] = "Team A"
        guest["draft_room_participant_id"] = "961df5e9-cdde-48d7-80dd-95a8ba3f46e5"
        self.assertFalse(is_canonical_commissioner(guest, doc))


if __name__ == "__main__":
    unittest.main()
