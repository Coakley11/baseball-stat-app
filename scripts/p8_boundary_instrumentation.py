"""Immediate-parent SCV + WebSocket boundary instrumentation (harness only)."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any

PRODUCTION_WIDGET_KEY = "solo_countdown_wake_solo_persistent"

P8_IMMEDIATE_PARENT_INSTALL_JS = """
(meta) => {
  const LOG = "__p8ImmediateParentBoundaryLog";
  const META = "__p8ImmediateParentBoundaryMeta";
  if (!window[LOG]) window[LOG] = [];
  if (window.__p8ImmediateParentListenerInstalled) {
    window[META] = Object.assign(window[META] || {}, meta || {}, { reinstall_at: Date.now() });
    return { already: true, count: window[LOG].length };
  }
  window.__p8ImmediateParentListenerInstalled = true;
  window[META] = Object.assign({}, meta || {}, { installed_at: Date.now() });
  function sanitizeUrl(u) {
    try {
      var x = new URL(String(u || location.href));
      if (x.searchParams.has("suite_sid")) x.searchParams.set("suite_sid", "[redacted]");
      return x.origin + x.pathname + (x.search || "");
    } catch (e) {
      return String(u || "");
    }
  }
  function resolveProductionSource(source) {
    var iframes = document.querySelectorAll("iframe");
    for (var i = 0; i < iframes.length; i++) {
      var el = iframes[i];
      try {
        if (el.contentWindow !== source) continue;
        var instanceId = "";
        var widgetKey = "";
        var isProd = false;
        try {
          var doc = el.contentDocument;
          var solo = doc && doc.getElementById("solo-expire-client");
          if (solo) {
            isProd = true;
            instanceId = String(solo.getAttribute("data-iframe-instance") || "");
            widgetKey = String(solo.getAttribute("data-widget-key") || "");
          }
        } catch (e2) {}
        return {
          iframe_dom_index: i,
          iframe_is_connected: !!el.isConnected,
          iframe_instance_id: instanceId,
          widget_key: widgetKey,
          is_production_countdown: isProd,
          child_src: sanitizeUrl(el.src || ""),
        };
      } catch (e3) {}
    }
    return {
      iframe_dom_index: -1,
      iframe_is_connected: false,
      iframe_instance_id: "",
      is_production_countdown: false,
      child_src: "",
    };
  }
  function onMsg(ev) {
    var d = ev && ev.data;
    if (!d || typeof d !== "object") return;
    var mt = String(d.type || "");
    if (mt !== "streamlit:setComponentValue" && mt !== "solo:stage1ImmediateParentProbe") return;
    var val = d.value != null ? String(d.value) : "";
    var assoc = resolveProductionSource(ev.source);
    var rec = {
      event: "production_stage1_immediate_parent_scv_received",
      receipt_wall_ts: Date.now(),
      message_type: mt,
      exact_payload_preview: val.slice(0, 400),
      event_origin: String((ev && ev.origin) || ""),
      source_association: assoc,
      source_matches_production_iframe: !!assoc.is_production_countdown,
      parent_frame_url: sanitizeUrl(location.href),
      parent_window_name: String(window.name || ""),
      production_iframe_instance_id: String(d.iframe_instance_id || d.iframe_instance || assoc.iframe_instance_id || ""),
      iframe_connected_state: assoc.iframe_is_connected,
      widget_key: String(d.widget_key || assoc.widget_key || ""),
      browser_send_event_id: String(d.browser_send_event_id || ""),
      deployment_sha: String((window[META] && window[META].deployment_sha) || ""),
      diagnostic_run_id: String((window[META] && window[META].diagnostic_run_id) || ""),
      expected_token: String((window[META] && window[META].expected_token) || ""),
    };
    window[LOG].push(rec);
    if (window[LOG].length > 200) window[LOG] = window[LOG].slice(-160);
  }
  window.addEventListener("message", onMsg, true);
  return { installed: true, parent_url: sanitizeUrl(location.href) };
}
"""


def install_production_immediate_parent_listener(
    page,
    *,
    deployment_sha: str,
    diagnostic_run_id: str,
    expected_token: str,
    room_id: str,
    pick_index: int | None,
    widget_key: str,
) -> dict[str, Any]:
    from stage1_frame2_parent_boundary import find_production_countdown_frame

    prod_fr, prod_idx = find_production_countdown_frame(page)
    if prod_fr is None:
        return {"ok": False, "error": "production_countdown_frame_not_found"}
    parent = prod_fr.parent_frame
    if parent is None:
        return {"ok": False, "error": "no_parent_frame", "prod_frame_index": prod_idx}
    meta = {
        "deployment_sha": str(deployment_sha or "")[:7],
        "diagnostic_run_id": str(diagnostic_run_id or ""),
        "expected_token": str(expected_token or "")[:400],
        "room_id": str(room_id or ""),
        "pick_index": pick_index,
        "widget_key": str(widget_key or PRODUCTION_WIDGET_KEY),
        "production_iframe_playwright_index": prod_idx,
    }
    try:
        res = parent.evaluate(P8_IMMEDIATE_PARENT_INSTALL_JS, meta)
        return {
            "ok": True,
            "prod_frame_index": prod_idx,
            "parent_frame_index": _frame_index(page, parent),
            "parent_url": _sanitize(parent.url),
            "production_iframe_discovery": meta,
            "result": res,
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "prod_frame_index": prod_idx}


def scrape_immediate_parent_boundary_log(page) -> dict[str, Any]:
    from stage1_frame2_parent_boundary import find_production_countdown_frame

    prod_fr, prod_idx = find_production_countdown_frame(page)
    if prod_fr is None:
        return {"records": [], "absence": {"reason": "production_frame_not_found"}}
    parent = prod_fr.parent_frame
    if parent is None:
        return {"records": [], "absence": {"reason": "no_parent_frame"}}
    try:
        raw = parent.evaluate(
            """() => ({
              records: window.__p8ImmediateParentBoundaryLog || [],
              meta: window.__p8ImmediateParentBoundaryMeta || {},
            })"""
        )
        if isinstance(raw, dict):
            raw["parent_frame_index"] = _frame_index(page, parent)
            raw["parent_url"] = _sanitize(parent.url)
            raw["prod_frame_index"] = prod_idx
            return raw
    except Exception as exc:
        return {"records": [], "error": type(exc).__name__}
    return {"records": []}


def _frame_index(page, target) -> int | None:
    for i, fr in enumerate(page.frames):
        if fr is target:
            return i
    return None


def _sanitize(url: str) -> str:
    from stage1_frame_transport_probe import sanitize_url

    return sanitize_url(url or "")


class WebSocketBoundaryCapture:
    """Playwright WebSocket frame capture with safe token-presence hashing."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.sockets: list[dict[str, Any]] = []

    def attach(self, page) -> None:
        def _on_ws(ws):
            sid = f"ws_{len(self.sockets)}"
            self.sockets.append({"id": sid, "url": _redact_ws_url(ws.url), "opened_at": time.time()})

            def _record(direction: str, payload: Any) -> None:
                text = payload if isinstance(payload, str) else str(payload)
                if len(text) > 200000:
                    text = text[:200000]
                lowered = text.lower()
                interesting = any(
                    k in lowered
                    for k in (
                        "widget",
                        "component",
                        "setcomponent",
                        "rerun",
                        "delta",
                        "session",
                        "backmsg",
                    )
                ) or PRODUCTION_WIDGET_KEY in text
                if not interesting and len(text) < 40:
                    return
                token_hint = _token_presence_indicator(text)
                self.frames.append(
                    {
                        "wall_ts": time.time(),
                        "direction": direction,
                        "ws_id": sid,
                        "byte_len": len(text.encode("utf-8", errors="ignore")),
                        "frame_type_hint": _frame_type_hint(text),
                        "sha256_prefix": hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16],
                        "token_presence": token_hint,
                        "snippet_safe": _redact_snippet(text[:280]),
                    }
                )
                if len(self.frames) > 500:
                    self.frames = self.frames[-400:]

            ws.on("framesent", lambda p: _record("outbound", p))
            ws.on("framereceived", lambda p: _record("inbound", p))

        page.on("websocket", _on_ws)


def _redact_ws_url(url: str) -> str:
    return re.sub(r"([?&])(token|key|sid|secret|auth)=[^&]+", r"\1\2=[redacted]", url or "", flags=re.I)


def _redact_snippet(text: str) -> str:
    return re.sub(
        r"(suite_sid|apikey|authorization|bearer)[\"':=\s]+[^\s\"',}{]+",
        r"\1=[redacted]",
        text,
        flags=re.I,
    )


def _token_presence_indicator(text: str) -> dict[str, Any]:
    m = re.search(r"([A-F0-9]{8})\|(\d+)\|(\d+\.?\d*)", text)
    if m:
        return {"room_id": m.group(1), "pick": m.group(2), "deadline_fragment": m.group(3)[:20]}
    if PRODUCTION_WIDGET_KEY in text:
        return {"widget_key_literal": True}
    return {}


def _frame_type_hint(text: str) -> str:
    if "rerun" in text.lower():
        return "rerun_hint"
    if "setComponent" in text or "component" in text.lower():
        return "component_hint"
    return "other"


def enrich_post_send_server_audit(
    peak_rows: list[dict[str, Any]],
    *,
    send_epoch: float,
    deployment_sha: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in peak_rows:
        if str(row.get("event") or "") != "production_stage1_script_begin":
            continue
        ts = float(row.get("ts") or 0)
        if ts < send_epoch - 0.05:
            continue
        out.append(
            {
                "event": "production_stage1_script_begin_durable",
                "source": "harness_peak_ledger",
                "server_ts": ts,
                "script_run_seq": row.get("script_run_seq"),
                "run_id": row.get("run_id"),
                "room_id": row.get("room_id"),
                "pick_index": row.get("pick_index"),
                "deadline": row.get("deadline"),
                "expected_token": row.get("expected_token"),
                "session_state_widget_value": row.get("session_state_value") or row.get("pending_session_state_value"),
                "active_page": row.get("active_page"),
                "deployment_sha": deployment_sha,
                "declaration_eligibility_hint": row.get("actionable_mount_eligible"),
            }
        )
    for row in peak_rows:
        if str(row.get("event") or "") != "production_stage1_declaration_returned":
            continue
        ts = float(row.get("ts") or 0)
        if ts < send_epoch - 0.05:
            continue
        if not out:
            continue
        out[-1]["direct_component_return"] = row.get("direct_component_return")
        out[-1]["session_state_value"] = row.get("session_state_value")
        out[-1]["coalesced_value"] = row.get("coalesced_value")
        out[-1]["declaration_returned_ts"] = ts
    return out


def build_unified_timeline(
    *,
    send_epoch: float,
    send_boundary: dict[str, Any],
    iframe_entries: list[dict[str, Any]],
    immediate_records: list[dict[str, Any]],
    ws_frames: list[dict[str, Any]],
    post_send_server: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from p8_sender_rerun_trace import normalize_epoch_ts

    events: list[dict[str, Any]] = []

    def add(t_rel: float | None, kind: str, source: str, **extra: Any) -> None:
        events.append({"t_rel_send_s": t_rel, "kind": kind, "source": source, **extra})

    add(0.0, "child_transport_before_postMessage", "production_iframe_lifecycle", **send_boundary)

    for rec in immediate_records:
        wt_ms = float(rec.get("receipt_wall_ts") or 0)
        wt = wt_ms / 1000.0 if wt_ms > 1e12 else wt_ms
        t_rel = round(wt - send_epoch, 3) if wt > 1e9 else None
        add(t_rel, "production_stage1_immediate_parent_scv_received", "immediate_parent_listener", **rec)

    for e in iframe_entries:
        ts = normalize_epoch_ts(e.get("ts"))
        if ts is None or ts < send_epoch - 5:
            continue
        stage = str(e.get("stage") or "")
        extra = str(e.get("extra") or "")
        if stage in ("tick_cancelled", "iframe_remount") or "streamlit_render" in extra:
            add(round(ts - send_epoch, 3), stage, "iframe_lifecycle", extra=extra[:200])

    for wf in ws_frames:
        wt = float(wf.get("wall_ts") or 0)
        if wt < send_epoch - 5:
            continue
        add(round(wt - send_epoch, 3), f"websocket_{wf.get('direction')}", "playwright_ws", **wf)

    for row in post_send_server:
        ts = float(row.get("server_ts") or 0)
        add(round(ts - send_epoch, 3), "production_stage1_script_begin_durable", "server_audit", **row)

    events.sort(key=lambda x: (x.get("t_rel_send_s") is None, x.get("t_rel_send_s") or 999))
    return events


def classify_first_missing_boundary(
    *,
    send_epoch: float,
    exact_token: str,
    send_boundary: dict[str, Any],
    immediate_log: dict[str, Any],
    ws_capture: WebSocketBoundaryCapture,
    post_send_server: list[dict[str, Any]],
    peak_rows: list[dict[str, Any]],
    iframe_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    from p8_sender_rerun_trace import normalize_epoch_ts

    sending_inst = str(send_boundary.get("iframe_instance_id") or "")
    records = list(immediate_log.get("records") or [])
    scv_exact = [
        r
        for r in records
        if r.get("message_type") == "streamlit:setComponentValue"
        and exact_token in str(r.get("exact_payload_preview") or "")
    ]
    scv_prod_match = [r for r in scv_exact if r.get("source_matches_production_iframe")]
    iframe_disconnect_ts: float | None = None
    streamlit_render_ts: float | None = None
    for e in iframe_entries:
        ts = normalize_epoch_ts(e.get("ts"))
        if ts is None or ts < send_epoch - 0.05:
            continue
        stage = str(e.get("stage") or "")
        extra = str(e.get("extra") or "")
        if stage == "tick_cancelled" and "streamlit_render" in extra:
            streamlit_render_ts = ts
        if stage == "iframe_remount":
            iframe_disconnect_ts = ts

    parent_receipt_ts: float | None = None
    if scv_prod_match:
        wt_ms = float(scv_prod_match[0].get("receipt_wall_ts") or 0)
        parent_receipt_ts = wt_ms / 1000.0 if wt_ms > 1e12 else wt_ms

    ws_after_send = [f for f in ws_capture.frames if float(f.get("wall_ts") or 0) >= send_epoch - 0.02]
    ws_out_after = [f for f in ws_after_send if f.get("direction") == "outbound"]
    ws_in_after = [f for f in ws_after_send if f.get("direction") == "inbound"]
    first_ws_out_ts = min((float(f["wall_ts"]) for f in ws_out_after), default=None)
    first_ws_in_ts = min((float(f["wall_ts"]) for f in ws_in_after), default=None)

    post_begins = post_send_server
    decl_after = [
        r
        for r in peak_rows
        if str(r.get("event") or "") == "production_stage1_declaration_returned"
        and float(r.get("ts") or 0) >= send_epoch - 0.05
    ]
    decl_nonempty = any(
        str(r.get("coalesced_value") or "").strip() not in ("", "None") for r in decl_after
    )

    absence_note = None
    if not scv_exact:
        absence_note = {
            "event": "production_stage1_immediate_parent_scv_absent",
            "reason": (immediate_log.get("absence") or {}).get("reason") or "no_exact_token_scv_in_immediate_parent",
            "expected_token": exact_token,
            "sending_iframe_instance_id": sending_inst,
        }

    code = "LIFECYCLE9"
    rationale = "Boundary trace incomplete or ambiguous."
    correction = "TBD after boundary pin"

    if not scv_exact:
        if streamlit_render_ts or iframe_disconnect_ts:
            code = "LIFECYCLE1"
            rationale = "Production child send proven; immediate parent did not record exact SCV before render/remount."
            correction = "Component teardown/remount timing relative to parent message delivery"
        elif not ws_out_after and not post_begins:
            code = "LIFECYCLE3"
            rationale = "No authoritative immediate-parent SCV; no post-send WS/server rerun — loss likely before or at parent/protocol."
            correction = "Immediate-parent message path (iframe → parent frame)"
    elif scv_exact and not scv_prod_match:
        code = "LIFECYCLE2"
        rationale = "Immediate parent received message with exact token but source did not match production iframe."
        correction = "Source association / nested iframe identity at parent listener"
    elif scv_prod_match and not ws_out_after:
        code = "LIFECYCLE3"
        rationale = "Exact production SCV at immediate parent; no outbound WebSocket update observed after send."
        correction = "Streamlit component protocol / frontend SCV → backend update"
    elif scv_prod_match and ws_out_after and not post_begins:
        code = "LIFECYCLE4"
        rationale = "Outbound WebSocket after send; no post-send server script_begin in durable peak audit."
        correction = "Frontend-to-backend update transport / rerun trigger"
    elif post_begins and not decl_after:
        code = "LIFECYCLE5"
        rationale = "Post-send server script_begin captured; no declaration_returned after send."
        correction = "Post-send page routing / declaration eligibility"
    elif decl_after and not decl_nonempty:
        code = "LIFECYCLE6"
        rationale = "Post-send declaration occurred but return values empty."
        correction = "Component identity/key or return-value lifecycle"
    elif (
        scv_prod_match
        and parent_receipt_ts
        and (iframe_disconnect_ts or streamlit_render_ts)
        and first_ws_out_ts
        and parent_receipt_ts < (iframe_disconnect_ts or streamlit_render_ts or 0) < first_ws_out_ts
    ):
        code = "LIFECYCLE7"
        rationale = "Iframe replacement/render after parent receipt but before first outbound WebSocket."
        correction = "Frontend acceptance window vs component remount timing"

    labels = {
        "LIFECYCLE1": "LIFECYCLE1 — IFRAME_REMOVED_BEFORE_IMMEDIATE_PARENT_RECEIPT",
        "LIFECYCLE2": "LIFECYCLE2 — IMMEDIATE_PARENT_SOURCE_MISMATCH",
        "LIFECYCLE3": "LIFECYCLE3 — PARENT_RECEIVES_BUT_STREAMLIT_PROTOCOL_REJECTS",
        "LIFECYCLE4": "LIFECYCLE4 — FRONTEND_SENDS_UPDATE_BUT_BACKEND_RERUN_DOES_NOT_START",
        "LIFECYCLE5": "LIFECYCLE5 — BACKEND_RERUN_STARTS_BUT_COMPONENT_NOT_REDECLARED",
        "LIFECYCLE6": "LIFECYCLE6 — COMPONENT_REDECLARED_BUT_RETURN_VALUE_EMPTY",
        "LIFECYCLE7": "LIFECYCLE7 — IFRAME_REPLACED_DURING_FRONTEND_ACCEPTANCE_WINDOW",
        "LIFECYCLE8": "LIFECYCLE8 — BACKEND RERUN OCCURRED BUT DURABLE AUDIT MISSED IT",
        "LIFECYCLE9": "LIFECYCLE9 — OTHER",
    }

    return {
        "code": code,
        "label": labels.get(code, code),
        "rationale": rationale,
        "smallest_correction_boundary": correction,
        "provisional_boundary": "PRODUCTION_POSTMESSAGE_EMITTED_BUT_NO_BACKEND_RERUN_OBSERVED",
        "absence_note": absence_note,
        "facts": {
            "send_epoch": send_epoch,
            "sending_iframe_instance_id": sending_inst,
            "parent_receipt_ts": parent_receipt_ts,
            "parent_scv_exact_count": len(scv_exact),
            "parent_scv_production_source_count": len(scv_prod_match),
            "iframe_disconnect_or_render_ts": iframe_disconnect_ts or streamlit_render_ts,
            "first_ws_outbound_ts": first_ws_out_ts,
            "first_ws_inbound_ts": first_ws_in_ts,
            "post_send_script_begin_count": len(post_begins),
            "declaration_nonempty": decl_nonempty,
        },
    }
