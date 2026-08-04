"""Tests for QUEUEUI audit harness protocol guards."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from queueui_audit_protocol import (  # noqa: E402
    INVALID_PROTOCOL_RUN,
    MIN_PREDICATE_SCRIPT_RUN_SEQ,
    OPERATOR_VERIFIED_DEPLOY_ENV,
    PREDICATE_EVENT,
    QUEUEUIAUDIT_UNEXPECTED_EXPIRATION_ACTIVITY,
    evaluate_audit_completion,
    first_forbidden_protocol_violation,
    forbidden_protocol_event,
    operator_verified_deploy_authorized,
    queueui_audit_url_excludes_solo_diag_timer,
    queueui_root_predicate_audit_url_base,
    resolve_deployment_verification,
)
from queueui_audit_deploy_preflight import QUEUEUIAUDIT_DEPLOY_BLOCK  # noqa: E402
from queueui_root_classify import classify_queueui_root  # noqa: E402


def test_audit_url_excludes_solo_diag_timer() -> None:
    url = queueui_root_predicate_audit_url_base()
    assert "solo_component_diag=1" in url
    assert queueui_audit_url_excludes_solo_diag_timer(url)
    assert "solo_diag_timer" not in url


def test_token_claim_invalidates_protocol() -> None:
    rows = [{"event": "production_stage1_token_claim_attempt", "script_run_seq": 2}]
    v = first_forbidden_protocol_violation(rows)
    assert v is not None
    assert v["event"].startswith("production_stage1_token_claim_")


def test_autopick_invalidates_protocol() -> None:
    rows = [{"event": "production_stage1_autopick_about_to_enter"}]
    assert first_forbidden_protocol_violation(rows) is not None


def test_zero_predicate_events_not_completed() -> None:
    out = evaluate_audit_completion(
        ledger_rows=[],
        server_latch={"ok": True},
        room_id="ABCD1234",
        protocol_violation=None,
    )
    assert out["completed"] is False
    assert out["audit_execution_status"] != "COMPLETED"


def test_empty_room_id_not_completed() -> None:
    rows = [
        {
            "event": PREDICATE_EVENT,
            "script_run_seq": i,
        }
        for i in range(1, MIN_PREDICATE_SCRIPT_RUN_SEQ + 1)
    ]
    out = evaluate_audit_completion(
        ledger_rows=rows,
        server_latch={"ok": True},
        room_id="",
        protocol_violation=None,
    )
    assert out["completed"] is False


def test_fewer_than_three_predicate_seq_not_completed() -> None:
    rows = [
        {"event": PREDICATE_EVENT, "script_run_seq": 1},
        {"event": PREDICATE_EVENT, "script_run_seq": 2},
    ]
    out = evaluate_audit_completion(
        ledger_rows=rows,
        server_latch={"ok": True},
        room_id="ROOM1",
        protocol_violation=None,
    )
    assert out["completed"] is False
    assert "fewer_than_three" in out.get("reason", "")


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
    assert out["verification_method"] == "failed_dom_scrape_no_operator_authorization"


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
    assert out["dom_marker_absent"] is True


def test_invalid_protocol_run_emits_no_queueuiroot() -> None:
    rows = [{"event": "production_stage1_try_claim_about_to_call"}]
    v = first_forbidden_protocol_violation(rows)
    assert v is not None
    out = evaluate_audit_completion(
        ledger_rows=rows,
        server_latch={"ok": True},
        room_id="R1",
        protocol_violation=v,
    )
    assert out["audit_execution_status"] == INVALID_PROTOCOL_RUN
    assert out["first_boundary"] == QUEUEUIAUDIT_UNEXPECTED_EXPIRATION_ACTIVITY
    root = classify_queueui_root(ledger_rows=rows)
    assert root.get("classification") is None


def test_try_claim_forbidden() -> None:
    assert (
        forbidden_protocol_event({"event": "production_stage1_try_claim_about_to_call"})
        == "production_stage1_try_claim_about_to_call"
    )


def test_deploy_block_constant() -> None:
    assert "DEPLOY_BLOCK" in QUEUEUIAUDIT_DEPLOY_BLOCK
