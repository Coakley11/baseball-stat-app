"""Shared Streamlit WebSocket / BackMsg grading for Pause and sibling (harness-only)."""

from __future__ import annotations

from typing import Any


def clear_ws_boundary_log(page) -> dict[str, Any]:
    """Reset __p8WsBoundaryLog in app frame windows (independent per click step)."""
    try:
        from p8_proven_start_delivery import aggregate_ws_boundary_log

        before_n = len(aggregate_ws_boundary_log(page))
    except Exception:
        before_n = -1
    try:
        cleared = page.evaluate(
            """() => {
          function clearWin(win) {
            try { if (Array.isArray(win.__p8WsBoundaryLog)) win.__p8WsBoundaryLog.length = 0; } catch (e) {}
          }
          clearWin(window);
          for (const f of document.querySelectorAll('iframe')) {
            try { if (f.contentWindow) clearWin(f.contentWindow); } catch (e) {}
          }
          return { cleared: true };
        }"""
        )
    except Exception as exc:
        return {"cleared": False, "error": str(exc)[:160], "entries_before_clear": before_n}
    out = dict(cleared) if isinstance(cleared, dict) else {"cleared": bool(cleared)}
    out["entries_before_clear"] = before_n
    try:
        out["entries_after_clear"] = len(aggregate_ws_boundary_log(page))
    except Exception:
        out["entries_after_clear"] = -1
    return out


def capture_streamlit_click_transport(
    page,
    *,
    click_ts: float,
    frame_url_hint: str = "",
    pre_script_run_seq: str = "",
    post_script_run_seq: str = "",
    include_strict_backmsg: bool = True,
    expected_widget_id: str = "",
) -> dict[str, Any]:
    """
    Capture WS traffic after click_ts.

    Strict protobuf fields (authoritative for S1–S3) live under ``strict_backmsg``.
    ``streamlit_backmsg_sent`` means ``rerun_script`` BackMsg decoded (not any outbound frame).

    When ``expected_widget_id`` is supplied, strict wire fragment comes from the target-trigger
    BackMsg only (not the first temporally nearby rerun_script frame).
    """
    try:
        from p8_proven_start_delivery import aggregate_ws_boundary_log, websocket_open_at_click
        from stage1_native_widget_transport import classify_transport_from_ws_samples
    except ImportError as exc:
        return {
            "transport_authority": "unavailable",
            "error": str(exc)[:200],
            "streamlit_backmsg_sent": None,
            "websocket_outbound_seen": False,
            "outbound_frames_after_click": 0,
            "inbound_frames_after_click": 0,
            "ws_log_sample": [],
        }

    hook = websocket_open_at_click(page)
    raw_log = aggregate_ws_boundary_log(page)
    outbound = [e for e in raw_log if isinstance(e, dict) and e.get("direction") == "outbound"]
    inbound = [e for e in raw_log if isinstance(e, dict) and e.get("direction") == "inbound"]
    t0_ms = float(click_ts) * 1000.0 - 50.0
    after_out = [e for e in outbound if float(e.get("wall_ts_ms") or 0) >= t0_ms]
    after_in = [e for e in inbound if float(e.get("wall_ts_ms") or 0) >= t0_ms]

    authority = "available" if (hook or len(raw_log) > 0) else "unavailable"
    classified = classify_transport_from_ws_samples(
        after_out,
        pre_script_run_seq=str(pre_script_run_seq or ""),
        post_script_run_seq=str(post_script_run_seq or ""),
        expected_widget_key=str(expected_widget_id or ""),
    )

    strict: dict[str, Any] = {}
    if include_strict_backmsg:
        from stage1_strict_backmsg_decode import summarize_strict_backmsg_evidence

        strict = summarize_strict_backmsg_evidence(
            raw_log,
            click_ts=click_ts,
            relaxed_ws_sample=after_out,
            expected_widget_id=str(expected_widget_id or ""),
        )

    # Protobuf trigger authority upgrades heuristic strict (component_value_hint + wrong hook key).
    if strict.get("target_trigger_backmsg_seen") or (
        expected_widget_id
        and strict.get("activated_widget_state_present")
        and any(str(expected_widget_id) in str(i) for i in (strict.get("activated_widget_ids") or []))
    ):
        classified["native_widget_event_observed_strict"] = True
        classified["native_widget_event_observed"] = True
        classified["protobuf_target_trigger_observed"] = True

    backmsg: bool | None
    if strict:
        backmsg = strict.get("streamlit_backmsg_sent")
    elif authority == "available":
        backmsg = bool(classified.get("streamlit_backmsg_sent"))
    else:
        backmsg = None

    first_ts = None
    if after_out:
        first_ts = min(float(e.get("wall_ts_ms") or 0) for e in after_out)

    widget_key_any = any(bool(e.get("widget_key_bytes_present")) for e in after_out)
    decoded_hints = {
        "widget_key_bytes_present_any": widget_key_any,
        "frame_type_hints": sorted({str(e.get("frame_type_hint") or "") for e in after_out if e.get("frame_type_hint")}),
    }

    return {
        "transport_authority": authority,
        "websocket_hook_seen": hook,
        "aggregate_ws_entries_total": len(raw_log),
        "websocket_outbound_seen": bool(strict.get("websocket_outbound_seen")) if strict else len(after_out) > 0,
        "websocket_inbound_activity_seen": bool(strict.get("websocket_inbound_activity_seen")) if strict else len(after_in) > 0,
        "protobuf_backmsg_decoded": strict.get("protobuf_backmsg_decoded") if strict else None,
        "rerun_script_backmsg_seen": strict.get("rerun_script_backmsg_seen") if strict else None,
        "widget_states_present": strict.get("widget_states_present") if strict else None,
        "activated_widget_state_present": strict.get("activated_widget_state_present") if strict else None,
        "outbound_frames_after_click": int(classified.get("outbound_frames_after_click") or len(after_out)),
        "inbound_frames_after_click": len(after_in),
        "streamlit_backmsg_sent": backmsg,
        "streamlit_outbound_after_click": bool(classified.get("streamlit_outbound_after_click")),
        "native_widget_event_observed": classified.get("native_widget_event_observed"),
        "native_widget_event_observed_strict": classified.get("native_widget_event_observed_strict"),
        "generic_component_traffic_only": classified.get("generic_component_traffic_only"),
        "ws_log_sample": list(classified.get("ws_log_sample") or after_out[:8]),
        "ws_log_inbound_sample": after_in[:8],
        "first_outbound_wall_ts_ms": first_ts,
        "click_ts": click_ts,
        "frame_url_hint": frame_url_hint[:240] if frame_url_hint else "",
        "decoded_hints": decoded_hints,
        "python_rerun_started": classified.get("python_rerun_started"),
        "script_run_seq_changed": classified.get("script_run_seq_changed"),
        "strict_backmsg": strict,
    }


def build_transport_comparison_row(dom: dict[str, Any], transport: dict[str, Any], *, python_effect: str, ui_effect: str) -> dict[str, Any]:
    strict = dict(transport.get("strict_backmsg") or {})
    if strict:
        from stage1_strict_backmsg_decode import build_strict_evidence_table_row

        row = build_strict_evidence_table_row(
            trusted_dom_click=bool(dom.get("trusted_dom_click")),
            strict=strict,
            python_effect=python_effect,
        )
        row["ui_effect"] = ui_effect
        row["transport_authority"] = transport.get("transport_authority")
        return row
    hints = dict(transport.get("decoded_hints") or {})
    sample = list(transport.get("ws_log_sample") or [])
    first = sample[0] if sample else {}
    return {
        "trusted_dom_click": bool(dom.get("trusted_dom_click")),
        "streamlit_backmsg_sent": transport.get("streamlit_backmsg_sent"),
        "outbound_ws_count": transport.get("outbound_frames_after_click"),
        "inbound_ws_after_click": transport.get("inbound_frames_after_click"),
        "widget_id_decoded": hints.get("widget_key_bytes_present_any"),
        "widget_trigger_value_decoded": first.get("frame_type_hint") if isinstance(first, dict) else None,
        "transport_authority": transport.get("transport_authority"),
        "python_session_effect": python_effect,
        "ui_effect": ui_effect,
    }
