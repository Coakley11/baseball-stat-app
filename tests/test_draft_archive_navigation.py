"""Tests for Saved Draft Library fantasy page navigation helpers."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock

import pandas as pd

from draft_archive_ui import (
    DRAFT_SIMULATOR_PAGE,
    FANTASY_LINEUP_PAGE,
    FANTASY_NAV_TARGETS,
    FANTASY_STANDINGS_PAGE,
    FANTASY_WAIVER_PAGE,
    LIVE_DRAFT_PAGE,
    SAVED_DRAFT_LIBRARY_PAGE,
    SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY,
    _fantasy_nav_button_widget_key,
    _nav_label,
    _on_click_navigate_to_page,
    _render_archive_actions,
    purge_fantasy_nav_widget_keys,
    render_active_saved_draft_chip,
    render_fantasy_page_header,
    render_saved_draft_library_page,
    schedule_fantasy_analysis_navigation,
    schedule_page_navigation,
    schedule_return_from_saved_draft_library,
    schedule_saved_draft_library_navigation,
)
from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY, save_simulator_team_archive
from fantasy_context_source import USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY
from fantasy_league_context import (
    PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY,
    apply_pending_league_context_activation,
    save_simulator_league_context,
)


class DraftArchiveNavigationTests(unittest.TestCase):
    def test_schedule_fantasy_analysis_navigation_sets_pending_and_target(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
        save_simulator_league_context(session, board, my_team_name="Daniel")
        self.assertTrue(schedule_fantasy_analysis_navigation(session, FANTASY_STANDINGS_PAGE))
        self.assertEqual(session["_navigate_to_page"], FANTASY_STANDINGS_PAGE)
        self.assertEqual(session["_skip_page_restore_for"], FANTASY_STANDINGS_PAGE)
        self.assertTrue(session.get("_suite_page_user_nav"))
        self.assertIn(PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY, session)
        apply_pending_league_context_activation(session)
        self.assertEqual(session.get("room_your_team"), "Daniel")

    def test_schedule_fantasy_analysis_navigation_without_active_context(self) -> None:
        session: dict = {}
        self.assertFalse(schedule_fantasy_analysis_navigation(session, FANTASY_LINEUP_PAGE))

    def test_schedule_navigation_from_legacy_team_archive(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
        entry = save_simulator_team_archive(
            session,
            board,
            team_name="Daniel",
            draft_name="Legacy team snapshot",
        )
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = str(entry.get("draft_id") or "")
        self.assertTrue(schedule_fantasy_analysis_navigation(session, FANTASY_STANDINGS_PAGE))
        self.assertEqual(session["_navigate_to_page"], FANTASY_STANDINGS_PAGE)
        apply_pending_league_context_activation(session)
        self.assertEqual(session.get("room_your_team"), "Daniel")


class SavedDraftLibraryNavigationTests(unittest.TestCase):
    def test_schedule_page_navigation_queues_target(self) -> None:
        session = {"main_sidebar_page": "Fantasy Standings Tracker", "active_page": "Fantasy Standings Tracker"}
        schedule_page_navigation(session, SAVED_DRAFT_LIBRARY_PAGE)
        self.assertEqual(session["_navigate_to_page"], SAVED_DRAFT_LIBRARY_PAGE)
        self.assertEqual(session["_skip_page_restore_for"], SAVED_DRAFT_LIBRARY_PAGE)
        self.assertTrue(session.get("_suite_page_user_nav"))

    def test_schedule_saved_draft_library_navigation_sets_target_and_return(self) -> None:
        session = {"active_page": FANTASY_LINEUP_PAGE}
        schedule_saved_draft_library_navigation(session)
        self.assertEqual(session["_navigate_to_page"], SAVED_DRAFT_LIBRARY_PAGE)
        self.assertEqual(session["_skip_page_restore_for"], SAVED_DRAFT_LIBRARY_PAGE)
        self.assertEqual(session[SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY], FANTASY_LINEUP_PAGE)
        self.assertTrue(session.get("_suite_page_user_nav"))

    def test_schedule_saved_draft_library_from_standings(self) -> None:
        session = {"active_page": FANTASY_STANDINGS_PAGE}
        schedule_saved_draft_library_navigation(session)
        self.assertEqual(session[SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY], FANTASY_STANDINGS_PAGE)

    def test_schedule_saved_draft_library_from_waiver_wire(self) -> None:
        page = "Waiver Wire / Add-Drop Center"
        session = {"active_page": page}
        schedule_saved_draft_library_navigation(session)
        self.assertEqual(session["_navigate_to_page"], SAVED_DRAFT_LIBRARY_PAGE)
        self.assertEqual(session[SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY], page)

    def test_schedule_return_from_saved_draft_library(self) -> None:
        session = {
            SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY: FANTASY_LINEUP_PAGE,
            "active_page": SAVED_DRAFT_LIBRARY_PAGE,
        }
        self.assertTrue(schedule_return_from_saved_draft_library(session))
        self.assertEqual(session["_navigate_to_page"], FANTASY_LINEUP_PAGE)
        self.assertEqual(session["_skip_page_restore_for"], FANTASY_LINEUP_PAGE)
        self.assertNotIn(SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY, session)


class SavedDraftLibraryRenderTests(unittest.TestCase):
    def _mock_st(self) -> MagicMock:
        st = MagicMock()
        st.markdown = MagicMock()
        st.caption = MagicMock()
        st.metric = MagicMock()
        st.info = MagicMock()
        st.success = MagicMock()
        st.warning = MagicMock()
        st.toast = MagicMock()
        st.divider = MagicMock()
        st.container = MagicMock(
            return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock()),
                __exit__=MagicMock(return_value=False),
            )
        )
        st.expander = MagicMock(
            return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock()),
                __exit__=MagicMock(return_value=False),
            )
        )
        st.columns = MagicMock(side_effect=lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))])
        st.button = MagicMock(return_value=False)
        st.checkbox = MagicMock(return_value=False)
        st.rerun = MagicMock()
        st.session_state = {}
        return st

    def test_render_archive_actions_accepts_page_label_fn(self) -> None:
        params = inspect.signature(_render_archive_actions).parameters
        self.assertIn("page_label_fn", params)
        st = self._mock_st()
        session: dict = {}
        entry = {"draft_id": "d1", "draft_name": "Mock Draft", "draft_type": "simulator", "team_name": "Daniel"}
        _render_archive_actions(
            st,
            session,
            entry,
            active_id="other",
            active_context_id="",
            page_label_fn=lambda key: f"Label:{key}",
        )
        st.button.assert_called()

    def test_nav_label_renders_live_and_simulator_icons(self) -> None:
        live = _nav_label(LIVE_DRAFT_PAGE, "Open Live Draft Room", None)
        sim = _nav_label(DRAFT_SIMULATOR_PAGE, "Go to Draft Room Simulator", None)
        self.assertIn("Live Draft Room", live)
        self.assertIn("Draft Room Simulator", sim)
        self.assertTrue(live.startswith("📡"))
        self.assertTrue(sim.startswith("🧾"))

    def test_fantasy_nav_targets_exclude_current_page(self) -> None:
        self.assertEqual(
            FANTASY_NAV_TARGETS[FANTASY_STANDINGS_PAGE],
            (SAVED_DRAFT_LIBRARY_PAGE, FANTASY_LINEUP_PAGE),
        )
        self.assertEqual(
            FANTASY_NAV_TARGETS[FANTASY_LINEUP_PAGE],
            (SAVED_DRAFT_LIBRARY_PAGE, FANTASY_STANDINGS_PAGE, FANTASY_WAIVER_PAGE),
        )
        self.assertEqual(
            FANTASY_NAV_TARGETS[FANTASY_WAIVER_PAGE],
            (SAVED_DRAFT_LIBRARY_PAGE, FANTASY_STANDINGS_PAGE, FANTASY_LINEUP_PAGE),
        )
        self.assertNotIn(FANTASY_WAIVER_PAGE, FANTASY_NAV_TARGETS[FANTASY_STANDINGS_PAGE])
        self.assertNotIn(FANTASY_WAIVER_PAGE, FANTASY_NAV_TARGETS[FANTASY_WAIVER_PAGE])

    def test_render_archive_manage_actions_shows_rename_for_active_draft(self) -> None:
        from draft_archive_ui import _render_archive_manage_actions

        st = self._mock_st()
        session: dict = {}
        entry = {"draft_id": "d-active", "draft_name": "Active Draft", "draft_type": "simulator", "team_name": "Daniel"}
        _render_archive_manage_actions(
            st,
            session,
            entry,
            draft_id="d-active",
            is_active=True,
            widget_key_prefix="library_active",
        )
        labels = [str(call.args[0]) for call in st.button.call_args_list if call.args]
        self.assertIn("Rename Draft", labels)
        self.assertIn("Delete", labels)

    def test_render_archive_actions_shows_rename_for_inactive_draft(self) -> None:
        st = self._mock_st()
        session: dict = {}
        entry = {"draft_id": "d1", "draft_name": "Mock Draft", "draft_type": "simulator", "team_name": "Daniel"}
        _render_archive_actions(
            st,
            session,
            entry,
            active_id="other",
            active_context_id="",
            page_label_fn=lambda key: key,
        )
        labels = [str(call.args[0]) for call in st.button.call_args_list if call.args]
        self.assertIn("Set Active", labels)
        self.assertIn("Rename Draft", labels)
        self.assertIn("Delete", labels)

    def test_manage_action_keys_are_unique_between_active_sections(self) -> None:
        from draft_archive_ui import _render_archive_manage_actions

        st = self._mock_st()
        session: dict = {}
        entry = {"draft_id": "d-active", "draft_name": "Active Draft", "draft_type": "simulator"}
        _render_archive_manage_actions(
            st, session, entry, draft_id="d-active", is_active=True, widget_key_prefix="library_active",
        )
        top_keys = {call.kwargs.get("key") for call in st.button.call_args_list if call.kwargs.get("key")}
        st.button.reset_mock()
        _render_archive_manage_actions(
            st, session, entry, draft_id="d-active", is_active=False, widget_key_prefix="archive_list_dactive",
        )
        list_keys = {call.kwargs.get("key") for call in st.button.call_args_list if call.kwargs.get("key")}
        self.assertFalse(top_keys & list_keys)

    def test_render_saved_draft_library_page_with_archive(self) -> None:
        session: dict = {"room_your_team": "Daniel", "draft_shared_settings": {}}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
        from fantasy_league_context import save_simulator_league_context

        save_simulator_league_context(session, board, my_team_name="Daniel", defer_activation=True)
        st = self._mock_st()
        render_saved_draft_library_page(st, session, page_label_fn=lambda key: key)
        st.markdown.assert_called()

    def test_saved_draft_library_fantasy_sync_no_post_render_widget_assign(self) -> None:
        """Regression: assigning widget keys after checkbox render raises StreamlitAPIException."""
        from fantasy_context_ui import (
            _LIVE_CONTEXT_TOGGLE_WIDGET_KEY,
            _RESEARCH_SYNC_TOGGLE_WIDGET_KEY,
            _SIM_CONTEXT_TOGGLE_WIDGET_KEY,
        )

        class StreamlitAPIException(Exception):
            pass

        session: dict = {
            "room_your_team": "Daniel",
            "draft_shared_settings": {},
            USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: True,
            "use_active_league_context_waiver_filter": True,
        }
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
        from fantasy_league_context import save_simulator_league_context

        save_simulator_league_context(session, board, my_team_name="Daniel", defer_activation=True)

        rendered_widget_keys: set[str] = set()
        widget_keys = {
            _LIVE_CONTEXT_TOGGLE_WIDGET_KEY,
            _SIM_CONTEXT_TOGGLE_WIDGET_KEY,
            _RESEARCH_SYNC_TOGGLE_WIDGET_KEY,
        }

        class GuardSession(dict):
            def __setitem__(self, key, value) -> None:
                if key in rendered_widget_keys and key in widget_keys:
                    raise StreamlitAPIException(
                        f"Cannot set widget value after widget is instantiated: {key}"
                    )
                super().__setitem__(key, value)

        guarded = GuardSession(session)

        st = self._mock_st()

        def _checkbox_side_effect(*_args, **kwargs):
            key = kwargs.get("key")
            if key:
                rendered_widget_keys.add(key)
            return bool(kwargs.get("value"))

        st.checkbox.side_effect = _checkbox_side_effect

        render_saved_draft_library_page(st, guarded, page_label_fn=lambda key: key)
        self.assertEqual(
            rendered_widget_keys,
            widget_keys,
            "Expected all fantasy context checkboxes to render once",
        )


class FantasyNavWidgetKeyTests(unittest.TestCase):
    def _mock_st(self) -> MagicMock:
        st = MagicMock()
        st.markdown = MagicMock()
        st.caption = MagicMock()
        st.columns = MagicMock(side_effect=lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))])
        st.button = MagicMock(return_value=False)
        st.rerun = MagicMock()
        return st

    def test_nav_button_keys_use_nav_btn_suffix(self) -> None:
        key = _fantasy_nav_button_widget_key("standings_archive", "Fantasy_Lineup_Assistant")
        self.assertEqual(key, "standings_archive_nav_btn_Fantasy_Lineup_Assistant")
        self.assertIn("_nav_btn_", key)

    def test_purge_fantasy_nav_widget_keys_removes_legacy_and_new_keys(self) -> None:
        session = {
            "standings_archive_nav_Fantasy_Lineup_Assistant": True,
            "standings_archive_nav_btn_Fantasy_Lineup_Assistant": False,
            "lineup_team": "Daniel",
        }
        purge_fantasy_nav_widget_keys(session, key_prefix="standings_archive")
        self.assertNotIn("standings_archive_nav_Fantasy_Lineup_Assistant", session)
        self.assertNotIn("standings_archive_nav_btn_Fantasy_Lineup_Assistant", session)
        self.assertEqual(session["lineup_team"], "Daniel")

    def test_page_state_skips_fantasy_nav_widget_keys(self) -> None:
        from page_state import _is_ephemeral_widget_key

        self.assertTrue(_is_ephemeral_widget_key("standings_archive_nav_btn_Fantasy_Lineup_Assistant"))
        self.assertTrue(_is_ephemeral_widget_key("lineup_archive_nav_Fantasy_Standings_Tracker"))
        self.assertTrue(_is_ephemeral_widget_key("waiver_archive_nav_btn_Waiver_Wire_Add_Drop_Center"))

    def test_render_fantasy_page_header_does_not_persist_nav_button_keys(self) -> None:
        st = self._mock_st()
        session: dict = {
            "standings_archive_nav_Fantasy_Lineup_Assistant": True,
        }
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
        save_simulator_league_context(session, board, my_team_name="Daniel")
        render_fantasy_page_header(
            st,
            session,
            active_page=FANTASY_STANDINGS_PAGE,
            key_prefix="standings_archive",
            page_label_fn=lambda key: key,
        )
        self.assertNotIn("standings_archive_nav_Fantasy_Lineup_Assistant", session)
        nav_keys = [call.kwargs.get("key") for call in st.button.call_args_list if call.kwargs.get("key")]
        self.assertTrue(all("_nav_btn_" in str(key) for key in nav_keys))
        self.assertFalse(any("_nav_Fantasy_Lineup_Assistant" in str(key) and "_nav_btn_" not in str(key) for key in nav_keys))

    def test_render_active_saved_draft_chip_for_lineup_and_waiver(self) -> None:
        for prefix in ("lineup_archive", "waiver_archive"):
            st = self._mock_st()
            session: dict = {f"{prefix}_nav_Old_Key": True}
            board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
            save_simulator_league_context(session, board, my_team_name="Daniel")
            render_active_saved_draft_chip(
                st,
                session,
                key_prefix=prefix,
                page_label_fn=lambda key: key,
            )
            self.assertNotIn(f"{prefix}_nav_Old_Key", session)
            nav_keys = [call.kwargs.get("key") for call in st.button.call_args_list if call.kwargs.get("key")]
            self.assertTrue(nav_keys)
            self.assertTrue(all("_nav_btn_" in str(key) for key in nav_keys))

    def test_save_page_state_excludes_fantasy_nav_widget_keys(self) -> None:
        from page_state import save_page_state

        session = {
            "standings_archive_nav_btn_Fantasy_Lineup_Assistant": False,
            "standings_stats_source": "MLB API",
        }
        store: dict = {}
        save_page_state(session, FANTASY_STANDINGS_PAGE, store)
        saved = store.get(FANTASY_STANDINGS_PAGE) or {}
        self.assertIn("standings_stats_source", saved)
        self.assertNotIn("standings_archive_nav_btn_Fantasy_Lineup_Assistant", saved)

    def test_render_fantasy_page_navigation_uses_on_click(self) -> None:
        from draft_archive_ui import _on_click_navigate_fantasy_page, render_fantasy_page_navigation

        st = self._mock_st()
        session: dict = {}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
        save_simulator_league_context(session, board, my_team_name="Daniel")
        render_fantasy_page_navigation(
            st,
            session,
            active_page=FANTASY_STANDINGS_PAGE,
            key_prefix="standings_archive",
            page_label_fn=lambda key: key,
        )
        for call in st.button.call_args_list:
            self.assertIs(call.kwargs.get("on_click"), _on_click_navigate_fantasy_page)
            self.assertTrue(call.kwargs.get("args"))


if __name__ == "__main__":
    unittest.main()
