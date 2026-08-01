"""Tests for canonical production start helper and harness divergence."""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.p8_canonical_production_start import HELPER_NAME, establish_single_solo_live_draft
from scripts.p8_harness_start_classify import (
    CANONICAL_HELPER_NAME,
    HARNESS_START6,
    ROOM_LATCH_REFERENCE_CHAIN,
    classify_harness_start_divergence,
    compare_harness_chains,
)
from scripts.p8_start_audit_reconcile import collect_start_audit_rows
from scripts.p8_start_boundary_classify import START8, classify_start_boundary


ROOT = Path(__file__).resolve().parent.parent


def test_room_latch_and_gate_b_import_same_helper() -> None:
    latch_src = (ROOT / "scripts" / "run_production_room_latch_verification.py").read_text(encoding="utf-8")
    gate_src = (ROOT / "scripts" / "run_production_callback_binding_diagnostic.py").read_text(encoding="utf-8")
    assert "establish_single_solo_live_draft" in latch_src
    assert "establish_single_solo_live_draft" in gate_src
    assert CANONICAL_HELPER_NAME in latch_src
    assert CANONICAL_HELPER_NAME in gate_src


def test_gate_b_no_longer_calls_run_gate_b_production_start() -> None:
    gate_src = (ROOT / "scripts" / "run_production_callback_binding_diagnostic.py").read_text(encoding="utf-8")
    tree = ast.parse(gate_src)
    call_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "run_gate_b_production_start" not in call_names


def test_run_gate_b_delegates_to_canonical_helper() -> None:
    harness_src = (ROOT / "scripts" / "p8_production_start_harness.py").read_text(encoding="utf-8")
    assert "establish_single_solo_live_draft" in harness_src


def test_compare_chains_first_difference_prior_gate_b() -> None:
    cmp_out = compare_harness_chains(
        reference=ROOM_LATCH_REFERENCE_CHAIN,
        actual={
            "helper_name": "establish_single_solo_live_draft",
            "fresh_lobby_cleanup": "ensure_fresh_setup_lobby (separate before run_gate_b)",
            "navigation_helper": "goto_and_wake(production_url)",
            "setup_surface_helper": "ensure_p8_ldr_setup_surface",
            "start_click_helper": "dispatch_start_single_authoritative_click",
            "post_click_ledger_poll": "handler_exited_or_room_creation_exited",
            "ledger_filter": "filter_latch_ledger_rows",
            "room_latch_verify": "classify_room_latch_verify",
        },
    )
    first = cmp_out.get("first_difference") or {}
    assert first.get("field") == "fresh_lobby_cleanup"


def test_handler_rows_recovered_outside_narrow_filter() -> None:
    click_ts = 100.0
    rows = [
        {"event": "production_stage1_start_handler_entered", "ts": 100.1, "run_id": "runA", "room_id": "ABC12345"},
        {
            "event": "production_stage1_start_handler_exited",
            "ts": 100.2,
            "run_id": "runA",
            "created_room_id": "ABC12345",
            "streamlit_session_id": "sess-1",
        },
    ]
    narrow = [r for r in rows if r.get("run_id") == "wrong"]
    recon = collect_start_audit_rows(
        rows,
        click_ts=click_ts,
        diagnostic_run_id="runA",
        streamlit_session_id="sess-1",
        created_room_id="ABC12345",
    )
    assert recon["handler_exited_count"] == 1
    assert len(narrow) == 0


def test_start8_suppressed_when_reconciled_room_exists() -> None:
    click_ts = 50.0
    rows = [
        {"event": "production_live_draft_branch_canary", "ts": 50.2, "room_id": "D0159964"},
        {
            "event": "production_stage1_start_handler_exited",
            "ts": 50.3,
            "created_room_id": "D0159964",
            "handler_success": True,
        },
    ]
    recon = collect_start_audit_rows(rows, click_ts=click_ts, created_room_id="D0159964")
    out = classify_start_boundary(
        ldr_surface={"setup_visible": True, "live_draft_main_marker": True},
        click_transport={"dom_click_dispatched": True, "streamlit_backmsg_sent": True, "selector_found": True},
        ledger_rows=[],
        authoritative_state={"room_id": "", "in_progress": False},
        start_proof={},
        click_ts=click_ts,
        reconciled_audit=recon,
    )
    assert out["classification"] != START8


def test_authoritative_room_blocks_start8_harness_classify() -> None:
    div = classify_harness_start_divergence(
        result={"room_id": "D0159964", "room_latch_pass": False, "click_count": 1},
        functional_start_label="START8 — BUTTON_TRUE_BUT_START_HANDLER_NOT_ENTERED",
        audit_reconcile={"audit_filter_mismatch": True, "handler_exited_count": 1},
    )
    assert div["classification"] == HARNESS_START6


def test_session_mismatch_blocks_harness() -> None:
    div = classify_harness_start_divergence(
        result={"room_latch_pass": False, "click_count": 1, "identity_timeline": []},
        identity_timeline=[
            {"streamlit_session_id": "a", "diagnostic_run_id": "r1", "page_url": "https://x/?active_page=Live"},
            {"streamlit_session_id": "b", "diagnostic_run_id": "r1", "page_url": "https://x/?active_page=Live"},
        ],
    )
    assert "HARNESS_START4" in div["classification"]


def test_click_count_must_be_one() -> None:
    div = classify_harness_start_divergence(
        result={"room_latch_pass": False, "click_count": 2, "identity_timeline": []},
    )
    assert "HARNESS_START10" in div["classification"]


def test_helper_name_constant() -> None:
    assert HELPER_NAME == "establish_single_solo_live_draft"


def test_diagnostic_scripts_reference_same_symbol() -> None:
    for path in (
        "scripts/run_production_room_latch_verification.py",
        "scripts/run_production_callback_binding_diagnostic.py",
    ):
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "establish_single_solo_live_draft" in names
