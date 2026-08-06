"""Browser auth bridge durability diagnostics (unit tests)."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from suite_auth_browser import save_browser_auth_tokens
from suite_auth_browser_bridge_diag import readback_after_browser_auth_save


def _tokens() -> dict:
    return {"access_token": "access-test", "refresh_token": "refresh-test"}


class BridgeDurabilityTests(unittest.TestCase):
    def test_readback_failure_marks_incomplete(self) -> None:
        with mock.patch(
            "suite_auth_browser_bridge_diag.probe_browser_auth_storage",
            return_value={"production_row_found": False, "rejection_reason": "token_record_missing"},
        ):
            rb = readback_after_browser_auth_save("sid-1", expected_user_id="u1", save_reported_success=True)
        self.assertFalse(rb["readback_record_complete"])
        self.assertEqual(rb["failure_reason"], "token_record_missing")

    def test_save_without_readback_fails_persistence(self) -> None:
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-save"}
        st.session_state = {"_suite_auth_user_id": "uuid-1"}
        with mock.patch(
            "suite_storage_supabase.save_browser_auth_session",
            return_value={"write_committed": True, "write_mode": "upsert"},
        ), mock.patch(
            "suite_auth_browser_bridge_diag.readback_after_browser_auth_save",
            return_value={
                "readback_record_complete": False,
                "readback_row_found": False,
                "failure_reason": "token_record_missing",
            },
        ), mock.patch(
            "live_draft_auth_prestart_stage1_diag.emit_prestart_hydration_checkpoint"
        ):
            save_browser_auth_tokens(st, _tokens(), auth_user_id="uuid-1")
        self.assertFalse(st.session_state.get("_unused"))

    def test_diagnostics_contain_no_raw_tokens(self) -> None:
        rb = readback_after_browser_auth_save("x", save_reported_success=True)
        blob = json.dumps(rb, default=str)
        self.assertNotIn("eyJ", blob)
        self.assertNotIn("refresh-test", blob)


if __name__ == "__main__":
    unittest.main()
