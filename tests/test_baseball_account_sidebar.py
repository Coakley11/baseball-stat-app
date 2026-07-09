"""Tests for baseball sidebar Real Accounts status."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock, patch

from baseball_account_sidebar import (
    ACCOUNT_EXPANDER_FLAG,
    account_sidebar_should_render,
    real_account_status,
    render_baseball_account_sidebar,
    request_account_sign_in_panel,
)
from suite_auth import AUTH_SESSION_KEY, AUTH_TOKENS_KEY, AUTH_USER_EMAIL_KEY, AUTH_USER_ID_KEY


class BaseballAccountSidebarTests(unittest.TestCase):
    @patch("suite_auth.is_auth_enabled", return_value=False)
    def test_auth_disabled(self, _mock: object) -> None:
        status = real_account_status({})
        self.assertFalse(status["auth_enabled"])
        self.assertIn("disabled", status["message"].lower())

    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("suite_auth.auth_session_complete", return_value=False)
    def test_not_signed_in(self, _complete: object, _enabled: object) -> None:
        status = real_account_status({})
        self.assertTrue(status["auth_enabled"])
        self.assertFalse(status["signed_in"])
        self.assertEqual(status["message"], "Not signed in")

    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("suite_auth.auth_session_complete", return_value=True)
    @patch("suite_auth.current_auth_email", return_value="daniel@example.com")
    def test_signed_in(self, _email: object, _complete: object, _enabled: object) -> None:
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uuid-123",
            AUTH_USER_EMAIL_KEY: "daniel@example.com",
            AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
        }
        status = real_account_status(session)
        self.assertTrue(status["signed_in"])
        self.assertEqual(status["email"], "daniel@example.com")
        self.assertEqual(status["auth_user_id"], "uuid-123")

    def test_request_account_sign_in_panel(self) -> None:
        session: dict = {}
        request_account_sign_in_panel(session)
        self.assertTrue(session.get(ACCOUNT_EXPANDER_FLAG))

    @patch("suite_auth.is_auth_enabled", return_value=True)
    def test_account_sidebar_should_render_when_auth_enabled(self, _enabled: object) -> None:
        self.assertTrue(account_sidebar_should_render({}))

    @patch("suite_auth.is_auth_enabled", return_value=False)
    def test_account_sidebar_should_not_render_when_auth_disabled(self, _enabled: object) -> None:
        self.assertFalse(account_sidebar_should_render({}))

    def test_account_sidebar_does_not_use_sidebar_render_guard(self) -> None:
        source = inspect.getsource(render_baseball_account_sidebar)
        self.assertNotIn("claim_sidebar_render", source)

    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("suite_auth.auth_session_complete", return_value=False)
    @patch("suite_auth.render_auth_panel")
    @patch("baseball_account_sidebar.prepare_baseball_auth_session")
    def test_signed_out_renders_flat_login_panel(
        self,
        _prepare: object,
        mock_render_auth: object,
        _complete: object,
        _enabled: object,
    ) -> None:
        st = MagicMock()
        st.session_state = {"_sidebar_account_rendered_this_run": True}
        render_baseball_account_sidebar(st)
        mock_render_auth.assert_called_once()
        _args, kwargs = mock_render_auth.call_args
        self.assertTrue(kwargs.get("flat_sidebar"))
        self.assertTrue(kwargs.get("expanded"))
        st.sidebar.markdown.assert_called()

    def test_streamlit_app_renders_account_before_choose_page(self) -> None:
        from pathlib import Path

        source = Path(__file__).resolve().parents[1].joinpath("streamlit_app.py").read_text(encoding="utf-8")
        account_idx = source.index("render_baseball_account_sidebar(st)")
        choose_idx = source.index('st.sidebar.radio(\n    "Choose Page"')
        self.assertLess(account_idx, choose_idx)


if __name__ == "__main__":
    unittest.main()
