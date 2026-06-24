"""Tests for baseball sidebar Real Accounts status."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from baseball_account_sidebar import (
    ACCOUNT_EXPANDER_FLAG,
    real_account_status,
    request_account_sign_in_panel,
)
from suite_auth import AUTH_SESSION_KEY, AUTH_USER_EMAIL_KEY, AUTH_USER_ID_KEY


class BaseballAccountSidebarTests(unittest.TestCase):
    @patch("suite_auth.is_auth_enabled", return_value=False)
    def test_auth_disabled(self, _mock: object) -> None:
        status = real_account_status({})
        self.assertFalse(status["auth_enabled"])
        self.assertIn("disabled", status["message"].lower())

    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("suite_auth.is_authenticated", return_value=False)
    def test_not_signed_in(self, _auth: object, _enabled: object) -> None:
        status = real_account_status({})
        self.assertTrue(status["auth_enabled"])
        self.assertFalse(status["signed_in"])
        self.assertEqual(status["message"], "Not signed in")

    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("suite_auth.is_authenticated", return_value=True)
    @patch("suite_auth.current_auth_email", return_value="daniel@example.com")
    def test_signed_in(self, _email: object, _auth: object, _enabled: object) -> None:
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uuid-123",
            AUTH_USER_EMAIL_KEY: "daniel@example.com",
        }
        status = real_account_status(session)
        self.assertTrue(status["signed_in"])
        self.assertEqual(status["email"], "daniel@example.com")
        self.assertEqual(status["auth_user_id"], "uuid-123")

    def test_request_account_sign_in_panel(self) -> None:
        session: dict = {}
        request_account_sign_in_panel(session)
        self.assertTrue(session.get(ACCOUNT_EXPANDER_FLAG))


if __name__ == "__main__":
    unittest.main()
