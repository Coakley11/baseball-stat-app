"""Live Draft setup mode — solo vs shared multiplayer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import create_and_host_shared_room, join_shared_draft_room
from draft_room_create_verify import is_plausible_share_code
from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, LIVE_DRAFT_ROOM_KEY, LocalFileSharedRoomStore
from live_draft_setup_mode import (
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    can_start_live_draft,
    finalize_shared_room_create,
    get_live_draft_setup_mode,
    is_solo_draft_mode,
    set_live_draft_setup_mode,
    shared_room_code,
    shared_room_ready_for_start,
    stamp_room_setup_mode,
)
from live_draft_setup_ui import start_button_disabled


def _sample_room(**overrides) -> dict:
    pool = pd.DataFrame([{"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"}])
    room = {
        "draft_room_id": "MODE1",
        "status": "not_started",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "your_team": "Danny", "user_team": "Danny", "teams": ["Danny", "Amiel"]},
        "teams": ["Danny", "Amiel"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Danny"},
            {"Pick": 2, "Round": 1, "Team": "Amiel"},
        ],
        "draft_board": [],
        "rosters": {"Danny": [], "Amiel": []},
        "drafted_player_ids": [],
        "pool": pool,
    }
    room.update(overrides)
    return room


class SetupModeTests(unittest.TestCase):
    def test_solo_mode_default(self) -> None:
        session: dict = {}
        self.assertEqual(get_live_draft_setup_mode(session), SETUP_MODE_SOLO)
        self.assertTrue(is_solo_draft_mode(session))

    def test_multi_team_solo_has_no_room_code(self) -> None:
        session = {"live_draft_setup_mode": SETUP_MODE_SOLO, "live_draft_room": _sample_room(status="in_progress")}
        self.assertEqual(shared_room_code(session), "")
        ok, _ = can_start_live_draft(session)
        self.assertTrue(ok)

    def test_shared_requires_room_code_before_start(self) -> None:
        session = {"live_draft_setup_mode": SETUP_MODE_SHARED}
        ok, reason = can_start_live_draft(session)
        self.assertFalse(ok)
        self.assertIn("room code", reason.lower())
        disabled, help_text = start_button_disabled(session)
        self.assertTrue(disabled)

    def test_shared_ready_when_code_and_room_exist(self) -> None:
        session = {
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            ACTIVE_SHARED_ROOM_CODE_KEY: "ABC123",
            "live_draft_room": _sample_room(),
        }
        self.assertTrue(shared_room_ready_for_start(session))
        ok, _ = can_start_live_draft(session)
        self.assertTrue(ok)


class SharedRoomCreateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host = {"draft_room_participant_id": "host-user", "room_your_team": "Danny"}
        self._patch = mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_prepare_shared_generates_six_char_code(self, _auth: object) -> None:
        session = {LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED}
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED)
        room = _sample_room()
        code, err = finalize_shared_room_create(session, room, host_team="Danny")
        self.assertFalse(err, err)
        self.assertEqual(len(code), 6)
        self.assertTrue(is_plausible_share_code(code))
        self.assertEqual(str(room.get("status")), "not_started")

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_guest_joins_with_displayed_code(self, _auth: object) -> None:
        session = {LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED}
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED)
        room = _sample_room()
        code, _ = finalize_shared_room_create(session, room, host_team="Danny", store=self.store)
        guest = {"draft_room_participant_id": "guest-user"}
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Amiel", store=self.store)
        self.assertTrue(ok, msg)
        self.assertEqual(shared_room_code(guest), code)

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_create_failure_does_not_activate_code(self, _auth: object) -> None:
        session = {LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED}
        room = _sample_room()
        with mock.patch("draft_room_context.create_and_host_shared_room", return_value=("", {})):
            code, err = finalize_shared_room_create(session, room, host_team="Danny")
        self.assertEqual(code, "")
        self.assertIn("Could not create shared room", err)
        self.assertEqual(shared_room_code(session), "")


class RoomConfigStampTests(unittest.TestCase):
    def test_stamp_persists_mode_on_room(self) -> None:
        session = {"live_draft_setup_mode": SETUP_MODE_SOLO}
        room = _sample_room()
        stamp_room_setup_mode(room, session)
        self.assertEqual(room["config"]["draft_setup_mode"], SETUP_MODE_SOLO)


# re-export key used in tests
from live_draft_setup_mode import LIVE_DRAFT_SETUP_MODE_KEY  # noqa: E402


if __name__ == "__main__":
    unittest.main()
