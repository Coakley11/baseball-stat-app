"""Strict BackMsg protobuf decode from captured WS outbound payloads (harness-only)."""

from __future__ import annotations

import base64
from typing import Any


def outbound_frames_after_click(raw_log: list[dict[str, Any]], click_ts: float) -> list[dict[str, Any]]:
    t0_ms = float(click_ts) * 1000.0 - 50.0
    out: list[dict[str, Any]] = []
    for e in raw_log:
        if not isinstance(e, dict) or e.get("direction") != "outbound":
            continue
        if float(e.get("wall_ts_ms") or 0) >= t0_ms:
            out.append(dict(e))
    return out


def decode_outbound_frame_entry(entry: dict[str, Any]) -> dict[str, Any]:
    from p8_streamlit_backmsg_decode import try_parse_backmsg

    row: dict[str, Any] = {
        "wall_ts_ms": entry.get("wall_ts_ms"),
        "byte_len": entry.get("byte_len"),
        "ws_url_redacted": entry.get("ws_url_redacted"),
        "frame_type_hint_heuristic": entry.get("frame_type_hint"),
        "has_payload_base64": bool(entry.get("payload_base64")),
    }
    b64 = entry.get("payload_base64")
    if not b64:
        row["decode"] = {"parsed": False, "parse_error": "payload_base64_missing"}
        return row
    try:
        data = base64.b64decode(str(b64))
    except Exception as exc:
        row["decode"] = {"parsed": False, "parse_error": f"base64_decode_failed:{exc}"[:120]}
        return row
    row["decode"] = try_parse_backmsg(data)
    return row


def _activated_widget_states(decode: dict[str, Any]) -> list[dict[str, Any]]:
    if decode.get("backmsg_oneof_type") != "rerun_script":
        return []
    activated: list[dict[str, Any]] = []
    for ws in decode.get("widget_states") or []:
        if not isinstance(ws, dict):
            continue
        if ws.get("trigger_value") is True:
            activated.append(dict(ws))
    return activated


def summarize_strict_backmsg_evidence(
    raw_log: list[dict[str, Any]],
    *,
    click_ts: float,
    relaxed_ws_sample: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Authoritative strict fields; relaxed heuristics are supplementary only."""
    frames = outbound_frames_after_click(raw_log, click_ts)
    decoded_rows = [decode_outbound_frame_entry(e) for e in frames]

    protobuf_decoded_any = any(bool((r.get("decode") or {}).get("parsed")) for r in decoded_rows)
    rerun_rows = [r for r in decoded_rows if (r.get("decode") or {}).get("backmsg_oneof_type") == "rerun_script"]
    rerun_script_seen = len(rerun_rows) > 0

    widget_states_count = 0
    wire_rerun_target_fragment_id = ""
    other_fragment_ids_observed: list[str] = []
    all_activated: list[dict[str, Any]] = []
    for r in rerun_rows:
        dec = r.get("decode") or {}
        widget_states_count = max(widget_states_count, int(dec.get("widget_state_count") or 0))
        cs = dec.get("client_state") if isinstance(dec.get("client_state"), dict) else {}
        fid = str(cs.get("fragment_id") or "").strip()
        if fid:
            if not wire_rerun_target_fragment_id:
                wire_rerun_target_fragment_id = fid
            elif fid != wire_rerun_target_fragment_id and fid not in other_fragment_ids_observed:
                other_fragment_ids_observed.append(fid)
        all_activated.extend(_activated_widget_states(dec))

    # Legacy alias — prefer wire_rerun_target_fragment_id in new artifacts.
    fragment_ids = ([wire_rerun_target_fragment_id] if wire_rerun_target_fragment_id else []) + other_fragment_ids_observed

    payload_missing = any(not r.get("has_payload_base64") for r in decoded_rows) if frames else False
    decode_available = not payload_missing and all(
        (r.get("decode") or {}).get("parse_error") != "BackMsg_pb2_unavailable" for r in decoded_rows
    ) if frames else True

    inbound_after = [
        e
        for e in raw_log
        if isinstance(e, dict)
        and e.get("direction") == "inbound"
        and float(e.get("wall_ts_ms") or 0) >= (float(click_ts) * 1000.0 - 50.0)
    ]

    out: dict[str, Any] = {
        "protobuf_decode_available": decode_available and not payload_missing,
        "websocket_outbound_seen": len(frames) > 0,
        "websocket_inbound_activity_seen": len(inbound_after) > 0,
        "outbound_ws_frame_count": len(frames),
        "protobuf_backmsg_decoded": protobuf_decoded_any,
        "rerun_script_backmsg_seen": rerun_script_seen,
        "widget_states_present": widget_states_count > 0,
        "widget_states_count_max": widget_states_count,
        "activated_widget_state_present": len(all_activated) > 0,
        "activated_widget_states": all_activated[:24],
        "activated_widget_ids": [str(w.get("id") or "") for w in all_activated if w.get("id")][:24],
        "wire_rerun_target_fragment_id": wire_rerun_target_fragment_id,
        "other_fragment_ids_observed": other_fragment_ids_observed[:8],
        "fragment_ids_from_rerun": fragment_ids[:8],
        "decoded_outbound_frames": decoded_rows[:12],
        "supplementary_relaxed_heuristic": {},
    }

    if relaxed_ws_sample is not None:
        try:
            from stage1_native_widget_transport import classify_transport_from_ws_samples

            relaxed = classify_transport_from_ws_samples(relaxed_ws_sample)
            out["supplementary_relaxed_heuristic"] = {
                "streamlit_outbound_after_click": relaxed.get("streamlit_outbound_after_click"),
                "native_widget_event_observed": relaxed.get("native_widget_event_observed"),
                "native_widget_event_observed_strict": relaxed.get("native_widget_event_observed_strict"),
                "component_value_only_hint": relaxed.get("generic_component_traffic_only"),
                "note": "not_authoritative_for_strict_S1_S2_S3",
            }
        except ImportError:
            pass

    # Legacy field — protobuf rerun_script only (not generic outbound).
    out["streamlit_backmsg_sent"] = rerun_script_seen if out["protobuf_decode_available"] else None
    return out


def build_strict_evidence_table_row(
    *,
    trusted_dom_click: bool,
    strict: dict[str, Any],
    python_effect: str,
) -> dict[str, Any]:
    return {
        "trusted_dom_click": trusted_dom_click,
        "outbound_ws_frames": strict.get("outbound_ws_frame_count"),
        "valid_backmsg_frames": sum(
            1
            for r in strict.get("decoded_outbound_frames") or []
            if (r.get("decode") or {}).get("parsed")
        ),
        "rerun_script_backmsg": strict.get("rerun_script_backmsg_seen"),
        "widget_states_count": strict.get("widget_states_count_max"),
        "triggered_widget_state_present": strict.get("activated_widget_state_present"),
        "triggered_widget_ids": list(strict.get("activated_widget_ids") or [])[:8],
        "wire_rerun_target_fragment_id": strict.get("wire_rerun_target_fragment_id")
        or ((strict.get("fragment_ids_from_rerun") or [""])[0] if strict.get("fragment_ids_from_rerun") else ""),
        "other_fragment_ids_observed": list(strict.get("other_fragment_ids_observed") or [])[:8],
        "fragment_id": strict.get("wire_rerun_target_fragment_id")
        or ((strict.get("fragment_ids_from_rerun") or [""])[0] if strict.get("fragment_ids_from_rerun") else ""),
        "python_session_effect": python_effect,
        "websocket_outbound_seen": strict.get("websocket_outbound_seen"),
        "protobuf_decode_available": strict.get("protobuf_decode_available"),
    }
