"""Latch reconciliation and START precedence regression tests."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.p8_room_latch_reconcile import (
    LATCHREC1,
    merge_latch_rows_from_full_ledger,
    replay_artifact_latch,
    server_latch_bundle_proven,
)
from scripts.p8_start_boundary_classify import START7, START_PIPELINE_PASS, classify_start_boundary

ROOT = Path(__file__).resolve().parent.parent


def test_later_button_false_does_not_override_start_success() -> None:
    click_ts = 100.0
    rows = [
        {
            "event": "production_stage1_start_button_value",
            "ts": 100.1,
            "script_run_seq": 6,
            "on_click_callback_armed": True,
            "button_return_value": True,
        },
        {
            "event": "production_stage1_start_button_value",
            "ts": 101.5,
            "script_run_seq": 7,
            "on_click_callback_armed": False,
            "button_return_value": False,
        },
        {
            "event": "production_stage1_start_handler_entered",
            "ts": 100.2,
            "script_run_seq": 6,
        },
        {
            "event": "production_stage1_start_handler_exited",
            "ts": 100.3,
            "script_run_seq": 6,
            "created_room_id": "D0FF6120",
        },
        {"event": "production_live_draft_branch_canary", "ts": 100.0, "script_run_seq": 6},
    ]
    recon = {
        "handler_entered_count": 1,
        "handler_exited_count": 1,
        "inferred_created_room_id": "D0FF6120",
    }
    out = classify_start_boundary(
        ldr_surface={"setup_visible": True, "live_draft_main_marker": True},
        click_transport={"dom_click_dispatched": True, "streamlit_backmsg_sent": True, "selector_found": True},
        ledger_rows=rows,
        authoritative_state={"room_id": "D0FF6120", "in_progress": True},
        start_proof={"countdown_mounted": True},
        click_ts=click_ts,
        reconciled_audit=recon,
    )
    assert out["classification"] == START_PIPELINE_PASS
    assert out["classification"] != START7


def test_harness_and_application_run_ids_may_differ_in_replay() -> None:
    art_path = ROOT / "data" / "production_p8_binding_diagnostic.json"
    if not art_path.is_file():
        return
    artifact = json.loads(art_path.read_text(encoding="utf-8"))
    if artifact.get("diagnostic_run_id") != "a610bf3d8ba24559":
        return
    replay = replay_artifact_latch(artifact)
    assert replay["harness_run_id"] == "a610bf3d8ba24559"
    assert replay["application_diagnostic_run_id"] == "735c98335b034715"
    assert replay["harness_run_id"] != replay["application_diagnostic_run_id"]


def test_application_run_id_filter_recovery() -> None:
    app_run = "735c98335b034715"
    full = [
        {
            "event_id": "x:1",
            "event": "production_stage1_start_handler_exited",
            "run_id": app_run,
            "created_room_id": "D0FF6120",
            "ts": 10.0,
            "pick_index": 0,
            "deadline": 20.0,
        }
    ]
    filtered: list = []
    merged, meta = merge_latch_rows_from_full_ledger(
        filtered,
        full,
        application_diagnostic_run_id=app_run,
        created_room_id="D0FF6120",
        click_ts=9.0,
    )
    assert meta["recovered_count"] == 1
    assert merged[0]["run_id"] == app_run


def test_d0ff6120_replay_latch_rec1_when_server_bundle_complete() -> None:
    art_path = ROOT / "data" / "production_p8_binding_diagnostic.json"
    if not art_path.is_file():
        return
    artifact = json.loads(art_path.read_text(encoding="utf-8"))
    if str((artifact.get("production_setup") or {}).get("room_id") or "") != "D0FF6120":
        return
    replay = replay_artifact_latch(artifact)
    assert replay["room_id"] == "D0FF6120"
    assert replay["server_latch_bundle"].get("ok") is True
    assert replay["room_latch_pass_reconciled"] is True
    assert LATCHREC1.split(" ")[0] in replay["latch_reconciliation"]["classification"]


def test_server_latch_ignores_empty_ui_scrape() -> None:
    filtered = [
        {
            "event": "production_stage1_start_handler_exited",
            "created_room_id": "ABC12345",
            "pick_index": 0,
            "deadline": 999.0,
            "ts": 1.0,
        },
        {
            "event": "production_stage1_handler_exit_session_state_proof",
            "local_created_room_id": "ABC12345",
            "pick_index": 0,
            "session_deadline_token": "ABC12345|0|999",
            "ts": 1.1,
        },
        {"event": "production_countdown_declaration_post", "room_id": "ABC12345", "pick_index": 0, "ts": 1.2},
    ]
    timeline = [
        {
            "operation": "read",
            "reason": "ultra_early_room_state",
            "room_id_after": "ABC12345",
            "draft_status": "in_progress",
            "pick_index": 0,
            "deadline_token": "999",
            "ts": 2.0,
        }
    ]
    bundle = server_latch_bundle_proven(filtered_ledger=filtered, timeline=timeline, created_room_id="ABC12345")
    assert bundle["ok"] is True


def test_later_room_clear_fails_latch() -> None:
    filtered = [
        {"event": "production_stage1_start_handler_exited", "created_room_id": "ABC12345", "pick_index": 0, "deadline": 1.0, "ts": 1.0},
    ]
    timeline = [{"operation": "clear", "room_id_before": "ABC12345", "ts": 2.0}]
    bundle = server_latch_bundle_proven(filtered_ledger=filtered, timeline=timeline, created_room_id="ABC12345")
    assert bundle["ok"] is False
    assert bundle["checks"]["later_clear"] is True
