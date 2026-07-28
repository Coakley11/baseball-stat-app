"""Stage 1A parent-boundary validation: frame-2 Playwright listener + observer context."""

from __future__ import annotations

import json
import time
from typing import Any

from stage1_frame_transport_probe import PRODUCTION_WIDGET_KEY, _FRAME_FLAGS_JS, sanitize_url

FRAME2_MSG_KEY = "__soloStage1ImmediateParentMessages"
FRAME2_META_KEY = "__soloStage1Frame2ObserverMeta"

FRAME2_INSTALL_LISTENER_JS = """
() => {
  const MSG_KEY = "__soloStage1ImmediateParentMessages";
  const META_KEY = "__soloStage1Frame2ObserverMeta";
  if (!window[MSG_KEY]) window[MSG_KEY] = [];
  function sanitizeUrl(u) {
    try {
      const x = new URL(String(u || location.href));
      if (x.searchParams.has("suite_sid")) x.searchParams.set("suite_sid", "[redacted]");
      return x.origin + x.pathname + (x.search || "");
    } catch (e) {
      return String(u || "").replace(/suite_sid=[^&]+/gi, "suite_sid=[redacted]");
    }
  }
  function resolveSource(source) {
    const iframes = document.querySelectorAll("iframe");
    for (let i = 0; i < iframes.length; i++) {
      const el = iframes[i];
      try {
        if (el.contentWindow !== source) continue;
        let instanceId = "";
        try {
          const doc = el.contentDocument;
          const solo = doc && doc.getElementById("solo-expire-client");
          if (solo) instanceId = String(solo.getAttribute("data-iframe-instance") || "");
        } catch (e2) {}
        return {
          iframe_dom_index: i,
          iframe_is_connected: !!el.isConnected,
          iframe_instance_id: instanceId,
          child_src: sanitizeUrl(el.src || ""),
        };
      } catch (e3) {}
    }
    return { iframe_dom_index: -1, iframe_is_connected: false, iframe_instance_id: "", child_src: "" };
  }
  function introspect() {
    let parentUrl = "";
    try { parentUrl = sanitizeUrl(window.parent.location.href); } catch (e) { parentUrl = "opaque"; }
    return {
      observer_id: "playwright_frame2_injected",
      frame_url: sanitizeUrl(location.href),
      window_name: String(window.name || ""),
      is_top: window === window.top,
      is_parent_self: window.parent === window,
      parent_frame_url: parentUrl,
      child_frame_count: window.frames ? window.frames.length : 0,
      document_url: sanitizeUrl(document.URL || location.href),
      navigation_id: String(document.URL || "") + "@" + String(document.readyState || ""),
    };
  }
  if (window.__soloStage1Frame2ListenerInstalled) {
    const meta = window[META_KEY] || {};
    meta.reinstall_count = (meta.reinstall_count || 0) + 1;
    meta.last_reinstall_at = Date.now();
    window[META_KEY] = meta;
    return { already: true, message_count: window[MSG_KEY].length, meta: introspect() };
  }
  window.__soloStage1Frame2ListenerInstalled = true;
  const installedAt = Date.now();
  function onMsg(ev) {
    const d = ev && ev.data;
    if (!d || typeof d !== "object") return;
    const mt = String(d.type || "");
    const val = d.value != null ? String(d.value) : "";
    const assoc = resolveSource(ev.source);
    const row = {
      seq: window[MSG_KEY].length + 1,
      perf_ts: (typeof performance !== "undefined" ? performance.now() : Date.now()),
      wall_ts: Date.now(),
      receiving_window_level: "FRAME2_PLAYWRIGHT_INJECTED",
      event_origin: String((ev && ev.origin) || ""),
      message_type: mt,
      is_parent_probe: mt === "solo:stage1ImmediateParentProbe",
      is_set_component_value: mt === "streamlit:setComponentValue",
      value_preview: val.slice(0, 220),
      expected_token_probe: String(d.expected_token || "").slice(0, 220),
      browser_send_event_id: String(d.browser_send_event_id || ""),
      widget_key: String(d.widget_key || ""),
      iframe_instance_id: String(d.iframe_instance_id || d.iframe_instance || assoc.iframe_instance_id || ""),
      source_association: assoc,
      event_source_connected: assoc.iframe_is_connected,
      payload_json: JSON.stringify(d).slice(0, 1200),
    };
    window[MSG_KEY].push(row);
    if (window[MSG_KEY].length > 400) window[MSG_KEY] = window[MSG_KEY].slice(-320);
  }
  window.addEventListener("message", onMsg, true);
  window[META_KEY] = Object.assign(introspect(), {
    installed_at: installedAt,
    observer_ready_at: Date.now(),
    reinstall_count: 0,
  });
  return { installed: true, meta: window[META_KEY] };
}
"""

_OBSERVER_CONTEXT_JS = """
(observerId) => {
  function sanitizeUrl(u) {
    try {
      const x = new URL(String(u || location.href));
      if (x.searchParams.has("suite_sid")) x.searchParams.set("suite_sid", "[redacted]");
      return x.origin + x.pathname + (x.search || "");
    } catch (e) {
      return String(u || "").replace(/suite_sid=[^&]+/gi, "suite_sid=[redacted]");
    }
  }
  let parentUrl = "opaque";
  try { parentUrl = sanitizeUrl(window.parent.location.href); } catch (e) {}
  const flags = {
    has_ldr_ui: false,
    has_production_countdown: false,
    has_stage1_app_observer: !!document.getElementById("solo-stage1-parent-observer-export"),
    has_stage1_ledger_probe: !!document.getElementById("solo-stage1-production-ledger"),
  };
  try {
    const t = (document.body && document.body.innerText) || "";
    flags.has_ldr_ui = /Pause Draft|Live Draft Room|ccTimer/i.test(t.slice(0, 60000));
  } catch (e) {}
  flags.has_production_countdown = !!document.getElementById("solo-expire-client");
  return {
    observer_id: String(observerId || "unknown"),
    frame_url: sanitizeUrl(location.href),
    window_name: String(window.name || ""),
    window_is_top: window === window.top,
    window_parent_is_self: window.parent === window,
    parent_frame_url: parentUrl,
    child_frame_count: window.frames ? window.frames.length : 0,
    flags: flags,
    is_probable_ldr_host_frame: flags.has_ldr_ui && !flags.has_production_countdown,
    harness_top_log_len: (window.__solo_stage1_harness_top_observer_v1 && window.__solo_stage1_harness_top_observer_v1.messages)
      ? window.__solo_stage1_harness_top_observer_v1.messages.length : 0,
    recorded_at: Date.now(),
  };
}
"""


def find_ldr_host_frame(page) -> tuple[Any | None, int | None]:
    """Streamlit LDR host (frame 2): has LDR UI, not the component iframe document."""
    best = None
    best_idx: int | None = None
    for i, fr in enumerate(page.frames):
        try:
            flags = fr.evaluate(_FRAME_FLAGS_JS)
        except Exception:
            continue
        if not isinstance(flags, dict):
            continue
        if flags.get("has_production_countdown") or flags.get("has_minimal_control"):
            continue
        if not flags.get("has_ldr_ui"):
            continue
        url = sanitize_url(fr.url)
        if "/~/" in url or "active_page=Live" in url.replace("+", " "):
            best = fr
            best_idx = i
    return best, best_idx


def find_production_countdown_frame(page) -> tuple[Any | None, int | None]:
    for i, fr in enumerate(page.frames):
        try:
            flags = fr.evaluate(_FRAME_FLAGS_JS)
        except Exception:
            continue
        if isinstance(flags, dict) and flags.get("has_production_countdown"):
            return fr, i
    return None, None


def install_frame2_parent_listener(page) -> dict[str, Any]:
    host, idx = find_ldr_host_frame(page)
    if host is None:
        return {"ok": False, "error": "ldr_host_frame_not_found"}
    try:
        res = host.evaluate(FRAME2_INSTALL_LISTENER_JS)
        return {
            "ok": True,
            "frame_index": idx,
            "frame_url": sanitize_url(host.url),
            "result": res,
        }
    except Exception as exc:
        return {"ok": False, "frame_index": idx, "error": type(exc).__name__}


def scrape_frame2_parent_messages(page) -> dict[str, Any]:
    host, idx = find_ldr_host_frame(page)
    if host is None:
        return {"messages": [], "meta": {}, "frame_index": None}
    try:
        raw = host.evaluate(
            f"""() => ({{
              messages: window.{FRAME2_MSG_KEY} || [],
              meta: window.{FRAME2_META_KEY} || {{}},
              navigation: {{ url: document.URL, readyState: document.readyState }},
            }})"""
        )
        if isinstance(raw, dict):
            raw["frame_index"] = idx
            raw["frame_url"] = sanitize_url(host.url)
            return raw
    except Exception as exc:
        return {"messages": [], "meta": {}, "error": type(exc).__name__, "frame_index": idx}
    return {"messages": [], "meta": {}, "frame_index": idx}


def collect_observer_execution_contexts(page) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    prod_fr, prod_idx = find_production_countdown_frame(page)
    host_fr, host_idx = find_ldr_host_frame(page)
    for i, fr in enumerate(page.frames):
        for obs_id in (
            "streamlit_frame_scan",
            "app_early_parent_observer",
            "harness_top_init",
        ):
            if obs_id == "app_early_parent_observer" and not (
                i == 0 or (host_idx is not None and i == host_idx)
            ):
                continue
            try:
                ctx = fr.evaluate(_OBSERVER_CONTEXT_JS, obs_id)
                if isinstance(ctx, dict):
                    ctx["playwright_frame_index"] = i
                    ctx["frame_sanitized_url"] = sanitize_url(fr.url)
                    if prod_fr and host_fr:
                        try:
                            is_host = fr.url == host_fr.url and i == host_idx
                            ctx["is_ldr_host_frame_index"] = bool(is_host)
                            ctx["proves_frame2_observer"] = (
                                obs_id == "playwright_frame2_injected" and is_host
                            )
                        except Exception:
                            pass
                    contexts.append(ctx)
            except Exception:
                continue
    try:
        if host_fr is not None and host_idx is not None:
            meta = host_fr.evaluate(f"() => window.{FRAME2_META_KEY} || null")
            if meta:
                contexts.append(
                    {
                        "observer_id": "playwright_frame2_injected",
                        "playwright_frame_index": host_idx,
                        "frame_sanitized_url": sanitize_url(host_fr.url),
                        "meta": meta,
                        "is_ldr_host_frame_index": True,
                        "proves_frame2_observer": True,
                    }
                )
    except Exception:
        pass
    if prod_fr is not None and host_fr is not None:
        try:
            rel = prod_fr.evaluate(
                """() => {
                  try {
                    return {
                      parent_equals_top: window.parent === window.top,
                      parent_href: String(window.parent.location.href || '').slice(0, 200),
                    };
                  } catch (e) {
                    return { parent_equals_top: false, parent_href: 'opaque' };
                  }
                }"""
            )
            contexts.append(
                {
                    "observer_id": "production_countdown_iframe_sender",
                    "playwright_frame_index": prod_idx,
                    "sender_parent_relationship": rel,
                }
            )
        except Exception:
            pass
    return contexts


def scrape_stage1_ledger_all_frames(page) -> dict[str, Any]:
    """Find Base64 ledger probe in any frame (not only top)."""
    probe_id = "solo-stage1-production-ledger"
    hits: list[dict[str, Any]] = []
    for i, fr in enumerate(page.frames):
        try:
            row = fr.evaluate(
                f"""() => {{
                  const out = {{ frame_index: {i}, url: location.href, b64: '', rows: 0, run_id: '', window_b64: false }};
                  try {{
                    if (window.__soloStage1LedgerB64) {{
                      out.b64 = window.__soloStage1LedgerB64;
                      out.window_b64 = true;
                    }}
                  }} catch (e) {{}}
                  const el = document.getElementById("{probe_id}");
                  if (el) {{
                    out.probe_found = true;
                    out.b64 = out.b64 || el.getAttribute("data-b64") || "";
                    out.rows = parseInt(el.getAttribute("data-rows") || "0", 10) || 0;
                    out.run_id = el.getAttribute("data-run-id") || "";
                  }}
                  return out;
                }}"""
            )
            if isinstance(row, dict) and (row.get("probe_found") or row.get("window_b64") or row.get("b64")):
                row["sanitized_url"] = sanitize_url(str(row.get("url") or fr.url))
                hits.append(row)
        except Exception:
            continue
    best = {}
    if hits:
        best = max(hits, key=lambda h: int(h.get("rows") or 0))
    return {"hits": hits, "best": best}


def classify_parent_boundary_p(
    *,
    frame2_probe_received: bool,
    frame2_scv_received: bool,
    sender_stale_or_detached: bool,
    observer_in_frame2: bool,
    frame2_listener_lost: bool,
    scv_from_stale_source: bool,
    scv_from_current_source: bool,
    python_bound: bool,
) -> str:
    if not observer_in_frame2 and not frame2_probe_received and not frame2_scv_received:
        return "P1"
    if frame2_listener_lost and not frame2_probe_received and not frame2_scv_received:
        return "P2"
    if sender_stale_or_detached:
        return "P3"
    if frame2_probe_received and frame2_scv_received:
        if scv_from_stale_source:
            return "P7"
        if scv_from_current_source and not python_bound:
            return "P8"
        return "P4"
    if frame2_probe_received and not frame2_scv_received:
        return "P5"
    if not frame2_probe_received and not frame2_scv_received:
        return "P6"
    if scv_from_stale_source:
        return "P7"
    if scv_from_current_source and not python_bound:
        return "P8"
    return "P6"
