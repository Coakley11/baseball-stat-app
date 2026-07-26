"""Unit tests for P6 writer-session ledger."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from live_draft_solo_parity_p6_persistent_diag import (
    P6_SESSION_LEDGERS_KEY,
    append_p6_ledger_row,
    build_writer_probe_payload,
    get_p6_ledger_for_run,
    python_receipt_from_payload,
    synthetic_room_id_for_run,
)


class P6WriterSessionLedgerTests(unittest.TestCase):
    def test_session_state_ledger_by_run_id(self) -> None:
        run_id = "test-run-writer-session"
        session: dict = {
            "_solo_parity_p6_persistent_diag": True,
            "_solo_parity_ladder_control": "P6",
            "_solo_p6_run_id": run_id,
        }
        append_p6_ledger_row(
            session,
            "script_begin",
            expected_token="",
            actual_token="",
        )
        append_p6_ledger_row(
            session,
            "callback_entry",
            actual_token="PARITY|0|1.0",
            raw_widget_value="'PARITY|0|1.0'",
        )
        rows = get_p6_ledger_for_run(session, run_id)
        self.assertEqual(len(rows), 2)
        self.assertIsInstance(session.get(P6_SESSION_LEDGERS_KEY), dict)
        payload = {
            "expected_token": "PARITY|0|1.0",
            "callback_rows": rows,
        }
        self.assertTrue(python_receipt_from_payload(payload))

    def test_build_writer_probe_payload(self) -> None:
        st = MagicMock()
        st.session_state = {}
        session = {
            "_solo_parity_p6_persistent_diag": True,
            "_solo_p6_run_id": "rid-1",
        }
        payload = build_writer_probe_payload(st, session)
        self.assertEqual(payload.get("diagnostic_run_id"), "rid-1")
        self.assertEqual(payload.get("synthetic_room_id"), synthetic_room_id_for_run("rid-1"))

    def test_synthetic_room_id_short_run(self) -> None:
        rid = "d72e8776-b929-4379-b268-7a79cb549b8e"
        self.assertEqual(synthetic_room_id_for_run(rid), "PARITY_d72e8776")


if __name__ == "__main__":
    unittest.main()
