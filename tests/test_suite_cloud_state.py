"""Regression tests for suite cloud save helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from suite_cloud_state import reconcile_stale_resume_session_flags, save_cloud_full_session_with_result


class SaveCloudFullSessionWithResultTests(unittest.TestCase):
    def test_resolves_without_importerror(self) -> None:
        self.assertTrue(callable(save_cloud_full_session_with_result))

    @patch("suite_storage_config.cloud_storage_enabled", return_value=True)
    @patch("suite_cloud_state.save_cloud_full_session_with_details", return_value=(True, "", "baseball"))
    @patch("suite_cloud_state.load_cloud_full_session", return_value=({}, "2026-06-25T00:00:00"))
    @patch("draft_room_state.draft_room_restore_stats", return_value={"pick_count": 4})
    def test_readback_pick_count_ok(self, _stats, _load, _save, _enabled) -> None:
        ok, err = save_cloud_full_session_with_result(
            "baseball",
            {"draft_room_state": {"board": []}},
            page="Live Draft Room",
            summary="test",
            min_draft_pick_count=4,
        )
        self.assertTrue(ok)
        self.assertEqual(err, "")

    @patch("suite_storage_config.cloud_storage_enabled", return_value=True)
    @patch("suite_cloud_state.save_cloud_full_session_with_details", return_value=(True, "", "baseball"))
    @patch("suite_cloud_state.load_cloud_full_session", return_value=({}, "2026-06-25T00:00:00"))
    @patch("draft_room_state.draft_room_restore_stats", return_value={"pick_count": 2})
    def test_readback_pick_count_mismatch(self, _stats, _load, _save, _enabled) -> None:
        ok, err = save_cloud_full_session_with_result(
            "baseball",
            {"draft_room_state": {"board": []}},
            min_draft_pick_count=4,
        )
        self.assertFalse(ok)
        self.assertIn("readback_pick_mismatch", err)

    @patch("suite_storage_config.cloud_storage_enabled", return_value=True)
    @patch(
        "suite_cloud_state.save_cloud_full_session_with_details",
        return_value=(False, "cloud_save_failed", "baseball"),
    )
    def test_cloud_save_failed(self, _save, _enabled) -> None:
        ok, err = save_cloud_full_session_with_result("baseball", {"active_page": "Home"})
        self.assertFalse(ok)
        self.assertEqual(err, "cloud_save_failed")


class ReconcileStaleResumeFlagsTests(unittest.TestCase):
    @patch("suite_cloud_state._ami_return_url_active", return_value=False)
    def test_preserves_pending_saved_draft_library_navigation(self, _ami: object) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Fantasy Lineup Assistant",
            "main_sidebar_page": "Fantasy Lineup Assistant",
            "_navigate_to_page": "Saved Draft Library",
            "_skip_page_restore_for": "Saved Draft Library",
            "_suite_resume_launch_baseball": True,
        }
        cleared = reconcile_stale_resume_session_flags(st, "baseball")
        self.assertNotIn("_navigate_to_page", cleared)
        self.assertNotIn("_skip_page_restore_for", cleared)
        self.assertEqual(st.session_state["_navigate_to_page"], "Saved Draft Library")
        self.assertEqual(st.session_state["_skip_page_restore_for"], "Saved Draft Library")
        self.assertIn("_suite_resume_launch_baseball", cleared)

    @patch("suite_cloud_state._ami_return_url_active", return_value=False)
    def test_clears_stale_navigate_to_page_when_already_on_target(self, _ami: object) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Saved Draft Library",
            "main_sidebar_page": "Saved Draft Library",
            "_navigate_to_page": "Saved Draft Library",
        }
        cleared = reconcile_stale_resume_session_flags(st, "baseball")
        self.assertIn("_navigate_to_page", cleared)
        self.assertNotIn("_navigate_to_page", st.session_state)


if __name__ == "__main__":
    unittest.main()
