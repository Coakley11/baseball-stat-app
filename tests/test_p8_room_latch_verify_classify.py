"""Tests for VERIFY room-latch classifier."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.p8_room_latch_verify_classify import (
    VERIFY1,
    VERIFY4,
    VERIFY7,
    VERIFY8,
    VERIFY10,
    classify_room_latch_verify,
)

ROOT = Path(__file__).resolve().parent.parent


def _handler_proof_row(room: str = "ABC") -> dict:
    return {
        "event": "production_stage1_handler_exit_session_state_proof",
        "session_matches_local": True,
        "ts": 2.0,
        "room_id": room,
        "pick_index": 0,
        "deadline": 99999.0,
        "authoritative_session_state": {
            "session_room_id": room,
            "session_draft_status": "in_progress",
            "session_pick_index": 0,
            "restore_blocked_reason": "auth_required",
        },
    }


def _auth_restore_step(room: str = "ABC") -> dict:
    return {
        "ts": 1.5,
        "operation": "restore",
        "reason": "prepare_live_draft_state",
        "preserve_inference": {
            "restore_blocked_reason": "auth_required",
            "inferred_preserve_success": True,
            "room_before": room,
            "room_after_post_restore": room,
        },
    }


def _ultra_read(room: str = "ABC", ts: float = 3.0) -> dict:
    return {
        "ts": ts,
        "operation": "read",
        "reason": "ultra_early_before_cleanup",
        "room_id_after": room,
        "draft_status": "in_progress",
        "pick_index": 0,
        "deadline_token": "99999.0",
    }


def _active_ui_scrape(room: str = "ABC") -> dict:
    return {
        "room_id": room,
        "in_progress": True,
        "setup_start_visible": False,
        "ui": {"ccTimer": 5},
        "text_excerpt": "Time remaining: 5s",
    }


def test_verify1_auth_restore_preserves_room_with_surface() -> None:
    timeline = [
        _auth_restore_step(),
        {
            "ts": 3.0,
            "operation": "surface",
            "room_id_after": "ABC",
            "draft_status": "in_progress",
        },
    ]
    out = classify_room_latch_verify(
        timeline=timeline,
        filtered_ledger=[],
        created_room_id="ABC",
        final_surface=timeline[-1],
        final_scrape={"room_id": "", "in_progress": False},
    )
    assert out["classification"] == VERIFY1


def test_verify1_handler_server_read_and_ui_without_surface_decision() -> None:
    timeline = [
        _auth_restore_step(),
        {"ts": 2.1, "operation": "handler_session_proof", "room_id_after": "ABC"},
        _ultra_read(ts=3.0),
    ]
    ledger = [_handler_proof_row()]
    out = classify_room_latch_verify(
        timeline=timeline,
        filtered_ledger=ledger,
        created_room_id="ABC",
        final_surface=None,
        final_scrape=_active_ui_scrape(),
    )
    assert out["classification"] == VERIFY1
    assert out["audit"].get("verify1_without_surface_decision")


def test_missing_surface_decision_alone_not_verify10_when_authoritative() -> None:
    out = classify_room_latch_verify(
        timeline=[_auth_restore_step("488AA3BA"), _ultra_read("488AA3BA", 3.0)],
        filtered_ledger=[_handler_proof_row("488AA3BA")],
        created_room_id="488AA3BA",
        final_surface=None,
        final_scrape=_active_ui_scrape("488AA3BA"),
    )
    assert out["classification"] == VERIFY1
    assert out["classification"] != VERIFY10


def test_later_clear_defeats_verify1() -> None:
    timeline = [
        _auth_restore_step(),
        _ultra_read(),
        {
            "ts": 4.0,
            "operation": "clear",
            "room_id_before": "ABC",
            "room_id_after": "",
            "reason": "setup_cleanup",
        },
    ]
    out = classify_room_latch_verify(
        timeline=timeline,
        filtered_ledger=[_handler_proof_row()],
        created_room_id="ABC",
        final_surface=None,
        final_scrape=_active_ui_scrape(),
    )
    assert out["classification"] == VERIFY4


def test_mismatched_final_room_id_verify8() -> None:
    out = classify_room_latch_verify(
        timeline=[_auth_restore_step(), _ultra_read()],
        filtered_ledger=[_handler_proof_row()],
        created_room_id="ABC",
        final_surface=None,
        final_scrape=_active_ui_scrape("OTHER1"),
    )
    assert out["classification"] == VERIFY8


def test_setup_visible_final_ui_fails_without_server_surface() -> None:
    out = classify_room_latch_verify(
        timeline=[_auth_restore_step(), _ultra_read()],
        filtered_ledger=[_handler_proof_row()],
        created_room_id="ABC",
        final_surface=None,
        final_scrape={
            "room_id": "ABC",
            "in_progress": False,
            "setup_start_visible": True,
        },
    )
    assert out["classification"] != VERIFY1


def test_scrape_cannot_override_earlier_server_state_loss() -> None:
    timeline = [
        _auth_restore_step(),
        _ultra_read(ts=3.0),
        {
            "ts": 4.0,
            "operation": "clear",
            "room_id_before": "ABC",
            "room_id_after": "",
            "reason": "explicit_clear",
        },
    ]
    out = classify_room_latch_verify(
        timeline=timeline,
        filtered_ledger=[_handler_proof_row()],
        created_room_id="ABC",
        final_surface=None,
        final_scrape=_active_ui_scrape(),
    )
    assert out["classification"] == VERIFY4


def test_ui_only_insufficient_for_verify1() -> None:
    out = classify_room_latch_verify(
        timeline=[],
        filtered_ledger=[],
        created_room_id="ABC",
        final_surface=None,
        final_scrape=_active_ui_scrape(),
    )
    assert out["classification"] == VERIFY10


def test_verify7_surface_valid_scrape_empty() -> None:
    timeline = [
        {
            "ts": 3.0,
            "operation": "surface",
            "room_id_after": "ABC",
            "draft_status": "in_progress",
        },
    ]
    out = classify_room_latch_verify(
        timeline=timeline,
        filtered_ledger=[],
        created_room_id="ABC",
        final_surface=timeline[0],
        final_scrape={"room_id": "", "setup_start_visible": True},
    )
    assert out["classification"] == VERIFY7


def test_scrape_cannot_outrank_server_surface_verify7() -> None:
    timeline = [
        {"ts": 2.5, "operation": "surface", "room_id_after": "50416388", "draft_status": "in_progress"},
    ]
    out = classify_room_latch_verify(
        timeline=timeline,
        filtered_ledger=[],
        created_room_id="50416388",
        final_surface=timeline[0],
        final_scrape={"room_id": "", "in_progress": False},
    )
    assert out["classification"] == VERIFY7


def test_production_room_latch_verification_488aa3ba_reclassifies_verify1() -> None:
    path = ROOT / "data" / "production_room_latch_verification.json"
    if not path.is_file():
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    out = classify_room_latch_verify(
        timeline=report.get("room_state_timeline") or [],
        filtered_ledger=(report.get("latch_ledger_export") or {}).get("rows") or [],
        created_room_id=str(report.get("created_room_id") or ""),
        final_surface=report.get("final_server_surface_decision"),
        final_scrape=report.get("final_ui_scrape") or {},
    )
    assert out["classification"] == VERIFY1
