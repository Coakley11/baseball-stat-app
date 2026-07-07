"""Sign-in must not bounce the user off their current page."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from baseball_persistent_state import apply_baseball_disk_state
from suite_user_persistence import (
    AUTH_PAGE_PRESERVE_KEY,
    SESSION_USER_OWNED_PAGE_KEY,
    preserve_page_through_auth,
)


class AuthPagePreserveTests(unittest.TestCase):
    def test_preserve_page_through_auth_captures_current_page(self) -> None:
        session = {
            "active_page": "Saved Draft Library",
            "main_sidebar_page": "Saved Draft Library",
            "_suite_last_persisted_page": "Saved Draft Library",
        }
        page = preserve_page_through_auth(session)
        self.assertEqual(page, "Saved Draft Library")
        self.assertEqual(session.get(AUTH_PAGE_PRESERVE_KEY), "Saved Draft Library")
        self.assertEqual(session.get(SESSION_USER_OWNED_PAGE_KEY), "Saved Draft Library")
        self.assertTrue(session.get("_suite_workspace_force_sync"))
        self.assertNotIn("_suite_workspace_synced::baseball", session)

    def test_apply_restore_keeps_auth_preserved_page(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Saved Draft Library",
            "main_sidebar_page": "Saved Draft Library",
            "_suite_last_persisted_page": "Saved Draft Library",
            AUTH_PAGE_PRESERVE_KEY: "Saved Draft Library",
            SESSION_USER_OWNED_PAGE_KEY: "Saved Draft Library",
            "active_page_source": "auth_preserve",
        }
        cloud_state = {
            "active_page": "Historical Explorer",
            "main_sidebar_page": "Historical Explorer",
            "draft_archive_teams": [{"draft_id": "d1"}],
            "page_filter_state": {},
        }
        with patch("workflow_persist_guard.merge_protected_workflow_on_restore"):
            apply_baseball_disk_state(st, cloud_state)
        self.assertEqual(st.session_state.get("active_page"), "Saved Draft Library")
        self.assertEqual(st.session_state.get("main_sidebar_page"), "Saved Draft Library")
        self.assertEqual(st.session_state.get("_suite_page_overwrite_source"), "auth_page_preserved")

    def test_persist_auth_session_preserves_page(self) -> None:
        from suite_auth import _persist_auth_session

        session: dict = {
            "active_page": "Saved Draft Library",
            "main_sidebar_page": "Saved Draft Library",
        }
        user = MagicMock()
        user.id = "auth-user-1"
        user.email = "coach@example.com"
        user.user_metadata = {}
        tokens = {"access_token": "a", "refresh_token": "r"}
        with patch("suite_auth._apply_authenticated_user") as apply_user:
            apply_user.side_effect = lambda ss, _u, **_kw: ss.update(
                {"_suite_auth_user_id": "auth-user-1", "_suite_auth_user_email": "coach@example.com"}
            )
            with patch("suite_storage_supabase.ensure_user_row", return_value="suite-uuid"):
                with patch("suite_workspace_registry.ensure_owned_workspace_for_session"):
                    with patch("suite_auth.enforce_workspace_ownership"):
                        with patch("suite_user.reset_account_cache"):
                            _persist_auth_session(session, user=user, tokens=tokens)
        self.assertEqual(session.get("active_page"), "Saved Draft Library")
        self.assertEqual(session.get(AUTH_PAGE_PRESERVE_KEY), "Saved Draft Library")


if __name__ == "__main__":
    unittest.main()
