"""Tests for the consolidated Baseball Account & Workspace sidebar control."""

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
    def test_auth_disabled_is_not_labelled_as_a_login(
        self,
        mock_cc: object,
        _ctx: object,
        _init: object,
        _prepare: object,
        _enabled: object,
    ) -> None:
        """With sign-in switched off there is nothing to log into, so the header must
        not say "Login" and the body must say plainly this is a local workspace."""
        from baseball_account_workspace import render_baseball_account_workspace_control

        st = MagicMock()
        st.session_state = {}
        st.sidebar.expander.return_value.__enter__ = MagicMock(return_value=None)
        st.sidebar.expander.return_value.__exit__ = MagicMock(return_value=False)
        st.button.return_value = False
        render_baseball_account_workspace_control(st, on_reset=lambda _s: None)
        args, kwargs = st.sidebar.expander.call_args
        self.assertEqual(args[0], "Account & Workspace")
        captions = " ".join(str(c.args[0]) for c in st.caption.call_args_list)
        self.assertIn("Local workspace", captions)
        self.assertIn("isn't available on this deploy", captions)
        self.assertIn("Workspace: **Workspace**", captions)
        mock_cc.assert_called_once()
        # No authenticated identity is claimed and no Log out is offered.
        self.assertNotIn(
            "suite_account_workspace_logout_btn",
            [c.kwargs.get("key") for c in st.button.call_args_list],
        )

    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("suite_auth.is_authenticated", return_value=False)
    @patch("suite_auth.render_auth_panel")
    @patch("baseball_account_sidebar.prepare_baseball_auth_session")
    @patch("suite_account_settings.init_suite_workspace")
    @patch("suite_account_settings.build_account_settings_context", return_value={})
    def test_logged_out_says_not_signed_in_and_offers_the_auth_panel(
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
        self.assertEqual(args[0], "Account & Workspace")
        self.assertEqual(kwargs.get("key"), "suite_account_workspace_expander")
        self.assertTrue(kwargs.get("expanded"))
        st.markdown.assert_any_call("**Not signed in**")
        # The existing email/password flow is the only sign-in path.
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
    @patch("suite_workspace.can_show_developer_tools", return_value=False)
    @patch("baseball_account_workspace._render_command_center_entry")
    def test_logged_in_nests_command_center_and_saved_sessions(
        self,
        mock_cc: object,
        _dev: object,
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
        self.assertEqual(args[0], "Account & Workspace")
        st.markdown.assert_any_call("Signed in as **daniel@example.com**")
        captions = " ".join(str(c.args[0]) for c in st.caption.call_args_list)
        self.assertIn("Workspace: **Daniel**", captions)
        # Exactly one Log out: the auth panel used to add a second one here.
        button_keys = [c.kwargs.get("key") for c in st.button.call_args_list]
        self.assertEqual(button_keys.count("suite_account_workspace_logout_btn"), 1)
        mock_auth.assert_not_called()
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


class PortfolioModesAreDeveloperOnlyTests(unittest.TestCase):
    """Portfolio Screenshot / Demo Mode stay available to developers only."""

    def setUp(self) -> None:
        self.source = Path(__file__).resolve().parents[1].joinpath(
            "streamlit_app.py"
        ).read_text(encoding="utf-8")
        start = self.source.index("# Portfolio Screenshot / Demo Mode are developer tools")
        self.block = self.source[start : self.source.index(
            "render_developer_mode_sidebar_toggle()", start)]

    def test_toggles_render_only_in_developer_mode(self) -> None:
        gate = self.block.index("if developer_mode_enabled():")
        self.assertLess(gate, self.block.index("pp.render_sidebar_toggle(st)"))

    def test_hidden_modes_are_cleared_so_saves_are_never_stranded(self) -> None:
        """Capture mode skips background persistence; with the toggle hidden a user
        left in it would silently stop saving."""
        hidden = self.block[self.block.index("else:"):]
        self.assertIn("st.session_state.pop(pp.SESSION_KEY, None)", hidden)
        self.assertIn("st.session_state.pop(pp.DEMO_SESSION_KEY, None)", hidden)

    def test_capture_mode_does_skip_persistence(self) -> None:
        """Guards the reason the keys are cleared, not just the clearing."""
        import portfolio_polish as pp

        st = MagicMock()
        st.session_state = {pp.DEMO_SESSION_KEY: True}
        self.assertTrue(pp.skip_background_persistence(st))
