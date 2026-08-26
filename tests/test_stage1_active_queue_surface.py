"""Frame-aware active draft / queue UI gate (B01F65DE regression fixtures)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_active_queue_surface import (  # noqa: E402
    ACTIVE_QUEUE_SURFACE_RESOLVED,
    QUEUE_ACTIVE_PAGE1A,
    QUEUE_ACTIVE_PAGE1B,
    QUEUE_ACTIVE_PAGE1D,
    QUEUE_ACTIVE_PAGE1E,
    QUEUE_ACTIVE_PAGE1F,
    QUEUE_SURFACE_NAV_LABELS,
    classify_active_page_boundary,
    evaluate_active_live_page_gate,
    evaluate_queue_ui_ready,
    evaluate_server_active_draft_ready,
    scrape_frame_aware_active_observation,
    surface_activation_labels_are_navigation_only,
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


def test_surface_activation_navigation_only_cannot_match_add_to_queue() -> None:
    assert surface_activation_labels_are_navigation_only()
    combined = " ".join(QUEUE_SURFACE_NAV_LABELS).lower()
    assert "add to queue" not in combined


def test_surface_activation_queue_mutation_detection_new_names_only() -> None:
    """Pre/post snapshot in wait_for_active_queue_surface flags only new queue identities."""
    pre = ["Francisco Lindor"]
    post = ["Francisco Lindor", "Pete Alonso"]
    pre_set = {n.lower() for n in pre}
    post_set = {n.lower() for n in post}
    assert bool(post_set - pre_set) is True
    post_reorder = ["Francisco Lindor"]
    post_reorder_set = {n.lower() for n in post_reorder}
    assert bool(post_reorder_set - pre_set) is False


def _prod_start_val(room: str, token: str) -> dict:
    return {
        "latched_room_id": room,
        "in_progress": True,
        "room_latch_pass": True,
        "expected_token": token,
        "pick_index": 0,
    }


def test_d3a2141_fixture_resolves_when_add_to_queue_present() -> None:
    """48117734 gate snapshot: server ready, add-to-queue=2, board_rows=0."""
    obs = {
        "visible_room_id": "",
        "pick_index": 0,
        "pick0_token_ui": "BBE0C5A3|0|1787716581.354",
        "pick0_deadline_ui": "1787716581.3538802",
        "pause_draft_count": 2,
        "resume_draft_count": 2,
        "board_rows": 0,
        "add_to_queue_button_count": 2,
        "frames_with_add_to_queue": 1,
        "server_latched_room_id": "BBE0C5A3",
        "server_expected_token": "BBE0C5A3|0|1787716581.354",
        "frame_probes": [{"frameIndex": 1, "isAppFrame": True, "addToQueue": 2, "hasLedger": True}],
        "post_create_active_draft_render_failed": False,
        "recommendation_cards_hint": True,
    }
    ev = evaluate_active_live_page_gate(
        obs, start_val=_prod_start_val("BBE0C5A3", "BBE0C5A3|0|1787716581.354"), while_paused=True
    )
    assert ev["passed"] is True
    assert ev["classification"] == ACTIVE_QUEUE_SURFACE_RESOLVED


def test_3713de5_fixture_board_only_without_rec_classifies_1f_not_1d() -> None:
    """2cd42978 final gate: board_rows=10 but no Add-to-Queue anywhere after tab activation."""
    obs = {
        "visible_room_id": "FB60F59B",
        "pick_index": 0,
        "pick0_token_ui": "FB60F59B|0|1787750384.450",
        "pick0_deadline_ui": "1787750384.4504023",
        "pause_draft_count": 2,
        "resume_draft_count": 2,
        "board_rows": 10,
        "add_to_queue_button_count": 0,
        "frames_with_add_to_queue": 0,
        "server_latched_room_id": "FB60F59B",
        "server_expected_token": "FB60F59B|0|1787750384.450",
        "frame_probes": [{"frameIndex": 1, "isAppFrame": True, "boardRows": 10, "addToQueue": 0, "hasLedger": True}],
        "post_create_active_draft_render_failed": False,
        "recommendation_cards_hint": False,
    }
    server = evaluate_server_active_draft_ready(
        obs, start_val=_prod_start_val("FB60F59B", "FB60F59B|0|1787750384.450"), while_paused=True
    )
    queue = evaluate_queue_ui_ready(obs)
    assert server["ready"] is True
    assert queue["ready"] is False
    assert (
        classify_active_page_boundary(
            observation=obs,
            server_eval=server,
            queue_eval=queue,
            surface_activation_attempted=True,
        )
        == QUEUE_ACTIVE_PAGE1F
    )


def test_post_create_active_draft_render_failure_classifies_1f() -> None:
    obs = {
        "visible_room_id": "FB60F59B",
        "pick_index": 0,
        "pick0_token_ui": "FB60F59B|0|1787750384.450",
        "pick0_deadline_ui": "1787750384.4504023",
        "pause_draft_count": 2,
        "resume_draft_count": 2,
        "board_rows": 0,
        "add_to_queue_button_count": 0,
        "frames_with_add_to_queue": 0,
        "server_latched_room_id": "FB60F59B",
        "server_expected_token": "FB60F59B|0|1787750384.450",
        "frame_probes": [
            {
                "frameIndex": 1,
                "isAppFrame": True,
                "postCreateActiveDraftRenderFailed": True,
                "hasLedger": True,
            }
        ],
        "post_create_active_draft_render_failed": True,
        "recommendation_cards_hint": False,
    }
    ev = evaluate_active_live_page_gate(
        obs,
        start_val=_prod_start_val("FB60F59B", "FB60F59B|0|1787750384.450"),
        while_paused=True,
        surface_activation_attempted=True,
    )
    assert ev["passed"] is False
    assert ev["classification"] == QUEUE_ACTIVE_PAGE1F


def test_board_visible_still_computing_classifies_1b_before_activation() -> None:
    obs = {
        "visible_room_id": "FB60F59B",
        "pick_index": 0,
        "pick0_token_ui": "FB60F59B|0|1787750384.450",
        "pick0_deadline_ui": "1787750384.4504023",
        "pause_draft_count": 1,
        "resume_draft_count": 0,
        "board_rows": 10,
        "add_to_queue_button_count": 0,
        "frames_with_add_to_queue": 0,
        "server_latched_room_id": "FB60F59B",
        "server_expected_token": "FB60F59B|0|1787750384.450",
        "frame_probes": [{"frameIndex": 1, "isAppFrame": True, "boardRows": 10, "hasLedger": True}],
        "post_create_active_draft_render_failed": False,
        "recommendation_cards_hint": False,
    }
    server = evaluate_server_active_draft_ready(
        obs, start_val=_prod_start_val("FB60F59B", "FB60F59B|0|1787750384.450"), while_paused=True
    )
    queue = evaluate_queue_ui_ready(obs)
    assert (
        classify_active_page_boundary(
            observation=obs,
            server_eval=server,
            queue_eval=queue,
            surface_activation_attempted=False,
        )
        == QUEUE_ACTIVE_PAGE1B
    )


def test_buttons_on_non_preferred_frame_classifies_1a() -> None:
    obs = {
        "visible_room_id": "FB60F59B",
        "pick_index": 0,
        "pick0_token_ui": "FB60F59B|0|1787750384.450",
        "board_rows": 0,
        "add_to_queue_button_count": 0,
        "frames_with_add_to_queue": 1,
        "server_latched_room_id": "FB60F59B",
        "server_expected_token": "FB60F59B|0|1787750384.450",
        "frame_probes": [
            {"frameIndex": 0, "isAppFrame": False, "addToQueue": 2},
            {"frameIndex": 1, "isAppFrame": True, "addToQueue": 0, "hasLedger": True},
        ],
        "post_create_active_draft_render_failed": False,
    }
    server = evaluate_server_active_draft_ready(
        obs, start_val=_prod_start_val("FB60F59B", "FB60F59B|0|1787750384.450"), while_paused=True
    )
    queue = evaluate_queue_ui_ready(obs)
    assert (
        classify_active_page_boundary(
            observation=obs,
            server_eval=server,
            queue_eval=queue,
            surface_activation_attempted=True,
        )
        == QUEUE_ACTIVE_PAGE1A
    )
