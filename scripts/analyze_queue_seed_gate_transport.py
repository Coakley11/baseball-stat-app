"""Retrospective transport + lifecycle report from production_bridge_queue_seed_gate.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from stage1_native_widget_transport import classify_transport_from_ws_samples

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARTIFACT = ROOT / "data" / "production_bridge_queue_seed_gate.json"


def _samples_from_transport_block(block: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(block, dict):
        return []
    sample = block.get("ws_log_sample")
    if isinstance(sample, list):
        return [e for e in sample if isinstance(e, dict)]
    return []


def _handler_proof_pause(pause: dict[str, Any]) -> dict[str, Any]:
    server = pause.get("pause_server_proof") if isinstance(pause.get("pause_server_proof"), dict) else {}
    return {
        "pause_classification": pause.get("pause_classification"),
        "server_paused_recognized": server.get("paused_recognized"),
        "resume_draft_count": server.get("resume_draft_count"),
    }


def _francisco_step(gate: dict[str, Any]) -> dict[str, Any] | None:
    seed = gate.get("queue_seed") if isinstance(gate.get("queue_seed"), dict) else {}
    for step in seed.get("seed_steps") or []:
        if isinstance(step, dict) and str(step.get("player_name") or "").lower().startswith("francisco"):
            return step
    return None


def build_report(gate: dict[str, Any]) -> dict[str, Any]:
    pause = gate.get("pause_delivery") if isinstance(gate.get("pause_delivery"), dict) else {}
    pause_click = pause.get("pause_click") if isinstance(pause.get("pause_click"), dict) else {}
    pause_ts = float(pause_click.get("click_timestamp") or 0)
    pause_transport_raw = pause.get("pause_click_transport") if isinstance(pause.get("pause_click_transport"), dict) else {}
    pause_samples = _samples_from_transport_block(pause_transport_raw)
    pause_classified = classify_transport_from_ws_samples(pause_samples)

    start = gate.get("start_latch") if isinstance(gate.get("start_latch"), dict) else {}
    start_transport = gate.get("start_click_transport")
    start_report: dict[str, Any] = {
        "click_timestamp": None,
        "handler_entered": start.get("handler_entered"),
        "ws_samples_in_artifact": bool(start_transport),
        "note": "Start WS sample not stored in gate artifact; use handler_entered + future start_click_transport.",
    }
    if isinstance(start_transport, dict):
        start_ts = float((gate.get("start_click") or {}).get("click_timestamp") or 0)
        start_samples = _samples_from_transport_block(start_transport)
        start_classified = classify_transport_from_ws_samples(start_samples)
        start_report.update(
            {
                "click_timestamp": start_ts or None,
                "transport": start_classified,
                "native_widget_event_observed": start_classified.get("native_widget_event_observed"),
                "native_widget_event_observed_strict": start_classified.get("native_widget_event_observed_strict"),
            }
        )

    francisco = _francisco_step(gate)
    francisco_report: dict[str, Any] = {"found": bool(francisco)}
    if francisco:
        detail = francisco.get("delivery_detail") if isinstance(francisco.get("delivery_detail"), dict) else {}
        transport = detail.get("post_click_transport") if isinstance(detail.get("post_click_transport"), dict) else {}
        samples = _samples_from_transport_block(transport)
        classified = classify_transport_from_ws_samples(
            samples,
            pre_script_run_seq=str(transport.get("script_run_seq_before") or ""),
            post_script_run_seq=str(transport.get("ledger_script_run_seq_after") or ""),
        )
        francisco_report.update(
            {
                "click_timestamp": detail.get("click_end_ts") or detail.get("click_start_ts"),
                "transport_recorded": transport,
                "transport_reclassified": classified,
                "app_render_trace": francisco.get("app_render_trace"),
                "script_run_at_click": transport.get("script_run_seq_before"),
                "callback_entered": (francisco.get("app_queue_trace") or {}).get("callback_entered"),
                "classification": francisco.get("classification"),
            }
        )

    timeline = {
        "pause_click_ts": pause_ts,
        "francisco_click_ts": francisco_report.get("click_timestamp"),
        "seconds_pause_to_francisco": None,
    }
    if pause_ts and francisco_report.get("click_timestamp"):
        timeline["seconds_pause_to_francisco"] = round(float(francisco_report["click_timestamp"]) - pause_ts, 3)

    return {
        "room_id": start.get("room_id") or pause.get("room_id"),
        "runtime_sha": gate.get("required_cloud_sha"),
        "bridge_prefix": gate.get("bridge_suite_sid_prefix"),
        "detector_validation": {
            "pause": {
                "click_timestamp": pause_ts,
                "outbound_frames": pause_classified.get("outbound_frames_after_click"),
                "native_widget_frames_relaxed": pause_classified.get("native_widget_frame_count"),
                "native_widget_frames_strict": pause_classified.get("native_widget_frame_count_strict"),
                "component_frames_only": pause_classified.get("component_value_only_frame_count"),
                "native_widget_event_observed": pause_classified.get("native_widget_event_observed"),
                "native_widget_event_observed_strict": pause_classified.get("native_widget_event_observed_strict"),
                "streamlit_outbound_after_click": pause_classified.get("streamlit_outbound_after_click"),
                "handler_proof": _handler_proof_pause(pause),
                "legacy_pause_streamlit_backmsg_sent": pause_transport_raw.get("streamlit_backmsg_sent"),
            },
            "start": start_report,
            "francisco": francisco_report,
        },
        "interpretation": {
            "detector_false_negative_on_pause": (
                pause_classified.get("native_widget_event_observed_strict") is False
                and pause.get("pause_classification") == "PAUSE_DELIVERY_RESOLVED"
            ),
            "relaxed_detector_matches_pause": pause_classified.get("native_widget_event_observed") is True,
            "francisco_same_ws_shape_as_pause": (
                pause_classified.get("native_widget_event_observed")
                == (francisco_report.get("transport_reclassified") or {}).get("native_widget_event_observed")
            ),
        },
        "timeline": timeline,
    }


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ARTIFACT
    gate = json.loads(path.read_text(encoding="utf-8"))
    report = build_report(gate)
    out_path = path.with_suffix(".transport_analysis.json")
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    print(json.dumps({"written": str(out_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
