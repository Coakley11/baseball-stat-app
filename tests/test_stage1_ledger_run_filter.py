"""Ledger run filter for Stage 1 diagnostic attribution."""

from __future__ import annotations

from scripts.stage1_ledger_run_filter import filter_ledger_rows_for_diagnostic_run


def test_cross_run_rows_excluded() -> None:
    rows = [
        {
            "run_id": "aaaa1111",
            "room_id": "ROOM1111",
            "event": "production_stage1_delivery_only_observation_completed",
            "token": "ROOM1111|0|1.0",
        },
        {
            "run_id": "bbbb2222",
            "room_id": "ROOM2222",
            "event": "production_stage1_bound_token_gate",
            "expected_token": "ROOM2222|0|2.0",
        },
    ]
    out = filter_ledger_rows_for_diagnostic_run(
        rows,
        run_id="bbbb2222",
        room_id="ROOM2222",
        exact_token="ROOM2222|0|2.0",
    )
    assert out["rows_before"] == 2
    assert out["rows_after"] == 1
    assert out["rejected_count"] == 1
    assert "run_id_mismatch" in out["rejected"][0]["reasons"]


def test_token_room_mismatch_rejected() -> None:
    rows = [
        {
            "run_id": "run1",
            "room_id": "AAAA",
            "event": "production_stage1_post_bind_actionable_flush",
            "bound_token": "BBBB|0|1.0",
        },
    ]
    out = filter_ledger_rows_for_diagnostic_run(
        rows,
        run_id="run1",
        room_id="AAAA",
        exact_token="AAAA|0|9.0",
    )
    assert out["rows_after"] == 0
    assert any("token_room_mismatch" in r["reasons"] for r in out["rejected"])
