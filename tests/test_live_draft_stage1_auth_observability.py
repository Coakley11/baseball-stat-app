"""Stage-1 auth observability: current-state probe and auth snapshot buffer."""

from __future__ import annotations

import unittest

from live_draft_solo_component_diagnostics import SOLO_DIAG_ENABLED_KEY
from live_draft_stage1_current_auth_state import build_current_auth_state_payload
from live_draft_stage1_production_ledger import (
    AUTH_SNAPSHOT_MAX_ROWS,
    MAX_ROWS,
    auth_snapshot_rows,
    bump_stage1_script_run_seq,
    ensure_stage1_run_id,
    ledger_rows_for_export,
    note_stage1_event,
    update_stage1_auth_snapshot,
)
from suite_auth import AUTH_SESSION_KEY


class TestAuthSnapshotBuffer(unittest.TestCase):
    def _session(self):
        return {
            "solo_component_diag": True,
            SOLO_DIAG_ENABLED_KEY: True,
            "_solo_stage1_run_id": "runtest01",
            "_solo_stage1_script_run_seq": 1,
            AUTH_SESSION_KEY: {"user": "x"},
            "_suite_auth_last_hydration_source": "already_complete",
        }

    def test_auth_snapshot_survives_general_ledger_rollover(self):
        session = self._session()
        ensure_stage1_run_id(session)
        auth_row = {
            "event_id": "runtest01:1:production_stage1_auth_state_before_start_control",
            "event": "production_stage1_auth_state_before_start_control",
            "ts": 1.0,
            "is_authenticated": True,
            "auth_session_complete": True,
        }
        update_stage1_auth_snapshot(session, auth_row)
        class _St:
            query_params = {"solo_component_diag": "1"}

        st = _St()
        for i in range(MAX_ROWS + 50):
            bump_stage1_script_run_seq(session)
            note_stage1_event(session, "production_stage1_registration_hook_exited", st=st, extra={"i": i})
        snap = auth_snapshot_rows(session)
        self.assertTrue(any(r.get("event") == "production_stage1_auth_state_before_start_control" for r in snap))
        exported = ledger_rows_for_export(session)
        self.assertTrue(
            any(r.get("event") == "production_stage1_auth_state_before_start_control" for r in exported),
            "auth snapshot must appear in export after general ledger rollover",
        )

    def test_already_complete_current_state_payload(self):
        session = self._session()
        session[AUTH_SESSION_KEY] = {"sub": "u1"}
        session["_suite_auth_last_hydration_source"] = "already_complete"
        payload = build_current_auth_state_payload(
            session,
            st=None,
            start_visible=True,
            start_enabled=True,
        )
        self.assertEqual(payload["auth_hydration_source"], "already_complete")
        self.assertTrue(payload["start_enabled"])
        self.assertIn("is_authenticated", payload)

    def test_no_secrets_in_current_auth_payload(self):
        session = self._session()
        session["_access_token"] = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.fake"
        payload = build_current_auth_state_payload(session, st=None, start_enabled=True)
        blob = str(payload).lower()
        self.assertNotIn("eyj", blob)
        self.assertNotIn("@", blob)

    def test_snapshot_cap(self):
        session = self._session()
        for i in range(AUTH_SNAPSHOT_MAX_ROWS + 5):
            update_stage1_auth_snapshot(
                session,
                {
                    "event": "production_stage1_auth_prestart_hydration",
                    "checkpoint": f"cp_{i}",
                    "ts": float(i),
                    "event_id": f"r:{i}:production_stage1_auth_prestart_hydration",
                },
            )
        self.assertLessEqual(len(auth_snapshot_rows(session)), AUTH_SNAPSHOT_MAX_ROWS)


class TestHarnessObservabilityClassification(unittest.TestCase):
    def test_observability7_when_high_seq_no_auth_rows(self):
        from playwright_auth_observability import AUTH_OBSERVABILITY7, classify_auth_observability

        ss = {"enabled": True, "frame_index": 2}
        cp = {
            "start_enabled": True,
            "diagnostic_query_flags": {"suite_sid_present": True, "solo_component_diag": True},
        }
        lb = {"auth_row_count": 0, "row_count": 400, "ledger_same_frame_as_start": True, "extract_meta": {"max_event_index": 4216}}
        binding = {"ui_ledger_streamlit_session_match": True, "ui_ledger_run_match": True}
        code, _, _ = classify_auth_observability(
            start_surface=ss, checkpoint=cp, ledger_bind=lb, binding=binding
        )
        self.assertEqual(code, AUTH_OBSERVABILITY7)


if __name__ == "__main__":
    unittest.main()
