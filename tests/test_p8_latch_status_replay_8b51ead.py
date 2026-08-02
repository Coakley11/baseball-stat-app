"""LATCHSTATUS replay — artifact 8b51ead and authority precedence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from p8_room_status_authority import (  # noqa: E402
    LATCHSTATUS1,
    LATCHSTATUS4,
    LATCHSTATUS8,
    LATCHSTATUS10,
    classify_latch_status_boundary,
    merge_ui_with_server_status,
    normalize_room_status,
    resolve_authoritative_room_status,
)
from p8_start_boundary_classify import START9D, START_PIPELINE_PASS, classify_start_boundary  # noqa: E402
from replay_p8_8b51ead_latch_status import replay_8b51ead_setup  # noqa: E402


def test_normalize_in_progress_variants() -> None:
    assert normalize_room_status("in_progress") == "in_progress"
    assert normalize_room_status("IN_PROGRESS") == "in_progress"
    assert normalize_room_status("") == "missing"


def test_8b51ead_replay_latchstatus1_not_start9d() -> None:
    art = ROOT / "data" / "production_p8_binding_diagnostic.json"
    if not art.is_file():
        return
    raw = json.loads(art.read_text(encoding="utf-8"))
    if raw.get("harness_run_id") != "8b51ead096e040dd":
        return
    replay = replay_8b51ead_setup(art)
    assert replay["latch_status_classification"]["classification"] == LATCHSTATUS1
    assert replay["room_status_authority"]["status_in_progress_server"] is True
    assert replay["room_status_authority"]["normalized_status"] == "in_progress"
    assert replay["ui_scrape_status"]["in_progress"] is False


def test_server_in_progress_overrides_missing_ui_for_start_boundary() -> None:
    rows = [
        {
            "event": "production_stage1_room_state_read",
            "run_id": "app111",
            "ts": 10.0,
            "script_run_seq": 14,
            "session_room_id": "ABCD1234",
            "session_draft_status": "in_progress",
            "pick_index": 0,
        },
        {"event": "production_live_draft_branch_canary", "run_id": "app111", "ts": 9.0, "script_run_seq": 12},
    ]
    ui = {"room_id": "ABCD1234", "in_progress": False, "setup_start_visible": False}
    auth = resolve_authoritative_room_status(
        ledger_rows=rows,
        room_id="ABCD1234",
        application_diagnostic_run_id="app111",
        ui_scrape=ui,
    )
    merged = merge_ui_with_server_status(ui, auth)
    out = classify_start_boundary(
        ldr_surface={"setup_visible": True, "live_draft_main_marker": True},
        click_transport={"dom_click_dispatched": True, "streamlit_backmsg_sent": True, "selector_found": True},
        ledger_rows=rows,
        authoritative_state=merged,
        start_proof={"countdown_mounted": True},
        click_ts=8.0,
        reconciled_audit={"handler_exited_count": 1, "inferred_created_room_id": "ABCD1234"},
    )
    assert out["classification"] == START_PIPELINE_PASS
    assert out["classification"] != START9D


def test_genuine_non_in_progress_server_fails_latch() -> None:
    rows = [
        {
            "event": "production_stage1_room_creation_exited",
            "run_id": "app222",
            "room_id": "EFGH5678",
            "room_status": "setup",
            "ts": 1.0,
        }
    ]
    auth = resolve_authoritative_room_status(
        ledger_rows=rows,
        room_id="EFGH5678",
        application_diagnostic_run_id="app222",
        ui_scrape={"room_id": "EFGH5678", "in_progress": False},
    )
    assert auth["status_in_progress_server"] is False
    cls = classify_latch_status_boundary(
        status_resolution=auth,
        room_latch_pass=False,
        ledger_rows=rows,
        timeline=[],
        room_id="EFGH5678",
        application_diagnostic_run_id="app222",
    )
    assert cls["classification"] == LATCHSTATUS4


def test_harness_and_application_run_ids_differ_8b51ead() -> None:
    art = ROOT / "data" / "production_p8_binding_diagnostic.json"
    if not art.is_file():
        return
    raw = json.loads(art.read_text(encoding="utf-8"))
    if raw.get("harness_run_id") != "8b51ead096e040dd":
        return
    replay = replay_8b51ead_setup(art)
    assert replay["harness_run_id"] == "8b51ead096e040dd"
    assert replay["application_diagnostic_run_id"] == "9a346d731566454a"
    assert replay["application_ledger_row_count"] > 0
    assert "9a346d731566454a" in replay["harness_run_id_on_rows"]


def test_room_latch_pass_contradiction_detected() -> None:
    auth = {
        "status_in_progress_server": False,
        "normalized_status": "setup",
        "ui_status_normalized": "setup",
    }
    cls = classify_latch_status_boundary(
        status_resolution=auth,
        room_latch_pass=True,
        ledger_rows=[],
        timeline=[],
        room_id="ZZZZ9999",
        application_diagnostic_run_id="app",
    )
    assert cls["classification"] != LATCHSTATUS1


def test_run_id_filter_mismatch_latchstatus8() -> None:
    rows = [{"event": "production_stage1_room_state_read", "run_id": "only_app", "session_draft_status": "in_progress"}]
    cls = classify_latch_status_boundary(
        status_resolution={"status_in_progress_server": False, "normalized_status": "missing", "ui_status_normalized": "missing"},
        room_latch_pass=False,
        ledger_rows=rows,
        timeline=[],
        room_id="ROOM0001",
        application_diagnostic_run_id="wrong_harness_id",
        harness_run_id="harness_only",
    )
    assert cls["classification"] in (LATCHSTATUS8, LATCHSTATUS10)
