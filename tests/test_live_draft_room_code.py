"""Room code resolution, display, and multiplayer create flow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import create_and_host_shared_room, join_shared_draft_room, resolve_shared_room_code
from draft_room_create_verify import is_plausible_share_code
from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, SHARED_ROOM_META_KEY, LocalFileSharedRoomStore
from live_draft_room_ui import render_live_draft_room_code_header


def _sample_live_room() -> dict:
    pool = pd.DataFrame(
        [{"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"}]
    )
    return {
        "draft_room_id": "MULTI1",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "your_team": "Team 1", "timer_seconds": 60},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team 1"},
            {"Pick": 2, "Round": 1, "Team": "Team 2"},
        ],
        "draft_board": [],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


class ResolveSharedRoomCodeTests(unittest.TestCase):
    def test_active_key(self) -> None:
        session = {ACTIVE_SHARED_ROOM_CODE_KEY: "abc123"}
        self.assertEqual(resolve_shared_room_code(session), "ABC123")

    def test_meta_fallback_restores_active_key(self) -> None:
        session = {SHARED_ROOM_META_KEY: {"room_code": "XYZ789"}}
        self.assertEqual(resolve_shared_room_code(session), "XYZ789")
        self.assertEqual(session[ACTIVE_SHARED_ROOM_CODE_KEY], "XYZ789")

    def test_rejects_internal_session_id(self) -> None:
        session = {ACTIVE_SHARED_ROOM_CODE_KEY: "AB12CD34"}
        self.assertEqual(resolve_shared_room_code(session), "")


class SharedRoomCreateCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host = {"draft_room_participant_id": "host-user", "room_your_team": "Team 1"}
        self._patch = mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_create_produces_six_char_code(self, _auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host, _sample_live_room(), store=self.store)
        self.assertEqual(len(code), 6)
        self.assertTrue(is_plausible_share_code(code))
        self.assertEqual(resolve_shared_room_code(self.host), code)

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_code_survives_meta_only_session(self, _auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host, _sample_live_room(), store=self.store)
        refreshed = {SHARED_ROOM_META_KEY: {"room_code": code}}
        self.assertEqual(resolve_shared_room_code(refreshed), code)

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_guest_joins_with_host_code(self, _auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host, _sample_live_room(), store=self.store)
        guest = {"draft_room_participant_id": "guest-user"}
        ok, msg, _ = join_shared_draft_room(guest, code, store=self.store)
        self.assertTrue(ok, msg)
        self.assertEqual(resolve_shared_room_code(guest), code)


class RoomCodeHeaderUiTests(unittest.TestCase):
    def test_missing_code_shows_warning(self) -> None:
        st = mock.MagicMock()
        session = {ACTIVE_SHARED_ROOM_CODE_KEY: ""}
        render_live_draft_room_code_header(st, session, multiplayer=True)
        st.warning.assert_called_once()
        warning_text = str(st.warning.call_args)
        self.assertIn("Room code missing", warning_text)

    def test_code_renders_panel(self) -> None:
        st = mock.MagicMock()
        session = {ACTIVE_SHARED_ROOM_CODE_KEY: "ABC123"}
        render_live_draft_room_code_header(st, session, multiplayer=True)
        st.warning.assert_not_called()
        html = " ".join(str(c) for c in st.markdown.call_args_list)
        self.assertIn("ABC123", html)


if __name__ == "__main__":
    unittest.main()
