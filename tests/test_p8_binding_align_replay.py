"""Replay production P8 binding artifacts for BINDALIGN / pick-0 contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def f71_artifact() -> dict:
    path = ROOT / "data" / "production_p8_binding_diagnostic.json"
    if not path.is_file():
        pytest.skip("production_p8_binding_diagnostic.json not present")
    return json.loads(path.read_text(encoding="utf-8"))


def test_f71_replay_bindalign4_and_pick0_contract(f71_artifact: dict) -> None:
    from scripts.p8_binding_align_classify import BINDALIGN4, replay_artifact

    out = replay_artifact(f71_artifact)
    assert out["harness_run_id"] == "f71d5f97331343de"
    assert out["application_diagnostic_run_id"] == "588cf190214940c1"
    assert out["room_id"] == "7BF00903"
    contract = out["pick0_contract"]
    assert contract["expected_pick_0_token_raw"] == "7BF00903|0|1785675734.534"
    assert contract["pick_index"] == 0
    inv = out["focused_invariants"]
    assert inv["accepted_claims"] >= 1
    assert inv["auto_pick_entries"] >= 1
    assert inv["callback_handoff_written"] >= 1
    assert out["bindalign_classification"] == BINDALIGN4
    assert out["pick1_evidence"]["classification"] == "A. Authoritative room advancement"


def test_pick0_token_fields_stay_aligned_on_f71(f71_artifact: dict) -> None:
    from scripts.p8_binding_align_classify import replay_artifact

    tokens = replay_artifact(f71_artifact)["independent_tokens"]
    pick0 = tokens["pre_expiration_expected_token_raw"]
    assert tokens["callback_handoff_written_token_raw"] == pick0
    assert tokens["gate_selected_token_raw"] == pick0
    assert tokens["observation_input_token_raw"] == pick0


def test_classify_focused_outcome_detects_bindalign4_from_ledger(f71_artifact: dict) -> None:
    from scripts.p8_binding_align_classify import replay_artifact
    from scripts.p8_diagnostic_setup import classify_focused_p8_outcome

    replay = replay_artifact(f71_artifact)
    rows = (
        (f71_artifact.get("p8_ladder") or {}).get("ledger_filter") or {}
    ).get("filtered_rows") or []
    ladder = f71_artifact.get("p8_ladder") or {}
    outcome = classify_focused_p8_outcome(
        setup_valid=True,
        setup_abort_reason="",
        python_chain=ladder.get("python_binding_chain") or {},
        gate_rows=[r for r in rows if r.get("event") == "production_stage1_bound_token_gate"],
        browser_send=ladder.get("production_countdown_send") or {},
        filtered_meta={"filtered_rows": rows},
        observability_valid=True,
    )
    assert "BINDALIGN4" in outcome
    assert replay["focused_invariants"]["accepted_claims"] >= 1


def test_focused_invariant_report_exposes_harness_fields(f71_artifact: dict) -> None:
    from scripts.p8_binding_align_classify import build_focused_invariant_report

    rows = (
        (f71_artifact.get("p8_ladder") or {}).get("ledger_filter") or {}
    ).get("filtered_rows") or []
    report = build_focused_invariant_report(rows, room_id="7BF00903")
    for key in (
        "try_claim_call_count",
        "accepted_claim_count",
        "rejected_claim_count",
        "callback_claim_count",
        "actionable_flush_count",
        "auto_pick_entry_count",
        "committed_pick_count",
        "room_pick_index_before",
        "room_pick_index_after",
    ):
        assert key in report
    assert report["accepted_claim_count"] >= 1
