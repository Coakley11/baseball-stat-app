"""Tests for room latch classifier (LATCH5 priority)."""

from __future__ import annotations

from scripts.p8_room_latch_classify import (
    LATCH5,
    LATCH6,
    LATCH9,
    classify_room_latch,
)


def _proof_row(room_id: str = "50416388") -> dict:
    return {
        "event": "production_stage1_handler_exit_session_state_proof",
        "ts": 2.0,
        "local_created_room_id": room_id,
        "session_matches_local": True,
        "authoritative_session_state": {"session_room_id": room_id, "streamlit_session_id": "s1"},
    }


def _surface_row(room_id: str = "50416388") -> dict:
    return {
        "event": "production_stage1_surface_decision",
        "ts": 2.5,
        "session_room_id": room_id,
        "draft_in_progress": True,
    }


def _empty_auth_restore(ts: float = 3.0, room_id: str = "50416388") -> dict:
    return {
        "event": "production_stage1_room_state_restore",
        "ts": ts,
        "reason": "prepare_live_draft_state",
        "restored_room_id": "",
        "room_id": room_id,
        "post_restore_snapshot": {
            "session_room_id": "",
            "restore_blocked_reason": "auth_required",
        },
    }


def test_latch5_beats_latch9_on_empty_auth_restore() -> None:
    out = classify_room_latch(
        ledger_rows=[
            {"event": "production_stage1_room_creation_exited", "ts": 1.8, "created_room_id": "50416388", "room_creation_success": True},
            _proof_row(),
            _surface_row(),
            _empty_auth_restore(),
        ],
        authoritative_state={"room_id": "", "in_progress": False},
        click_ts=1.0,
        created_room_id="50416388",
    )
    assert out["classification"] == LATCH5
    assert out["audit"].get("underlying_trigger") == "AUTH_REQUIRED_EMPTY_RESTORE"
    assert out["classification"] != LATCH9


def test_latch6_requires_room_id_surviving_in_session_reads() -> None:
    out = classify_room_latch(
        ledger_rows=[
            {"event": "production_stage1_room_creation_exited", "ts": 2.0, "created_room_id": "ABC", "room_creation_success": True},
            {
                "event": "production_stage1_room_state_read",
                "ts": 3.0,
                "read_label": "ultra_early_before_cleanup",
                "session_room_id": "ABC",
            },
        ],
        authoritative_state={"room_id": "", "in_progress": False},
        click_ts=1.0,
        created_room_id="ABC",
    )
    assert out["classification"] == LATCH6


def test_empty_auth_restore_produces_latch5() -> None:
    out = classify_room_latch(
        ledger_rows=[
            _proof_row("0696E41E"),
            _surface_row("0696E41E"),
            _empty_auth_restore(room_id="0696E41E"),
        ],
        authoritative_state={"room_id": "", "setup_start_visible": True},
        click_ts=1.0,
        created_room_id="0696E41E",
    )
    assert LATCH5 in out["classification"]
    assert out["audit"]["underlying_trigger"] == "AUTH_REQUIRED_EMPTY_RESTORE"
