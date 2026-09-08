"""Tests for consolidated Baseball Login / Account & Workspace sidebar control."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from suite_auth import AUTH_SESSION_KEY, AUTH_TOKENS_KEY, AUTH_USER_EMAIL_KEY, AUTH_USER_ID_KEY


class BaseballAccountWorkspaceTests(unittest.TestCase):
    def test_streamlit_app_uses_consolidated_control_before_choose_page(self) -> None:
        source = Path(__file__).resolve().parents[1].joinpath("streamlit_app.py").read_text(
            encoding="utf-8"
        )
        chrome_idx = source.index("_render_baseball_sidebar_chrome(st)")
        choose_idx = source.index('st.sidebar.radio(\n    "Choose Page"')
        self.assertLess(chrome_idx, choose_idx)
        self.assertIn("render_baseball_account_workspace_control", source)
        self.assertNotIn("render_baseball_account_sidebar(st)", source)
        # Old standalone chrome must not remain as the happy-path fallback.
        chrome_src = source[
            source.index("def _render_baseball_sidebar_chrome") : source.index(
                "def _on_resume_live_draft_sidebar"
            )
        ]
        self.assertNotIn("render_command_center_sidebar_link", chrome_src)
        self.assertNotIn("render_reset_controls", chrome_src)

    @patch("suite_auth.is_auth_enabled", return_value=False)
    @patch("baseball_account_sidebar.prepare_baseball_auth_session")
    @patch("suite_account_settings.init_suite_workspace")
    @patch("suite_account_settings.build_account_settings_context", return_value={})
    @patch("baseball_account_workspace._render_command_center_entry")
    def test_auth_disabled_uses_login_top_entry(
        self,
        mock_cc: object,
        _ctx: object,
        _init: object,
        _prepare: object,
        _enabled: object,
    ) -> None:
        from baseball_account_workspace import render_baseball_account_workspace_control

        st = MagicMock()
        st.session_state = {}
        st.sidebar.expander.return_value.__enter__ = MagicMock(return_value=None)
        st.sidebar.expander.return_value.__exit__ = MagicMock(return_value=False)
        st.button.return_value = False
        render_baseball_account_workspace_control(st, on_reset=lambda _s: None)
        args, kwargs = st.sidebar.expander.call_args
        self.assertEqual(args[0], "Login")
        mock_cc.assert_called_once()

    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("suite_auth.is_authenticated", return_value=False)
    @patch("suite_auth.render_auth_panel")
    @patch("baseball_account_sidebar.prepare_baseball_auth_session")
    @patch("suite_account_settings.init_suite_workspace")
    @patch("suite_account_settings.build_account_settings_context", return_value={})
    def test_logged_out_shows_login_expander(
        self,
        _ctx: object,
        _init: object,
        _prepare: object,
        mock_auth: object,
        _authed: object,
        _enabled: object,
    ) -> None:
        from baseball_account_workspace import render_baseball_account_workspace_control

        st = MagicMock()
        st.session_state = {}
        render_baseball_account_workspace_control(st, on_reset=lambda _s: None)
        st.sidebar.expander.assert_called()
        args, kwargs = st.sidebar.expander.call_args
        self.assertEqual(args[0], "Login")
        self.assertEqual(kwargs.get("key"), "suite_account_workspace_expander")
        mock_auth.assert_called_once()

    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("suite_auth.is_authenticated", return_value=True)
    @patch("suite_auth.current_auth_email", return_value="daniel@example.com")
    @patch("suite_auth.render_auth_panel")
    @patch("suite_auth.logout")
    @patch("baseball_account_sidebar.prepare_baseball_auth_session")
    @patch("suite_account_settings.init_suite_workspace")
    @patch(
        "suite_account_settings.build_account_settings_context",
        return_value={"active_workspace_label": "Daniel", "email_display": "daniel@example.com"},
    )
    @patch(
        "suite_account_settings.account_workspace_expander_label",
        return_value="Account & Workspace · Daniel",
    )
    @patch("suite_workspace.can_show_developer_tools", return_value=False)
    @patch("baseball_account_workspace._render_command_center_entry")
    def test_logged_in_nests_command_center_and_saved_sessions(
        self,
        mock_cc: object,
        _dev: object,
        _label: object,
        _ctx: object,
        _init: object,
        _prepare: object,
        _logout: object,
        mock_auth: object,
        _email: object,
        _authed: object,
        _enabled: object,
    ) -> None:
        from baseball_account_workspace import render_baseball_account_workspace_control

        st = MagicMock()
        st.session_state = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uuid-123",
            AUTH_USER_EMAIL_KEY: "daniel@example.com",
            AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
        }
        # Expander context manager
        st.sidebar.expander.return_value.__enter__ = MagicMock(return_value=None)
        st.sidebar.expander.return_value.__exit__ = MagicMock(return_value=False)
        st.button.return_value = False

        render_baseball_account_workspace_control(st, on_reset=lambda _s: None)
        args, kwargs = st.sidebar.expander.call_args
        self.assertEqual(args[0], "Account & Workspace · Daniel")
        self.assertEqual(kwargs.get("key"), "suite_account_workspace_expander")
        mock_cc.assert_called_once()
        # Saved Sessions reset button key
        reset_keys = [
            c.kwargs.get("key")
            for c in st.button.call_args_list
            if isinstance(c.kwargs, dict)
        ]
        self.assertIn("suite_reset_btn::baseball", reset_keys)


if __name__ == "__main__":
    unittest.main()
