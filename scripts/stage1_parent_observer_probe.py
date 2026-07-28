"""Playwright helpers: early top observer + merged Stage 1A server ledger scrape."""

from __future__ import annotations

import base64
import json
from typing import Any

from live_draft_stage1_production_ledger import STAGE1_PROBE_ID

_INSTALL_TOP_OBSERVER_JS = r"""
() => {
  const NS = "__solo_stage1_harness_top_observer_v1";
  if (window[NS] && window[NS].installed) return { already: true };
  window[NS] = { installed: true, seq: 0, messages: [] };
  function onMsg(ev) {
    const d = ev && ev.data;
    const val = d && d.value;
    const valStr = typeof val === "string" ? val : "";
    const mt = d && d.type ? String(d.type) : "";
    let sourceConnected = false;
    try {
      const iframes = document.querySelectorAll("iframe");
      for (let i = 0; i < iframes.length; i++) {
        try {
          if (iframes[i].contentWindow === ev.source) {
            sourceConnected = !!iframes[i].isConnected;
            break;
          }
        } catch (e) {}
      }
    } catch (e2) {}
    window[NS].messages.push({
      observer: "harness_top",
      seq: ++window[NS].seq,
      perf_ts: (typeof performance !== "undefined" ? performance.now() : Date.now()),
      wall_ts: Date.now(),
      receiving_window: "top",
      receiving_window_level: "LEVEL_2_TOP",
      receiving_parent_sanitized_url: String(location.href || "").replace(/suite_sid=[^&]+/gi, "suite_sid=[redacted]"),
      event_origin: String((ev && ev.origin) || ""),
      message_type: mt,
      is_set_component_value: mt === "streamlit:setComponentValue",
      is_frame_height: mt === "streamlit:setFrameHeight",
      is_register_component: mt === "streamlit:registerComponent" || mt === "solo:rvCountdownRegister",
      value_preview: valStr.slice(0, 200),
      browser_send_event_id: String((d && d.browser_send_event_id) || ""),
      widget_key: String((d && d.widget_key) || ""),
      component_id: String((d && (d.id || d.componentId)) || ""),
      event_source_connected: sourceConnected,
    });
    if (window[NS].messages.length > 300) window[NS].messages = window[NS].messages.slice(-240);
  }
  window.addEventListener("message", onMsg, true);
  return { installed: true };
}
"""

HARNESS_TOP_OBSERVER_INIT_SCRIPT = """
(function(){
  const NS = "__solo_stage1_harness_top_observer_v1";
  if (window[NS] && window[NS].installed) return;
  window[NS] = { installed: true, seq: 0, messages: [] };
  function onMsg(ev) {
    const d = ev && ev.data;
    const val = d && d.value;
    const valStr = typeof val === "string" ? val : "";
    const mt = d && d.type ? String(d.type) : "";
    window[NS].messages.push({
      observer: "harness_top_init",
      seq: ++window[NS].seq,
      perf_ts: (typeof performance !== "undefined" ? performance.now() : Date.now()),
      wall_ts: Date.now(),
      receiving_window: "top",
      receiving_window_level: "LEVEL_2_TOP",
      event_origin: String((ev && ev.origin) || ""),
      message_type: mt,
      is_set_component_value: mt === "streamlit:setComponentValue",
      value_preview: valStr.slice(0, 200),
      browser_send_event_id: String((d && d.browser_send_event_id) || ""),
      widget_key: String((d && d.widget_key) || ""),
    });
    if (window[NS].messages.length > 300) window[NS].messages = window[NS].messages.slice(-240);
  }
  window.addEventListener("message", onMsg, true);
})();
"""

_SCrape_TOP_JS = """
() => {
  const out = { harness_top: [], app_observer: null };
  try {
    const h = window.__solo_stage1_harness_top_observer_v1;
    if (h && Array.isArray(h.messages)) out.harness_top = h.messages.slice(-250);
  } catch (e) {}
  try {
    const el = document.getElementById("solo-stage1-parent-observer-export");
    if (el) {
      const raw = el.getAttribute("data-json") || "";
      if (raw) out.app_observer = JSON.parse(raw);
    }
  } catch (e2) {}
  return out;
}
"""

_SCrape_LEDGER_JS = f"""
() => {{
  const out = {{ rows: [], run_id: "", source: "" }};
  try {{
    if (window.__soloStage1LedgerB64) {{
      const raw = atob(window.__soloStage1LedgerB64);
      const p = JSON.parse(raw);
      out.rows = p.rows || [];
      out.run_id = p.run_id || "";
      out.source = "window_b64";
      return out;
    }}
  }} catch (e) {{}}
  try {{
    const el = document.getElementById("{STAGE1_PROBE_ID}");
    if (el) {{
      const b64 = el.getAttribute("data-b64") || "";
      if (b64) {{
        const raw = atob(b64);
        const p = JSON.parse(raw);
        out.rows = p.rows || [];
        out.run_id = p.run_id || el.getAttribute("data-run-id") || "";
        out.source = "probe_b64";
      }}
    }}
  }} catch (e2) {{}}
  return out;
}}
"""


def install_harness_top_observer(page) -> dict[str, Any]:
    try:
        return page.evaluate(_INSTALL_TOP_OBSERVER_JS) or {}
    except Exception as exc:
        return {"error": type(exc).__name__}


def scrape_parent_observer_exports(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(_SCrape_TOP_JS)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def scrape_stage1_production_ledger(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(_SCrape_LEDGER_JS)
        if not isinstance(raw, dict):
            return {"rows": [], "source": "none"}
        return raw
    except Exception:
        return {"rows": [], "source": "error"}


def merge_ledger_rows(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {str(r.get("event_id") or "") for r in existing if isinstance(r, dict)}
    merged = list(existing)
    for row in incoming:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("event_id") or "")
        if eid and eid in seen:
            continue
        if eid:
            seen.add(eid)
        merged.append(row)
    merged.sort(key=lambda r: (float(r.get("ts") or 0), str(r.get("event_id") or "")))
    return merged[-400:]


def decode_ledger_b64(b64: str) -> dict[str, Any]:
    try:
        raw = base64.b64decode(b64.encode("ascii")).decode("utf-8")
        return json.loads(raw)
    except Exception:
        return {}
