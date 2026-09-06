"""Guest Join must leave Solo/setup routing and enter Shared lobby on next resolve."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from draft_room_context import (
    establish_shared_room_route_after_join,
    join_shared_draft_room,
)
from draft_room_participant_state import ACTIVE_PARTICIPANT_TEAM_KEY
from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    LocalFileSharedRoomStore,
    reset_shared_room_store_for_tests,
)
from live_draft_completion import LIFECYCLE_SETUP, LIFECYCLE_WAITING_SHARED_LOBBY, resolve_live_draft_lifecycle
from live_draft_setup_mode import (
    LIVE_DRAFT_SETUP_MODE_KEY,
    PREFERRED_NEXT_DRAFT_MODE_KEY,
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    finalize_shared_room_create,
    is_shared_lobby,
    set_live_draft_setup_mode,
)
from live_draft_setup_ui import render_guest_join_from_setup
from live_draft_state import LIVE_DRAFT_ROOM_KEY
from suite_auth import AUTH_USER_ID_KEY


def _sample_room(teams: list[str] | None = None) -> dict:
    team_list = teams or ["Team A", "Team B"]
    return {
        "draft_room_id": "JOINROUTE1",
        "status": "not_started",
        "teams": list(team_list),
        "config": {
            "teams": list(team_list),
            "picks_per_team": 2,
            "draft_type": "Snake",
        },
        "pick_order": [],
        "draft_board": [],
        "current_pick_index": 0,
        "pool": None,
    }


class GuestJoinRouteAfterJoinTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._patches = [
            mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_shared_state.get_local_shared_room_store", return_value=self.store),
            mock.patch("draft_room_shared_state.shared_room_backend_name", return_value="local_file"),
            mock.patch("draft_room_context.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_context.shared_room_backend_name", return_value="local_file"),
            mock.patch("baseball_persistent_state.force_save_baseball_state", return_value=None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def _seed_host(self) -> tuple[str, dict]:
        host = {
            "draft_room_participant_id": "workspace:daniel",
            AUTH_USER_ID_KEY: "local:daniel",
            "_suite_active_workspace_id": "daniel",
        }
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        code, err = finalize_shared_room_create(
            host, _sample_room(), host_team="Team A", store=self.store
        )
        self.assertFalse(err, err)
        self.assertTrue(code)
        return code, host

    def test_successful_guest_join_resolves_shared_lobby_not_setup(self) -> None:
        code, _host = self._seed_host()
        guest: dict = {
            "draft_room_participant_id": "workspace:guest",
            AUTH_USER_ID_KEY: "local:guest",
            "_suite_active_workspace_id": "guest",
            LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SOLO,
            PREFERRED_NEXT_DRAFT_MODE_KEY: SETUP_MODE_SOLO,
            "_live_draft_force_setup_after_delete": True,
            "_live_draft_deleting": "done",
            "page_filter_state": {
                "Live Draft Room": {
                    LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SOLO,
                    "live_draft_join_code_input": "",
                }
            },
            "_join_shared_draft_from_setup": True,
            "_join_requested_code": code,
            "_join_requested_team": "Team B",
        }
        import streamlit as st

        with mock.patch.object(st, "session_state", guest):
            need_rerun = render_guest_join_from_setup(st, guest)
        self.assertTrue(need_rerun)
        self.assertEqual(guest.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        self.assertTrue(isinstance(guest.get(LIVE_DRAFT_ROOM_KEY), dict))
        self.assertEqual(guest.get("draft_room_participant_team"), "Team B")
        # Multiplayer prepare_global_draft_context intentionally clears room_your_team;
        # participant team + active room code are the join identity.
        self.assertNotIn("_live_draft_force_setup_after_delete", guest)
        self.assertNotEqual(str(guest.get("_live_draft_deleting") or "").lower(), "done")
        # Shared mode must control next route (widget-safe pending or direct).
        mode = guest.get(LIVE_DRAFT_SETUP_MODE_KEY) or guest.get(PREFERRED_NEXT_DRAFT_MODE_KEY)
        self.assertEqual(mode, SETUP_MODE_SHARED)
        self.assertTrue(is_shared_lobby(guest))
        self.assertEqual(
            resolve_live_draft_lifecycle(guest),
            LIFECYCLE_WAITING_SHARED_LOBBY,
        )
        # Stale Solo page_filter mode must not keep lifecycle on setup.
        self.assertNotEqual(resolve_live_draft_lifecycle(guest), LIFECYCLE_SETUP)

    def test_existing_member_rejoin_does_not_duplicate_membership(self) -> None:
        code, _host = self._seed_host()
        guest = {
            "draft_room_participant_id": "workspace:guest",
            AUTH_USER_ID_KEY: "local:guest",
            "_suite_active_workspace_id": "guest",
        }
        ok1, msg1, doc1 = join_shared_draft_room(
            guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok1, msg1)
        parts1 = dict((doc1 or {}).get("participants") or {})
        self.assertIn("workspace:guest", parts1)
        ok2, msg2, doc2 = join_shared_draft_room(
            guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok2, msg2)
        self.assertIn("already joined", msg2.lower())
        parts2 = dict((doc2 or {}).get("participants") or {})
        self.assertEqual(len(parts2), len(parts1))
        self.assertEqual(
            resolve_live_draft_lifecycle(guest),
            LIFECYCLE_WAITING_SHARED_LOBBY,
        )

    def test_failed_join_stays_on_setup(self) -> None:
        guest: dict = {
            "draft_room_participant_id": "workspace:guest",
            AUTH_USER_ID_KEY: "local:guest",
            LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED,
            "_join_shared_draft_from_setup": True,
            "_join_requested_code": "ZZZZZZ",
            "_join_requested_team": "Team B",
        }
        import streamlit as st

        with mock.patch.object(st, "session_state", guest):
            need_rerun = render_guest_join_from_setup(st, guest)
        self.assertFalse(need_rerun)
        self.assertTrue(guest.get("_draft_join_error"))
        self.assertFalse(guest.get(ACTIVE_SHARED_ROOM_CODE_KEY))
        self.assertEqual(resolve_live_draft_lifecycle(guest), LIFECYCLE_SETUP)

    def test_establish_route_helper_clears_force_setup(self) -> None:
        session = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "ABC123",
            LIVE_DRAFT_ROOM_KEY: {
                "draft_room_id": "X",
                "status": "not_started",
                "room_code": "ABC123",
                "config": {"room_code": "ABC123", "draft_setup_mode": SETUP_MODE_SHARED},
            },
            "draft_room_participant_team": "Team B",
            "_live_draft_force_setup_after_delete": True,
            "_live_draft_deleting": "done",
            LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SOLO,
        }
        contract = establish_shared_room_route_after_join(session)
        self.assertTrue(contract.get("ok"))
        self.assertNotIn("_live_draft_force_setup_after_delete", session)
        self.assertEqual(session.get(ACTIVE_PARTICIPANT_TEAM_KEY) or session.get("draft_room_participant_team"), "Team B")
        self.assertEqual(
            session.get(PREFERRED_NEXT_DRAFT_MODE_KEY) or session.get(LIVE_DRAFT_SETUP_MODE_KEY),
            SETUP_MODE_SHARED,
        )

    def test_host_create_still_enters_shared_lobby(self) -> None:
        code, host = self._seed_host()
        self.assertEqual(host.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        self.assertTrue(is_shared_lobby(host))
        self.assertEqual(resolve_live_draft_lifecycle(host), LIFECYCLE_WAITING_SHARED_LOBBY)


if __name__ == "__main__":
    unittest.main()
