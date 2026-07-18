"""P0: draft create must survive End/Delete flags; Shared mode must stick."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from live_draft_completion import (
    LIFECYCLE_ACTIVE_DRAFT,
    LIFECYCLE_SETUP,
    LIFECYCLE_WAITING_SHARED_LOBBY,
    resolve_live_draft_lifecycle,
)
from live_draft_setup_mode import (
    PREFERRED_NEXT_DRAFT_MODE_KEY,
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    commit_live_draft_mode_from_widget,
    get_preferred_next_draft_mode,
    is_shared_multiplayer_intent,
    persist_live_draft_setup_mode_preference,
    seed_live_draft_setup_mode_before_widget,
)
from live_draft_start_progress import (
    START_IN_FLIGHT_KEY,
    begin_live_draft_start,
    clear_post_delete_create_blocks,
    expire_stale_live_draft_start,
    finish_live_draft_start,
    is_live_draft_start_in_flight,
)
from live_draft_termination import reset_context_for_new_live_draft


def _room(*, status: str = "not_started", mode: str = SETUP_MODE_SHARED) -> dict:
    return {
        "draft_room_id": "CREATE1",
        "status": status,
        "current_pick_index": 0,
        "config": {
            "num_teams": 2,
            "picks_per_team": 4,
            "your_team": "Team A",
            "user_team": "Team A",
            "teams": ["Team A", "Team B"],
            "draft_setup_mode": mode,
        },
        "teams": ["Team A", "Team B"],
        "draft_board": [],
        "rosters": {"Team A": [], "Team B": []},
        "pool": pd.DataFrame([{"playerID": "p1", "fullName": "A", "Primary Position": "OF"}]),
    }


class PostDeleteCreateTests(unittest.TestCase):
    def test_force_setup_flag_cleared_on_new_create_context(self) -> None:
        session = {
            "_live_draft_deleting": "done",
            "_live_draft_force_setup_after_delete": True,
            "_live_draft_suppress_fragments": True,
        }
        reset_context_for_new_live_draft(session)
        self.assertNotIn("_live_draft_deleting", session)
        self.assertNotIn("_live_draft_force_setup_after_delete", session)
        session["live_draft_room"] = _room(status="in_progress", mode=SETUP_MODE_SOLO)
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_ACTIVE_DRAFT)

    def test_begin_start_clears_delete_blocks_before_create(self) -> None:
        session = {
            "_live_draft_deleting": "done",
            "_live_draft_force_setup_after_delete": True,
        }
        begin_live_draft_start(session, mode="prepare_shared")
        self.assertTrue(session.get(START_IN_FLIGHT_KEY))
        self.assertNotIn("_live_draft_force_setup_after_delete", session)
        session["live_draft_room"] = _room(status="not_started")
        session["active_shared_draft_room_code"] = "ABC123"
        finish_live_draft_start(session, ok=True)
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_WAITING_SHARED_LOBBY)

    def test_uncleared_force_setup_still_blocks_stale_room(self) -> None:
        session = {
            "_live_draft_force_setup_after_delete": True,
            "live_draft_room": _room(status="in_progress"),
            "active_shared_draft_room_code": "OLD123",
        }
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_SETUP)
        self.assertIsNone(session.get("live_draft_room"))


class SharedLobbyLifecycleTests(unittest.TestCase):
    def test_not_started_shared_uses_is_shared_key(self) -> None:
        session = {
            PREFERRED_NEXT_DRAFT_MODE_KEY: SETUP_MODE_SHARED,
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "live_draft_room": _room(status="not_started"),
            "active_shared_draft_room_code": "ZZ99AA",
        }
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_WAITING_SHARED_LOBBY)

    def test_orphan_solo_not_started_clears_to_setup(self) -> None:
        session = {
            "live_draft_setup_mode": SETUP_MODE_SOLO,
            "live_draft_room": _room(status="not_started", mode=SETUP_MODE_SOLO),
        }
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_SETUP)
        self.assertIsNone(session.get("live_draft_room"))


class ModeStickyTests(unittest.TestCase):
    def test_commit_radio_writes_preferred_next_and_page_snapshot(self) -> None:
        session: dict = {"auth_user_id": "u1", "workspace_id": "w1"}
        with mock.patch(
            "user_page_preferences.save_user_page_preferences", return_value=True
        ) as save:
            with mock.patch(
                "user_page_preferences.collect_live_draft_setup_settings",
                return_value={"live_draft_team_count": 2, "live_draft_picks_per_team": 4},
            ):
                commit_live_draft_mode_from_widget(session, SETUP_MODE_SHARED, st=object())
        self.assertEqual(session.get(PREFERRED_NEXT_DRAFT_MODE_KEY), SETUP_MODE_SHARED)
        self.assertEqual(get_preferred_next_draft_mode(session), SETUP_MODE_SHARED)
        block = (session.get("page_filter_state") or {}).get("Live Draft Room") or {}
        self.assertEqual(block.get(PREFERRED_NEXT_DRAFT_MODE_KEY), SETUP_MODE_SHARED)
        self.assertTrue(save.called)

    def test_page_restore_does_not_overwrite_shared_with_solo_snapshot(self) -> None:
        from live_draft_state import restore_live_draft_page_filters

        session = {
            PREFERRED_NEXT_DRAFT_MODE_KEY: SETUP_MODE_SHARED,
            "live_draft_setup_mode": SETUP_MODE_SHARED,
        }
        store = {
            "Live Draft Room": {
                "live_draft_setup_mode": SETUP_MODE_SOLO,
                "preferred_next_draft_mode": SETUP_MODE_SOLO,
                "live_draft_team_count": 2,
            }
        }
        restore_live_draft_page_filters(session, store)
        self.assertEqual(session.get(PREFERRED_NEXT_DRAFT_MODE_KEY), SETUP_MODE_SHARED)
        self.assertEqual(session.get("live_draft_setup_mode"), SETUP_MODE_SHARED)
        self.assertEqual(session.get("live_draft_team_count"), 2)

    def test_orphan_solo_room_does_not_hide_shared_intent(self) -> None:
        session = {
            PREFERRED_NEXT_DRAFT_MODE_KEY: SETUP_MODE_SHARED,
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "live_draft_room": _room(status="not_started", mode=SETUP_MODE_SOLO),
        }
        self.assertTrue(is_shared_multiplayer_intent(session))

    def test_failed_create_keeps_shared_preference(self) -> None:
        session = {
            PREFERRED_NEXT_DRAFT_MODE_KEY: SETUP_MODE_SHARED,
            "live_draft_setup_mode": SETUP_MODE_SHARED,
        }
        # Simulate failure cleanup without mode rewrite.
        clear_post_delete_create_blocks(session)
        finish_live_draft_start(session, ok=False, error="pool failed")
        self.assertEqual(get_preferred_next_draft_mode(session), SETUP_MODE_SHARED)

    def test_seed_uses_preferred_next_not_solo_default_when_prefs_shared(self) -> None:
        session: dict = {}
        with mock.patch(
            "live_draft_setup_mode.get_preferred_next_draft_mode",
            return_value=SETUP_MODE_SHARED,
        ):
            seeded = seed_live_draft_setup_mode_before_widget(session)
        self.assertEqual(seeded, SETUP_MODE_SHARED)
        self.assertEqual(session.get("live_draft_setup_mode"), SETUP_MODE_SHARED)


class StartTimeoutTests(unittest.TestCase):
    def test_stale_in_flight_expires(self) -> None:
        import time

        session: dict = {}
        begin_live_draft_start(session, mode="new")
        session["_live_draft_start_mono_t0"] = time.monotonic() - 120.0
        self.assertTrue(expire_stale_live_draft_start(session))
        self.assertFalse(is_live_draft_start_in_flight(session))
        self.assertIn("_live_draft_start_error", session)


class SharedCreateKeepsModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        from draft_room_shared_state import LocalFileSharedRoomStore

        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self._patch = mock.patch(
            "draft_room_shared_state.get_shared_room_store", return_value=self.store
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_create_after_delete_flags_reaches_lobby(self, _auth: object) -> None:
        from live_draft_setup_mode import finalize_shared_room_create

        session = {
            "_live_draft_deleting": "done",
            "_live_draft_force_setup_after_delete": True,
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            PREFERRED_NEXT_DRAFT_MODE_KEY: SETUP_MODE_SHARED,
            "draft_room_participant_id": "host-user",
            "auth_user_id": "host-user",
        }
        begin_live_draft_start(session, mode="prepare_shared")
        reset_context_for_new_live_draft(session)
        room = _room(status="not_started")
        code, err = finalize_shared_room_create(session, room, host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        self.assertTrue(code)
        finish_live_draft_start(session, ok=True)
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_WAITING_SHARED_LOBBY)
        self.assertEqual(get_preferred_next_draft_mode(session), SETUP_MODE_SHARED)


if __name__ == "__main__":
    unittest.main()
