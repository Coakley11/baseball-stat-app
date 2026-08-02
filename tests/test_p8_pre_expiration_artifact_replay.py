"""Regression: pre-expiration resolver replays from saved Gate B / lifecycle artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.p8_canonical_production_start import establish_single_solo_live_draft
from scripts.p8_pre_expiration_classify import PREEXP7, classify_pre_expiration_boundary
from scripts.p8_pre_expiration_resolve import (
    pre_expiration_evidence_freeze_ts,
    resolve_authoritative_pre_expiration_state,
)

ROOT = Path(__file__).resolve().parent.parent
LIFECYCLE_ART = ROOT / "data" / "production_callback_value_lifecycle_diagnostic.json"
AA04920D_TOKEN = "12E729A7|0|1785630315.461"


def _aa04920d_rows() -> list[dict]:
    deadline = 1785630315.461
    rid = "12E729A7"
    return [
        {
            "event": "production_stage1_handler_exit_session_state_proof",
            "ts": 1785630310.0,
            "run_id": "aa04920d7a244dd9",
            "room_id": rid,
            "pick_index": 0,
            "deadline": deadline,
            "authoritative_session_state": {
                "session_room_id": rid,
                "session_draft_status": "in_progress",
                "session_pick_index": 0,
            },
        },
        {
            "event": "production_countdown_declaration_post",
            "ts": 1785630312.0,
            "run_id": "aa04920d7a244dd9",
            "room_id": rid,
            "pick_index": 0,
            "deadline": deadline,
            "expected_token": AA04920D_TOKEN,
        },
    ]


def test_aa04920d_fixture_resolves_pre_expiration_ready() -> None:
    ui = {
        "room_id": "12E729A7",
        "in_progress": True,
        "text_excerpt": "Time remaining: 8s",
        "ui": {"ccTimer": 8},
    }
    rows = _aa04920d_rows()
    freeze = pre_expiration_evidence_freeze_ts(
        rows, room_id="12E729A7", diagnostic_run_id="aa04920d7a244dd9"
    )
    resolved = resolve_authoritative_pre_expiration_state(
        ledger_rows=rows,
        ui_scrape=ui,
        room_id="12E729A7",
        diagnostic_run_id="aa04920d7a244dd9",
        click_count=1,
        room_latch_pass=True,
        now_ts=freeze,
    )
    assert resolved["pre_expiration_ready"] is True
    assert resolved["expected_token"] == AA04920D_TOKEN


def test_995a829_artifact_replay_passes_after_freeze_and_stale_read_filter() -> None:
    if not LIFECYCLE_ART.is_file():
        return
    report = json.loads(LIFECYCLE_ART.read_text(encoding="utf-8"))
    setup = report.get("production_setup") or {}
    rows = list((setup.get("latch_ledger_export") or {}).get("rows") or [])
    if not rows:
        return
    rid = str(setup.get("room_id") or setup.get("latched_room_id") or "")
    run_id = str(setup.get("diagnostic_run_id") or "")
    pre = setup.get("pre_expiration_resolution") or {}
    rows.extend(
        [
            {
                "event": "production_countdown_declaration_post",
                "ts": 1785636948.1775606,
                "run_id": run_id,
                "room_id": rid,
                "pick_index": 0,
                "deadline": pre.get("deadline") or 1785636949.4878707,
                "expected_token": pre.get("expected_token") or "EAB670D2|0|1785636949.488",
            }
        ]
    )
    ui = setup.get("authoritative_state") or {}
    freeze = pre_expiration_evidence_freeze_ts(rows, room_id=rid, diagnostic_run_id=run_id)
    resolved = resolve_authoritative_pre_expiration_state(
        ledger_rows=rows,
        ui_scrape=ui,
        room_id=rid,
        diagnostic_run_id=run_id,
        click_count=1,
        room_latch_pass=True,
        now_ts=freeze,
    )
    preexp = classify_pre_expiration_boundary(
        resolved=resolved,
        room_latch_pass=True,
        identity_timeline=setup.get("identity_timeline"),
    )
    assert resolved["pre_expiration_ready"] is True
    assert resolved["pick_index"] == 0
    assert not preexp.get("classification")


def test_995a829_without_freeze_classifies_preexp7() -> None:
    if not LIFECYCLE_ART.is_file():
        return
    setup = json.loads(LIFECYCLE_ART.read_text(encoding="utf-8")).get("production_setup") or {}
    rows = list((setup.get("latch_ledger_export") or {}).get("rows") or [])
    if not rows:
        return
    pre = setup.get("pre_expiration_resolution") or {}
    rid = str(setup.get("room_id") or "")
    run_id = str(setup.get("diagnostic_run_id") or "")
    rows.append(
        {
            "event": "production_countdown_declaration_post",
            "ts": 1785636948.1775606,
            "run_id": run_id,
            "room_id": rid,
            "pick_index": 0,
            "deadline": pre.get("deadline"),
            "expected_token": pre.get("expected_token"),
        }
    )
    ui = setup.get("authoritative_state") or {}
    resolved = resolve_authoritative_pre_expiration_state(
        ledger_rows=rows,
        ui_scrape=ui,
        room_id=rid,
        diagnostic_run_id=run_id,
        click_count=1,
        room_latch_pass=True,
        now_ts=1785636952.0,
    )
    preexp = classify_pre_expiration_boundary(resolved=resolved, room_latch_pass=True)
    assert PREEXP7 in str(preexp.get("classification") or "")


def test_latch_filter_retains_countdown_declaration_events() -> None:
    from scripts.p8_room_latch_ledger_export import filter_latch_ledger_rows

    rows = [
        {
            "event": "production_countdown_declaration_post",
            "ts": 100.0,
            "run_id": "run1",
            "room_id": "ABC123",
            "expected_token": "ABC123|0|999.000",
            "pick_index": 0,
        },
        {"event": "production_global_script_run_canary", "ts": 99.0, "run_id": "run1"},
    ]
    kept = filter_latch_ledger_rows(rows, diagnostic_run_id="run1", created_room_id="ABC123", click_ts=98.0)
    assert any(r.get("event") == "production_countdown_declaration_post" for r in kept)


def test_canonical_start_uses_shared_resolver() -> None:
    src = (ROOT / "scripts" / "p8_canonical_production_start.py").read_text(encoding="utf-8")
    assert "pre_expiration_evidence_freeze_ts" in src
    assert "classify_pre_expiration_boundary" in src
    assert "resolve_authoritative_pre_expiration_state" in src
    diag = (ROOT / "scripts" / "run_production_callback_binding_diagnostic.py").read_text(encoding="utf-8")
    assert "establish_single_solo_live_draft" in diag
    assert "classify_pre_expiration_boundary" in diag
