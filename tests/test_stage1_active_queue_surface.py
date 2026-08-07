"""Frame-aware active draft / queue UI gate (B01F65DE regression fixtures)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_active_queue_surface import (  # noqa: E402
    ACTIVE_QUEUE_SURFACE_RESOLVED,
    QUEUE_ACTIVE_PAGE1B,
    QUEUE_ACTIVE_PAGE1E,
    evaluate_active_live_page_gate,
    evaluate_queue_ui_ready,
    evaluate_server_active_draft_ready,
    scrape_frame_aware_active_observation,
)


def _b01_start_val() -> dict:
    return {
        "latched_room_id": "B01F65DE",
        "in_progress": True,
        "room_latch_pass": True,
        "expected_token": "B01F65DE|0|1786120329.289",
        "pick_index": 0,
        "deadline": 1786120329.2889254,
    }


def _b01_observation_like_production_run() -> dict:
    """Mirrors production_stage1_authenticated_summary active_live_page_gate observation."""
    return {
        "visible_room_id": "",
        "pick_index": None,
        "pick0_token_ui": "",
        "pick0_deadline_ui": "1786120329.2889254",
        "pause_draft_count": 1,
        "resume_draft_count": 1,
        "board_rows": 0,
        "add_to_queue_button_count": 0,
        "countdown_or_timer_present": True,
        "server_latched_room_id": "B01F65DE",
        "server_expected_token": "B01F65DE|0|1786120329.289",
        "frame_probes": [
            {"frameIndex": 0, "frameUrl": "https://app/?top", "addToQueue": 0, "isAppFrame": False},
            {
                "frameIndex": 2,
                "frameUrl": "https://app/~/+/",
                "addToQueue": 0,
                "pauseCount": 1,
                "resumeCount": 1,
                "isAppFrame": True,
                "hasLedger": True,
            },
        ],
        "frames_with_add_to_queue": 0,
    }


def test_b01_server_ready_without_visible_room_dom() -> None:
    obs = _b01_observation_like_production_run()
    server = evaluate_server_active_draft_ready(obs, start_val=_b01_start_val(), while_paused=True)
    assert server["ready"] is True
    assert server["checks"]["pick_index_zero"] is True
    assert server["checks"]["room_latch_identity"] is True


def test_b01_queue_ui_not_ready_classifies_1b_or_1e() -> None:
    obs = _b01_observation_like_production_run()
    ev = evaluate_active_live_page_gate(obs, start_val=_b01_start_val(), while_paused=True)
    assert ev["passed"] is False
    assert ev["server_active_draft_ready"]["ready"] is True
    assert ev["queue_ui_ready"]["ready"] is False
    assert ev["classification"] in (QUEUE_ACTIVE_PAGE1B, QUEUE_ACTIVE_PAGE1E)


def test_full_pass_when_queue_controls_present() -> None:
    obs = _b01_observation_like_production_run()
    obs["add_to_queue_button_count"] = 2
    obs["board_rows"] = 3
    ev = evaluate_active_live_page_gate(obs, start_val=_b01_start_val(), while_paused=True)
    assert ev["passed"] is True
    assert ev["classification"] == ACTIVE_QUEUE_SURFACE_RESOLVED


def test_scrape_merges_expected_token_without_mount() -> None:
    obs = scrape_frame_aware_active_observation(
        None,  # type: ignore[arg-type]
        start_val=_b01_start_val(),
        frame_probes=_b01_observation_like_production_run()["frame_probes"],
    )
    assert obs["pick0_token_ui"] == "B01F65DE|0|1786120329.289"
    assert obs["pick_index"] == 0
    queue = evaluate_queue_ui_ready(obs)
    assert queue["ready"] is False
