"""Immediate-parent SCV + WebSocket boundary instrumentation (harness only)."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any

PRODUCTION_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
PRODUCTION_COMPONENT_NAME = "solo_countdown_wake"

P8_WS_BOUNDARY_INIT_SCRIPT = """
(function () {
  if (window.__p8WsBoundaryHookInstalled) return;
  window.__p8WsBoundaryHookInstalled = true;
  window.__p8WsBoundaryLog = [];
  var LOG = window.__p8WsBoundaryLog;
  var Orig = WebSocket;
  function sha256HexAsync(bytes, cb) {
    try {
      if (!crypto || !crypto.subtle) {
        cb("");
        return;
      }
      crypto.subtle.digest("SHA-256", bytes).then(function (buf) {
        var arr = Array.from(new Uint8Array(buf));
        cb(arr.map(function (b) { return ("0" + b.toString(16)).slice(-2); }).join("").slice(0, 64));
      }).catch(function () { cb(""); });
    } catch (e) {
      cb("");
    }
  }
  function toBytes(data) {
    if (data == null) return new Uint8Array(0);
    if (typeof data === "string") return new TextEncoder().encode(data);
    if (data instanceof ArrayBuffer) return new Uint8Array(data);
    if (ArrayBuffer.isView(data)) return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    return new TextEncoder().encode(String(data));
  }
  function searchMeta(bytes, meta) {
    meta = meta || window.__p8WsCorrelationMeta || {};
    var token = String(meta.expected_token || "");
    var widget = String(meta.widget_key || "solo_countdown_wake_solo_persistent");
    var comp = String(meta.component_name || "solo_countdown_wake");
    function has(sub) {
      if (!sub) return false;
      var enc = new TextEncoder().encode(sub);
      if (enc.length === 0 || bytes.length < enc.length) return false;
      outer: for (var i = 0; i <= bytes.length - enc.length; i++) {
        for (var j = 0; j < enc.length; j++) {
          if (bytes[i + j] !== enc[j]) continue outer;
        }
        return true;
      }
      return false;
    }
    return {
      expiration_token_bytes_present: has(token),
      widget_key_bytes_present: has(widget),
      component_name_bytes_present: has(comp),
    };
  }
  function frameCategory(bytes) {
    var s = "";
    try {
      s = new TextDecoder("utf-8", { fatal: false }).decode(bytes.slice(0, Math.min(bytes.length, 8192)));
    } catch (e1) {}
    var low = s.toLowerCase();
    if (low.indexOf("rerun") >= 0) return "rerun_request_hint";
    if (low.indexOf("widget") >= 0 || low.indexOf("backmsg") >= 0) return "widget_state_backmsg_hint";
    if (low.indexOf("component") >= 0 || low.indexOf("setcomponent") >= 0) return "component_value_hint";
    if (low.indexOf("session") >= 0 || low.indexOf("delt") >= 0) return "client_state_hint";
    if (bytes.length <= 4) return "heartbeat_or_control";
    return "streamlit_binary_or_other";
  }
  function record(direction, data, wsMeta) {
    var bytes = toBytes(data);
    var wall = Date.now();
    var meta = searchMeta(bytes, window.__p8WsCorrelationMeta);
    var entry = {
      wall_ts_ms: wall,
      direction: direction,
      byte_len: bytes.length,
      frame_type_hint: frameCategory(bytes),
      expiration_token_bytes_present: meta.expiration_token_bytes_present,
      widget_key_bytes_present: meta.widget_key_bytes_present,
      component_name_bytes_present: meta.component_name_bytes_present,
      ws_url_redacted: wsMeta && wsMeta.url ? wsMeta.url : "",
      diagnostic_run_id: String((window.__p8WsCorrelationMeta || {}).diagnostic_run_id || ""),
      room_id: String((window.__p8WsCorrelationMeta || {}).room_id || ""),
      deployment_sha: String((window.__p8WsCorrelationMeta || {}).deployment_sha || ""),
    };
    sha256HexAsync(bytes, function (hash) {
      entry.sha256 = hash;
      LOG.push(entry);
      if (LOG.length > 600) LOG.splice(0, LOG.length - 500);
    });
  }
  window.WebSocket = function (url, protocols) {
    var ws = protocols !== undefined ? new Orig(url, protocols) : new Orig(url);
    var wsMeta = { url: String(url || "").replace(/([?&])(token|key|sid|secret|auth)=[^&]+/gi, "$1$2=[redacted]") };
    var send0 = ws.send.bind(ws);
    ws.send = function (data) {
      record("outbound", data, wsMeta);
      return send0(data);
    };
    ws.addEventListener("message", function (ev) {
      record("inbound", ev.data, wsMeta);
    });
    return ws;
  };
  window.WebSocket.prototype = Orig.prototype;
  try {
    Object.assign(window.WebSocket, Orig);
  } catch (e2) {}
})();
"""

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
    """Playwright + in-page WebSocket.send hook capture (hashed/redacted; token byte search)."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.sockets: list[dict[str, Any]] = []
        self._context_attached = False
        self._exact_token = ""
        self._widget_key = PRODUCTION_WIDGET_KEY

    def attach_context(self, context) -> None:
        try:
            context.add_init_script(P8_WS_BOUNDARY_INIT_SCRIPT)
            self._context_attached = True
        except Exception:
            pass

    def set_page_correlation_meta(
        self,
        page,
        *,
        expected_token: str,
        widget_key: str = PRODUCTION_WIDGET_KEY,
        diagnostic_run_id: str = "",
        room_id: str = "",
        deployment_sha: str = "",
    ) -> None:
        meta = {
            "expected_token": str(expected_token or ""),
            "widget_key": str(widget_key or PRODUCTION_WIDGET_KEY),
            "component_name": PRODUCTION_COMPONENT_NAME,
            "diagnostic_run_id": str(diagnostic_run_id or ""),
            "room_id": str(room_id or ""),
            "deployment_sha": str(deployment_sha or "")[:7],
        }
        self._exact_token = str(expected_token or "")
        self._widget_key = str(widget_key or PRODUCTION_WIDGET_KEY)
        try:
            page.evaluate(
                """(m) => { window.__p8WsCorrelationMeta = Object.assign(window.__p8WsCorrelationMeta || {}, m); }""",
                meta,
            )
        except Exception:
            pass

    def scrape_browser_log(self, page) -> list[dict[str, Any]]:
        try:
            raw = page.evaluate("() => (window.__p8WsBoundaryLog || []).slice()")
            if isinstance(raw, list):
                out: list[dict[str, Any]] = []
                for row in raw:
                    if not isinstance(row, dict):
                        continue
                    wt_ms = float(row.get("wall_ts_ms") or 0)
                    out.append(
                        {
                            "wall_ts": wt_ms / 1000.0 if wt_ms > 1e12 else wt_ms,
                            "direction": row.get("direction"),
                            "byte_len": row.get("byte_len"),
                            "frame_type_hint": row.get("frame_type_hint"),
                            "sha256": row.get("sha256"),
                            "expiration_token_bytes_present": bool(row.get("expiration_token_bytes_present")),
                            "widget_key_bytes_present": bool(row.get("widget_key_bytes_present")),
                            "component_name_bytes_present": bool(row.get("component_name_bytes_present")),
                            "source": "browser_ws_hook",
                            "diagnostic_run_id": row.get("diagnostic_run_id"),
                            "room_id": row.get("room_id"),
                            "deployment_sha": row.get("deployment_sha"),
                        }
                    )
                return out
        except Exception:
            pass
        return []

    def attach(self, page) -> None:
        def _on_ws(ws):
            sid = f"ws_{len(self.sockets)}"
            self.sockets.append({"id": sid, "url": _redact_ws_url(ws.url), "opened_at": time.time()})

            def _record(direction: str, payload: Any) -> None:
                b = _payload_to_bytes(payload)
                if len(b) > 200000:
                    b = b[:200000]
                meta = _byte_presence_meta(
                    b,
                    exact_token=self._exact_token,
                    widget_key=self._widget_key,
                    window_meta=None,
                )
                text = b.decode("utf-8", errors="ignore")
                lowered = text.lower()
                interesting = (
                    meta["expiration_token_bytes_present"]
                    or meta["widget_key_bytes_present"]
                    or meta["component_name_bytes_present"]
                    or any(
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
                    )
                    or len(b) >= 40
                )
                if not interesting and len(b) < 8:
                    return
                self.frames.append(
                    {
                        "wall_ts": time.time(),
                        "direction": direction,
                        "ws_id": sid,
                        "byte_len": len(b),
                        "frame_type_hint": _frame_type_hint_bytes(b, text),
                        "sha256_prefix": hashlib.sha256(b).hexdigest()[:16],
                        "sha256": hashlib.sha256(b).hexdigest(),
                        "expiration_token_bytes_present": meta["expiration_token_bytes_present"],
                        "widget_key_bytes_present": meta["widget_key_bytes_present"],
                        "component_name_bytes_present": meta["component_name_bytes_present"],
                        "source": "playwright_ws",
                        "snippet_safe": _redact_snippet(text[:280]),
                    }
                )
                if len(self.frames) > 500:
                    self.frames = self.frames[-400:]

            ws.on("framesent", lambda p: _record("outbound", p))
            ws.on("framereceived", lambda p: _record("inbound", p))

        page.on("websocket", _on_ws)

    def merged_frames(self, page) -> list[dict[str, Any]]:
        browser = self.scrape_browser_log(page)
        merged = list(self.frames) + browser
        merged.sort(key=lambda r: float(r.get("wall_ts") or 0))
        dedup: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for row in merged:
            key = (
                round(float(row.get("wall_ts") or 0), 3),
                row.get("direction"),
                row.get("byte_len"),
                row.get("sha256") or row.get("sha256_prefix"),
            )
            if key in seen:
                continue
            seen.add(key)
            dedup.append(row)
        return dedup


def _payload_to_bytes(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8", errors="surrogateescape")
    if isinstance(payload, (bytearray, memoryview)):
        return bytes(payload)
    return str(payload).encode("utf-8", errors="ignore")


def _byte_presence_meta(
    data: bytes,
    *,
    exact_token: str = "",
    widget_key: str = PRODUCTION_WIDGET_KEY,
    window_meta: dict[str, Any] | None,
) -> dict[str, bool]:
    tok = str(exact_token or (window_meta or {}).get("expected_token") or "")
    wkey = str(widget_key or PRODUCTION_WIDGET_KEY)
    comp = PRODUCTION_COMPONENT_NAME
    return {
        "expiration_token_bytes_present": bool(tok) and tok.encode("utf-8") in data,
        "widget_key_bytes_present": wkey.encode("utf-8") in data,
        "component_name_bytes_present": comp.encode("utf-8") in data,
    }


def _frame_type_hint_bytes(data: bytes, text: str) -> str:
    low = (text or "").lower()
    if "rerun" in low:
        return "rerun_request_hint"
    if "widget" in low or "backmsg" in low:
        return "widget_state_backmsg_hint"
    if "setcomponent" in text or "component" in low:
        return "component_value_hint"
    if "session" in low or "delta" in low:
        return "client_state_hint"
    if len(data) <= 4:
        return "heartbeat_or_control"
    return "streamlit_binary_or_other"


def correlate_websocket_boundary(
    frames: list[dict[str, Any]],
    *,
    send_epoch: float,
    parent_receipt_epoch: float | None,
    exact_token: str,
    widget_key: str = PRODUCTION_WIDGET_KEY,
    diagnostic_run_id: str = "",
    room_id: str = "",
    deployment_sha: str = "",
) -> dict[str, Any]:
    """Correlate outbound/inbound WS frames to immediate-parent SCV receipt."""
    anchor = parent_receipt_epoch if parent_receipt_epoch and parent_receipt_epoch > 1e9 else send_epoch
    outbound_window = [
        f
        for f in frames
        if f.get("direction") == "outbound"
        and anchor - 0.05 <= float(f.get("wall_ts") or 0) <= anchor + 2.0
    ]
    outbound_window.sort(key=lambda x: float(x.get("wall_ts") or 0))

    def _is_widget_update(f: dict[str, Any]) -> bool:
        return bool(
            f.get("expiration_token_bytes_present")
            or f.get("widget_key_bytes_present")
            or f.get("frame_type_hint") in ("widget_state_backmsg_hint", "component_value_hint")
        )

    first_out = outbound_window[0] if outbound_window else None
    correlated_out = next(
        (
            f
            for f in outbound_window
            if f.get("expiration_token_bytes_present") or f.get("widget_key_bytes_present")
        ),
        None,
    )
    pick_out = correlated_out or first_out
    out_ts = float(pick_out.get("wall_ts") or 0) if pick_out else None

    inbound_window: list[dict[str, Any]] = []
    if out_ts:
        inbound_window = [
            f
            for f in frames
            if f.get("direction") == "inbound"
            and out_ts - 0.02 <= float(f.get("wall_ts") or 0) <= out_ts + 3.0
        ]
        inbound_window.sort(key=lambda x: float(x.get("wall_ts") or 0))
    first_in = inbound_window[0] if inbound_window else None

    def _latency(from_ts: float | None, to_ts: float | None) -> float | None:
        if from_ts is None or to_ts is None:
            return None
        return round(to_ts - from_ts, 4)

    first_out_after_parent = next(
        (f for f in outbound_window if float(f.get("wall_ts") or 0) >= anchor - 0.001),
        None,
    )
    answers = {
        "first_outbound_after_parent_contains_expiration_token": bool(
            first_out_after_parent and first_out_after_parent.get("expiration_token_bytes_present")
        ),
        "first_outbound_after_parent_contains_widget_key": bool(
            first_out_after_parent and first_out_after_parent.get("widget_key_bytes_present")
        ),
        "first_outbound_after_parent_is_widget_update": bool(
            first_out_after_parent and _is_widget_update(first_out_after_parent)
        ),
        "first_outbound_after_parent_category": (
            first_out_after_parent.get("frame_type_hint") if first_out_after_parent else None
        ),
    }
    inbound_232_candidate = None
    if out_ts:
        for f in inbound_window:
            rel = float(f.get("wall_ts") or 0) - send_epoch
            if 0.15 <= rel <= 0.35:
                inbound_232_candidate = f
                break

    return {
        "anchor_epoch": anchor,
        "diagnostic_run_id": diagnostic_run_id,
        "room_id": room_id,
        "deployment_sha": deployment_sha,
        "outbound_within_2s_of_parent": outbound_window,
        "correlated_outbound": pick_out,
        "first_outbound_after_parent": first_out_after_parent,
        "inbound_within_3s_of_outbound": inbound_window,
        "correlated_inbound_first": first_in,
        "inbound_near_232ms_after_send": inbound_232_candidate,
        "parent_to_first_outbound_latency_s": _latency(anchor, out_ts),
        "send_to_first_outbound_latency_s": _latency(send_epoch, out_ts),
        "outbound_to_first_inbound_latency_s": _latency(out_ts, float(first_in.get("wall_ts") or 0) if first_in else None),
        "explicit_answers": answers,
    }


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
        ev = str(row.get("event") or "")
        ts = float(row.get("ts") or 0)
        if ts < send_epoch - 0.05:
            continue
        if ev == "production_stage1_script_begin":
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
                    "session_state_widget_value": row.get("session_state_value")
                    or row.get("pending_session_state_value")
                    or row.get("session_state_widget_value"),
                    "active_page": row.get("active_page"),
                    "deployment_sha": deployment_sha,
                    "declaration_eligibility_hint": row.get("actionable_mount_eligible"),
                }
            )
        elif ev in (
            "production_global_script_run_canary",
            "production_live_draft_branch_canary",
            "production_countdown_declaration_pre",
            "production_countdown_declaration_post",
        ):
            out.append(
                {
                    "event": ev,
                    "source": "harness_peak_ledger",
                    "server_ts": ts,
                    **{k: v for k, v in row.items() if k not in ("event", "ts")},
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
        for entry in reversed(out):
            if entry.get("event") == "production_stage1_script_begin_durable":
                entry["direct_component_return"] = row.get("direct_component_return")
                entry["session_state_value"] = row.get("session_state_value")
                entry["coalesced_value"] = row.get("coalesced_value")
                entry["declaration_returned_ts"] = ts
                break
    return out


def build_unified_timeline(
    *,
    send_epoch: float,
    send_boundary: dict[str, Any],
    iframe_entries: list[dict[str, Any]],
    immediate_records: list[dict[str, Any]],
    ws_frames: list[dict[str, Any]],
    post_send_server: list[dict[str, Any]],
    ws_correlation: dict[str, Any] | None = None,
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

    if ws_correlation:
        co = ws_correlation.get("correlated_outbound")
        if isinstance(co, dict):
            co_extra = {k: v for k, v in co.items() if k != "source"}
            add(
                round(float(co.get("wall_ts") or send_epoch) - send_epoch, 3),
                "websocket_correlated_outbound",
                "ws_correlation",
                **co_extra,
            )
        ci = ws_correlation.get("correlated_inbound_first")
        if isinstance(ci, dict):
            ci_extra = {k: v for k, v in ci.items() if k != "source"}
            add(
                round(float(ci.get("wall_ts") or send_epoch) - send_epoch, 3),
                "websocket_correlated_inbound",
                "ws_correlation",
                **ci_extra,
            )

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
        wf_extra = {k: v for k, v in wf.items() if k != "source"}
        add(round(wt - send_epoch, 3), f"websocket_{wf.get('direction')}", "playwright_ws", **wf_extra)

    for row in post_send_server:
        ts = float(row.get("server_ts") or 0)
        kind = str(row.get("event") or "production_stage1_script_begin_durable")
        row_extra = {k: v for k, v in row.items() if k not in ("event", "source")}
        add(round(ts - send_epoch, 3), kind, "server_audit", **row_extra)

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
    ws_correlation: dict[str, Any] | None = None,
    page: Any | None = None,
) -> dict[str, Any]:
    from p8_sender_rerun_trace import normalize_epoch_ts

    records = list(immediate_log.get("records") or [])
    scv_exact = [
        r
        for r in records
        if r.get("message_type") == "streamlit:setComponentValue"
        and exact_token in str(r.get("exact_payload_preview") or "")
    ]
    scv_prod_match = [r for r in scv_exact if r.get("source_matches_production_iframe")]

    parent_receipt_ts: float | None = None
    if scv_prod_match:
        wt_ms = float(scv_prod_match[0].get("receipt_wall_ts") or 0)
        parent_receipt_ts = wt_ms / 1000.0 if wt_ms > 1e12 else wt_ms

    merged_ws = ws_capture.merged_frames(page) if page is not None else list(ws_capture.frames)
    if ws_correlation is None:
        ws_correlation = correlate_websocket_boundary(
            merged_ws,
            send_epoch=send_epoch,
            parent_receipt_epoch=parent_receipt_ts,
            exact_token=exact_token,
        )

    correlated_out = ws_correlation.get("correlated_outbound")
    outbound_has_token = bool(
        correlated_out
        and (
            correlated_out.get("expiration_token_bytes_present")
            or correlated_out.get("widget_key_bytes_present")
        )
    )
    answers = ws_correlation.get("explicit_answers") or {}

    def _post_rows(event: str) -> list[dict[str, Any]]:
        return [
            r
            for r in peak_rows
            if str(r.get("event") or "") == event and float(r.get("ts") or 0) >= send_epoch - 0.05
        ]

    global_canaries = _post_rows("production_global_script_run_canary")
    branch_canaries = _post_rows("production_live_draft_branch_canary")
    decl_pre = _post_rows("production_countdown_declaration_pre")
    decl_post = _post_rows("production_countdown_declaration_post")
    post_begins = [
        r
        for r in post_send_server
        if r.get("event") == "production_stage1_script_begin_durable"
        or (
            str(r.get("event") or "") == "production_global_script_run_canary"
            and float(r.get("server_ts") or 0) >= send_epoch - 0.05
        )
    ]
    legacy_begins = _post_rows("production_stage1_script_begin")

    decl_after = _post_rows("production_stage1_declaration_returned")
    decl_post_rows = decl_post or decl_after
    decl_nonempty = any(
        str(r.get("direct_return_value") or r.get("coalesced_value") or "").strip() not in ("", "None", "''")
        or (
            str(r.get("same_key_session_state_value") or r.get("session_state_value") or "").strip()
            not in ("", "missing", "''")
            and exact_token in str(r.get("same_key_session_state_value") or r.get("session_state_value") or "")
        )
        for r in decl_post_rows
    )

    ws_out_after = [f for f in merged_ws if float(f.get("wall_ts") or 0) >= send_epoch - 0.02 and f.get("direction") == "outbound"]
    ws_in_after = [f for f in merged_ws if float(f.get("wall_ts") or 0) >= send_epoch - 0.02 and f.get("direction") == "inbound"]
    first_ws_out_ts = min((float(f["wall_ts"]) for f in ws_out_after), default=None)
    first_ws_in_ts = min((float(f["wall_ts"]) for f in ws_in_after), default=None)

    streamlit_render_ts: float | None = None
    for e in iframe_entries:
        ts = normalize_epoch_ts(e.get("ts"))
        if ts is None or ts < send_epoch - 0.05:
            continue
        stage = str(e.get("stage") or "")
        extra = str(e.get("extra") or "")
        if stage == "tick_cancelled" and "streamlit_render" in extra:
            streamlit_render_ts = ts

    code = "LIFECYCLE9"
    rationale = "Boundary trace incomplete or ambiguous."
    correction = "TBD after boundary pin"
    first_missing = "unknown"

    has_parent_scv = bool(scv_prod_match or scv_exact)

    if not has_parent_scv:
        code = "LIFECYCLE9"
        rationale = "Expected immediate-parent exact SCV not present in retained trace window."
        correction = "Immediate-parent listener / send detection alignment"
        first_missing = "immediate_parent_scv"
    elif not outbound_has_token and not any(
        f.get("expiration_token_bytes_present") or f.get("widget_key_bytes_present") for f in ws_out_after
    ):
        code = "LIFECYCLE3"
        rationale = "Immediate parent received exact SCV; no outbound WebSocket frame contained expiration token or widget key."
        correction = "Streamlit parent SCV to outbound widget-state/back-message encoding"
        first_missing = "outbound_ws_widget_update"
    elif not global_canaries:
        code = "LIFECYCLE4"
        rationale = (
            "Correlated outbound WebSocket carried production token/widget bytes; "
            "no production_global_script_run_canary after send."
        )
        correction = "Frontend widget update to backend script execution trigger"
        first_missing = "global_backend_script_run"
    elif not branch_canaries:
        code = "LIFECYCLE5"
        rationale = "Global backend script canary fired after send; Live Draft branch canary absent."
        correction = "Page routing / active_page to Live Draft Room branch entry"
        first_missing = "live_draft_branch_canary"
    elif not decl_pre:
        code = "LIFECYCLE6"
        rationale = "Global and Live Draft branch canaries present; countdown declaration pre absent."
        correction = "Live Draft branch to production countdown declaration path"
        first_missing = "countdown_declaration_pre"
    elif not decl_nonempty:
        code = "LIFECYCLE7"
        rationale = "Countdown declaration pre/post observed; direct return and Session State remain empty."
        correction = "Component declaration to return value / Session State bind"
        first_missing = "non_empty_component_return"
    elif global_canaries and not legacy_begins:
        code = "LIFECYCLE8"
        rationale = "Post-send global canary retained; legacy production_stage1_script_begin audit line absent."
        correction = "Durable audit retention / event mirror (not bind transport)"
        first_missing = "legacy_script_begin_retention"
    else:
        code = "LIFECYCLE9"
        rationale = "All major transitions observed in trace; no single missing boundary under LIFECYCLE3–8 rules."
        correction = "None for this pass (investigation complete or needs finer-grained bucket)"
        first_missing = "none_under_rules"

    labels = {
        "LIFECYCLE3": "LIFECYCLE3 — PARENT_RECEIVES BUT FRONTEND DOES NOT SEND WIDGET UPDATE",
        "LIFECYCLE4": "LIFECYCLE4 — FRONTEND SENDS EXACT UPDATE BUT BACKEND SCRIPT DOES NOT RUN",
        "LIFECYCLE5": "LIFECYCLE5 — BACKEND RUNS BUT LIVE DRAFT BRANCH IS NOT ENTERED",
        "LIFECYCLE6": "LIFECYCLE6 — LIVE DRAFT BRANCH RUNS BUT COMPONENT IS NOT REDECLARED",
        "LIFECYCLE7": "LIFECYCLE7 — COMPONENT REDECLARED BUT RETURN VALUE REMAINS EMPTY",
        "LIFECYCLE8": "LIFECYCLE8 — BACKEND RERUN OCCURRED BUT PRIOR DURABLE AUDIT MISSED IT",
        "LIFECYCLE9": "LIFECYCLE9 — OTHER",
    }

    inbound_232 = ws_correlation.get("inbound_near_232ms_after_send")
    inbound_232_kind = None
    if isinstance(inbound_232, dict):
        inbound_232_kind = inbound_232.get("frame_type_hint")

    return {
        "code": code,
        "label": labels.get(code, code),
        "rationale": rationale,
        "smallest_correction_boundary": correction,
        "first_missing_transition": first_missing,
        "provisional_boundary": "LIFECYCLE4_PROVISIONAL — FRONTEND SEND ACTIVITY PRESENT BUT BACKEND RERUN NOT OBSERVED",
        "ws_correlation": ws_correlation,
        "ws_explicit_answers": answers,
        "inbound_232ms_frame_category": inbound_232_kind,
        "absence_note": None,
        "facts": {
            "send_epoch": send_epoch,
            "parent_receipt_ts": parent_receipt_ts,
            "parent_scv_exact_count": len(scv_exact),
            "parent_scv_production_source_count": len(scv_prod_match),
            "outbound_has_production_token_or_widget": outbound_has_token,
            "first_ws_outbound_ts": first_ws_out_ts,
            "first_ws_inbound_ts": first_ws_in_ts,
            "streamlit_render_ts": streamlit_render_ts,
            "post_send_global_canary_count": len(global_canaries),
            "post_send_branch_canary_count": len(branch_canaries),
            "post_send_declaration_pre_count": len(decl_pre),
            "post_send_declaration_post_count": len(decl_post),
            "post_send_script_begin_count": len(legacy_begins),
            "declaration_nonempty": decl_nonempty,
        },
    }
