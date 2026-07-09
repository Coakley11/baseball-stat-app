"""Auth session completeness and workspace-restore protection."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from baseball_persistent_state import apply_baseball_disk_state
from suite_auth import (
    AUTH_PENDING_LOGIN_KEY,
    AUTH_SESSION_KEY,
    AUTH_TOKENS_KEY,
    AUTH_USER_EMAIL_KEY,
    AUTH_USER_ID_KEY,
    auth_session_complete,
    login_with_email,
    process_pending_auth_login,
    restore_auth_session,
    snapshot_auth_session,
)


class AuthSessionCompleteTests(unittest.TestCase):
    def test_auth_session_complete_requires_user_id_and_tokens(self) -> None:
        with patch("suite_auth.is_auth_enabled", return_value=True):
            self.assertFalse(auth_session_complete({}))
            self.assertFalse(
                auth_session_complete(
                    {
                        AUTH_SESSION_KEY: True,
                        AUTH_USER_ID_KEY: "uuid-1",
                    }
                )
            )
            self.assertTrue(
                auth_session_complete(
                    {
                        AUTH_SESSION_KEY: True,
                        AUTH_USER_ID_KEY: "uuid-1",
                        AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
                    }
                )
            )

    def test_apply_disk_state_restores_auth_snapshot(self) -> None:
        st = MagicMock()
        st.session_state = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uuid-daniel",
            AUTH_USER_EMAIL_KEY: "daniel.cohen11@yahoo.com",
            AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
            "active_page": "Saved Draft Library",
            "main_sidebar_page": "Saved Draft Library",
            "page_filter_state": {},
        }
        cloud_state = {
            "active_page": "Historical Explorer",
            "main_sidebar_page": "Historical Explorer",
            "draft_archive_teams": [{"draft_id": "d1"}],
            "page_filter_state": {},
        }
        with patch("workflow_persist_guard.merge_protected_workflow_on_restore"):
            apply_baseball_disk_state(st, cloud_state)
        self.assertTrue(st.session_state.get(AUTH_SESSION_KEY))
        self.assertEqual(st.session_state.get(AUTH_USER_ID_KEY), "uuid-daniel")
        self.assertEqual(
            st.session_state.get(AUTH_TOKENS_KEY),
            {"access_token": "a", "refresh_token": "r"},
        )

    def test_restore_auth_keeps_complete_session(self) -> None:
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uuid-daniel",
            AUTH_USER_EMAIL_KEY: "daniel.cohen11@yahoo.com",
            AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
        }
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth._sync_auth_account_identity", return_value="uuid-daniel"
        ), patch("suite_auth.enforce_workspace_ownership"), patch(
            "draft_archive_visibility.sanitize_workflow_library_for_account"
        ):
            ok = restore_auth_session(session)
        self.assertTrue(ok)
        self.assertTrue(session.get(AUTH_SESSION_KEY))

    def test_login_rejects_empty_credentials(self) -> None:
        session: dict = {}
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth._auth_api"
        ) as auth_api:
            ok, msg = login_with_email(session, email="", password="")
            self.assertFalse(ok)
            self.assertIn("email and password", msg.lower())
            auth_api.assert_not_called()

    def test_process_pending_auth_login_before_workspace(self) -> None:
        session: dict = {}
        st = MagicMock()
        st.session_state = session
        session[AUTH_PENDING_LOGIN_KEY] = {
            "email": "daniel.cohen11@yahoo.com",
            "password": "secret",
        }
        user = MagicMock()
        user.id = "uuid-daniel"
        user.email = "daniel.cohen11@yahoo.com"
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth._auth_api"
        ) as auth_api, patch(
            "suite_auth._user_from_auth_response", return_value=user
        ), patch(
            "suite_auth._tokens_from_auth_response",
            return_value={"access_token": "a", "refresh_token": "r"},
        ), patch(
            "suite_auth._sync_auth_account_identity", return_value="uuid-daniel"
        ), patch(
            "suite_workspace_registry.ensure_owned_workspace_for_session"
        ), patch(
            "suite_auth.enforce_workspace_ownership"
        ), patch(
            "suite_user_persistence.preserve_page_through_auth"
        ), patch(
            "draft_archive_visibility.sanitize_workflow_library_for_account"
        ):
            auth_api.return_value.sign_in_with_password.return_value = object()
            ok = process_pending_auth_login(st)
        self.assertTrue(ok)
        self.assertTrue(auth_session_complete(session))
        self.assertNotIn(AUTH_PENDING_LOGIN_KEY, session)

    def test_snapshot_auth_session_copies_tokens(self) -> None:
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
        }
        snap = snapshot_auth_session(session)
        self.assertEqual(snap[AUTH_TOKENS_KEY], {"access_token": "a", "refresh_token": "r"})
        snap[AUTH_TOKENS_KEY]["access_token"] = "mutated"
        self.assertEqual(session[AUTH_TOKENS_KEY]["access_token"], "a")


if __name__ == "__main__":
    unittest.main()
