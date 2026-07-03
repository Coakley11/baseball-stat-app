"""Baseball AMI sidebar button label — must not show generic Command Center send text."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from baseball_ami_sidebar import (
    BASEBALL_AMI_SIDEBAR_CODE_GENERATION,
    EXPECTED_CODE_GENERATION,
    RENDER_MODULE,
    baseball_insight_button_label,
    render_baseball_insight_sidebar,
)
from suite_analytical_question import (
    BASEBALL_INSIGHT_BUTTON_LABEL,
    ami_sidebar_submit_label,
    infer_runtime_suite_app_id,
    resolve_ami_sidebar_app_id,
)
from suite_workspace import set_active_workspace_id


class BaseballAmiButtonLabelTests(unittest.TestCase):
    def test_constant_is_baseball_insight(self) -> None:
        self.assertEqual(BASEBALL_INSIGHT_BUTTON_LABEL, "⚾ Baseball Insight")
        self.assertEqual(baseball_insight_button_label(), "⚾ Baseball Insight")

    def test_code_generation_is_current(self) -> None:
        self.assertEqual(BASEBALL_AMI_SIDEBAR_CODE_GENERATION, EXPECTED_CODE_GENERATION)

    def test_submit_label_for_baseball_app_ids(self) -> None:
        for source_app in ("baseball", "Baseball Stat App", "baseball stat app", "BASEBALL"):
            label = ami_sidebar_submit_label(source_app)
            self.assertEqual(label, "⚾ Baseball Insight", msg=source_app)
            self.assertNotIn("Send to Command Center", label)

    def test_runtime_baseball_forces_label_when_source_app_empty(self) -> None:
        session = {"_suite_runtime_app_id": "baseball"}
        self.assertEqual(ami_sidebar_submit_label("", session), "⚾ Baseball Insight")
        self.assertEqual(resolve_ami_sidebar_app_id("", session), "baseball")

    def test_infer_runtime_from_session_flag(self) -> None:
        self.assertEqual(infer_runtime_suite_app_id({"_suite_runtime_app_id": "baseball"}), "baseball")
        self.assertEqual(infer_runtime_suite_app_id({}), "")

    def test_non_baseball_apps_keep_suite_defaults(self) -> None:
        self.assertEqual(ami_sidebar_submit_label("investment"), "Send to Command Center")
        self.assertEqual(ami_sidebar_submit_label("nba"), "Get NBA Insight")
        self.assertEqual(ami_sidebar_submit_label("music"), "Ask the Music Coach")

    def test_baseball_sidebar_renders_insight_button_without_debug_marker(self) -> None:
        mock_st = MagicMock()
        mock_st.session_state = {"_suite_runtime_app_id": "baseball"}
        mock_st.sidebar = MagicMock()
        mock_st.sidebar.text_area.return_value = ""
        mock_st.sidebar.button.return_value = False

        render_baseball_insight_sidebar(
            mock_st,
            source_page="Live Draft Room",
            session_state=mock_st.session_state,
        )

        button_calls = mock_st.sidebar.button.call_args_list
        self.assertGreaterEqual(len(button_calls), 1)
        label = button_calls[0].args[0]
        self.assertEqual(label, "⚾ Baseball Insight")
        mock_st.sidebar.info.assert_not_called()
        self.assertNotIn("_ami_sidebar_render_debug", mock_st.session_state)

    def test_baseball_sidebar_hides_debug_for_unrelated_session_flags(self) -> None:
        mock_st = MagicMock()
        mock_st.session_state = {
            "_suite_runtime_app_id": "baseball",
            "investment_show_dev_diagnostics": True,
            "cc_developer_mode": True,
        }
        mock_st.sidebar = MagicMock()
        mock_st.sidebar.text_area.return_value = ""
        mock_st.sidebar.button.return_value = False

        render_baseball_insight_sidebar(
            mock_st,
            source_page="Live Draft Room",
            session_state=mock_st.session_state,
        )

        caption_calls = [str(c.args[0]) for c in mock_st.sidebar.caption.call_args_list if c.args]
        self.assertTrue(any("Ask about players" in t for t in caption_calls))
        self.assertFalse(any("AMI submit debug" in t for t in caption_calls))
        self.assertNotIn("_ami_sidebar_render_debug", mock_st.session_state)

    def test_baseball_sidebar_shows_debug_when_developer_mode_checkbox(self) -> None:
        from suite_workspace import set_developer_mode_user

        mock_st = MagicMock()
        mock_st.session_state = {"_suite_runtime_app_id": "baseball"}
        set_active_workspace_id(mock_st, "daniel")
        set_developer_mode_user(mock_st.session_state, True, source="test")
        mock_st.sidebar = MagicMock()
        mock_st.sidebar.text_area.return_value = ""
        mock_st.sidebar.button.return_value = False

        render_baseball_insight_sidebar(
            mock_st,
            source_page="Live Draft Room",
            session_state=mock_st.session_state,
        )

        caption_calls = mock_st.sidebar.caption.call_args_list
        self.assertGreaterEqual(len(caption_calls), 1)
        marker_text = " ".join(str(c.args[0]) for c in caption_calls if c.args)
        self.assertIn(RENDER_MODULE, marker_text)
        self.assertIn("CURRENT", marker_text)
        debug = mock_st.session_state.get("_ami_sidebar_render_debug") or {}
        self.assertEqual(debug.get("submit_label"), "⚾ Baseball Insight")

    def test_streamlit_entrypoint_uses_baseball_ami_sidebar(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("from baseball_ami_sidebar import render_baseball_insight_sidebar", text)
        self.assertIn("render_baseball_insight_sidebar(", text)
        self.assertNotIn('render_applied_math_sidebar_entry(\n    st,\n    source_app="baseball"', text)

    def test_applied_math_entry_redirects_baseball(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "suite_analytical_question.py").read_text(encoding="utf-8")
        self.assertIn("from baseball_ami_sidebar import render_baseball_insight_sidebar", text)


if __name__ == "__main__":
    unittest.main()
