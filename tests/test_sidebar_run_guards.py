"""Sidebar idempotency guards — one account / CC / saved-session block per run."""

from __future__ import annotations

import unittest

from suite_sidebar_run import (
    GUARD_ACCOUNT,
    GUARD_COMMAND_CENTER,
    reset_sidebar_run_guards,
    claim_sidebar_render,
)


class SidebarRunGuardTests(unittest.TestCase):
    def test_claim_once_per_run_after_reset(self) -> None:
        ss: dict = {}
        reset_sidebar_run_guards(ss)
        self.assertTrue(claim_sidebar_render(ss, GUARD_ACCOUNT))
        self.assertFalse(claim_sidebar_render(ss, GUARD_ACCOUNT))

    def test_reset_allows_next_run(self) -> None:
        ss: dict = {}
        reset_sidebar_run_guards(ss)
        self.assertTrue(claim_sidebar_render(ss, GUARD_COMMAND_CENTER))
        reset_sidebar_run_guards(ss)
        self.assertTrue(claim_sidebar_render(ss, GUARD_COMMAND_CENTER))


if __name__ == "__main__":
    unittest.main()
