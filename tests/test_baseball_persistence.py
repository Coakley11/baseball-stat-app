"""Tests for Baseball cross-device persistence snapshot."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from baseball_persistent_state import (
    _workspace_restore_cloud_first,
    apply_baseball_disk_state,
    build_baseball_disk_state,
)


class TestWorkspaceRestoreCloudFirst(unittest.TestCase):
    def test_cloud_first_when_cloud_enabled_even_in_demo(self) -> None:
        with patch("suite_storage_config.cloud_storage_enabled", return_value=True):
            with patch("suite_auth.is_auth_enabled", return_value=True):
                with patch("suite_auth.is_authenticated", return_value=False):
                    self.assertTrue(_workspace_restore_cloud_first({}))

    def test_disk_first_only_when_cloud_disabled(self) -> None:
        with patch("suite_storage_config.cloud_storage_enabled", return_value=False):
            self.assertFalse(_workspace_restore_cloud_first({}))


class TestBaseballPersistence(unittest.TestCase):
    def test_build_disk_state_snapshots_active_page_filters(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Comparison Tool",
            "page_filter_state": {},
            "sig_player_a_clean": "Juan Soto (NYY)",
            "sig_player_b_clean": "Francisco Lindor (NYM)",
            "compare_players": ["Juan Soto (NYY)", "Francisco Lindor (NYM)"],
            "compare_stat": "OPS",
            "comparison_state": {
                "players": ["Juan Soto (NYY)", "Francisco Lindor (NYM)"],
                "player_a": "Juan Soto (NYY)",
                "player_b": "Francisco Lindor (NYM)",
            },
        }
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob.get("active_page"), "Comparison Tool")
        meta = blob.get("baseball_workspace_state") or {}
        self.assertEqual(meta.get("page"), "Comparison Tool")
        self.assertEqual(meta.get("schema_version"), 1)
        self.assertTrue(meta.get("device_id"))
        top_cs = blob.get("comparison_state") or {}
        self.assertEqual(top_cs.get("players"), ["Juan Soto (NYY)", "Francisco Lindor (NYM)"])
        pf = blob.get("page_filter_state") or {}
        cmp = pf.get("Comparison Tool") or {}
        self.assertEqual(cmp.get("sig_player_a_clean"), "Juan Soto (NYY)")
        self.assertEqual(
            cmp.get("compare_players"),
            ["Juan Soto (NYY)", "Francisco Lindor (NYM)"],
        )

    def test_build_disk_state_includes_career_state(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Career Totals",
            "page_filter_state": {},
            "career_state": {
                "filters": {
                    "career_year_range_filter": (2010, 2024),
                    "career_sort_stat_filter": "HR",
                }
            },
            "career_year_range_filter": (2010, 2024),
            "career_sort_stat_filter": "HR",
        }
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob.get("career_state", {}).get("filters", {}).get("career_sort_stat_filter"), "HR")
        meta = blob.get("baseball_workspace_state") or {}
        self.assertEqual(meta.get("career_filters", {}).get("career_sort_stat_filter"), "HR")

    def test_apply_disk_state_sets_navigation_and_players(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Trend Value",
            "main_sidebar_page": "Trend Value",
            "page_filter_state": {"Trend Value": {"trend_players_multi": ["Aaron Judge"]}},
            "trend_players_multi": ["Aaron Judge"],
            "_page_state_last_active": "Trend Value",
        }
        cloud_state = {
            "active_page": "Comparison Tool",
            "page_filter_state": {
                "Comparison Tool": {
                    "sig_player_a_clean": "Juan Soto (NYY)",
                    "sig_player_b_clean": "Francisco Lindor (NYM)",
                    "compare_players": ["Juan Soto (NYY)", "Francisco Lindor (NYM)"],
                }
            },
        }
        apply_baseball_disk_state(st, cloud_state)
        ss = st.session_state
        self.assertEqual(ss["active_page"], "Comparison Tool")
        self.assertEqual(ss["main_sidebar_page"], "Comparison Tool")
        # Same-page restore must not leave a sticky schedule (fights sidebar clicks).
        self.assertNotIn("_navigate_to_page", ss)
        self.assertEqual(ss["sig_player_a_clean"], "Juan Soto (NYY)")
        self.assertEqual(ss["sig_player_b_clean"], "Francisco Lindor (NYM)")
        self.assertTrue(ss.get("_suite_cloud_workspace_applied"))

    def test_apply_disk_state_preserves_scheduled_saved_draft_library_navigation(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Fantasy Lineup Assistant",
            "main_sidebar_page": "Fantasy Lineup Assistant",
            "page_filter_state": {},
            "_navigate_to_page": "Saved Draft Library",
            "_skip_page_restore_for": "Saved Draft Library",
            "_saved_draft_library_return_page": "Fantasy Lineup Assistant",
        }
        cloud_state = {
            "active_page": "Fantasy Lineup Assistant",
            "page_filter_state": {},
        }
        apply_baseball_disk_state(st, cloud_state)
        ss = st.session_state
        self.assertEqual(ss["active_page"], "Saved Draft Library")
        self.assertEqual(ss["main_sidebar_page"], "Saved Draft Library")
        self.assertEqual(ss["_navigate_to_page"], "Saved Draft Library")
        self.assertEqual(ss.get("_suite_page_overwrite_source"), "scheduled_navigation_preserved")

    def test_apply_disk_state_skips_empty_archives_when_cloud_has_drafts(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Historical Explorer",
            "main_sidebar_page": "Historical Explorer",
            "page_filter_state": {},
        }
        cloud_state = {
            "active_page": "Historical Explorer",
            "page_filter_state": {},
            "draft_archive_teams": [],
        }
        persisted = {
            "draft_archive_teams": [{"draft_id": "cloud01", "draft_name": "Cloud Draft"}],
        }
        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value={}):
            with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value=persisted):
                apply_baseball_disk_state(st, cloud_state)
        ss = st.session_state
        self.assertEqual(len(ss.get("draft_archive_teams") or []), 1)
        self.assertEqual(ss["draft_archive_teams"][0]["draft_id"], "cloud01")


class TestSettingsCloudSaveNotBlocked(unittest.TestCase):
    """Settings-change saves must reach the cloud even when workspace sync was skipped.

    Regression for: draft settings + league format reverted on refresh because
    their save reasons were missing from _FORCE_SAVE_CLOUD_REASONS, so the cloud
    write was blocked ("workspace_sync_not_applied") while only local disk saved.
    Historical/career chart saves (historical_edit/career_edit) were in the set,
    which is why charts persisted but draft settings/format did not.
    """

    SETTINGS_REASONS = (
        "draft_room_settings_changed",
        "live_draft_setting_changed",
        "draft_sim_settings_changed",
        "draft_assistant_settings_changed",
        "fantasy_context_source_changed",
        "global_settings_changed",
        "historical_chart_save",
        "career_chart_save",
    )

    def test_settings_reasons_in_force_save_cloud_reasons(self) -> None:
        from suite_user_persistence import _FORCE_SAVE_CLOUD_REASONS

        for reason in self.SETTINGS_REASONS:
            self.assertIn(reason, _FORCE_SAVE_CLOUD_REASONS, msg=reason)

    def test_settings_reasons_not_cloud_blocked_when_sync_skipped(self) -> None:
        from suite_user_persistence import _cloud_autosave_blocked_reason

        for reason in self.SETTINGS_REASONS:
            st = MagicMock()
            st.session_state = {"_suite_workspace_sync_skipped_no_apply": True}
            blocked = _cloud_autosave_blocked_reason(
                st, "baseball", {"active_page": "Draft Room Simulator"}, save_reason=reason
            )
            self.assertIsNone(blocked, msg=f"{reason} should not be cloud-blocked")


if __name__ == "__main__":
    unittest.main()
