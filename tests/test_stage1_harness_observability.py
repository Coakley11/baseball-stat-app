"""Harness-only Stage 1A observability: ledger merge and post-commit timer wait."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_harness_observability import (  # noqa: E402
    authoritative_exact_token_delivery,
    is_completed_token_event,
    is_valid_next_token,
    ledger_rows_from_callback_audit,
    merge_ledger_sources,
    parse_expire_token_fields,
    rows_from_b64,
    split_stage1a_grades,
)


def _merge(a: list, b: list) -> list:
    out = list(a)
    for row in b:
        if row not in out:
            out.append(row)
    return out


def test_merge_preserves_nonempty_when_final_dom_empty() -> None:
    loop_rows = [{"event": "production_stage1_token_claim_result", "event_id": "a1", "accepted": True}]
    callback_rows = ledger_rows_from_callback_audit(
        {
            "callbacks": [
                {
                    "callback_source": "return_value_session_bind",
                    "delivery_claimed": True,
                    "reject_code": "",
                    "raw_token": "ROOM|0|1.0",
                    "ts": 1.0,
                }
            ],
            "pick_commits": [{"pick_index_before": 0, "pick_index_after": 1, "player": "X"}],
        },
        server_chain="pick_committed|page_repaint_completed",
        server_stages=["pick_committed", "page_repaint_completed"],
    )
    meta = merge_ledger_sources(
        observation_loop_rows=loop_rows,
        peak_observation_rows=loop_rows,
        durable_best_b64="",
        final_dom_rows=[],
        callback_audit_rows=callback_rows,
        merge_fn=_merge,
    )
    assert meta["raw_dom_ledger_row_count"] == 0
    assert meta["callback_audit_row_count"] > 0
    assert meta["merged_server_ledger_row_count"] > 0
    assert "callback_audit_fallback" in meta["ledger_source_used"]


def test_duplicate_suppressed_does_not_count_as_next_token() -> None:
    completed = "ROOM|0|100.0"
    assert not is_valid_next_token(completed, completed_token=completed, room_id="ROOM", expected_pick_index=1)
    assert is_valid_next_token("ROOM|1|200.0", completed_token=completed, room_id="ROOM", expected_pick_index=1)
    cb = {"reject_code": "post_action_duplicate_suppressed", "raw_token": completed}
    assert is_completed_token_event(cb, completed)


def test_authoritative_exact_token_from_callback_not_dom() -> None:
    ok = authoritative_exact_token_delivery(
        token_sent="ROOM|0|1.0",
        component_raw="",
        server_chain="token_processed|pick_committed",
        callbacks=[
            {
                "callback_source": "return_value_session_bind",
                "delivery_claimed": True,
                "reject_code": "",
            }
        ],
        merged_ledger=[],
        mount_return="",
    )
    assert ok is True


def test_split_grades_functional_pass_observability_fail() -> None:
    checks = {
        "5_exact_token_delivery": True,
        "6_one_accepted_callback": True,
        "6a_observation_never_claimed": True,
        "6b_return_value_session_bind_accepted": True,
        "6c_claim_source_not_other": True,
        "7_zero_duplicate_processing": True,
        "7b_no_late_flush_owner": True,
        "7c_no_on_change_owner": True,
        "8_one_pick_committed": True,
        "9_pick_advances_once": True,
        "13_pick_from_expire_not_harness": True,
        "14_queue_player_ignored": True,
        "1_authenticated_at_expire": True,
        "2_room_in_progress_before_expire": True,
        "3_browser_deadline_crossed": True,
        "4_component_value_sent": True,
        "ledger_durable_retained": True,
        "10_new_deadline_after_commit": False,
        "15_next_token_after_commit": False,
        "16_next_timer_fully_verified": False,
        "11_countdown_restarts_above_zero": True,
        "12_board_or_pool_updated": True,
    }
    split = split_stage1a_grades(
        checks=checks,
        ledger_meta={"merged_server_ledger_row_count": 3},
        next_timer_wait={"status": "timeout"},
        timer_classification="T1_SERVER_NEXT_TIMER_NOT_CREATED",
    )
    assert split["functional_verdict"] == "PASS"
    assert split["observability_verdict"] == "FAIL"
    assert "FUNCTIONAL_AUTOPICK_PASS" in split["overall_classification"]


def test_parse_expire_token_pick_index_one() -> None:
    fields = parse_expire_token_fields("ABC|1|12345.6")
    assert fields["pick_index"] == 1
    assert fields["draft_id"] == "ABC"


def test_rows_from_b64_padding() -> None:
    import base64
    import json

    payload = {"rows": [{"event": "x", "event_id": "1"}]}
    b64 = base64.b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    rows = rows_from_b64(b64)
    assert len(rows) == 1
