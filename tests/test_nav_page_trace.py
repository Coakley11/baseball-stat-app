"""Tests for Daniel nav assignment trace + body page resolve."""

from __future__ import annotations

import unittest

from nav_page_trace import (
    assign_nav_key,
    format_nav_trace_text,
    is_nav_page_trace_enabled,
    resolve_body_page,
)


class NavPageTraceTests(unittest.TestCase):
    def test_enabled_for_daniel_workspace(self) -> None:
        ss = {"_suite_active_workspace_id": "daniel"}
        self.assertTrue(is_nav_page_trace_enabled(ss))

    def test_disabled_for_coakley(self) -> None:
        ss = {
            "_suite_active_workspace_id": "coakley11",
            "_suite_auth_username": "coakley11",
        }
        self.assertFalse(is_nav_page_trace_enabled(ss))

    def test_assign_logs_previous_and_new(self) -> None:
        ss = {"_suite_active_workspace_id": "daniel", "active_page": "Historical Explorer"}
        assign_nav_key(
            ss,
            "active_page",
            "Live Draft Room",
            function="unit_test",
            reason="click",
        )
        self.assertEqual(ss["active_page"], "Live Draft Room")
        text = format_nav_trace_text(ss)
        self.assertIn("unit_test", text)
        self.assertIn("Historical Explorer", text)
        self.assertIn("Live Draft Room", text)

    def test_resolve_prefers_sidebar_when_active_stale(self) -> None:
        ss = {
            "_suite_active_workspace_id": "daniel",
            "active_page": "Historical Explorer",
            "main_sidebar_page": "Live Draft Room",
            "_suite_user_owned_page": "Live Draft Room",
            "_suite_page_user_nav": True,
        }
        winner = resolve_body_page(
            ss,
            radio_selected="Live Draft Room",
            normalize_page_key=lambda v: str(v or "").strip(),
            function="unit_test.resolve",
        )
        self.assertEqual(winner, "Live Draft Room")
        self.assertEqual(ss["active_page"], "Live Draft Room")


if __name__ == "__main__":
    unittest.main()
