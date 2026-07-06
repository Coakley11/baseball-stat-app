"""Regression tests for Saved Draft Library Streamlit on_click callbacks."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock, patch

from draft_archive_ui import (
    _on_analyze_draft_click,
    _on_click_navigate_to_page,
    _on_click_return_from_saved_draft_library,
    _on_click_saved_draft_library,
    _on_live_draft_save_click,
    _on_simulator_save_click,
)


class DraftArchiveCallbackTests(unittest.TestCase):
    def test_navigate_callback_accepts_registered_args(self) -> None:
        session: dict = {"active_page": "Saved Draft Library"}
        with patch("streamlit.session_state", session, create=True):
            _on_click_navigate_to_page("Live Draft Room", "archive_open_live_x", "open_live_draft_room")
        self.assertEqual(session.get("_navigate_to_page"), "Live Draft Room")

    def test_saved_draft_library_callback_accepts_registered_args(self) -> None:
        session: dict = {"active_page": "Draft Room Simulator", "draft_archive_teams": []}
        with patch("streamlit.session_state", session, create=True):
            _on_click_saved_draft_library(
                "Draft Room Simulator",
                "view_library_btn",
                "view_in_saved_draft_library",
            )
        self.assertEqual(session.get("_navigate_to_page"), "Saved Draft Library")

    def test_return_from_library_callback_accepts_registered_args(self) -> None:
        session: dict = {"_saved_draft_library_return_page": "Draft Room Simulator"}
        with patch("streamlit.session_state", session, create=True):
            _on_click_return_from_saved_draft_library("library_return_to_workflow")
        self.assertEqual(session.get("_navigate_to_page"), "Draft Room Simulator")

    def test_simulator_save_click_signature_matches_button_kwargs(self) -> None:
        params = inspect.signature(_on_simulator_save_click).parameters
        self.assertIn("team_name", params)
        self.assertIn("key_prefix", params)
        self.assertNotEqual(params["team_name"].kind, inspect.Parameter.VAR_KEYWORD)

    def test_simulator_save_click_invokes_save_body(self) -> None:
        session: dict = {"sim_draft_archive_name_input": "Mock League"}
        with patch("streamlit.session_state", session, create=True):
            with patch("draft_archive_ui._execute_simulator_league_context_save") as execute:
                _on_simulator_save_click(team_name="Daniel", key_prefix="sim_draft_archive")
        execute.assert_called_once()

    def test_live_draft_save_click_signature_matches_button_kwargs(self) -> None:
        params = inspect.signature(_on_live_draft_save_click).parameters
        self.assertIn("team_name", params)
        self.assertIn("key_prefix", params)
        self.assertIn("defer_activation", params)
        self.assertNotEqual(params["team_name"].kind, inspect.Parameter.VAR_KEYWORD)

    def test_live_draft_save_click_records_trace_before_persist(self) -> None:
        session: dict = {
            "live_draft_complete_name_input": "David vs Barry",
            "live_draft_room": {
                "status": "complete",
                "teams": ["Daniel", "Rival"],
                "config": {"user_team": "Daniel", "league_name": "Test"},
                "picks": [],
            },
        }
        mock_st = MagicMock()
        with patch("streamlit.session_state", session, create=True):
            with patch("draft_archive_ui._execute_live_draft_save", return_value=({"draft_id": "d1"}, {}, True)) as execute:
                _on_live_draft_save_click(team_name="Daniel", key_prefix="live_draft_complete", defer_activation=True)
        self.assertTrue(session.get("_draft_save_trace_expand"))
        self.assertTrue(session.get("_draft_library_save_diag", {}).get("save_request_received"))
        self.assertTrue(session.get("_draft_save_button_trace", {}).get("save_requested"))
        execute.assert_called_once()
        self.assertTrue(execute.call_args.kwargs.get("trace_already_started"))

    def test_analyze_draft_click_rejects_incomplete_room(self) -> None:
        session: dict = {
            "live_draft_room": {
                "status": "in_progress",
                "current_pick_index": 0,
                "pick_order": [{"Team": "Daniel", "Pick": 1}],
            }
        }
        with patch("streamlit.session_state", session, create=True):
            _on_analyze_draft_click(key_prefix="live_draft_complete")
        flash = session.get("_draft_analyze_ui_flash")
        self.assertIsInstance(flash, dict)
        self.assertEqual(flash.get("level"), "error")
        self.assertIn("complete", str(flash.get("message") or "").lower())

    def test_analyze_draft_enforce_pending_navigation(self) -> None:
        session: dict = {
            "_draft_analyze_nav_pending": True,
            "active_page": "Saved Draft Library",
            "main_sidebar_page": "Saved Draft Library",
        }
        from draft_archive_ui import enforce_pending_analyze_draft_navigation

        self.assertTrue(enforce_pending_analyze_draft_navigation(session))
        self.assertEqual(session.get("active_page"), "Draft Lab / Simulation")
        self.assertEqual(session.get("main_sidebar_page"), "Draft Lab / Simulation")
        self.assertEqual(session.get("_suite_nav_consumed_target"), "Draft Lab / Simulation")

    def test_analyze_draft_click_pushes_and_navigates_complete_room(self) -> None:
        board = [
            {"Round": 1, "Pick": 1, "Fantasy Team": "Daniel", "fullName": "Player A", "Primary Position": "OF", "Expected Fantasy Value": 0.82, "Model Rank": 12, "Market Rank": 18, "Fantasy Edge": 6},
            {"Round": 1, "Pick": 2, "Fantasy Team": "Ariel", "fullName": "Player B", "Primary Position": "SS", "Expected Fantasy Value": 0.79, "Model Rank": 20, "Market Rank": 25, "Fantasy Edge": 5},
        ]
        session: dict = {
            "live_draft_room": {
                "status": "complete",
                "current_pick_index": 2,
                "teams": ["Daniel", "Ariel"],
                "config": {"num_teams": 2, "picks_per_team": 1, "scoring_type": "Roto (5x5)"},
                "draft_board": board,
                "pick_order": [{"Team": "Daniel", "Pick": 1}, {"Team": "Ariel", "Pick": 2}],
                "pool": [],
            }
        }
        with patch("streamlit.session_state", session, create=True):
            _on_analyze_draft_click(key_prefix="live_draft_complete")
        flash = session.get("_draft_analyze_ui_flash")
        self.assertIsInstance(flash, dict)
        self.assertNotEqual(flash.get("level"), "error", msg=str(flash))
        self.assertEqual(session.get("_navigate_to_page"), "Draft Lab / Simulation")
        self.assertEqual(session.get("active_page"), "Draft Lab / Simulation")
        self.assertEqual(session.get("main_sidebar_page"), "Draft Lab / Simulation")
        self.assertEqual(session.get("_suite_nav_consumed_target"), "Draft Lab / Simulation")
        self.assertEqual(session.get("draft_lab_preferred_tab"), "Draft Board")
        pending = session.get("_pending_page_transfer")
        self.assertIsInstance(pending, dict)
        self.assertEqual(pending.get("target"), "Draft Lab / Simulation")
        self.assertIn("draft_lab_results", session)
        self.assertFalse(getattr(session["draft_lab_results"].get("draft"), "empty", True))


if __name__ == "__main__":
    unittest.main()
