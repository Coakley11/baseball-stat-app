"""Sidebar idempotency guards — one account / CC / saved-session block per run."""

from __future__ import annotations

import unittest

from suite_sidebar_run import (
    GUARD_ACCOUNT,
    GUARD_COMMAND_CENTER,
    GUARD_DEV_TOGGLE,
    claim_sidebar_render,
    reset_sidebar_run_guards,
    reset_sidebar_run_guards_for_tests,
)


class SidebarRunGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_sidebar_run_guards_for_tests()

    def test_claim_once_per_run_after_reset(self) -> None:
        ss: dict = {}
        reset_sidebar_run_guards(ss)
        self.assertTrue(claim_sidebar_render(ss, GUARD_ACCOUNT))
        self.assertFalse(claim_sidebar_render(ss, GUARD_ACCOUNT))

    def test_dev_toggle_guard_blocks_second_claim_same_execution(self) -> None:
        ss: dict = {}
        reset_sidebar_run_guards(ss)
        self.assertTrue(claim_sidebar_render(ss, GUARD_DEV_TOGGLE))
        self.assertFalse(claim_sidebar_render(ss, GUARD_DEV_TOGGLE))

    def test_session_flag_reset_does_not_allow_duplicate_claim_same_execution(self) -> None:
        ss: dict = {}
        reset_sidebar_run_guards(ss)
        self.assertTrue(claim_sidebar_render(ss, GUARD_DEV_TOGGLE))
        ss[GUARD_DEV_TOGGLE] = False
        self.assertFalse(claim_sidebar_render(ss, GUARD_DEV_TOGGLE))

    def test_reset_allows_next_run(self) -> None:
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
