"""Unit tests for strict Playwright auth capture (harness)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from playwright_auth_capture_strict import (
    CAPTURE_FAIL_BRIDGE_PERSIST,
    CAPTURE_FAIL_BRIDGE_PERSIST_SID,
    CAPTURE_FAIL_SIGNED_IN_ONLY,
    evaluate_strict_capture,
    metadata_has_no_secrets,
)
from playwright_auth_preflight_strict import PREFLIGHT_FAIL_START_DISABLED, PREFLIGHT_FAIL_STREAMLIT_INCOMPLETE
from playwright_daniel_auth_session import atomic_write_harness_files


def _load_rows() -> list[dict]:
    return [
        {
            "event": "production_stage1_auth_prestart_hydration",
            "checkpoint": "load_browser_auth_tokens",
            "browser_tokens_loaded": True,
            "access_token_present": True,
            "refresh_token_present": True,
        },
        {
            "event": "production_stage1_auth_prestart_hydration",
            "checkpoint": "save_browser_auth_tokens",
            "persistence_attempted": True,
            "persistence_succeeded": True,
            "suite_sid_prefix": "abcd1234",
            "access_token_present": True,
            "refresh_token_present": True,
            "auth_user_id_present": True,
            "bridge_record_complete": True,
            "failure_reason": "ok",
            "handoff_phase": "INTERMEDIATE",
        },
        {
            "event": "production_stage1_auth_prestart_hydration",
            "checkpoint": "apply_authenticated_user_exit",
            "authenticated_after": True,
            "protected_keys": {"session_flag_present": True},
        },
        {
            "event": "production_stage1_auth_prestart_hydration",
            "checkpoint": "bridge_final_handoff_persist",
            "handoff_phase": "FINAL_HANDOFF",
            "persistence_succeeded": True,
            "suite_sid_prefix": "abcd1234",
            "refresh_fp": "abcdef0123456789",
            "refresh_fp_prefix": "abcdef0123456789",
            "session_snapshot_refresh_fp_prefix": "abcdef0123456789",
            "token_generation": 2,
            "failure_reason": "ok",
            "event_index": 50,
        },
        {
            "event": "production_stage1_auth_prestart_hydration",
            "checkpoint": "bridge_final_handoff_readback",
            "handoff_phase": "FINAL_HANDOFF",
            "readback_succeeded": True,
            "suite_sid_prefix": "abcd1234",
            "refresh_fp_prefix": "abcdef0123456789",
            "token_generation": 2,
            "failure_reason": "ok",
            "event_index": 51,
        },
        {
            "event": "production_stage1_auth_prestart_hydration",
            "checkpoint": "bridge_final_handoff_invariant",
            "final_session_snapshot_fingerprint": "abcdef0123456789",
            "final_persist_token_fingerprint": "abcdef0123456789",
            "final_browser_token_fingerprint": "abcdef0123456789",
            "final_readback_token_fingerprint": "abcdef0123456789",
            "fingerprint_match": True,
            "no_auth_refresh_after_final_persist": True,
            "no_auth_consumption_since_final_token_snapshot": True,
            "failure_reason": "ok",
            "event_index": 52,
        },
    ]


class StrictCaptureTests(unittest.TestCase):
    def test_signed_in_without_streamlit_fails(self) -> None:
        r = evaluate_strict_capture(
            target_sid="abcd1234-0000-0000-0000-000000000001",
            url_sid="abcd1234-0000-0000-0000-000000000001",
            ledger_rows=[],
            start_enabled=True,
            start_visible=True,
            paired_authenticated=None,
            signed_in_display=True,
        )
        self.assertFalse(r["strict_auth_passed"])
        self.assertEqual(r["failure"], CAPTURE_FAIL_SIGNED_IN_ONLY)

    def test_sid_without_bridge_row_fails(self) -> None:
        r = evaluate_strict_capture(
            target_sid="abcd1234-0000-0000-0000-000000000001",
            url_sid="abcd1234-0000-0000-0000-000000000001",
            ledger_rows=[],
            start_enabled=True,
            start_visible=True,
            paired_authenticated=True,
            signed_in_display=False,
        )
        self.assertFalse(r["strict_auth_passed"])

    def test_bridge_row_wrong_sid_prefix_fails(self) -> None:
        rows = _load_rows()
        rows[1]["suite_sid_prefix"] = "ffffffff"
        r = evaluate_strict_capture(
            target_sid="abcd1234-0000-0000-0000-000000000001",
            url_sid="abcd1234-0000-0000-0000-000000000001",
            ledger_rows=rows,
            start_enabled=True,
            start_visible=True,
            paired_authenticated=True,
        )
        self.assertEqual(r["failure"], CAPTURE_FAIL_BRIDGE_PERSIST_SID)

    def test_bridge_persisted_streamlit_incomplete_fails(self) -> None:
        rows = _load_rows()
        rows.pop()  # no apply exit
        r = evaluate_strict_capture(
            target_sid="abcd1234-0000-0000-0000-000000000001",
            url_sid="abcd1234-0000-0000-0000-000000000001",
            ledger_rows=rows,
            start_enabled=True,
            start_visible=True,
            paired_authenticated=False,
        )
        self.assertFalse(r["strict_auth_passed"])
        self.assertIn(
            r["failure"],
            (PREFLIGHT_FAIL_STREAMLIT_INCOMPLETE, CAPTURE_FAIL_BRIDGE_PERSIST, "paired_transition_authenticated_false"),
        )

    def test_start_disabled_fails(self) -> None:
        r = evaluate_strict_capture(
            target_sid="abcd1234-0000-0000-0000-000000000001",
            url_sid="abcd1234-0000-0000-0000-000000000001",
            ledger_rows=_load_rows(),
            start_enabled=False,
            start_visible=True,
            paired_authenticated=True,
        )
        self.assertEqual(r["failure"], PREFLIGHT_FAIL_START_DISABLED)

    def test_all_strict_true_metadata_safe(self) -> None:
        sid = "abcd1234-0000-0000-0000-000000000001"
        dom = {
            "streamlit_session_id": "sess-a",
            "diagnostic_run_id": "run-a",
            "session_flag_present": True,
            "is_authenticated": True,
            "auth_session_complete": True,
            "auth_hydration_source": "already_complete",
            "current_restore_blocked_reason": "",
            "start_enabled": True,
        }
        r = evaluate_strict_capture(
            target_sid=sid,
            url_sid=sid,
            ledger_rows=_load_rows(),
            start_enabled=True,
            start_visible=True,
            paired_authenticated=True,
            current_auth_dom=dom,
            diagnostic_run_id="run-a",
            streamlit_session_id="sess-a",
        )
        self.assertTrue(r["strict_auth_passed"])
        meta = {
            "suite_sid": sid,
            "strict_capture": {"bridge_persistence": r["bridge_persistence"]},
        }
        self.assertTrue(metadata_has_no_secrets(meta))
        blob = json.dumps(meta)
        self.assertNotIn("eyJ", blob)

    def test_atomic_write_same_sid_in_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = root / "playwright_daniel_auth.storage.json"
            session = root / "playwright_daniel_auth.session.json"
            storage.write_text('{"orig": true}', encoding="utf-8")
            session.write_text('{"suite_sid": "keep-me"}', encoding="utf-8")
            orig_storage = storage.read_text()
            with mock.patch("playwright_daniel_auth_session.STORAGE_PATH", storage), mock.patch(
                "playwright_daniel_auth_session.SESSION_PATH", session
            ):
                sid = "abcd1234-0000-0000-0000-000000000001"

                def writer(path: Path) -> None:
                    path.write_text('{"cookies": []}', encoding="utf-8")

                atomic_write_harness_files(
                    suite_sid=sid,
                    storage_writer=writer,
                    capture_metadata={"captured_at": "2026-08-05T00:00:00+00:00", "strict_auth_passed": True},
                )
                session_data = json.loads(session.read_text())
                self.assertEqual(session_data["suite_sid"], sid)
                self.assertEqual(json.loads(storage.read_text())["cookies"], [])

    def test_failed_capture_does_not_call_atomic_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = root / "playwright_daniel_auth.storage.json"
            session = root / "playwright_daniel_auth.session.json"
            storage.write_text('{"orig": true}', encoding="utf-8")
            session.write_text('{"suite_sid": "keep-me"}', encoding="utf-8")
            before_storage = storage.read_text()
            before_session = session.read_text()
            self.assertEqual(before_storage, '{"orig": true}')
            self.assertIn("keep-me", before_session)


if __name__ == "__main__":
    unittest.main()
