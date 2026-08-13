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


def _frame_decode(row: dict[str, Any]) -> dict[str, Any]:
    dec = row.get("decode")
    return dict(dec) if isinstance(dec, dict) else {}


def _frame_fragment_id(row: dict[str, Any]) -> str:
    dec = _frame_decode(row)
    if dec.get("backmsg_oneof_type") != "rerun_script":
        return ""
    cs = dec.get("client_state") if isinstance(dec.get("client_state"), dict) else {}
    return str(cs.get("fragment_id") or "").strip()


def _frame_has_expected_trigger(row: dict[str, Any], expected_widget_id: str) -> bool:
    want = str(expected_widget_id or "").strip()
    if not want:
        return False
    dec = _frame_decode(row)
    if dec.get("backmsg_oneof_type") != "rerun_script":
        return False
    for ws in dec.get("widget_states") or []:
        if not isinstance(ws, dict):
            continue
        if str(ws.get("id") or "").strip() == want and ws.get("trigger_value") is True:
            return True
    return False


def _target_widget_state(row: dict[str, Any], expected_widget_id: str) -> dict[str, Any] | None:
    want = str(expected_widget_id or "").strip()
    if not want:
        return None
    dec = _frame_decode(row)
    for ws in dec.get("widget_states") or []:
        if not isinstance(ws, dict):
            continue
        if str(ws.get("id") or "").strip() == want and ws.get("trigger_value") is True:
            return dict(ws)
    return None


def correlate_target_trigger_backmsg(
    decoded_rows: list[dict[str, Any]],
    *,
    expected_widget_id: str = "",
) -> dict[str, Any]:
    """Select authoritative wire fragment from the frame carrying expected widget trigger=true.

    When ``expected_widget_id`` is empty, returns legacy first-rerun selection fields only.
    When supplied and no matching trigger frame exists, wire is empty (no first-frame fallback).
    """
    want = str(expected_widget_id or "").strip()
    rerun_rows = [
        (i, r)
        for i, r in enumerate(decoded_rows)
        if isinstance(r, dict) and _frame_decode(r).get("backmsg_oneof_type") == "rerun_script"
    ]
    all_rerun_fragment_ids: list[str] = []
    first_rerun_fragment_id = ""
    for _i, r in rerun_rows:
        fid = _frame_fragment_id(r)
        if not fid:
            continue
        if not first_rerun_fragment_id:
            first_rerun_fragment_id = fid
        if fid not in all_rerun_fragment_ids:
            all_rerun_fragment_ids.append(fid)

    out: dict[str, Any] = {
        "expected_widget_id": want,
        "target_correlation_requested": bool(want),
        "first_rerun_fragment_id": first_rerun_fragment_id,
        "all_rerun_fragment_ids": all_rerun_fragment_ids[:16],
        "target_trigger_backmsg_seen": False,
        "target_trigger_frame_index": None,
        "target_trigger_wall_ts_ms": None,
        "target_trigger_fragment_id": "",
        "target_trigger_widget_state": None,
        "target_trigger_activated_widget_ids": [],
        "wire_rerun_target_fragment_id": "",
        "other_fragment_ids_observed": [],
        "target_backmsg_consistency": {
            "expected_widget_id": want,
            "expected_trigger_seen": False,
            "selected_fragment_id": "",
            "selected_frame_wall_ts_ms": None,
            "selected_frame_activated_ids": [],
            "unrelated_rerun_count_before_target": 0,
            "unrelated_rerun_count_after_target": 0,
        },
    }

    if not want:
        wire = first_rerun_fragment_id
        others = [f for f in all_rerun_fragment_ids if f != wire]
        out["wire_rerun_target_fragment_id"] = wire
        out["other_fragment_ids_observed"] = others[:8]
        out["target_backmsg_consistency"]["selected_fragment_id"] = wire
        return out

    target_idx_in_decoded: int | None = None
    target_row: dict[str, Any] | None = None
    for i, r in enumerate(decoded_rows):
        if not isinstance(r, dict):
            continue
        if _frame_has_expected_trigger(r, want):
            target_idx_in_decoded = i
            target_row = r
            break

    if target_row is None or target_idx_in_decoded is None:
        # Critical: no fallback to first unrelated rerun when correlation was requested.
        out["wire_rerun_target_fragment_id"] = ""
        out["other_fragment_ids_observed"] = list(all_rerun_fragment_ids)[:8]
        return out

    target_fid = _frame_fragment_id(target_row)
    activated = _activated_widget_states(_frame_decode(target_row))
    activated_ids = [str(w.get("id") or "") for w in activated if w.get("id")]
    before = 0
    after = 0
    for i, r in enumerate(decoded_rows):
        if not isinstance(r, dict):
            continue
        if _frame_decode(r).get("backmsg_oneof_type") != "rerun_script":
            continue
        if i < target_idx_in_decoded:
            before += 1
        elif i > target_idx_in_decoded:
            after += 1
    others = [f for f in all_rerun_fragment_ids if f != target_fid]

    out.update(
        {
            "target_trigger_backmsg_seen": True,
            "target_trigger_frame_index": target_idx_in_decoded,
            "target_trigger_wall_ts_ms": target_row.get("wall_ts_ms"),
            "target_trigger_fragment_id": target_fid,
            "target_trigger_widget_state": _target_widget_state(target_row, want),
            "target_trigger_activated_widget_ids": activated_ids[:24],
            "wire_rerun_target_fragment_id": target_fid,
            "other_fragment_ids_observed": others[:8],
            "target_backmsg_consistency": {
                "expected_widget_id": want,
                "expected_trigger_seen": True,
                "selected_fragment_id": target_fid,
                "selected_frame_wall_ts_ms": target_row.get("wall_ts_ms"),
                "selected_frame_activated_ids": activated_ids[:24],
                "unrelated_rerun_count_before_target": before,
                "unrelated_rerun_count_after_target": after,
            },
        }
    )
    return out


def summarize_strict_backmsg_evidence(
    raw_log: list[dict[str, Any]],
    *,
    click_ts: float,
    relaxed_ws_sample: list[dict[str, Any]] | None = None,
    expected_widget_id: str = "",
    decoded_outbound_frames: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Authoritative strict fields; relaxed heuristics are supplementary only.

    When ``expected_widget_id`` is supplied, ``wire_rerun_target_fragment_id`` is taken only from
    the rerun_script frame whose widget_states contain that id with ``trigger_value=true``.
    """
    if decoded_outbound_frames is not None:
        decoded_rows = [dict(r) for r in decoded_outbound_frames if isinstance(r, dict)]
        frames = list(decoded_rows)
    else:
        frames = outbound_frames_after_click(raw_log, click_ts)
        decoded_rows = [decode_outbound_frame_entry(e) for e in frames]

    protobuf_decoded_any = any(bool((r.get("decode") or {}).get("parsed")) for r in decoded_rows)
    rerun_rows = [r for r in decoded_rows if (r.get("decode") or {}).get("backmsg_oneof_type") == "rerun_script"]
    rerun_script_seen = len(rerun_rows) > 0

    widget_states_count = 0
    all_activated: list[dict[str, Any]] = []
    for r in rerun_rows:
        dec = r.get("decode") or {}
        widget_states_count = max(widget_states_count, int(dec.get("widget_state_count") or 0))
        all_activated.extend(_activated_widget_states(dec))

    correlated = correlate_target_trigger_backmsg(decoded_rows, expected_widget_id=expected_widget_id)
    wire_rerun_target_fragment_id = str(correlated.get("wire_rerun_target_fragment_id") or "")
    other_fragment_ids_observed = list(correlated.get("other_fragment_ids_observed") or [])
    fragment_ids = ([wire_rerun_target_fragment_id] if wire_rerun_target_fragment_id else []) + [
        f for f in other_fragment_ids_observed if f != wire_rerun_target_fragment_id
    ]

    payload_missing = any(not r.get("has_payload_base64") for r in decoded_rows) if frames else False
    if decoded_outbound_frames is not None:
        decode_available = True
        payload_missing = False
    else:
        decode_available = (
            not payload_missing
            and all(
                (r.get("decode") or {}).get("parse_error") != "BackMsg_pb2_unavailable" for r in decoded_rows
            )
            if frames
            else True
        )

    inbound_after = [
        e
        for e in raw_log
        if isinstance(e, dict)
        and e.get("direction") == "inbound"
        and float(e.get("wall_ts_ms") or 0) >= (float(click_ts) * 1000.0 - 50.0)
    ]

    want = str(expected_widget_id or "").strip()
    activated_present = len(all_activated) > 0
    if want:
        activated_present = bool(correlated.get("target_trigger_backmsg_seen"))

    out: dict[str, Any] = {
        "protobuf_decode_available": decode_available and not payload_missing,
        "websocket_outbound_seen": len(frames) > 0,
        "websocket_inbound_activity_seen": len(inbound_after) > 0,
        "outbound_ws_frame_count": len(frames),
        "protobuf_backmsg_decoded": protobuf_decoded_any,
        "rerun_script_backmsg_seen": rerun_script_seen,
        "widget_states_present": widget_states_count > 0,
        "widget_states_count_max": widget_states_count,
        "activated_widget_state_present": activated_present,
        "activated_widget_states": all_activated[:24],
        "activated_widget_ids": [str(w.get("id") or "") for w in all_activated if w.get("id")][:24],
        "wire_rerun_target_fragment_id": wire_rerun_target_fragment_id,
        "other_fragment_ids_observed": other_fragment_ids_observed[:8],
        "fragment_ids_from_rerun": fragment_ids[:8],
        "decoded_outbound_frames": decoded_rows[:12],
        "supplementary_relaxed_heuristic": {},
        "expected_widget_id": correlated.get("expected_widget_id") or "",
        "target_correlation_requested": bool(correlated.get("target_correlation_requested")),
        "target_trigger_backmsg_seen": bool(correlated.get("target_trigger_backmsg_seen")),
        "target_trigger_frame_index": correlated.get("target_trigger_frame_index"),
        "target_trigger_wall_ts_ms": correlated.get("target_trigger_wall_ts_ms"),
        "target_trigger_fragment_id": correlated.get("target_trigger_fragment_id") or "",
        "target_trigger_widget_state": correlated.get("target_trigger_widget_state"),
        "target_trigger_activated_widget_ids": list(correlated.get("target_trigger_activated_widget_ids") or []),
        "first_rerun_fragment_id": correlated.get("first_rerun_fragment_id") or "",
        "all_rerun_fragment_ids": list(correlated.get("all_rerun_fragment_ids") or []),
        "target_backmsg_consistency": dict(correlated.get("target_backmsg_consistency") or {}),
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
        "target_trigger_backmsg_seen": strict.get("target_trigger_backmsg_seen"),
        "expected_widget_id": strict.get("expected_widget_id"),
    }
