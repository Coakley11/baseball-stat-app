"""Tests for VERIFY room-latch classifier."""

from __future__ import annotations

from scripts.p8_room_latch_verify_classify import (
    VERIFY1,
    VERIFY3,
    VERIFY4,
    VERIFY7,
    classify_room_latch_verify,
)


def test_verify1_auth_restore_preserves_room() -> None:
    timeline = [
        {
            "ts": 2.0,
            "operation": "restore",
            "reason": "prepare_live_draft_state",
            "preserve_inference": {
                "restore_blocked_reason": "auth_required",
                "inferred_preserve_success": True,
                "room_before": "ABC",
                "room_after_post_restore": "ABC",
            },
        },
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


def test_verify3_auth_restore_wipes_room() -> None:
    timeline = [
        {
            "ts": 2.0,
            "operation": "restore",
            "reason": "prepare_live_draft_state",
            "preserve_inference": {
                "restore_blocked_reason": "auth_required",
                "inferred_preserve_success": False,
                "inferred_clear_foreign_likely": True,
                "room_before": "ABC",
                "room_after_post_restore": "",
            },
        },
    ]
    out = classify_room_latch_verify(
        timeline=timeline,
        filtered_ledger=[
            {"event": "production_stage1_handler_exit_session_state_proof", "session_matches_local": True}
        ],
        created_room_id="ABC",
        final_surface=None,
        final_scrape={"room_id": ""},
    )
    assert out["classification"] == VERIFY3


def test_verify4_later_clear() -> None:
    timeline = [
        {
            "ts": 2.0,
            "operation": "clear",
            "room_id_before": "ABC",
            "room_id_after": "",
            "reason": "setup_cleanup",
        },
    ]
    out = classify_room_latch_verify(
        timeline=timeline,
        filtered_ledger=[],
        created_room_id="ABC",
        final_surface=None,
        final_scrape={"room_id": ""},
    )
    assert out["classification"] == VERIFY4


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
    assert out["classification"] != "VERIFY8 — UI_OR_SCRAPER_WRONG_SESSION_OR_SURFACE"
