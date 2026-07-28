"""Early top-level MessageEvent observer for Stage 1A delivery diagnostics (no delivery owners)."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

OBSERVER_PROBE_ID = "solo-stage1-parent-observer"
WIDGET_KEY = "solo_countdown_wake_solo_persistent"
_OBSERVER_JS = r"""
(function(){
  var NS = "__solo_stage1_parent_observer_v2";
  if (window[NS] && window[NS].installed) return;
  window[NS] = { installed: true, seq: 0, registrations: [], messages: [] };
  function perfTs(){ try { return performance.now(); } catch(e){ return Date.now(); } }
  function sanitizeUrl(u){
    try {
      var x = new URL(String(u || location.href));
      if (x.searchParams.has("suite_sid")) x.searchParams.set("suite_sid", "[redacted]");
      return x.origin + x.pathname + (x.search || "");
    } catch(e){
      return String(u||"").replace(/suite_sid=[^&]+/gi, "suite_sid=[redacted]");
    }
  }
  function fp(win){
    if (!win) return "null";
    try { return "win@" + String(win.location && win.location.href ? sanitizeUrl(win.location.href).slice(0,80) : "?"); } catch(e){ return "win@opaque"; }
  }
  function resolveSource(source){
    var iframes = document.querySelectorAll("iframe");
    for (var i = 0; i < iframes.length; i++){
      var el = iframes[i];
      try {
        if (el.contentWindow !== source) continue;
        var instanceId = "", widgetHostId = "", mounted = false, widgetKey = "";
        try {
          var doc = el.contentDocument;
          var solo = doc && doc.getElementById("solo-expire-client");
          if (solo){
            instanceId = String(solo.getAttribute("data-iframe-instance")||"");
            widgetKey = String(solo.getAttribute("data-widget-key")||"");
            widgetHostId = "solo-expire-client";
            mounted = true;
          }
        } catch(e2){}
        return {
          production_iframe_dom_index: i,
          iframe_is_connected: !!el.isConnected,
          iframe_instance_id: instanceId,
          registered_widget_key: widgetKey,
          component_mounted: mounted,
          child_src: sanitizeUrl(el.src||"")
        };
      } catch(e3){}
    }
    return {
      production_iframe_dom_index: -1,
      iframe_is_connected: false,
      iframe_instance_id: "",
      registered_widget_key: "",
      component_mounted: false,
      child_src: ""
    };
  }
  function currentRegistered(){
    var latest = null;
    var regs = window[NS].registrations || [];
    for (var i = regs.length - 1; i >= 0; i--){
      if (regs[i] && regs[i].widget_key === "solo_countdown_wake_solo_persistent") { latest = regs[i]; break; }
    }
    return latest || {};
  }
  function onMsg(ev){
    var d = ev && ev.data;
    var assoc = resolveSource(ev.source);
    var reg = currentRegistered();
    var val = d && d.value;
    var valStr = typeof val === "string" ? val : (val != null ? String(val) : "");
    var mt = d && d.type ? String(d.type) : "";
    var row = {
      observer_seq: ++window[NS].seq,
      perf_ts: perfTs(),
      wall_ts: Date.now(),
      receiving_window: "top_or_embedded_host",
      receiving_window_fingerprint: fp(window),
      immediate_parent_equals_top: (function(){
        try { return window.parent === window.top; } catch(e){ return false; }
      })(),
      event_origin: String((ev && ev.origin) || ""),
      message_type: mt,
      is_streamlit_message: !!(d && d.isStreamlitMessage),
      is_set_component_value: mt === "streamlit:setComponentValue",
      is_frame_height: mt === "streamlit:setFrameHeight",
      is_register_component: mt === "streamlit:registerComponent" || mt.indexOf("rvCountdownRegister") >= 0 || mt === "solo:rvCountdownRegister",
      widget_key: String((d && (d.widgetKey || d.widget_key)) || assoc.registered_widget_key || ""),
      component_id: String((d && (d.id || d.componentId)) || ""),
      token_or_value_preview: valStr.slice(0, 200),
      browser_send_event_id: String((d && d.eventId) || ""),
      iframe_instance_id: assoc.iframe_instance_id,
      registered_iframe_instance_id: String(reg.instance_id || ""),
      source_matches_current_production_iframe: !!(reg.instance_id && assoc.iframe_instance_id && reg.instance_id === assoc.iframe_instance_id),
      source_window_connected: assoc.iframe_is_connected,
      iframe_association: assoc
    };
    window[NS].messages.push(row);
    if (window[NS].messages.length > 400) window[NS].messages = window[NS].messages.slice(-320);
    try {
      var el = document.getElementById("solo-stage1-parent-observer-export");
      if (el) {
        var payload = JSON.stringify({ registrations: window[NS].registrations, messages: window[NS].messages });
        el.setAttribute("data-json", payload.slice(0, 240000));
      }
    } catch(e4){}
  }
  window.addEventListener("message", onMsg, true);
  var regHandler = function(ev){
    var d = ev && ev.data;
    if (!d || typeof d !== "object") return;
    var t = String(d.type||"");
    if (t !== "solo:rvCountdownRegister" && t !== "streamlit:registerComponent") return;
    var assoc = resolveSource(ev.source);
    window[NS].registrations.push({
      ts: Date.now(),
      perf_ts: perfTs(),
      widget_key: String(d.widget_key || d.widgetKey || ""),
      instance_id: String(d.instance_id || d.instanceId || assoc.iframe_instance_id || ""),
      expected_token: String(d.expected_token || d.expectedToken || "").slice(0, 200),
      production_iframe_dom_index: assoc.production_iframe_dom_index
    });
  };
  window.addEventListener("message", regHandler, true);
})();
"""


def render_stage1_early_parent_observer(st: Any, session: dict[str, Any]) -> None:
    """Install before production countdown iframes on LDR (diagnostic only)."""
    if not stage1_production_ledger_enabled(st, session):
        return
    import streamlit.components.v1 as components

    components.html(
        f"""<!DOCTYPE html><html><body>
        <div id="solo-stage1-parent-observer-export" data-json=""></div>
        <script>{_OBSERVER_JS}</script>
        </body></html>""",
        height=0,
    )


def merge_observer_export_into_session(session: dict[str, Any], export: dict[str, Any]) -> None:
    """Persist latest browser observer snapshot into session for cross-rerun merge."""
    if not export:
        return
    prev = dict(session.get("_solo_stage1_parent_observer_export") or {})
    prev_msgs = list(prev.get("messages") or [])
    new_msgs = list(export.get("messages") or [])
    seen = {int(m.get("observer_seq") or 0) for m in prev_msgs if isinstance(m, dict)}
    merged = prev_msgs[:]
    for m in new_msgs:
        if not isinstance(m, dict):
            continue
        seq = int(m.get("observer_seq") or 0)
        if seq and seq in seen:
            continue
        if seq:
            seen.add(seq)
        merged.append(m)
    prev_regs = list(prev.get("registrations") or [])
    new_regs = list(export.get("registrations") or [])
    session["_solo_stage1_parent_observer_export"] = {
        "registrations": (prev_regs + new_regs)[-80:],
        "messages": merged[-400:],
        "merged_at": time.time(),
    }
