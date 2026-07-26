"""Unit tests for P6 persistent process-wide ledger."""

from __future__ import annotations

from live_draft_solo_parity_p6_persistent_diag import (
    append_p6_ledger_row,
    get_p6_ledger,
    python_receipt_from_payload,
)


def test_p6_ledger_append_and_python_receipt() -> None:
    session: dict = {
        "_solo_parity_p6_persistent_diag": True,
        "_solo_parity_ladder_control": "P6",
        "_solo_parity_p6_streamlit_session_id": "test_sid_p6",
    }
    append_p6_ledger_row(session, "script_beginning", expected_token="PARITY|0|1.0")
    append_p6_ledger_row(session, "on_change_callback_entry", raw_widget_value="'PARITY|0|1.0'")
    rows = get_p6_ledger("test_sid_p6")
    assert len(rows) >= 2
    payload = {
        "expected_token": "PARITY|0|1.0",
        "raw_session_state_value": "'PARITY|0|1.0'",
        "callback_rows": rows,
        "delivery_owner_tokens": {},
    }
    assert python_receipt_from_payload(payload) is True
