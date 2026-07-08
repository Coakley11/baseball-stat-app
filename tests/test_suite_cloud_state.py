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
    @patch(
        "suite_cloud_state.verify_cloud_draft_room_readback",
        return_value={"ok": True, "pick_count": 4, "cloud_app_key": "baseball", "selected_row_user_id": "user-1"},
    )
    def test_readback_pick_count_ok(self, _verify, _save, _enabled) -> None:
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
    @patch(
        "suite_cloud_state.verify_cloud_draft_room_readback",
        return_value={
            "ok": False,
            "pick_count": 0,
            "cloud_app_key": "baseball",
            "workspace_id": "daniel",
            "selected_row_user_id": "user-1",
            "error": "readback_pick_count_0_lt_4",
        },
    )
    def test_readback_pick_count_mismatch(self, _verify, _save, _enabled) -> None:
        ok, err = save_cloud_full_session_with_result(
            "baseball",
            {"draft_room_state": {"board": []}},
            min_draft_pick_count=4,
        )
        self.assertFalse(ok)
        self.assertIn("readback_pick_mismatch", err)
        self.assertIn("key=baseball", err)

    @patch("suite_storage_config.cloud_storage_enabled", return_value=True)
    @patch("suite_cloud_state.save_cloud_full_session_with_details", return_value=(True, "", "baseball"))
    def test_readback_blocks_workflow_fallback_with_picks(self, _save, _enabled) -> None:
        with patch("suite_cloud_state._streamlit_session", return_value={"_suite_cloud_write_used_workflow_fallback": True}):
            ok, err = save_cloud_full_session_with_result(
                "baseball",
                {"draft_room_state": {}},
                min_draft_pick_count=4,
            )
        self.assertFalse(ok)
        self.assertIn("workflow_fallback_omitted_draft_room_picks", err)

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


class DraftLibrarySliceTests(unittest.TestCase):
    def test_slice_includes_empty_archives_and_tombstones(self) -> None:
        from suite_cloud_state import _draft_library_slice_from_state

        state = {
            "draft_archive_teams": [],
            "_deleted_draft_archive_ids": ["gone01"],
        }
        slice_out = _draft_library_slice_from_state(state)
        self.assertEqual(slice_out.get("draft_archive_teams"), [])
        self.assertEqual(slice_out.get("_deleted_draft_archive_ids"), ["gone01"])


if __name__ == "__main__":
    unittest.main()
