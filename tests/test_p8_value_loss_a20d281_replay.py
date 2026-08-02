"""Replay VALUE classification from authoritative lifecycle artifact a20d281."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.p8_callback_boundary_classify import classify_callback_boundary
from scripts.p8_callback_value_loss_classify import (
    CLASSIFIER_FIX_SHA,
    VALUE4,
    VALUE9,
    classify_value_loss_boundary,
)
from scripts.p8_expiration_token_raw import build_expiration_token_raw_report

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "data" / "production_callback_value_lifecycle_diagnostic.json"
RUN_ID = "a20d281beb804834"
EXPECTED = "F2CA3800|0|1785639502.583"


def _lifecycle_filtered_rows(report: dict) -> list[dict]:
    exp = report.get("production_expiration") or {}
    rows = list(exp.get("filtered_ledger_rows") or [])
    if rows:
        return rows
    lf = exp.get("ledger_filter") or {}
    return list(lf.get("filtered_rows") or [])


def test_a20d281_artifact_replay_value4_mechanism_value9_correction() -> None:
    if not ARTIFACT.is_file():
        return
    report = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert str(report.get("production_diagnostic_run_id") or "").startswith(RUN_ID[:8]) or RUN_ID in str(
        report
    )
    token = str(report.get("production_exact_token") or EXPECTED).strip()
    rows = _lifecycle_filtered_rows(report)
    assert rows, "filtered ledger rows required for replay"
    cb = classify_callback_boundary(filtered_rows=rows, exact_token=token)
    assert str(cb.get("classification") or "").startswith("CB6")
    token_raw = build_expiration_token_raw_report(
        expected_token=token,
        filtered_rows=rows,
        expiration=report.get("production_expiration") or {},
        return_value_chain=report.get("production_return_value_chain") or {},
    )
    out = classify_value_loss_boundary(
        exact_token=token,
        filtered_rows=rows,
        callback_boundary=cb,
        token_raw=token_raw,
    )
    assert out["classification"] == VALUE4
    assert out.get("mechanism") == VALUE4
    assert out.get("correction_boundary") == VALUE9
    assert out.get("classifier_fix_sha") == CLASSIFIER_FIX_SHA
    audit = out.get("audit") or {}
    assert audit.get("last_equals_expected_phase") == "after_read_session_state_widget_key"
    assert audit.get("first_loss_phase") == "callback_exit"
    assert "813" not in str(out.get("first_value_loss") or "")  # expire_run mutation not the loss edge


def test_expire_run_mutation_does_not_block_value4_transition() -> None:
    exact = EXPECTED
    rows = [
        {
            "event": "production_stage1_prod_on_change_entered",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "session_state_value_repr": f"'{exact}'",
            "ts": 1.0,
            "event_id": "entered",
        },
        {
            "event": "production_stage1_prod_on_change_value_snapshot",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "phase": "callback_entry",
            "raw_value_repr": f"'{exact}'",
            "ts": 2.0,
            "event_id": "snap_in",
        },
        {
            "event": "production_stage1_session_state_mutation",
            "key": "_solo_persistent_wake_expire_run",
            "mutation_op": "set",
            "previous_value_repr": "None",
            "new_value_repr": "''",
            "ts": 2.1,
            "event_id": "mut_expire",
        },
        {
            "event": "production_stage1_prod_on_change_value_op",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "operation_label": "after_read_session_state_widget_key",
            "new_raw_value": f"'{exact}'",
            "ts": 2.2,
            "event_id": "op_after",
        },
        {
            "event": "production_stage1_prod_on_change_value_snapshot",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "phase": "callback_exit",
            "raw_value_repr": "''",
            "session_state_key_exists": False,
            "ts": 3.0,
            "event_id": "snap_out",
        },
        {
            "event": "production_stage1_prod_on_change_exited",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "session_state_value_at_exit_repr": "missing",
            "ts": 3.1,
            "event_id": "exited",
        },
        {
            "event": "production_stage1_post_callback_handoff_boundary",
            "boundary": "post_callback_session_state",
            "value_raw": "None",
        },
    ]
    token_raw = {
        "post_callback_session_value_raw": "",
        "wrapper_read_value_raw": "",
    }
    out = classify_value_loss_boundary(
        exact_token=exact,
        filtered_rows=rows,
        callback_boundary={"classification": "CB6"},
        token_raw=token_raw,
    )
    assert out["classification"] == VALUE4
    assert out.get("correction_boundary") == VALUE9
