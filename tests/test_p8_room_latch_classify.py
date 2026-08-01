"""Tests for room latch classifier."""

from __future__ import annotations

from scripts.p8_room_latch_classify import (
    LATCH1,
    LATCH2,
    LATCH4,
    LATCH6,
    classify_room_latch,
)


def test_latch1_room_created_not_in_session() -> None:
    out = classify_room_latch(
        ledger_rows=[
            {"event": "production_stage1_room_creation_exited", "ts": 2.0, "room_creation_success": True, "created_room_id": "ABC"},
            {
                "event": "production_stage1_handler_exit_session_state_proof",
                "ts": 2.1,
                "local_created_room_id": "ABC",
                "session_matches_local": False,
                "authoritative_session_state": {"session_room_id": ""},
            },
        ],
        authoritative_state={"room_id": "", "in_progress": False},
        click_ts=1.0,
        created_room_id="ABC",
    )
    assert out["classification"] == LATCH1


def test_latch2_blob_vs_live_room_key() -> None:
    out = classify_room_latch(
        ledger_rows=[
            {
                "event": "production_stage1_handler_exit_session_state_proof",
                "ts": 2.0,
                "local_created_room_id": "ABC",
                "session_matches_local": False,
                "authoritative_session_state": {
                    "session_room_id": "",
                    "canonical_blob_room_id": "ABC",
                },
            },
        ],
        authoritative_state={"room_id": "", "in_progress": False},
        click_ts=1.0,
        created_room_id="ABC",
    )
    assert out["classification"] == LATCH2


def test_latch4_clear_after_create() -> None:
    out = classify_room_latch(
        ledger_rows=[
            {"event": "production_stage1_room_creation_exited", "ts": 2.0, "created_room_id": "50416388", "room_creation_success": True},
            {"event": "production_stage1_room_state_write", "ts": 2.1, "new_room_id": "50416388", "prev_room_id": "", "new_status": "in_progress"},
            {"event": "production_stage1_room_state_clear", "ts": 2.2, "prev_room_id": "50416388", "reason": "setup_cleanup"},
        ],
        authoritative_state={"room_id": "", "in_progress": False},
        click_ts=1.0,
        created_room_id="50416388",
    )
    assert out["classification"] == LATCH4


def test_latch6_next_run_missing_room() -> None:
    out = classify_room_latch(
        ledger_rows=[
            {"event": "production_stage1_room_creation_exited", "ts": 2.0, "created_room_id": "50416388", "room_creation_success": True},
            {"event": "production_stage1_room_state_write", "ts": 2.1, "new_room_id": "50416388"},
            {
                "event": "production_stage1_room_state_read",
                "ts": 3.0,
                "read_label": "ultra_early_before_cleanup",
                "session_room_id": "",
            },
        ],
        authoritative_state={"room_id": "", "in_progress": False},
        click_ts=1.0,
        created_room_id="50416388",
    )
    assert out["classification"] == LATCH6
