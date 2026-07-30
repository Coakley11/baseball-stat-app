"""Tests for P8 boundary trace harness (no Cloud)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from p8_boundary_instrumentation import (  # noqa: E402
    WebSocketBoundaryCapture,
    classify_first_missing_boundary,
    enrich_post_send_server_audit,
)
from p8_sender_rerun_trace import find_production_send_boundary, normalize_epoch_ts  # noqa: E402


def test_normalize_epoch_ts_ms_and_s():
    assert normalize_epoch_ts(1785449920132) == 1785449920.132
    assert normalize_epoch_ts(1785449920.132) == 1785449920.132


def test_find_production_send_boundary():
    entries = [
        {
            "ts": 1785449920132,
            "stage": "transport_before_postMessage",
            "extra": '{"widget_key":"solo_countdown_wake_solo_persistent","token":"ABC|0|1.0"}',
        }
    ]
    row = find_production_send_boundary(entries)
    assert row.get("stage") == "transport_before_postMessage"
    assert "ABC" in str(row.get("token") or "")


def test_enrich_post_send_server_audit_filters_pre_send():
    send = 100.0
    rows = [
        {"event": "production_stage1_script_begin", "ts": 99.0, "script_run_seq": 1},
        {"event": "production_stage1_script_begin", "ts": 100.1, "script_run_seq": 2, "run_id": "r1"},
    ]
    out = enrich_post_send_server_audit(rows, send_epoch=send, deployment_sha="d73bcf3")
    assert len(out) == 1
    assert out[0]["script_run_seq"] == 2


def test_classify_lifecycle3_no_parent_no_ws():
    ws = WebSocketBoundaryCapture()
    cls = classify_first_missing_boundary(
        send_epoch=100.0,
        exact_token="ROOM|0|99.0",
        send_boundary={"iframe_instance_id": "solo_x", "token": "ROOM|0|99.0"},
        immediate_log={"records": []},
        ws_capture=ws,
        post_send_server=[],
        peak_rows=[],
        iframe_entries=[{"ts": 100500, "stage": "tick_cancelled", "extra": "streamlit_render"}],
    )
    assert cls["code"] in ("LIFECYCLE1", "LIFECYCLE3", "LIFECYCLE9")


def test_classify_lifecycle4_ws_no_server():
    ws = WebSocketBoundaryCapture()
    ws.frames.append({"wall_ts": 100.2, "direction": "outbound", "byte_len": 50})
    cls = classify_first_missing_boundary(
        send_epoch=100.0,
        exact_token="ROOM|0|99.0",
        send_boundary={"iframe_instance_id": "solo_x", "token": "ROOM|0|99.0"},
        immediate_log={
            "records": [
                {
                    "message_type": "streamlit:setComponentValue",
                    "exact_payload_preview": "ROOM|0|99.0",
                    "source_matches_production_iframe": True,
                    "receipt_wall_ts": 100050,
                }
            ]
        },
        ws_capture=ws,
        post_send_server=[],
        peak_rows=[],
        iframe_entries=[],
    )
    assert cls["code"] == "LIFECYCLE4"
