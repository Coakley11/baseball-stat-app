"""Tests for headed auth capture diagnostics (harness)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from playwright_auth_capture_diag import (
    AUTH_LOGIN4,
    AUTH_LOGIN7,
    classify_auth_login,
    is_oauth_callback_url,
    is_provider_url,
    ledger_login_timeline,
    login_transition_state,
    new_run_identity,
    trace_has_no_secrets,
    verify_capture_url,
)
from playwright_auth_capture_strict import evaluate_strict_capture


class CaptureDiagTests(unittest.TestCase):
    def test_failure_identity_retains_full_sid(self) -> None:
        sid = "fc6d5470-1111-2222-3333-444444444444"
        ident = new_run_identity(suite_sid=sid, target_url=f"https://example.test/?suite_sid={sid}")
        self.assertEqual(ident["suite_sid"], sid)
        self.assertEqual(ident["suite_sid_prefix"], "fc6d5470")

    def test_provider_vs_callback_urls(self) -> None:
        self.assertTrue(is_provider_url("https://accounts.google.com/o/oauth2/v2/auth"))
        self.assertTrue(
            is_oauth_callback_url(
                "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/?suite_sid=abc&code=x"
            )
        )
        self.assertFalse(is_provider_url("https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"))

    def test_signed_in_without_hydration_is_login_not_bridge(self) -> None:
        r = evaluate_strict_capture(
            target_sid="fc6d5470-1111-2222-3333-444444444444",
            url_sid="fc6d5470-1111-2222-3333-444444444444",
            ledger_rows=[],
            start_enabled=False,
            start_visible=True,
            paired_authenticated=None,
            signed_in_display=True,
        )
        self.assertFalse(r["strict_auth_passed"])
        self.assertNotEqual(r["failure"], "bridge_persistence_not_proven")
        state = login_transition_state(
            target_sid="fc6d5470-1111-2222-3333-444444444444",
            url_sid="fc6d5470-1111-2222-3333-444444444444",
            provider_seen=True,
            oauth_callback_seen=True,
            returned_to_app=True,
            storage={"supabase_storage_key_present": True},
            signed_in_display=True,
            ledger_rows=[],
            strict_failure=r["failure"],
            sign_in_initiated=True,
        )
        self.assertEqual(classify_auth_login(state), AUTH_LOGIN4)

    def test_sid_drift_classifies_login7(self) -> None:
        state = login_transition_state(
            target_sid="aaaa",
            url_sid="bbbb",
            provider_seen=True,
            oauth_callback_seen=True,
            returned_to_app=True,
            storage={},
            signed_in_display=False,
            ledger_rows=[],
            strict_failure="suite_sid_changed",
        )
        self.assertEqual(classify_auth_login(state, sid_drift=True), AUTH_LOGIN7)

    def test_trace_rejects_raw_tokens(self) -> None:
        blob = json.dumps({"note": "eyJhbGciOiJIUzI1NiJ9.abc.def"})
        self.assertFalse(trace_has_no_secrets(blob))

    def test_capture_url_check(self) -> None:
        sid = "fc6d5470-1111-2222-3333-444444444444"
        url = f"https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/?suite_sid={sid}"
        chk = verify_capture_url(url, expected_sid=sid)
        self.assertTrue(chk["hostname_ok"])
        self.assertTrue(chk["suite_sid_in_url"])

    def test_ledger_timeline_no_secrets(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "save_browser_auth_tokens_readback",
                "readback_record_complete": True,
                "matching_row_id": "row-uuid-1",
                "environment": {"url_fingerprint": "abc123"},
            }
        ]
        tl = ledger_login_timeline(rows)
        blob = json.dumps(tl)
        self.assertIn("readback", blob)
        self.assertNotIn("eyJ", blob)


if __name__ == "__main__":
    unittest.main()
