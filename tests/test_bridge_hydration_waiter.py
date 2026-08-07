"""Tests for AUTH_HYDRATE7 bridge hydration waiter helpers."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from bridge_hydration_waiter import (  # noqa: E402
    bound_bridge_hydration_passes,
    detect_restore_rerun_anomaly,
    hydration_fail_fast_from_restore_exit,
    latest_hydration_checkpoint,
    resolve_real_accounts_wake,
)
from playwright_auth_bridge_restore_harness import resolve_real_accounts_wake as harness_wake  # noqa: E402


def _row(checkpoint: str, **extra: object) -> dict:
    base = {
        "event": "production_stage1_auth_prestart_hydration",
        "checkpoint": checkpoint,
        "streamlit_session_id": "aaaa-bbbb",
        "diagnostic_run_id": "run1",
        "script_run_seq": 1,
        "event_index": 1,
    }
    base.update(extra)
    return base


class BridgeHydrationWaiterTests(unittest.TestCase):
    def test_real_accounts_wake_off_by_default_in_bridge_mode(self) -> None:
        os.environ.pop("BRIDGE_RESTORE_REAL_ACCOUNTS_WAKE", None)
        self.assertFalse(resolve_real_accounts_wake(bridge_restore_mode=True))
        self.assertFalse(harness_wake(bridge_restore_mode=True))

    def test_real_accounts_wake_on_for_non_bridge_by_default(self) -> None:
        os.environ.pop("BRIDGE_RESTORE_REAL_ACCOUNTS_WAKE", None)
        self.assertTrue(resolve_real_accounts_wake(bridge_restore_mode=False))

    def test_real_accounts_wake_env_override(self) -> None:
        os.environ["BRIDGE_RESTORE_REAL_ACCOUNTS_WAKE"] = "1"
        try:
            self.assertTrue(resolve_real_accounts_wake(bridge_restore_mode=True))
        finally:
            os.environ.pop("BRIDGE_RESTORE_REAL_ACCOUNTS_WAKE", None)

    def test_bound_pass_requires_dom_complete_and_start(self) -> None:
        bound = {
            "session_flag_present": True,
            "is_authenticated": True,
            "auth_session_complete": True,
            "current_restore_blocked_reason": "",
            "apply_authenticated_user_ok": True,
        }
        self.assertTrue(
            bound_bridge_hydration_passes(
                bound,
                suite_sid="sid-1",
                url_sid="sid-1",
                bridge_load_ok=True,
                start_enabled=True,
            )
        )

    def test_bound_pass_fails_on_wrong_suite_sid(self) -> None:
        bound = {
            "session_flag_present": True,
            "is_authenticated": True,
            "auth_session_complete": True,
            "current_restore_blocked_reason": "",
            "apply_authenticated_user_ok": True,
        }
        self.assertFalse(
            bound_bridge_hydration_passes(
                bound,
                suite_sid="sid-1",
                url_sid="sid-2",
                bridge_load_ok=True,
                start_enabled=True,
            )
        )

    def test_bound_pass_fails_when_stale_false_auth_would_block(self) -> None:
        bound = {
            "session_flag_present": True,
            "is_authenticated": False,
            "auth_session_complete": True,
            "current_restore_blocked_reason": "",
            "apply_authenticated_user_ok": True,
        }
        self.assertFalse(
            bound_bridge_hydration_passes(
                bound,
                suite_sid="s",
                url_sid="s",
                bridge_load_ok=True,
                start_enabled=True,
            )
        )

    def test_fail_fast_auth_api_error(self) -> None:
        reason = hydration_fail_fast_from_restore_exit(
            {"skip_or_failure_reason": "exception:AuthApiError"}
        )
        self.assertIn("AuthApiError", reason)

    def test_missing_provider_history_does_not_block_bound_pass(self) -> None:
        bound = {
            "session_flag_present": True,
            "is_authenticated": True,
            "auth_session_complete": True,
            "current_restore_blocked_reason": "",
            "apply_authenticated_user_ok": None,
        }
        self.assertTrue(
            bound_bridge_hydration_passes(
                bound,
                suite_sid="x",
                url_sid="x",
                bridge_load_ok=True,
                start_enabled=True,
            )
        )

    def test_restore_ok_plus_current_dom_passes(self) -> None:
        ledger = [
            _row(
                "load_browser_auth_tokens_lookup",
                access_token_present=True,
                refresh_token_present=True,
                rejection_reason="",
            ),
            _row("restore_auth_session_exit", skip_or_failure_reason="ok", authenticated_after=True),
        ]
        self.assertTrue(
            latest_hydration_checkpoint(ledger, "restore_auth_session_exit", streamlit_session_id="aaaa-bbbb")[
                "skip_or_failure_reason"
            ]
            == "ok"
        )

    def test_rerun_anomaly_after_successful_ok(self) -> None:
        ledger = [
            _row("restore_auth_session_exit", skip_or_failure_reason="ok", script_run_seq=1, event_index=1),
            _row("restore_auth_session_exit", skip_or_failure_reason="ok", script_run_seq=2, event_index=2),
        ]
        anomaly = detect_restore_rerun_anomaly(ledger, streamlit_session_id="aaaa-bbbb")
        self.assertTrue(anomaly["rerun_anomaly"])
        self.assertEqual(anomaly["restore_after_successful_ok_count"], 1)


if __name__ == "__main__":
    unittest.main()
