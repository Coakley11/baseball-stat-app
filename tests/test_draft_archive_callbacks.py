"""Regression tests for Saved Draft Library Streamlit on_click callbacks."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock, patch

from draft_archive_ui import (
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


if __name__ == "__main__":
    unittest.main()
