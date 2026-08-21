"""Strict capture keeps bridge proof when session finalization fails."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from playwright_auth_capture_strict import (
    CAPTURE_FAIL_SESSION_FINALIZE,
    bridge_persistence_proof,
    evaluate_strict_capture,
)


def _bridge_rows() -> list[dict]:
    return [
        {
            "event": "production_stage1_auth_prestart_hydration",
            "checkpoint": "save_browser_auth_tokens",
            "persistence_attempted": True,
            "persistence_succeeded": True,
            "suite_sid_prefix": "ed14dcd9",
            "bridge_record_complete": True,
        },
        {
            "event": "production_stage1_auth_prestart_hydration",
            "checkpoint": "save_browser_auth_tokens_readback",
            "readback_record_complete": True,
            "suite_sid_prefix": "ed14dcd9",
        },
        {
            "event": "production_stage1_auth_prestart_hydration",
            "checkpoint": "apply_authenticated_user_exit",
            "authenticated_after": True,
            "session_flag_present": False,
            "auth_session_complete": False,
        },
        {
            "event": "production_stage1_auth_state_before_start_control",
            "session_flag_present": False,
            "auth_session_complete": False,
            "is_authenticated": False,
            "start_button_enabled": False,
        },
    ]


class StrictCaptureBridgeSyncTests(unittest.TestCase):
    def test_bridge_persistence_preserved_on_start_disabled(self) -> None:
        sid = "ed14dcd9-53ea-491e-aeb0-91f0caff1045"
        r = evaluate_strict_capture(
            target_sid=sid,
            url_sid=sid,
            ledger_rows=_bridge_rows(),
            start_enabled=False,
            start_visible=True,
            paired_authenticated=True,
        )
        self.assertIn(
            r["failure"],
            (CAPTURE_FAIL_SESSION_FINALIZE, "start_control_disabled", "suite_auth_session_missing"),
        )
        self.assertTrue(r["bridge_persistence"]["persistence_succeeded"])
        self.assertTrue(r["bridge_persisted"])

    def test_bridge_proof_matches_timeline_helper(self) -> None:
        sid = "ed14dcd9-53ea-491e-aeb0-91f0caff1045"
        rows = _bridge_rows()
        self.assertTrue(bridge_persistence_proof(rows, target_sid=sid)["persistence_succeeded"])


if __name__ == "__main__":
    unittest.main()
