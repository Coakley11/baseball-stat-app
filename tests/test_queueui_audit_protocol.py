"""Tests for QUEUEUI audit harness protocol guards."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from queueui_audit_protocol import (  # noqa: E402
    INVALID_PROTOCOL_RUN,
    MIN_PREDICATE_SCRIPT_RUN_SEQ,
    OPERATOR_VERIFIED_DEPLOY_ENV,
    PREDICATE_EVENT,
    QUEUEUIAUDIT_PRESTART_STATE_NOT_CLEAN,
    QUEUEUIAUDIT_UNEXPECTED_EXPIRATION_ACTIVITY,
    capture_audit_baseline,
    evaluate_audit_completion,
    evaluate_prestart_isolation,
    first_forbidden_after_baseline,
    forbidden_protocol_event,
    operator_verified_deploy_authorized,
    partition_ledger_by_baseline,
    queueui_audit_url_excludes_solo_diag_timer,
    queueui_root_predicate_audit_url_base,
    resolve_deployment_verification,
    row_is_post_start,
)
from queueui_audit_deploy_preflight import QUEUEUIAUDIT_DEPLOY_BLOCK  # noqa: E402
from queueui_root_classify import classify_queueui_root  # noqa: E402


def _baseline(*, click_ts: float | None = None, run_id: str = "run1", count: int = 2) -> dict:
    ledger = [
        {"event_id": f"{run_id}:1:a", "run_id": run_id, "script_run_seq": 1, "ts": 1.0, "event": "a"},
        {"event_id": f"{run_id}:2:b", "run_id": run_id, "script_run_seq": 2, "ts": 2.0, "event": "b"},
    ][:count]
    identity = {"streamlit_session_id": "sid1", "diagnostic_run_id": run_id}
    lobby = {"has_start_new": True, "wake": {}}
    return capture_audit_baseline(ledger, identity, lobby, click_ts=click_ts or 10.0)


def test_audit_url_excludes_solo_diag_timer() -> None:
    url = queueui_root_predicate_audit_url_base()
    assert "solo_component_diag=1" in url
    assert queueui_audit_url_excludes_solo_diag_timer(url)
    assert "solo_diag_timer" not in url


def test_pre_baseline_forbidden_does_not_invalidate() -> None:
    base = _baseline(click_ts=100.0, count=1)
    ledger = [
        {
            "event_id": "run1:1:a",
            "run_id": "run1",
            "script_run_seq": 1,
            "ts": 1.0,
            "event": "production_stage1_token_claim_attempt",
        },
        {
            "event_id": "run1:3:c",
            "run_id": "run1",
            "script_run_seq": 3,
            "ts": 101.0,
            "event": PREDICATE_EVENT,
        },
    ]
    violation, pre, post = first_forbidden_after_baseline(ledger, base)
    assert violation is None
    assert len(pre) == 1
    assert pre[0]["event"].startswith("production_stage1_token_claim_")


def test_post_baseline_forbidden_invalidates() -> None:
    base = _baseline(click_ts=5.0, count=2)
    ledger = [
        {"event_id": "run1:1:a", "run_id": "run1", "script_run_seq": 1, "ts": 1.0, "event": "x"},
        {"event_id": "run1:2:b", "run_id": "run1", "script_run_seq": 2, "ts": 2.0, "event": "y"},
        {
            "event_id": "run1:3:c",
            "run_id": "run1",
            "script_run_seq": 3,
            "ts": 10.0,
            "event": "production_stage1_autopick_about_to_enter",
        },
    ]
    violation, _, post = first_forbidden_after_baseline(ledger, base)
    assert violation is not None
    assert violation["event"] == "production_stage1_autopick_about_to_enter"
    assert len(post) == 1


def test_mismatched_run_id_excluded_from_post() -> None:
    base = _baseline(click_ts=1.0, run_id="runA")
    row = {
        "event_id": "runB:9:z",
        "run_id": "runB",
        "script_run_seq": 9,
        "ts": 100.0,
        "event": PREDICATE_EVENT,
    }
    assert row_is_post_start(row, base, 5) is False


def test_mismatched_session_id_excluded() -> None:
    base = _baseline(click_ts=1.0)
    base["streamlit_session_id"] = "sidA"
    row = {
        "event_id": "run1:9:z",
        "run_id": "run1",
        "streamlit_session_id": "sidB",
        "script_run_seq": 9,
        "ts": 100.0,
        "event": PREDICATE_EVENT,
    }
    assert row_is_post_start(row, base, 5) is False


def test_timestamp_alone_insufficient_without_index_and_identity() -> None:
    base = _baseline(click_ts=50.0)
    row = {
        "event_id": "other:9:z",
        "run_id": "other",
        "script_run_seq": 9,
        "ts": 100.0,
        "event": PREDICATE_EVENT,
    }
    _, post = partition_ledger_by_baseline([row], base)
    assert post == []


def test_dirty_prestart_wake_produces_not_run_reason() -> None:
    lobby = {
        "has_start_new": True,
        "visible_room_id": "",
        "python_room_id": "",
        "python_room_present": "0",
        "pause_draft_count": 0,
        "wake": {"token": "9982438C|0|123.0", "actionable": "0"},
    }
    out = evaluate_prestart_isolation(lobby, [], setup_stable={"ok": True})
    assert out["passed"] is False
    assert "stale_persistent_wake_token" in out["reasons"]


def test_empty_room_id_cannot_complete() -> None:
    rows = [{"event": PREDICATE_EVENT, "script_run_seq": i, "ts": float(i)} for i in range(1, 5)]
    out = evaluate_audit_completion(
        ledger_rows=rows,
        server_latch={"ok": True, "server_status": "in_progress"},
        room_id="",
        protocol_violation=None,
        start_click_observed=True,
        ledger_summary={"handler_entered": True, "handler_exited": True},
    )
    assert out["completed"] is False


def test_three_predicate_seq_distinct_not_dom() -> None:
    rows = [
        {"event": PREDICATE_EVENT, "script_run_seq": 4, "ts": 11.0},
        {"event": PREDICATE_EVENT, "script_run_seq": 5, "ts": 12.0},
        {"event": PREDICATE_EVENT, "script_run_seq": 6, "ts": 13.0},
    ]
    out = evaluate_audit_completion(
        ledger_rows=rows,
        server_latch={"ok": True, "server_status": "in_progress"},
        room_id="ABC123",
        protocol_violation=None,
        start_click_observed=True,
        ledger_summary={
            "handler_entered": True,
            "handler_exited": True,
            "created_room_id_from_ledger": "ABC123",
        },
    )
    assert out["completed"] is True
    assert len(out["distinct_predicate_script_run_seq"]) == MIN_PREDICATE_SCRIPT_RUN_SEQ


def test_fewer_than_three_predicate_not_completed() -> None:
    rows = [
        {"event": PREDICATE_EVENT, "script_run_seq": 1, "ts": 1.0},
        {"event": PREDICATE_EVENT, "script_run_seq": 2, "ts": 2.0},
    ]
    out = evaluate_audit_completion(
        ledger_rows=rows,
        server_latch={"ok": True, "server_status": "in_progress"},
        room_id="R1",
        protocol_violation=None,
        start_click_observed=True,
        ledger_summary={"handler_entered": True, "handler_exited": True},
    )
    assert out["completed"] is False


def test_invalid_protocol_no_queueuiroot() -> None:
    base = _baseline(click_ts=1.0, count=1)
    violation, _, _ = first_forbidden_after_baseline(
        [
            {"event_id": "run1:1:a", "run_id": "run1", "ts": 0.5, "event": "x"},
            {
                "event_id": "run1:2:c",
                "run_id": "run1",
                "script_run_seq": 2,
                "ts": 5.0,
                "event": "production_stage1_try_claim_about_to_call",
            },
        ],
        base,
    )
    assert violation is not None
    out = evaluate_audit_completion(
        ledger_rows=[],
        server_latch={"ok": False},
        room_id="",
        protocol_violation=violation,
        start_click_observed=True,
        ledger_summary={},
    )
    assert out["audit_execution_status"] == INVALID_PROTOCOL_RUN
    assert out["first_boundary"] == QUEUEUIAUDIT_UNEXPECTED_EXPIRATION_ACTIVITY
    root = classify_queueui_root(ledger_rows=[violation["row"]])
    assert root.get("classification") is None


def test_empty_dom_cannot_pass_without_operator_flag() -> None:
    page = mock.MagicMock()
    with mock.patch(
        "queueui_audit_protocol.scrape_deploy_marker_from_page",
        return_value=("", "dom_scrape_empty"),
    ):
        with mock.patch.dict(os.environ, {"REQUIRED_CLOUD_SHA": "4359938"}, clear=False):
            os.environ.pop(OPERATOR_VERIFIED_DEPLOY_ENV, None)
            out = resolve_deployment_verification(
                page,
                {},
                required="4359938",
                deploy_pin="4359938",
            )
    assert out["preflight"]["passed"] is False


def test_operator_verified_mode_when_authorized() -> None:
    page = mock.MagicMock()
    env = {
        "REQUIRED_CLOUD_SHA": "4359938",
        OPERATOR_VERIFIED_DEPLOY_ENV: "1",
    }
    with mock.patch(
        "queueui_audit_protocol.scrape_deploy_marker_from_page",
        return_value=("", "dom_scrape_empty"),
    ):
        with mock.patch.dict(os.environ, env, clear=False):
            assert operator_verified_deploy_authorized(required="4359938", deploy_pin="4359938")
            out = resolve_deployment_verification(
                page,
                {},
                required="4359938",
                deploy_pin="4359938",
            )
    assert out["operator_verified_deploy_used"] is True
    assert out["preflight"]["passed"] is True


def test_prestart_boundary_constant() -> None:
    assert "NOT_CLEAN" in QUEUEUIAUDIT_PRESTART_STATE_NOT_CLEAN


def test_try_claim_forbidden() -> None:
    assert (
        forbidden_protocol_event({"event": "production_stage1_try_claim_about_to_call"})
        == "production_stage1_try_claim_about_to_call"
    )


def test_deploy_block_constant() -> None:
    assert "DEPLOY_BLOCK" in QUEUEUIAUDIT_DEPLOY_BLOCK
