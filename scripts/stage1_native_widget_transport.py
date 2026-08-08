"""Classify Streamlit websocket traffic: native widget vs generic component hints."""

from __future__ import annotations

from typing import Any


def classify_outbound_frame(entry: dict[str, Any]) -> dict[str, str]:
    hint = str(entry.get("frame_type_hint") or "").lower()
    wkey = bool(entry.get("widget_key_bytes_present"))
    native = hint == "widget_state_backmsg_hint" or wkey
    component_only = hint == "component_value_hint" and not wkey
    return {
        "frame_type_hint": hint or "unknown",
        "native_widget_event_hint": str(native).lower(),
        "component_value_only_hint": str(component_only).lower(),
    }


def scrape_native_widget_transport_evidence(page, *, click_ts: float, pre_script_run_seq: str = "") -> dict[str, Any]:
    """Distinguish native st.button widget traffic from solo timer/component SCV."""
    try:
        from p8_proven_start_delivery import aggregate_ws_boundary_log
    except ImportError:
        return {"error": "aggregate_ws_boundary_log_unavailable"}

    raw_log = aggregate_ws_boundary_log(page)
    outbound = [e for e in raw_log if isinstance(e, dict) and e.get("direction") == "outbound"]
    after = [e for e in outbound if float(e.get("wall_ts_ms") or 0) >= (click_ts * 1000.0 - 50.0)]
    enriched: list[dict[str, Any]] = []
    native_count = 0
    component_only_count = 0
    for entry in after[:24]:
        row = dict(entry)
        row.update(classify_outbound_frame(entry))
        if row.get("native_widget_event_hint") == "true":
            native_count += 1
        if row.get("component_value_only_hint") == "true":
            component_only_count += 1
        enriched.append(row)

    post_seq = ""
    seq_changed = False
    try:
        from p8_production_start_harness import scrape_stage1_ledger_rows

        rows = scrape_stage1_ledger_rows(page) or []
        if rows:
            post_seq = str(rows[-1].get("script_run_seq") or "")
    except Exception:
        pass
    if pre_script_run_seq and post_seq:
        try:
            seq_changed = int(post_seq) > int(pre_script_run_seq)
        except ValueError:
            seq_changed = post_seq != pre_script_run_seq

    native_widget_event_observed = native_count > 0
    generic_component_only = component_only_count > 0 and native_count == 0 and len(after) > 0

    return {
        "outbound_frames_after_click": len(after),
        "native_widget_event_observed": native_widget_event_observed,
        "native_widget_frame_count": native_count,
        "component_value_only_frame_count": component_only_count,
        "generic_component_traffic_only": generic_component_only,
        "streamlit_backmsg_sent": native_widget_event_observed,
        "python_rerun_started": bool(seq_changed),
        "script_run_seq_before": pre_script_run_seq,
        "ledger_script_run_seq_after": post_seq,
        "script_run_seq_changed": seq_changed,
        "ws_log_sample": enriched[:8],
    }


def classify_queue1c3a_subcode(
    *,
    click_target: dict[str, Any] | None,
    transport: dict[str, Any] | None,
    render_trace_present: bool,
    callback_trace_present: bool,
    callback_entered: bool | None,
) -> str:
    """Refine QUEUE1C3A using DOM target + transport + render/callback probes."""
    if not render_trace_present:
        return "QUEUE1C3A5"
    tgt = click_target if isinstance(click_target, dict) else {}
    tr = transport if isinstance(transport, dict) else {}
    if tgt.get("click_non_native_element"):
        return "QUEUE1C3A1"
    if tgt.get("inside_st_tooltip") and not tgt.get("is_st_base_button"):
        return "QUEUE1C3A1"
    if not tr.get("native_widget_event_observed") and tr.get("generic_component_traffic_only"):
        return "QUEUE1C3A2"
    if tr.get("native_widget_event_observed") and not tr.get("script_run_seq_changed"):
        return "QUEUE1C3A3"
    if tr.get("script_run_seq_changed") and callback_entered is False:
        return "QUEUE1C3A4"
    if callback_trace_present and not callback_entered:
        return "QUEUE1C3A4"
    return "QUEUE1C3A"
