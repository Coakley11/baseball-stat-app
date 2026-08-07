"""Bound current-auth precedence and AUTH_FINALIZE_DIAG classification."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from live_draft_stage1_current_auth_state import build_current_auth_state_payload  # noqa: E402
from playwright_auth_capture_strict import evaluate_strict_capture  # noqa: E402
from playwright_auth_current_state_eval import (  # noqa: E402
    AUTH_FINALIZE_DIAG1,
    AUTH_FINALIZE_DIAG2,
    AUTH_FINALIZE_DIAG3,
    bound_state_passes_observability_resolved,
    classify_auth_finalize_diag,
    evaluate_bound_current_auth_state,
)
from suite_auth import AUTH_SESSION_KEY, AUTH_TOKENS_KEY, AUTH_USER_ID_KEY  # noqa: E402


class TestRestoreBlockObservabilityFields(unittest.TestCase):
    def test_successful_auth_clears_current_restore_block(self) -> None:
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "u1",
            AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
            "_live_draft_restore_blocked_reason": "auth_required",
            "_live_draft_last_restore_failure_reason": "auth_required",
            "_live_draft_last_restore_failure_seq": 349,
            "_suite_auth_last_hydration_source": "already_complete",
            "_solo_stage1_script_run_seq": 349,
        }
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            payload = build_current_auth_state_payload(session, start_enabled=True)
        self.assertEqual(payload["current_restore_blocked_reason"], "")
        self.assertEqual(payload["last_restore_failure_reason"], "auth_required")
        self.assertEqual(payload["last_restore_failure_seq"], 349)

    def test_already_complete_cannot_retain_current_auth_required(self) -> None:
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "u1",
            AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
            "_live_draft_restore_blocked_reason": "auth_required",
            "_suite_auth_last_hydration_source": "already_complete",
        }
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            payload = build_current_auth_state_payload(session, start_enabled=True)
        self.assertFalse(payload["current_restore_blocked_reason"])


class TestBoundCurrentAuthPrecedence(unittest.TestCase):
    def _capture_dom(self) -> dict:
        path = ROOT / "data" / "capture_playwright_daniel_auth_once.result.json"
        if not path.is_file():
            self.skipTest("capture artifact missing")
        data = json.loads(path.read_text(encoding="utf-8"))
        cp = (data.get("observability_binding") or {}).get("checkpoint") or {}
        return cp.get("current_auth_dom") or {}

    def test_newer_dom_overrides_older_false_before_start(self) -> None:
        dom = self._capture_dom()
        if not dom:
            self.skipTest("no current_auth_dom in capture")
        rows = [
            {
                "event": "production_stage1_auth_state_before_start_control",
                "event_id": "run:349:production_stage1_auth_state_before_start_control",
                "script_run_seq": 3,
                "streamlit_session_id": dom.get("streamlit_session_id"),
                "diagnostic_run_id": dom.get("diagnostic_run_id"),
                "is_authenticated": False,
                "auth_session_complete": False,
                "session_flag_present": False,
                "restore_blocked_reason": "auth_required",
            },
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "apply_authenticated_user_exit",
                "script_run_seq": 7,
                "streamlit_session_id": dom.get("streamlit_session_id"),
                "diagnostic_run_id": dom.get("diagnostic_run_id"),
                "authenticated_after": True,
                "auth_session_complete": True,
                "session_flag_present": True,
            },
        ]
        dom_fixed = {**dom, "current_restore_blocked_reason": "", "restore_blocked_reason": ""}
        bound = evaluate_bound_current_auth_state(
            current_auth_dom=dom_fixed,
            ledger_rows=rows,
            diagnostic_run_id=str(dom.get("diagnostic_run_id") or ""),
            streamlit_session_id=str(dom.get("streamlit_session_id") or ""),
            start_enabled=True,
        )
        self.assertTrue(bound.get("is_authenticated"))
        self.assertTrue(bound.get("auth_session_complete"))
        self.assertEqual(bound["field_sources"].get("is_authenticated"), "current_auth_dom")
        self.assertTrue(bound.get("apply_authenticated_user_ok"))

    def test_apply_exit_authenticated_after_evaluates_ok(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "apply_authenticated_user_exit",
                "script_run_seq": 2,
                "authenticated_after": True,
                "session_flag_present": True,
            }
        ]
        bound = evaluate_bound_current_auth_state(ledger_rows=rows, start_enabled=True)
        self.assertTrue(bound.get("apply_authenticated_user_ok"))

    def test_mismatched_session_rows_rejected(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_state_before_start_control",
                "streamlit_session_id": "other-session",
                "is_authenticated": False,
                "auth_session_complete": False,
            }
        ]
        bound = evaluate_bound_current_auth_state(
            current_auth_dom={
                "streamlit_session_id": "bound-session",
                "is_authenticated": True,
                "auth_session_complete": True,
                "session_flag_present": True,
                "current_restore_blocked_reason": "",
            },
            ledger_rows=rows,
            streamlit_session_id="bound-session",
            start_enabled=True,
        )
        self.assertTrue(bound.get("is_authenticated"))
        self.assertNotEqual(bound["field_sources"].get("is_authenticated"), "ledger_before_start_latest")


class TestAuthFinalizeDiag(unittest.TestCase):
    def test_diag1_stale_restore_block(self) -> None:
        bound = {
            "is_authenticated": True,
            "auth_session_complete": True,
            "session_flag_present": True,
            "start_enabled": True,
            "current_restore_blocked_reason": "auth_required",
            "apply_authenticated_user_ok": True,
        }
        legacy = {"restore_blocked_reason": "auth_required", "apply_authenticated_user_ok": False}
        code, _, _ = classify_auth_finalize_diag(bound, legacy_strict=legacy)
        self.assertEqual(code, AUTH_FINALIZE_DIAG1)

    def test_diag2_older_before_start(self) -> None:
        bound = {
            "is_authenticated": True,
            "auth_session_complete": True,
            "session_flag_present": True,
            "start_enabled": True,
            "current_restore_blocked_reason": "",
            "current_auth_script_run_seq": 8,
            "before_start_script_run_seq": 3,
            "apply_authenticated_user_ok": True,
        }
        legacy = {"is_authenticated": False, "auth_session_complete": False}
        code, _, _ = classify_auth_finalize_diag(bound, legacy_strict=legacy)
        self.assertEqual(code, AUTH_FINALIZE_DIAG2)

    def test_diag3_apply_misparsed(self) -> None:
        bound = {
            "is_authenticated": True,
            "auth_session_complete": True,
            "session_flag_present": True,
            "start_enabled": True,
            "current_restore_blocked_reason": "",
            "apply_authenticated_user_ok": True,
        }
        legacy = {"apply_authenticated_user_ok": False}
        code, _, _ = classify_auth_finalize_diag(bound, legacy_strict=legacy)
        self.assertEqual(code, AUTH_FINALIZE_DIAG3)

    def test_capture_c4f46a81_replay_passes_with_corrected_dom(self) -> None:
        path = ROOT / "data" / "capture_playwright_daniel_auth_once.result.json"
        if not path.is_file():
            self.skipTest("capture artifact missing")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("suite_sid_prefix") != "c4f46a81":
            self.skipTest("unexpected capture sid")
        cp = (data.get("observability_binding") or {}).get("checkpoint") or {}
        dom = dict(cp.get("current_auth_dom") or {})
        dom["current_restore_blocked_reason"] = ""
        dom["restore_blocked_reason"] = ""
        rows = [
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "save_browser_auth_tokens_readback",
                "suite_sid_prefix": "c4f46a81",
                "readback_record_complete": True,
                "persistence_succeeded": True,
                "access_token_present": True,
                "refresh_token_present": True,
                "auth_user_id_present": True,
                "bridge_record_complete": True,
                "script_run_seq": 6,
                "streamlit_session_id": cp.get("streamlit_session_id"),
                "diagnostic_run_id": cp.get("diagnostic_run_id"),
            },
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "apply_authenticated_user_exit",
                "authenticated_after": True,
                "auth_session_complete": True,
                "session_flag_present": True,
                "script_run_seq": 7,
                "streamlit_session_id": cp.get("streamlit_session_id"),
                "diagnostic_run_id": cp.get("diagnostic_run_id"),
            },
        ]
        ev = evaluate_strict_capture(
            target_sid=str(data.get("suite_sid") or ""),
            url_sid=str(data.get("suite_sid") or ""),
            ledger_rows=rows,
            start_enabled=True,
            start_visible=True,
            paired_authenticated=None,
            current_auth_dom=dom,
            diagnostic_run_id=str(cp.get("diagnostic_run_id") or ""),
            streamlit_session_id=str(cp.get("streamlit_session_id") or ""),
        )
        bound = evaluate_bound_current_auth_state(
            current_auth_dom=dom,
            ledger_rows=rows,
            diagnostic_run_id=str(cp.get("diagnostic_run_id") or ""),
            streamlit_session_id=str(cp.get("streamlit_session_id") or ""),
            start_enabled=True,
        )
        self.assertTrue(bound_state_passes_observability_resolved(bound))
        self.assertTrue(ev.get("strict_auth_passed"))


if __name__ == "__main__":
    unittest.main()
