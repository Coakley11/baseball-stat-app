"""Tests for app-side rec-card queue trace scrape (Commit C harness)."""

from __future__ import annotations

from stage1_rec_queue_click_trace_scrape import merge_app_trace_into_step


def test_merge_app_trace_sets_callback_and_classification() -> None:
    step: dict = {"queue_before": []}
    trace = {
        "event_id": "abc123",
        "callback_entered": True,
        "added": True,
        "classification": "QUEUE1C3F",
        "payload": {
            "last": {
                "callback_entered": True,
                "queue_immediately_after_mutation": ["Francisco Lindor"],
                "post_prepare": {"queue_after_rerun_hydration": ["Francisco Lindor"]},
            }
        },
    }
    merge_app_trace_into_step(step, trace)
    assert step["app_classification"] == "QUEUE1C3F"
    assert step["app_callback_entered"] is True
    assert step["app_queue_after_mutation"] == ["Francisco Lindor"]
    assert step["app_queue_after_prepare"] == ["Francisco Lindor"]


def test_classify_queue1c_subcode_prefers_app_trace() -> None:
    from stage1_queue_seed_harness import classify_queue1c_subcode

    step = {
        "click_dispatched": True,
        "delivery_method": "playwright_ld_rec_card_meta_scope",
        "mutation_observed": False,
        "delivery_detail": {
            "post_click_transport": {"streamlit_backmsg_sent": True, "outbound_frames_after_click": 2},
        },
        "app_classification": "QUEUE1C3A",
        "app_callback_entered": False,
    }
    assert classify_queue1c_subcode(step) == "QUEUE1C3A"
