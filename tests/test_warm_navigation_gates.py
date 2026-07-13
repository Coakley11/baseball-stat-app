"""Warm-navigation gates — skip full cloud save/hydrate on clean page hops."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from baseball_persistent_state import prepare_baseball_workspace
from deployed_page_timing import WARM_TARGETS_MS, summarize_deployed_page_timing
from draft_archive_state import rename_draft_archive
from draft_library_manifest import (
    install_test_manifest_cloud_store,
    publish_library_manifest_to_cloud,
    sync_library_manifest_from_cloud,
)
from page_render_timing import finish_page_render, mark_navigation_start, record_milestone
from suite_user_persistence import _FORCE_SAVE_CLOUD_REASONS, _local_dirty_key


class WarmNavigationGateTests(unittest.TestCase):
    def test_page_change_not_force_cloud_reason(self) -> None:
        self.assertNotIn("page_change", _FORCE_SAVE_CLOUD_REASONS)

    def test_warm_fp_stable_when_library_manifest_revision_changes(self) -> None:
        st = MagicMock()
        ss: dict = {
            "_suite_auth_user_id": "daniel",
            "_suite_active_workspace_id": "daniel",
            "_suite_cloud_session_revision": "rev1",
            "draft_archive_teams": [{"draft_id": "abc"}],
            "_library_manifest_revision": 1,
            "_ws_synced": True,
        }
        st.session_state = ss
        with patch("suite_user_persistence._workspace_synced_key", return_value="_ws_synced"):
            with patch(
                "baseball_persistent_state.sync_workspace_protocol",
                return_value=True,
            ) as sync_mock:
                with patch("baseball_persistent_state.WORKSPACE_SCHEMA_VERSION", 1):
                    prepare_baseball_workspace(st)
                    self.assertFalse(ss.get("_baseball_warm_startup_skipped"))
                    cold_calls = sync_mock.call_count
                    self.assertGreaterEqual(cold_calls, 1)
                    # Manifest revision bump must not break warm skip.
                    ss["_library_manifest_revision"] = 99
                    prepare_baseball_workspace(st)
                    self.assertTrue(ss.get("_baseball_warm_startup_skipped"))
                    self.assertEqual(sync_mock.call_count, cold_calls)

    def test_deployed_timing_summary_includes_warm_flags(self) -> None:
        session: dict = {"_baseball_warm_startup_skipped": True, "_suite_page_change_save_skipped": "clean_warm_nav"}
        mark_navigation_start(session, "Saved Draft Library")
        record_milestone(session, "Saved Draft Library", "main_content_interactive")
        finish_page_render(session, "Saved Draft Library")
        summary = summarize_deployed_page_timing(session, "Saved Draft Library")
        self.assertTrue(summary.get("warm_startup_skipped"))
        self.assertEqual(summary.get("page_change_save_skipped"), "clean_warm_nav")
        self.assertEqual(summary.get("warm_target_ms"), WARM_TARGETS_MS["Saved Draft Library"])
        self.assertIn("main_content_interactive", summary.get("milestones_ms") or {})

    def test_rename_display_name_syncs_via_manifest(self) -> None:
        store: dict = {}
        install_test_manifest_cloud_store(store)
        phone = {
            "_suite_auth_user_id": "daniel",
            "_suite_active_workspace_id": "daniel",
            "draft_archive_teams": [
                {
                    "draft_id": "test_noncanonical_01",
                    "draft_name": "Temp Rename Subject",
                    "created_at": "2026-07-01T12:00:00+00:00",
                    "content_updated_at": "2026-07-01T12:00:00+00:00",
                    "content_revision": 1,
                }
            ],
        }
        dell = {
            "_suite_auth_user_id": "daniel",
            "_suite_active_workspace_id": "daniel",
            "draft_archive_teams": [
                {
                    "draft_id": "test_noncanonical_01",
                    "draft_name": "Temp Rename Subject",
                    "created_at": "2026-07-01T12:00:00+00:00",
                    "content_updated_at": "2026-07-01T12:00:00+00:00",
                    "content_revision": 1,
                }
            ],
        }
        publish_library_manifest_to_cloud(phone)
        rename_draft_archive(phone, "test_noncanonical_01", "Temp Rename Subject — Phone")
        sync_library_manifest_from_cloud(dell, force=True)
        self.assertEqual(dell["draft_archive_teams"][0]["draft_name"], "Temp Rename Subject — Phone")
        install_test_manifest_cloud_store(None)


class CleanPageChangeSaveSkipTests(unittest.TestCase):
    def test_dirty_key_name(self) -> None:
        self.assertEqual(_local_dirty_key("baseball"), "_suite_persist_local_dirty::baseball")


if __name__ == "__main__":
    unittest.main()
