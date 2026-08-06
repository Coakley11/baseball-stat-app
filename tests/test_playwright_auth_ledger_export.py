"""Export and evidence harness tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from playwright_auth_ledger_export import export_pre_click_auth_payloads


class AuthExportTests(unittest.TestCase):
    def test_pre_click_payloads_preserved(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_state_before_start_control",
                "run_id": "run1",
                "streamlit_session_id": "sid1",
                "script_run_seq": 2,
                "is_authenticated": True,
            },
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "load_browser_auth_tokens",
                "run_id": "run1",
                "streamlit_session_id": "sid1",
                "browser_tokens_loaded": True,
            },
        ]
        out = export_pre_click_auth_payloads(rows, diagnostic_run_id="run1", streamlit_session_id="sid1")
        self.assertEqual(out["payload_row_counts"]["production_stage1_auth_state_before_start_control"], 1)
        payload = out["payloads_by_event"]["production_stage1_auth_state_before_start_control"][0]
        self.assertTrue(payload.get("is_authenticated"))


if __name__ == "__main__":
    unittest.main()
