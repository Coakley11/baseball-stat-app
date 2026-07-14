"""Tests for fantasy workflow init tracing and prefs rerun gate."""

from __future__ import annotations

import time
import unittest

from fantasy_workflow_trace import (
    mark_fantasy_page_enter,
    prefs_app_rerun_allowed,
)


class FantasyWorkflowTraceTests(unittest.TestCase):
    def test_page_enter_suppresses_prefs_rerun(self) -> None:
        ss = {
            "_suite_active_workspace_id": "daniel",
            "active_page": "Live Draft Room",
        }
        mark_fantasy_page_enter(ss, "Live Draft Room")
        allowed, reason = prefs_app_rerun_allowed(ss)
        self.assertFalse(allowed)
        self.assertIn("suppress", reason)

    def test_cooldown_blocks_repeat_rerun(self) -> None:
        ss = {
            "_suite_active_workspace_id": "daniel",
            "_account_fantasy_prefs_last_app_rerun_at": time.time(),
        }
        allowed, reason = prefs_app_rerun_allowed(ss)
        self.assertFalse(allowed)
        self.assertEqual(reason, "cooldown_20s")


if __name__ == "__main__":
    unittest.main()
