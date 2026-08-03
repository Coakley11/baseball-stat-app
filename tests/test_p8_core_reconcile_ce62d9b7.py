"""Artifact replay: CORE run ce62d9b7b64c414f / 4d05bdc18dcf4e5b."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from p8_core_artifact_reconcile import reconcile_saved_core_run  # noqa: E402
from run_production_stage1_authenticated import grade_stage_1a  # noqa: E402


def _summary_path() -> Path:
    return ROOT / "data" / "production_stage1_authenticated_summary.json"


def test_ce62d9b7_ledger_claim_and_pick_reconciliation() -> None:
    path = _summary_path()
    if not path.is_file():
        return
    summary = json.loads(path.read_text(encoding="utf-8"))
    if summary.get("core_harness_run_id") != "ce62d9b7b64c414f":
        return
    report = reconcile_saved_core_run(summary)
    assert report["room_id"] == "3BEEA6F2"
    assert report["frozen_pick_0_token"] == "3BEEA6F2|0|1785728365.753"
    claims = report["claim_metrics"]
    assert claims["try_claim_call_count"] == 1
    assert claims["accepted_return_value_session_bind_count"] == 1
    assert "COREOBS3" in "".join(report["coreobs_classifications"])
    pick = report["pick_reconciliation"]
    assert pick["one_durable_pick"] is True
    assert pick["pick_index_delta"] == 1
    assert pick["committed_player"] == "Francisco Lindor"
    timer = report["server_next_timer"]
    assert timer["authoritative_pick_index"] == 1
    assert "1785728385.690" in str(timer["server_deadline"])
    assert timer["server_expected_token"] == "3BEEA6F2|1|1785728385.690"
    assert report["coren7_classification"].startswith("COREN7-4")
    assert report["room_at_send"]["server_in_progress_at_send"] is True


def test_ce62d9b7_regraded_functional_pass() -> None:
    path = _summary_path()
    if not path.is_file():
        return
    summary = json.loads(path.read_text(encoding="utf-8"))
    if summary.get("core_harness_run_id") != "ce62d9b7b64c414f":
        return
    sa = summary["stage1a"]
    exp = dict(sa["expiration"])
    exp["application_diagnostic_run_id"] = summary["application_diagnostic_run_id"]
    exp["fresh_room_id"] = summary["fresh_room_id"]
    draft = sa["draft_start_validation"]
    grade = grade_stage_1a(
        None,
        draft,
        exp,
        preflight={"authenticated_restored": True},
        stage1a_mode="CORE",
    )
    assert grade["functional_verdict"] == "PASS"
    assert grade["return_value_session_bind_accepted_count"] == 1
    assert grade["functional_checks"]["2_room_in_progress_before_expire"] is True
    assert grade["functional_checks"]["8_one_pick_committed"] is True
    assert "HARNESS OBSERVABILITY CORRECTIONS" in grade["overall_classification"]
