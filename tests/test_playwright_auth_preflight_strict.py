"""Unit tests for strict Playwright auth preflight."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from playwright_auth_preflight_strict import (
    PREFLIGHT_FAIL_NO_TOKEN_ROW,
    PREFLIGHT_FAIL_START_DISABLED,
    PREFLIGHT_FAIL_STREAMLIT_INCOMPLETE,
    evaluate_strict_preflight,
)


class StrictPreflightTests(unittest.TestCase):
    def test_sid_present_no_token_row_fails(self) -> None:
        r = evaluate_strict_preflight(
            harness_sid="aaa",
            url_sid="aaa",
            ledger_rows=[],
            start_enabled=True,
            start_visible=True,
            paired_authenticated=None,
            load_reason="token_record_missing",
        )
        self.assertFalse(r["authenticated_restored"])
        self.assertEqual(r["failure"], PREFLIGHT_FAIL_NO_TOKEN_ROW)

    def test_token_row_different_sid_fails(self) -> None:
        r = evaluate_strict_preflight(
            harness_sid="aaa",
            url_sid="bbb",
            ledger_rows=[],
            start_enabled=True,
            start_visible=True,
            paired_authenticated=None,
        )
        self.assertFalse(r["authenticated_restored"])

    def test_incomplete_record_fails(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "load_browser_auth_tokens",
                "browser_tokens_loaded": True,
                "access_token_present": True,
                "refresh_token_present": False,
            }
        ]
        r = evaluate_strict_preflight(
            harness_sid="same",
            url_sid="same",
            ledger_rows=rows,
            start_enabled=True,
            start_visible=True,
            paired_authenticated=None,
        )
        self.assertFalse(r["authenticated_restored"])

    def test_valid_bridge_and_session_passes(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "load_browser_auth_tokens",
                "browser_tokens_loaded": True,
                "access_token_present": True,
                "refresh_token_present": True,
            },
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "apply_authenticated_user_exit",
                "authenticated_after": True,
            },
        ]
        r = evaluate_strict_preflight(
            harness_sid="same",
            url_sid="same",
            ledger_rows=rows,
            start_enabled=True,
            start_visible=True,
            paired_authenticated=True,
        )
        self.assertTrue(r["authenticated_restored"])

    def test_start_disabled_fails_even_when_auth_complete(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "load_browser_auth_tokens",
                "browser_tokens_loaded": True,
                "access_token_present": True,
                "refresh_token_present": True,
            },
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "apply_authenticated_user_exit",
                "authenticated_after": True,
            },
        ]
        r = evaluate_strict_preflight(
            harness_sid="same",
            url_sid="same",
            ledger_rows=rows,
            start_enabled=False,
            start_visible=True,
            paired_authenticated=True,
        )
        self.assertEqual(r["failure"], PREFLIGHT_FAIL_START_DISABLED)

    def test_streamlit_incomplete_fails(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "load_browser_auth_tokens",
                "browser_tokens_loaded": True,
                "access_token_present": True,
                "refresh_token_present": True,
            }
        ]
        r = evaluate_strict_preflight(
            harness_sid="same",
            url_sid="same",
            ledger_rows=rows,
            start_enabled=True,
            start_visible=True,
            paired_authenticated=False,
        )
        self.assertIn(r["failure"], (PREFLIGHT_FAIL_STREAMLIT_INCOMPLETE, "paired_transition_authenticated_false"))

    def test_already_complete_without_apply_transition_passes(self) -> None:
        """UI/preflight already_complete may ignore paired=false.

        Does NOT imply STRICT BRIDGE READY: evaluate_strict_capture still requires
        a durable current-suite token row (see test_already_complete_bridge_save_repair).
        """
        rows = [
            {
                "event": "production_stage1_auth_state_before_start_control",
                "streamlit_session_id": "sess-a",
                "run_id": "run-a",
                "script_run_seq": 3,
                "is_authenticated": True,
                "auth_session_complete": True,
                "auth_hydration_source": "already_complete",
                "session_flag_present": True,
                "restore_blocked_reason": "",
            }
        ]
        r = evaluate_strict_preflight(
            harness_sid="same",
            url_sid="same",
            ledger_rows=rows,
            start_enabled=True,
            start_visible=True,
            paired_authenticated=False,
            streamlit_session_id="sess-a",
            diagnostic_run_id="run-a",
        )
        self.assertTrue(r["authenticated_restored"])
        self.assertTrue(r["paired_transition_ignored"])

    def test_paired_false_without_current_state_fails(self) -> None:
        r = evaluate_strict_preflight(
            harness_sid="same",
            url_sid="same",
            ledger_rows=[],
            start_enabled=True,
            start_visible=True,
            paired_authenticated=False,
        )
        self.assertFalse(r["authenticated_restored"])

    def test_before_start_explicit_false_fails(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_state_before_start_control",
                "is_authenticated": False,
                "auth_session_complete": False,
            }
        ]
        r = evaluate_strict_preflight(
            harness_sid="same",
            url_sid="same",
            ledger_rows=rows,
            start_enabled=True,
            start_visible=True,
            paired_authenticated=None,
        )
        self.assertEqual(r["failure"], PREFLIGHT_FAIL_STREAMLIT_INCOMPLETE)

    def test_stale_session_rows_excluded(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_state_before_start_control",
                "streamlit_session_id": "old",
                "is_authenticated": False,
                "auth_session_complete": False,
            },
            {
                "event": "production_stage1_auth_state_before_start_control",
                "streamlit_session_id": "new",
                "is_authenticated": True,
                "auth_session_complete": True,
                "auth_hydration_source": "already_complete",
                "session_flag_present": True,
            },
        ]
        r = evaluate_strict_preflight(
            harness_sid="same",
            url_sid="same",
            ledger_rows=rows,
            start_enabled=True,
            start_visible=True,
            paired_authenticated=False,
            streamlit_session_id="new",
        )
        self.assertTrue(r["authenticated_restored"])


if __name__ == "__main__":
    unittest.main()
