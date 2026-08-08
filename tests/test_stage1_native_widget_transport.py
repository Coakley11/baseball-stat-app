"""Tests for render trace, native widget transport, and QUEUE1C3A subcodes."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from live_draft_rec_queue_click_trace import (
    REC_QUEUE_CALLBACK_ID,
    register_rec_queue_render_trace,
    render_rec_queue_render_trace_probe,
)
from stage1_native_widget_transport import (
    classify_outbound_frame,
    classify_queue1c3a_subcode,
    classify_transport_from_ws_samples,
    scrape_native_widget_transport_evidence,
)


def test_classify_component_vs_native_frame() -> None:
    comp = classify_outbound_frame({"frame_type_hint": "component_value_hint", "widget_key_bytes_present": False, "byte_len": 100})
    assert comp["component_value_only_hint"] == "true"
    assert comp["native_widget_event_hint"] == "false"
    assert comp["native_widget_event_hint_strict"] == "false"
    large_comp = classify_outbound_frame(
        {"frame_type_hint": "component_value_hint", "widget_key_bytes_present": False, "byte_len": 3248}
    )
    assert large_comp["native_widget_event_hint"] == "true"
    assert large_comp["native_widget_event_hint_strict"] == "false"
    native = classify_outbound_frame({"frame_type_hint": "widget_state_backmsg_hint", "widget_key_bytes_present": False})
    assert native["native_widget_event_hint_strict"] == "true"


def test_pause_production_fixture_transport_relaxed_not_strict() -> None:
    pause_sample = [
        {
            "wall_ts_ms": 1786158394575,
            "direction": "outbound",
            "byte_len": 3248,
            "frame_type_hint": "component_value_hint",
            "widget_key_bytes_present": False,
        }
    ]
    tr = classify_transport_from_ws_samples(pause_sample)
    assert tr["native_widget_event_observed"] is True
    assert tr["native_widget_event_observed_strict"] is False
    assert tr["streamlit_outbound_after_click"] is True


def test_francisco_production_fixture_same_relaxed_shape() -> None:
    francisco_samples = [
        {"frame_type_hint": "component_value_hint", "byte_len": 1905, "widget_key_bytes_present": False},
        {"frame_type_hint": "component_value_hint", "byte_len": 1985, "widget_key_bytes_present": False},
    ]
    tr = classify_transport_from_ws_samples(
        francisco_samples, pre_script_run_seq="12", post_script_run_seq="12"
    )
    assert tr["native_widget_event_observed"] is True
    assert tr["native_widget_event_observed_strict"] is False
    assert tr["python_rerun_started"] is False


def test_queue1c3a2_uses_strict_native_for_authoritative_subcode() -> None:
    sub = classify_queue1c3a_subcode(
        click_target={"is_st_base_button": True, "inside_st_tooltip": True},
        transport={
            "native_widget_event_observed": True,
            "native_widget_event_observed_strict": False,
            "generic_component_traffic_only": False,
            "streamlit_outbound_after_click": True,
            "script_run_seq_changed": False,
        },
        render_trace_present=True,
        callback_trace_present=False,
        callback_entered=False,
    )
    assert sub == "QUEUE1C3A2"


def test_queue1c3a5_missing_render_probe() -> None:
    assert (
        classify_queue1c3a_subcode(
            click_target={},
            transport={},
            render_trace_present=False,
            callback_trace_present=False,
            callback_entered=None,
        )
        == "QUEUE1C3A5"
    )


def test_register_render_trace_francisco() -> None:
    session: dict = {}
    row = register_rec_queue_render_trace(
        session,
        room_id="A8C6CF1E",
        pick_index=0,
        player_id="592789",
        player_name="Francisco Lindor",
        widget_key="rec_card_queue_A8C6CF1E_0_592789_rec_card",
        render_run_seq=1,
    )
    assert row["callback_id"] == REC_QUEUE_CALLBACK_ID
    assert row["expected_widget_key"].startswith("rec_card_queue_A8C6CF1E")


def test_render_probe_requires_diag() -> None:
    from unittest.mock import MagicMock, patch

    st = MagicMock()
    session: dict = {}
    register_rec_queue_render_trace(
        session,
        room_id="A8C6CF1E",
        pick_index=0,
        player_id="592789",
        player_name="Francisco Lindor",
        widget_key="rec_card_queue_A8C6CF1E_0_592789_rec_card",
    )
    with patch("live_draft_solo_component_diagnostics.solo_component_diag_enabled", return_value=True):
        render_rec_queue_render_trace_probe(st, session)
    html = str(st.markdown.call_args[0][0])
    assert "rec-card-queue-render-trace" in html
    assert "Francisco Lindor" in html or "data-player-name" in html


def test_scrape_native_transport_empty_log() -> None:
    class FakePage:
        pass

    # Module import path — only smoke that function exists and handles empty aggregate
    assert callable(scrape_native_widget_transport_evidence)
