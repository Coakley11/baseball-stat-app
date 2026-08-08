"""Classify Streamlit websocket traffic: native widget vs generic component hints."""

from __future__ import annotations

from typing import Any

# Streamlit native st.button clicks often appear as component_value_hint frames without
# widget_key byte matches in the WS hook (see proven Pause/Start production captures).
_COMPONENT_USER_ACTION_MIN_BYTES = 800


def classify_outbound_frame(entry: dict[str, Any]) -> dict[str, str]:
    hint = str(entry.get("frame_type_hint") or "").lower()
    wkey = bool(entry.get("widget_key_bytes_present"))
    byte_len = int(entry.get("byte_len") or 0)
    strict_native = hint == "widget_state_backmsg_hint" or wkey
    component_user_action = hint == "component_value_hint" and byte_len >= _COMPONENT_USER_ACTION_MIN_BYTES
    relaxed_native = strict_native or component_user_action
    component_only = hint == "component_value_hint" and not relaxed_native
    return {
        "frame_type_hint": hint or "unknown",
        "native_widget_event_hint_strict": str(strict_native).lower(),
        "native_widget_event_hint": str(relaxed_native).lower(),
        "component_value_only_hint": str(component_only).lower(),
        "component_user_action_hint": str(component_user_action).lower(),
    }


def classify_transport_from_ws_samples(
    samples: list[dict[str, Any]],
    *,
    pre_script_run_seq: str = "",
    post_script_run_seq: str = "",
) -> dict[str, Any]:
    """Pure classifier for retrospective gate analysis (no live page)."""
    enriched: list[dict[str, Any]] = []
    native_strict = 0
    native_relaxed = 0
    component_only_count = 0
    for entry in samples[:24]:
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        row.update(classify_outbound_frame(entry))
        if row.get("native_widget_event_hint_strict") == "true":
            native_strict += 1
        if row.get("native_widget_event_hint") == "true":
            native_relaxed += 1
        if row.get("component_value_only_hint") == "true":
            component_only_count += 1
        enriched.append(row)

    seq_changed = False
    if pre_script_run_seq and post_script_run_seq:
        try:
            seq_changed = int(post_script_run_seq) > int(pre_script_run_seq)
        except ValueError:
            seq_changed = post_script_run_seq != pre_script_run_seq

    outbound_n = len(samples)
    native_widget_event_observed_strict = native_strict > 0
    native_widget_event_observed = native_relaxed > 0
    generic_component_traffic_only = (
        component_only_count > 0 and not native_widget_event_observed and outbound_n > 0
    )
    streamlit_outbound_after_click = outbound_n > 0

    return {
        "outbound_frames_after_click": outbound_n,
        "native_widget_event_observed_strict": native_widget_event_observed_strict,
        "native_widget_event_observed": native_widget_event_observed,
        "native_widget_frame_count_strict": native_strict,
        "native_widget_frame_count": native_relaxed,
        "component_value_only_frame_count": component_only_count,
        "generic_component_traffic_only": generic_component_traffic_only,
        "streamlit_outbound_after_click": streamlit_outbound_after_click,
        "streamlit_backmsg_sent": streamlit_outbound_after_click or native_widget_event_observed,
        "python_rerun_started": bool(seq_changed),
        "script_run_seq_before": pre_script_run_seq,
        "ledger_script_run_seq_after": post_script_run_seq,
        "script_run_seq_changed": seq_changed,
        "ws_log_sample": enriched[:8],
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

    post_seq = ""
    try:
        from p8_production_start_harness import scrape_stage1_ledger_rows

        rows = scrape_stage1_ledger_rows(page) or []
        if rows:
            post_seq = str(rows[-1].get("script_run_seq") or "")
    except Exception:
        pass

    out = classify_transport_from_ws_samples(
        after,
        pre_script_run_seq=pre_script_run_seq,
        post_script_run_seq=post_seq,
    )
    out["click_ts"] = click_ts
    return out


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
    # Authoritative QUEUE1C3A2 uses strict native detection (byte/widget hints), not relaxed SCV.
    strict_native = tr.get("native_widget_event_observed_strict")
    if strict_native is None:
        strict_native = tr.get("native_widget_event_observed")
    if not strict_native and tr.get("generic_component_traffic_only"):
        return "QUEUE1C3A2"
    if not strict_native and not tr.get("script_run_seq_changed") and tr.get("streamlit_outbound_after_click"):
        return "QUEUE1C3A2"
    if tr.get("native_widget_event_observed") and not tr.get("script_run_seq_changed"):
        return "QUEUE1C3A3"
    if tr.get("script_run_seq_changed") and callback_entered is False:
        return "QUEUE1C3A4"
    if callback_trace_present and not callback_entered:
        return "QUEUE1C3A4"
    return "QUEUE1C3A"
