"""Tests for QUEUEUI root predicate audit helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from live_draft_queueui_predicate_audit import compute_render_predicates  # noqa: E402
from queueui_audit_protocol import prestart_ledger_signals  # noqa: E402
from queueui_root_classify import QUEUEUIROOT1, QUEUEUIROOT2, QUEUEUIROOT3, classify_queueui_root  # noqa: E402


def test_prestart_ledger_signals_uses_latest_script_run_seq_only() -> None:
    ledger = [
        {
            "script_run_seq": 2,
            "run_id": "run-a",
            "streamlit_session_id": "sid-a",
            "restore": {"restore_blocked_reason": "auth_required"},
            "predicates": {"start_in_flight": True},
        },
        {
            "script_run_seq": 3,
            "run_id": "run-a",
            "streamlit_session_id": "sid-a",
            "restore": {"restore_blocked_reason": ""},
            "predicates": {"start_in_flight": False},
        },
    ]
    sig = prestart_ledger_signals(
        ledger,
        streamlit_session_id="sid-a",
        diagnostic_run_id="run-a",
    )
    assert sig["latest_script_run_seq"] == 3
    assert sig["restore_blocked_reason"] == ""
    assert sig["start_in_flight"] is False


def test_compute_render_predicates_room_picking_clears_rec_skip() -> None:
    session = {"_live_draft_start_in_flight": True, "live_draft_room": {"status": "in_progress", "draft_room_id": "R1"}}
    room = {"status": "in_progress", "draft_room_id": "R1", "draft_board": [], "pick_order": [{"Team": "A"}]}
    p = compute_render_predicates(session, room=room, lifecycle="active_draft", slot={"Team": "A"}, draft_in_progress=True)
    assert p["recommendation_predicate"] is True


def test_classify_root1_start_in_flight_stuck() -> None:
    rows = [
        {
            "event": "production_stage1_queueui_predicate_audit",
            "script_run_seq": 3,
            "checkpoint": "active_lifecycle_branch_entered",
            "predicates": {"start_in_flight": True, "lifecycle": "active_draft"},
        },
        {
            "event": "production_stage1_queueui_predicate_audit",
            "script_run_seq": 4,
            "checkpoint": "active_lifecycle_branch_entered",
            "predicates": {"start_in_flight": True},
        },
        {
            "event": "production_stage1_queueui_predicate_audit",
            "script_run_seq": 2,
            "checkpoint": "start_handler_after_finish_start",
            "predicates": {"start_in_flight": False},
        },
    ]
    out = classify_queueui_root(ledger_rows=rows)
    assert out["classification"] == QUEUEUIROOT1


def test_classify_root3_stale_auth_required() -> None:
    rows = [
        {
            "event": "production_stage1_queueui_predicate_audit",
            "script_run_seq": 5,
            "checkpoint": "active_lifecycle_branch_entered",
            "predicates": {"start_in_flight": False},
            "auth": {"authenticated": True},
            "restore": {"restore_blocked_reason": "auth_required"},
        },
        {
            "event": "production_stage1_queueui_predicate_audit",
            "script_run_seq": 6,
            "checkpoint": "room_body_entered",
            "predicates": {"start_in_flight": False},
            "auth": {"authenticated": True},
            "restore": {"restore_blocked_reason": "auth_required"},
        },
    ]
    out = classify_queueui_root(ledger_rows=rows)
    assert out["classification"] == QUEUEUIROOT3


def test_classify_root2_post_start_ldr_entry_unauth_with_preflight() -> None:
    rows = []
    for seq in (8, 9, 11):
        rows.append(
            {
                "event": "production_stage1_queueui_predicate_audit",
                "script_run_seq": seq,
                "checkpoint": "ldr_post_start_script_entry",
                "predicates": {"start_in_flight": seq == 8, "full_body_predicate": False},
                "auth": {"authenticated": False},
                "restore": {"restore_blocked_reason": "auth_required"},
            }
        )
    out = classify_queueui_root(ledger_rows=rows, auth_preflight_authenticated=True)
    assert out["classification"] == QUEUEUIROOT2
    assert out["proven"] is True
