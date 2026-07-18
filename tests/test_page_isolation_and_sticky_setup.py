"""Cross-page isolation + sticky Live Draft setup preferences."""

from __future__ import annotations

import unittest

from app_page_generation import (
    ACTIVE_PAGE_GENERATION_KEY,
    ACTIVE_PAGE_NAME_KEY,
    PAGE_RENDERER_COUNT_KEY,
    begin_page_run,
    fragment_allowed,
    note_page_renderer,
)
from live_draft_setup_ui import should_render_shared_room_created_card
from live_draft_termination import discard_live_draft_and_start_over
from user_page_preferences import (
    PAGE_KEY_LIVE_DRAFT_SETUP,
    collect_live_draft_setup_settings,
    ensure_live_draft_setup_preferences_loaded,
    get_user_page_preferences,
    live_draft_setup_number_default,
    save_user_page_preferences,
)


class PageGenerationGatingTests(unittest.TestCase):
    def test_begin_page_run_bumps_generation_on_change(self) -> None:
        session: dict = {}
        snap1 = begin_page_run(session, "Live Draft Room")
        self.assertEqual(snap1["page"], "Live Draft Room")
        gen1 = int(session[ACTIVE_PAGE_GENERATION_KEY])
        snap2 = begin_page_run(session, "Historical Explorer")
        self.assertEqual(snap2["page"], "Historical Explorer")
        self.assertGreater(int(session[ACTIVE_PAGE_GENERATION_KEY]), gen1)
        self.assertFalse(fragment_allowed(session, expected_page="Live Draft Room"))
        self.assertTrue(fragment_allowed(session, expected_page="Historical Explorer"))

    def test_note_page_renderer_detects_cross_page_historical_leak(self) -> None:
        session: dict = {}
        begin_page_run(session, "Live Draft Room")
        note_page_renderer(session, "render_historical_explorer", selected_page="Live Draft Room")
        self.assertIn("_cross_page_render_leak", session)
        self.assertEqual(int(session.get(PAGE_RENDERER_COUNT_KEY) or 0), 1)

    def test_fragment_rejects_mismatched_generation(self) -> None:
        session = {ACTIVE_PAGE_NAME_KEY: "Live Draft Room", ACTIVE_PAGE_GENERATION_KEY: 5}
        self.assertTrue(fragment_allowed(session, expected_page="Live Draft Room", expected_generation=5))
        self.assertFalse(fragment_allowed(session, expected_page="Live Draft Room", expected_generation=4))


class SharedRoomCreatedCardTests(unittest.TestCase):
    def test_card_hidden_without_room(self) -> None:
        session = {"active_shared_draft_room_code": "ABC123"}
        self.assertFalse(should_render_shared_room_created_card(session))
        self.assertNotIn("active_shared_draft_room_code", session)

    def test_card_hidden_when_tombstoned(self) -> None:
        session = {
            "active_shared_draft_room_code": "ABC123",
            "live_draft_room": {"status": "waiting", "sync": {"room_code": "ABC123"}},
            "_live_draft_ended_room_codes": ["ABC123"],
        }
        self.assertFalse(should_render_shared_room_created_card(session))

    def test_card_shown_for_waiting_room(self) -> None:
        session = {
            "active_shared_draft_room_code": "ABC123",
            "live_draft_room": {"status": "waiting", "sync": {"room_code": "ABC123"}},
        }
        self.assertTrue(should_render_shared_room_created_card(session))


class StickySetupPreferenceTests(unittest.TestCase):
    def test_mode_only_save_merges_team_and_picks(self) -> None:
        session: dict = {
            "auth_user_id": "daniel",
            "_suite_active_workspace_id": "ws-daniel",
        }
        save_user_page_preferences(
            "daniel",
            "ws-daniel",
            PAGE_KEY_LIVE_DRAFT_SETUP,
            {
                "live_draft_setup_mode": "shared_multiplayer",
                "live_draft_team_count": 2,
                "live_draft_picks_per_team": 4,
                "live_draft_proj_window": 5,
            },
            session=session,
            st=None,
            force_disk=False,
        )
        session["live_draft_setup_mode"] = "shared_multiplayer"
        # Mode-only collect/save must retain teams/picks.
        settings = collect_live_draft_setup_settings(session)
        settings["live_draft_setup_mode"] = "shared_multiplayer"
        # Drop teams from session to simulate partial collect overlay
        session.pop("live_draft_team_count", None)
        session.pop("live_draft_picks_per_team", None)
        settings2 = collect_live_draft_setup_settings(session)
        self.assertEqual(settings2.get("live_draft_team_count"), 2)
        self.assertEqual(settings2.get("live_draft_picks_per_team"), 4)
        save_user_page_preferences(
            "daniel",
            "ws-daniel",
            PAGE_KEY_LIVE_DRAFT_SETUP,
            {"live_draft_setup_mode": "shared_multiplayer"},
            session=session,
            st=None,
            force_disk=False,
        )
        saved = get_user_page_preferences("daniel", "ws-daniel", PAGE_KEY_LIVE_DRAFT_SETUP, session=session)
        assert isinstance(saved, dict)
        self.assertEqual(saved.get("live_draft_team_count"), 2)
        self.assertEqual(saved.get("live_draft_picks_per_team"), 4)
        self.assertEqual(saved.get("live_draft_proj_window"), 5)

    def test_number_default_uses_prefs_not_ten_fifteen(self) -> None:
        session: dict = {
            "auth_user_id": "daniel",
            "_suite_active_workspace_id": "ws-daniel",
            "page_filter_state": {
                "_user_page_preferences": {
                    PAGE_KEY_LIVE_DRAFT_SETUP: {
                        "settings": {
                            "live_draft_team_count": 2,
                            "live_draft_picks_per_team": 4,
                        }
                    }
                }
            },
        }
        self.assertEqual(live_draft_setup_number_default(session, "live_draft_team_count", 10), 2)
        self.assertEqual(live_draft_setup_number_default(session, "live_draft_picks_per_team", 15), 4)

    def test_discard_restores_sticky_setup_not_solo_ten_fifteen(self) -> None:
        session: dict = {
            "auth_user_id": "daniel",
            "_suite_active_workspace_id": "ws-daniel",
            "live_draft_setup_mode": "shared_multiplayer",
            "live_draft_team_count": 2,
            "live_draft_picks_per_team": 4,
            "live_draft_proj_window": 5,
            "live_draft_room": {
                "status": "in_progress",
                "draft_room_id": "dr-sticky",
                "sync": {"room_code": "STICKY"},
                "config": {"timer_seconds": 30, "draft_setup_mode": "shared_multiplayer"},
            },
            "active_shared_draft_room_code": "STICKY",
        }
        save_user_page_preferences(
            "daniel",
            "ws-daniel",
            PAGE_KEY_LIVE_DRAFT_SETUP,
            {
                "live_draft_setup_mode": "shared_multiplayer",
                "preferred_next_draft_mode": "shared_multiplayer",
                "live_draft_team_count": 2,
                "live_draft_picks_per_team": 4,
                "live_draft_proj_window": 5,
            },
            session=session,
            st=None,
            force_disk=False,
        )
        from unittest.mock import patch

        with patch("live_draft_termination._close_backend_room"), patch(
            "live_draft_termination.persist_durable_tombstones"
        ), patch("live_draft_termination._clear_query_room_params"):
            discard_live_draft_and_start_over(session, st=None)
        self.assertEqual(session.get("live_draft_setup_mode"), "shared_multiplayer")
        self.assertEqual(int(session.get("live_draft_team_count") or 0), 2)
        self.assertEqual(int(session.get("live_draft_picks_per_team") or 0), 4)
        self.assertEqual(int(session.get("live_draft_proj_window") or 0), 5)
        self.assertFalse(should_render_shared_room_created_card(session))

    def test_ensure_reseeds_missing_team_count(self) -> None:
        session: dict = {
            "auth_user_id": "daniel",
            "_suite_active_workspace_id": "ws-daniel",
            "_prefs_initialized:live_draft_setup": True,
            "live_draft_setup_mode": "shared_multiplayer",
        }
        save_user_page_preferences(
            "daniel",
            "ws-daniel",
            PAGE_KEY_LIVE_DRAFT_SETUP,
            {
                "live_draft_setup_mode": "shared_multiplayer",
                "live_draft_team_count": 2,
                "live_draft_picks_per_team": 4,
            },
            session=session,
            st=None,
            force_disk=False,
        )
        ensure_live_draft_setup_preferences_loaded(session)
        self.assertEqual(int(session.get("live_draft_team_count") or 0), 2)
        self.assertEqual(int(session.get("live_draft_picks_per_team") or 0), 4)


if __name__ == "__main__":
    unittest.main()
