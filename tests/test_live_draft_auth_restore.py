"""Auth-scoped live draft restore and single-user free pool drafting."""

from __future__ import annotations

import unittest
from unittest import mock

from draft_source_validation import allow_free_pool_drafting
from live_draft_state import live_draft_restore_allowed, workspace_blob_owned_by_session
from suite_auth import allowed_workspaces_for_user
from suite_workspace import normalize_workspace_id


class LiveDraftAuthRestoreTests(unittest.TestCase):
    def test_coakley_workspace_not_daniel(self) -> None:
        self.assertEqual(normalize_workspace_id("coakley11"), "coakley11")
        allowed = allowed_workspaces_for_user("coakley11")
        self.assertIn("coakley11", allowed)
        self.assertNotIn("daniel", allowed)

    def test_legacy_unowned_blob_blocked_for_coakley(self) -> None:
        session = {"_suite_auth_session": True, "_suite_auth_user_id": "uuid-coakley"}
        blob = {"draft_room_id": "room-1", "status": "in_progress", "draft_board": []}
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            with mock.patch("live_draft_state._current_auth_user_id", return_value="uuid-coakley"):
                with mock.patch("live_draft_state._current_auth_external_id", return_value="coakley11"):
                    with mock.patch("live_draft_state._current_workspace_id", return_value="coakley11"):
                        allowed, reason = live_draft_restore_allowed(session, blob, source="test")
        self.assertFalse(allowed)
        self.assertEqual(reason, "legacy_unowned_foreign_blob")

    def test_owned_blob_allowed_for_matching_auth(self) -> None:
        session = {"_suite_auth_session": True, "_suite_auth_user_id": "uuid-coakley"}
        blob = {
            "draft_room_id": "room-1",
            "status": "in_progress",
            "draft_board": [],
            "owner_auth_user_id": "uuid-coakley",
        }
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            with mock.patch("live_draft_state._current_auth_user_id", return_value="uuid-coakley"):
                allowed, reason = live_draft_restore_allowed(session, blob, source="test")
        self.assertTrue(allowed)
        self.assertEqual(reason, "auth_owner_match")

    def test_foreign_daniel_workspace_blob_rejected(self) -> None:
        session = {"_suite_auth_session": True, "_suite_auth_user_id": "uuid-coakley"}
        state = {"room_your_team": "Daniel"}
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            with mock.patch("live_draft_state._current_auth_external_id", return_value="coakley11"):
                with mock.patch("live_draft_state._current_workspace_id", return_value="daniel"):
                    owned, reason = workspace_blob_owned_by_session(session, state)
        self.assertFalse(owned)
        self.assertEqual(reason, "foreign_daniel_workspace")

    def test_single_user_live_allows_free_pool_even_when_flag_false(self) -> None:
        session = {"allow_free_pool_drafting": False}
        self.assertTrue(allow_free_pool_drafting(session, live_room={"config": {}}))


if __name__ == "__main__":
    unittest.main()
