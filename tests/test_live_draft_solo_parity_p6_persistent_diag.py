"""Unit tests for P6 persistent process-wide ledger."""

from __future__ import annotations

import unittest

from live_draft_solo_parity_p6_persistent_diag import (
    append_p6_ledger_row,
    get_p6_ledger_for_run,
    python_receipt_from_payload,
)


class P6PersistentLedgerTests(unittest.TestCase):
    def test_p6_ledger_append_by_run_id_and_python_receipt(self) -> None:
        run_id = "test-run-uuid-p6"
        session: dict = {
            "_solo_parity_p6_persistent_diag": True,
            "_solo_parity_ladder_control": "P6",
            "_solo_p6_run_id": run_id,
        }
        append_p6_ledger_row(
            session,
            "script_begin",
            expected_token="PARITY|0|1.0",
            actual_token="PARITY|0|1.0",
        )
        append_p6_ledger_row(
            session,
            "on_change_callback_entry",
            raw_widget_value="'PARITY|0|1.0'",
            actual_token="PARITY|0|1.0",
        )
        rows = get_p6_ledger_for_run(run_id)
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0].get("diagnostic_run_id"), run_id)
        payload = {
            "expected_token": "PARITY|0|1.0",
            "raw_session_state_value": "'PARITY|0|1.0'",
            "callback_rows": rows,
            "delivery_owner_tokens": {},
        }
        self.assertTrue(python_receipt_from_payload(payload))


if __name__ == "__main__":
    unittest.main()
