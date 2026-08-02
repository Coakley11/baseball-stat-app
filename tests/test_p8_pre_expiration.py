"""Tests for authoritative pre-expiration resolver and PREEXP classifier."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.p8_harness_start_classify import classify_harness_start_divergence
from scripts.p8_pre_expiration_classify import PREEXP1, PREEXP4, classify_pre_expiration_boundary
from scripts.p8_pre_expiration_resolve import resolve_authoritative_pre_expiration_state

ROOT = Path(__file__).resolve().parent.parent


def _ac613684_handler_rows() -> list[dict]:
    deadline = 1785628694.1844888
    return [
        {
            "event": "production_stage1_handler_exit_session_state_proof",
            "ts": 1785628684.2,
            "run_id": "aa13ba7c614d40dc",
            "room_id": "AC613684",
            "pick_index": 0,
            "deadline": deadline,
            "room_status": "in_progress",
            "authoritative_session_state": {
                "session_room_id": "AC613684",
                "session_draft_status": "in_progress",
                "session_pick_index": 0,
            },
        },
        {
            "event": "production_stage1_start_handler_exited",
            "ts": 1785628684.21,
            "run_id": "aa13ba7c614d40dc",
            "created_room_id": "AC613684",
            "pick_index": 0,
            "deadline": deadline,
            "draft_status": "in_progress",
        },
        {
            "event": "production_stage1_room_state_read",
            "ts": 1785628684.32,
            "run_id": "aa13ba7c614d40dc",
            "read_label": "ultra_early_before_cleanup",
            "session_room_id": "AC613684",
            "session_draft_status": "in_progress",
            "session_pick_index": 0,
            "deadline": deadline,
            "pick_index": 0,
        },
    ]


def test_server_pick_deadline_token_satisfies_gate_when_dom_empty() -> None:
    ui = {
        "room_id": "AC613684",
        "in_progress": True,
        "pick_index": None,
        "deadline": None,
        "production_token": "",
        "mount": {},
        "ui": {"ccTimer": 5},
        "text_excerpt": "Time remaining: 6s",
    }
    resolved = resolve_authoritative_pre_expiration_state(
        ledger_rows=_ac613684_handler_rows(),
        ui_scrape=ui,
        room_id="AC613684",
        diagnostic_run_id="aa13ba7c614d40dc",
        click_count=1,
        room_latch_pass=True,
        now_ts=1785628685.0,
    )
    assert resolved["pick_index"] == 0
    assert resolved["deadline"] is not None
    assert resolved["expected_token"]
    assert "AC613684" in resolved["expected_token"]
    assert resolved["pre_expiration_ready"] is True
    assert resolved["dom_diagnostics_missing"]["pick_index"] is True


def test_missing_token_everywhere_blocks() -> None:
    rows = [{"event": "production_stage1_room_state_read", "room_id": "ABC", "session_room_id": "ABC"}]
    resolved = resolve_authoritative_pre_expiration_state(
        ledger_rows=rows,
        ui_scrape={"room_id": "ABC", "in_progress": True, "text_excerpt": "Time remaining: 1s", "ui": {"ccTimer": 1}},
        room_id="ABC",
        click_count=1,
        room_latch_pass=True,
        now_ts=9999999999.0,
    )
    assert not resolved["pre_expiration_ready"]
    preexp = classify_pre_expiration_boundary(resolved=resolved, room_latch_pass=True)
    assert PREEXP4 in preexp["classification"] or PREEXP2 in preexp["classification"]


def test_room_latch_pass_blocks_harness_start8() -> None:
    assert (
        classify_harness_start_divergence(
            result={"room_latch_pass": True, "stale_page_proof": True, "click_count": 1},
        )
        is None
    )


def test_token_construction_requires_all_three_fields() -> None:
    rows = _ac613684_handler_rows()
    for r in rows:
        if "deadline" in r:
            r.pop("deadline", None)
    resolved = resolve_authoritative_pre_expiration_state(
        ledger_rows=rows,
        ui_scrape={"room_id": "AC613684", "in_progress": True, "ui": {"ccTimer": 5}, "text_excerpt": "Time remaining:"},
        room_id="AC613684",
        room_latch_pass=True,
    )
    assert not resolved.get("expected_token_constructed") or not resolved["pre_expiration_ready"]


def test_ac613684_artifact_replay_preexp_ready() -> None:
    path = ROOT / "data" / "production_callback_metadata_diagnostic.json"
    if not path.is_file():
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    setup = report.get("production_setup") or {}
    rows = (setup.get("latch_ledger_export") or {}).get("rows") or []
    if not rows:
        return
    ui = setup.get("authoritative_state") or {}
    resolved = resolve_authoritative_pre_expiration_state(
        ledger_rows=rows,
        ui_scrape=ui,
        room_id=str(setup.get("room_id") or "AC613684"),
        diagnostic_run_id=str(setup.get("diagnostic_run_id") or ""),
        click_count=1,
        room_latch_pass=True,
        now_ts=1785628685.0,
    )
    assert resolved["pre_expiration_ready"] is True


def test_dom_only_insufficient_without_server() -> None:
    resolved = resolve_authoritative_pre_expiration_state(
        ledger_rows=[],
        ui_scrape={
            "room_id": "AC613684",
            "in_progress": True,
            "pick_index": 0,
            "production_token": "AC613684|0|999.000",
            "ui": {"ccTimer": 5},
            "text_excerpt": "Time remaining: 5s",
        },
        room_latch_pass=False,
        room_id="AC613684",
    )
    assert not resolved["pre_expiration_ready"]
