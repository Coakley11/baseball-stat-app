"""Tests for Developer Mode auth/workspace diagnostics."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from baseball_account_sidebar import build_baseball_auth_status
from suite_auth import AUTH_SESSION_KEY, AUTH_USER_EMAIL_KEY, AUTH_USER_ID_KEY


class BaseballAuthDiagnosticsTests(unittest.TestCase):
    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("suite_auth.is_authenticated", return_value=True)
    @patch("suite_auth.current_auth_email", return_value="daniel.cohen11@example.com")
    @patch("suite_auth.resolve_auth_external_id", return_value="daniel.cohen11")
    @patch("suite_workspace_registry._account_context")
    @patch("suite_workspace.get_active_workspace_id", return_value="daniel")
    @patch("suite_workspace.workspace_label", return_value="Daniel")
    @patch("suite_workspace.workspace_persistence_meta", return_value={"cloud_app_key": "baseball"})
    @patch("suite_storage_config.cloud_storage_enabled", return_value=True)
    @patch("draft_room_membership.shared_room_requires_auth", return_value=True)
    def test_signed_in_status_includes_workspace_and_owner(
        self,
        _shared: object,
        _cloud: object,
        _meta: object,
        _label: object,
        _ws: object,
        mock_ctx: object,
        _ext: object,
        _email: object,
        _auth: object,
        _enabled: object,
    ) -> None:
        mock_ctx.return_value = {
            "owner_user_id": "uuid-daniel-11",
            "owner_external_id": "daniel.cohen11",
            "email": "daniel.cohen11@example.com",
            "display_name": "Daniel",
        }
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uuid-daniel-11",
            AUTH_USER_EMAIL_KEY: "daniel.cohen11@example.com",
        }
        status = build_baseball_auth_status(session)
        self.assertTrue(status["authenticated"])
        self.assertEqual(status["account_email"], "daniel.cohen11@example.com")
        self.assertEqual(status["owner_user_id"], "uuid-daniel-11")
        self.assertEqual(status["workspace_id"], "daniel")
        self.assertTrue(status["shared_drafts_auth_ok"])

    @patch("suite_auth.is_auth_enabled", return_value=True)
    @patch("suite_auth.is_authenticated", return_value=False)
    @patch("draft_room_membership.shared_room_requires_auth", return_value=True)
    def test_unsigned_in_reports_shared_draft_block(
        self,
        _shared: object,
        _auth: object,
        _enabled: object,
    ) -> None:
        status = build_baseball_auth_status({})
        self.assertFalse(status["authenticated"])
        self.assertFalse(status["shared_drafts_auth_ok"])
        self.assertIn("Shared drafts", status["save_block_reason"])


if __name__ == "__main__":
    unittest.main()
