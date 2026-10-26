"""Sidebar idempotency guards — one account / CC / saved-session block per run."""

from __future__ import annotations

import unittest
from threading import Event, Thread

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
        """Regression: after sign-in / next script run, chrome must remount."""
        ss: dict = {}
        reset_sidebar_run_guards(ss)
        self.assertTrue(claim_sidebar_render(ss, GUARD_COMMAND_CENTER))
        self.assertTrue(claim_sidebar_render(ss, GUARD_DEV_TOGGLE))
        # Simulate next script run (same process / same browser session).
        reset_sidebar_run_guards(ss)
        self.assertTrue(claim_sidebar_render(ss, GUARD_COMMAND_CENTER))
        self.assertTrue(claim_sidebar_render(ss, GUARD_DEV_TOGGLE))

    def test_reset_clears_dev_checkbox_materialized(self) -> None:
        from suite_sidebar_run import mark_dev_mode_checkbox_materialized, dev_mode_checkbox_materialized

        ss: dict = {}
        reset_sidebar_run_guards(ss)
        self.assertTrue(claim_sidebar_render(ss, GUARD_DEV_TOGGLE))
        mark_dev_mode_checkbox_materialized(ss)
        self.assertTrue(dev_mode_checkbox_materialized(ss))
        reset_sidebar_run_guards(ss)
        self.assertFalse(dev_mode_checkbox_materialized(ss))
        self.assertTrue(claim_sidebar_render(ss, GUARD_DEV_TOGGLE))

    def test_concurrent_sessions_do_not_suppress_each_other(self) -> None:
        """Interleave reset/claim so the former process-global guard would fail."""
        session_a: dict = {}
        session_b: dict = {}
        a_reset = Event()
        b_claimed = Event()
        claims: dict[str, bool] = {}

        def run_a() -> None:
            reset_sidebar_run_guards(session_a)
            a_reset.set()
            self.assertTrue(b_claimed.wait(timeout=2))
            claims["a"] = claim_sidebar_render(session_a, GUARD_ACCOUNT)

        def run_b() -> None:
            self.assertTrue(a_reset.wait(timeout=2))
            reset_sidebar_run_guards(session_b)
            claims["b"] = claim_sidebar_render(session_b, GUARD_ACCOUNT)
            b_claimed.set()

        threads = (Thread(target=run_a), Thread(target=run_b))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

        self.assertEqual(claims, {"a": True, "b": True})
        self.assertFalse(claim_sidebar_render(session_a, GUARD_ACCOUNT))
        self.assertFalse(claim_sidebar_render(session_b, GUARD_ACCOUNT))


if __name__ == "__main__":
    unittest.main()
