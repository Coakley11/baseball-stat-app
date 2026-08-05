"""Regression tests for QUEUEUI audit baseline partition and prestart isolation."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from queueui_audit_protocol import (  # noqa: E402
    capture_audit_baseline,
    distinct_predicate_script_run_seq,
    evaluate_audit_completion,
    evaluate_prestart_isolation,
    ledger_event_index,
    partition_ledger_by_baseline,
    prestart_ledger_signals,
    record_click_dispatch_times,
    row_is_post_start,
)
from queueui_root_classify import classify_queueui_root  # noqa: E402

RUN = "run001"
SID = "sid-session-1"
OTHER_RUN = "run999"


def _baseline(*, max_index: int = 100, count: int = 101) -> dict:
    ledger = [
        {
            "event_id": f"{RUN}:{i}:production_stage1_cloud_ledger_pipeline_canary",
            "run_id": RUN,
            "streamlit_session_id": SID,
            "ts": 1000.0 + i,
        }
        for i in range(1, count)
    ]
    identity = {"streamlit_session_id": SID, "diagnostic_run_id": RUN}
    lobby = {"inferred_status": "setup_lobby", "wake": {}}
    base = capture_audit_baseline(ledger, identity, lobby, preclick_captured_at=2000.0)
    record_click_dispatch_times(base, dispatch_started_at=2001.0, dispatch_completed_at=2005.0)
    base["baseline_event_index_max"] = max_index
    return base


def test_callback_during_blocking_click_is_post_baseline_by_event_index() -> None:
    baseline = _baseline(max_index=100)
    ledger = [
        {"event_id": f"{RUN}:100:production_stage1_script_begin", "run_id": RUN, "streamlit_session_id": SID, "ts": 1999},
        {
            "event_id": f"{RUN}:101:production_stage1_start_callback_entered",
            "run_id": RUN,
            "streamlit_session_id": SID,
            "ts": 2002.0,
        },
        {
            "event_id": f"{RUN}:102:production_stage1_start_handler_entered",
            "run_id": RUN,
            "streamlit_session_id": SID,
            "ts": 2003.0,
        },
    ]
    pre, post = partition_ledger_by_baseline(ledger, baseline)
    events = {r["event_id"] for r in post}
    assert f"{RUN}:101:production_stage1_start_callback_entered" in events
    assert f"{RUN}:102:production_stage1_start_handler_entered" in events
    assert len(pre) == 1


def test_handler_before_click_completion_timestamp_still_post_when_index_advances() -> None:
    baseline = _baseline(max_index=50)
    row = {
        "event_id": f"{RUN}:51:production_stage1_start_handler_exited",
        "run_id": RUN,
        "streamlit_session_id": SID,
        "ts": 2000.5,
    }
    assert baseline["click_dispatch_completed_at"] == 2005.0
    assert row_is_post_start(row, baseline, row_index=0)


def test_preclick_row_excluded_even_with_late_timestamp() -> None:
    baseline = _baseline(max_index=80)
    row = {
        "event_id": f"{RUN}:80:production_stage1_pending_start_absent",
        "run_id": RUN,
        "streamlit_session_id": SID,
        "ts": 9999.0,
    }
    assert not row_is_post_start(row, baseline, row_index=0)


def test_baseline_index_fields_immutable_after_new_probe_rows() -> None:
    baseline = _baseline(max_index=120)
    frozen = copy.deepcopy(baseline)
    ledger = [
        {
            "event_id": f"{RUN}:500:production_stage1_queueui_predicate_audit",
            "run_id": RUN,
            "streamlit_session_id": SID,
            "script_run_seq": 11,
            "ts": 3000,
        }
    ]
    partition_ledger_by_baseline(ledger, baseline)
    assert baseline["baseline_event_index_max"] == frozen["baseline_event_index_max"]
    assert baseline["ledger_row_count_at_click"] == frozen["ledger_row_count_at_click"]


def test_mismatched_run_or_session_excluded() -> None:
    baseline = _baseline(max_index=10)
    row = {
        "event_id": f"{OTHER_RUN}:99:production_stage1_start_handler_entered",
        "run_id": OTHER_RUN,
        "streamlit_session_id": SID,
        "ts": 3000,
    }
    assert not row_is_post_start(row, baseline, row_index=99)


def test_predicate_rows_seq_9_10_11_retained_post_baseline() -> None:
    baseline = _baseline(max_index=200)
    ledger = []
    for seq in (9, 10, 11):
        ledger.append(
            {
                "event_id": f"{RUN}:{200 + seq}:production_stage1_queueui_predicate_audit",
                "event": "production_stage1_queueui_predicate_audit",
                "run_id": RUN,
                "streamlit_session_id": SID,
                "script_run_seq": seq,
                "checkpoint": f"cp_{seq}",
                "ts": 2100 + seq,
            }
        )
    _, post = partition_ledger_by_baseline(ledger, baseline)
    seqs = distinct_predicate_script_run_seq(post)
    assert seqs == [9, 10, 11]


def test_multiple_checkpoints_one_sequence_count_once() -> None:
    rows = [
        {
            "event": "production_stage1_queueui_predicate_audit",
            "script_run_seq": 9,
            "checkpoint": "a",
        },
        {
            "event": "production_stage1_queueui_predicate_audit",
            "script_run_seq": 9,
            "checkpoint": "b",
        },
        {
            "event": "production_stage1_queueui_predicate_audit",
            "script_run_seq": 10,
            "checkpoint": "c",
        },
        {
            "event": "production_stage1_queueui_predicate_audit",
            "script_run_seq": 11,
            "checkpoint": "d",
        },
    ]
    assert distinct_predicate_script_run_seq(rows) == [9, 10, 11]


def test_fewer_than_three_sequences_cannot_classify_queueuiroot() -> None:
    rows = [
        {
            "event": "production_stage1_queueui_predicate_audit",
            "script_run_seq": 9,
            "auth": {"authenticated": False},
            "restore": {"restore_blocked_reason": "auth_required"},
            "predicates": {"full_body_predicate": False},
        },
        {
            "event": "production_stage1_queueui_predicate_audit",
            "script_run_seq": 11,
            "auth": {"authenticated": False},
            "restore": {"restore_blocked_reason": "auth_required"},
            "predicates": {"full_body_predicate": False},
        },
    ]
    completion = evaluate_audit_completion(
        ledger_rows=rows,
        server_latch={"ok": True, "server_room_id": "R1"},
        room_id="R1",
        protocol_violation=None,
        start_click_observed=True,
        ledger_summary={"handler_entered": True, "handler_exited": True},
    )
    assert completion["reason"] == "fewer_than_three_predicate_script_run_seq"
    root = classify_queueui_root(ledger_rows=rows)
    assert not root.get("proven")


def test_prestart_stale_auth_required_on_earlier_seq_does_not_fail() -> None:
    ledger = [
        {
            "run_id": RUN,
            "streamlit_session_id": SID,
            "script_run_seq": 2,
            "restore": {"restore_blocked_reason": "auth_required"},
        },
        {
            "run_id": RUN,
            "streamlit_session_id": SID,
            "script_run_seq": 3,
            "restore": {"restore_blocked_reason": ""},
        },
    ]
    sig = prestart_ledger_signals(ledger, streamlit_session_id=SID, diagnostic_run_id=RUN)
    assert sig["restore_blocked_reason"] == ""
    lobby = {
        "has_start_new": True,
        "wake": {},
        "inferred_status": "setup_lobby",
    }
    out = evaluate_prestart_isolation(
        lobby,
        ledger,
        setup_stable={"ok": True},
        streamlit_session_id=SID,
        diagnostic_run_id=RUN,
        auth_preflight_passed=True,
    )
    assert out["passed"]


def test_prestart_latest_seq_auth_required_still_fails() -> None:
    ledger = [
        {
            "run_id": RUN,
            "streamlit_session_id": SID,
            "script_run_seq": 3,
            "restore": {"restore_blocked_reason": "auth_required"},
        },
    ]
    lobby = {"has_start_new": True, "wake": {}, "inferred_status": "setup_lobby"}
    out = evaluate_prestart_isolation(
        ledger=ledger,
        lobby=lobby,
        setup_stable={"ok": True},
        streamlit_session_id=SID,
        diagnostic_run_id=RUN,
        auth_preflight_passed=True,
    )
    assert not out["passed"]
    assert "restore_blocked:auth_required" in out["reasons"]


def test_prestart_excludes_other_diagnostic_run() -> None:
    ledger = [
        {
            "run_id": OTHER_RUN,
            "streamlit_session_id": SID,
            "script_run_seq": 99,
            "restore": {"restore_blocked_reason": "auth_required"},
        },
        {
            "run_id": RUN,
            "streamlit_session_id": SID,
            "script_run_seq": 3,
            "restore": {"restore_blocked_reason": ""},
        },
    ]
    sig = prestart_ledger_signals(ledger, streamlit_session_id=SID, diagnostic_run_id=RUN)
    assert sig["restore_blocked_reason"] == ""


def test_auth_preflight_must_pass() -> None:
    out = evaluate_prestart_isolation(
        lobby={"has_start_new": True, "wake": {}},
        ledger=[],
        setup_stable={"ok": True},
        auth_preflight_passed=False,
    )
    assert "auth_preflight_failed" in out["reasons"]


def test_ledger_event_index_parser() -> None:
    assert ledger_event_index({"event_id": "abc:42:production_stage1_start_handler_entered"}) == 42
