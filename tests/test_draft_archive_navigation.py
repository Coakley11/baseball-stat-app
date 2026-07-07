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
    _nav_label,
    _render_archive_actions,
    render_saved_draft_library_page,
    schedule_fantasy_analysis_navigation,
    schedule_page_navigation,
    schedule_return_from_saved_draft_library,
    schedule_saved_draft_library_navigation,
)
from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY, save_simulator_team_archive
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


if __name__ == "__main__":
    unittest.main()
