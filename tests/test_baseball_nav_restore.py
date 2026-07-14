"""Tests for workspace restore not clobbering scheduled page navigation."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from baseball_persistent_state import apply_baseball_disk_state


class BaseballNavRestoreTests(unittest.TestCase):
    def test_apply_preserves_scheduled_navigation_target(self) -> None:
        ss = {
            "active_page": "Waiver Wire / Add-Drop Center",
            "main_sidebar_page": "Waiver Wire / Add-Drop Center",
            "_navigate_to_page": "Saved Draft Library",
            "_skip_page_restore_for": "Saved Draft Library",
            "_suite_page_user_nav": True,
        }
        st_obj = SimpleNamespace(session_state=ss)
        apply_baseball_disk_state(
            st_obj,
            {"active_page": "Waiver Wire / Add-Drop Center"},
        )
        self.assertEqual(ss["active_page"], "Saved Draft Library")
        self.assertEqual(ss["_navigate_to_page"], "Saved Draft Library")
        self.assertEqual(ss.get("_suite_page_overwrite_source"), "scheduled_navigation_preserved")

    def test_apply_honors_consumed_navigation_target(self) -> None:
        ss = {
            "active_page": "Waiver Wire / Add-Drop Center",
            "main_sidebar_page": "Waiver Wire / Add-Drop Center",
            "_suite_nav_consumed_target": "Saved Draft Library",
            "_suite_nav_consumed_this_run": True,
        }
        st_obj = SimpleNamespace(session_state=ss)
        apply_baseball_disk_state(
            st_obj,
            {"active_page": "Waiver Wire / Add-Drop Center"},
        )
        self.assertEqual(ss["active_page"], "Saved Draft Library")
        self.assertEqual(ss["main_sidebar_page"], "Saved Draft Library")
        self.assertEqual(ss.get("_suite_page_overwrite_source"), "nav_consumed_preserved")

    def test_apply_clears_sticky_same_page_navigate(self) -> None:
        ss = {
            "active_page": "Historical Explorer",
            "main_sidebar_page": "Historical Explorer",
            "_navigate_to_page": "Historical Explorer",
        }
        st_obj = SimpleNamespace(session_state=ss)
        apply_baseball_disk_state(
            st_obj,
            {"active_page": "Historical Explorer"},
        )
        self.assertEqual(ss["active_page"], "Historical Explorer")
        self.assertNotIn("_navigate_to_page", ss)

    def test_sidebar_nav_beats_stale_skip_for_historical_explorer(self) -> None:
        """Daniel-style workspace: durable skip must not override a sidebar hop."""
        ss = {
            "active_page": "Live Draft Room",
            "main_sidebar_page": "Live Draft Room",
            "_suite_page_user_nav": True,
            "_suite_user_owned_page": "Live Draft Room",
            "active_page_source": "user_sidebar",
            # Leftover skip from an old full_session / prior restore.
            "_skip_page_restore_for": "Historical Explorer",
            "_suite_last_persisted_page": "Historical Explorer",
        }
        st_obj = SimpleNamespace(session_state=ss)
        apply_baseball_disk_state(
            st_obj,
            {
                "active_page": "Historical Explorer",
                "_skip_page_restore_for": "Historical Explorer",
            },
        )
        self.assertEqual(ss["active_page"], "Live Draft Room")
        self.assertEqual(ss["main_sidebar_page"], "Live Draft Room")
        self.assertEqual(ss.get("_suite_page_overwrite_source"), "user_page_preserved")
        self.assertNotEqual(ss.get("_skip_page_restore_for"), "Historical Explorer")


if __name__ == "__main__":
    unittest.main()
