"""Playwright frame topology + immediate-parent postMessage listeners (Stage 1A transport)."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

PRODUCTION_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
MINIMAL_WIDGET_KEY = "solo_countdown_wake_transport_minimal"

_FRAME_FLAGS_JS = """
() => {
  function sanitizeUrl(u) {
    try {
      const x = new URL(String(u || location.href));
      if (x.searchParams.has("suite_sid")) x.searchParams.set("suite_sid", "[redacted]");
      return x.origin + x.pathname + (x.search || "");
    } catch (e) {
      return String(u || "").replace(/suite_sid=[^&]+/gi, "suite_sid=[redacted]");
    }
  }
  let hasLdrUi = false;
  try {
    const t = (document.body && document.body.innerText) || "";
    hasLdrUi = /Pause Draft|Live Draft Room|ccTimer|Draft board/i.test(t.slice(0, 80000));
  } catch (e) {}
  const hasProductionCountdown = !!document.getElementById("solo-expire-client");
  const hasMinimalControl = !!document.getElementById("repro-client");
  const hasParentDiagListener = !!document.getElementById("solo-transport-boundary-diag-parent");
  let childIframeCount = 0;
  try { childIframeCount = document.querySelectorAll("iframe").length; } catch (e) {}
  return {
    sanitized_url: sanitizeUrl(location.href),
    frame_name: String(window.name || ""),
    has_ldr_ui: hasLdrUi,
    has_production_countdown: hasProductionCountdown,
    has_minimal_control: hasMinimalControl,
    has_parent_diag_listener: hasParentDiagListener,
    child_iframe_count: childIframeCount,
  };
}
"""

_INSTALL_IMMEDIATE_PARENT_JS = """
(childMeta) => {
  const LS = "__solo_immediate_parent_transport_v1";
  if (window[LS] && window[LS].installed) {
    window[LS].targets = (window[LS].targets || []).concat([childMeta]);
    return { already: true, count: (window.__solo_immediate_parent_msgs || []).length };
  }
  window[LS] = { installed: true, targets: [childMeta] };
  if (!window.__solo_immediate_parent_msgs) window.__solo_immediate_parent_msgs = [];
  function sanitizeUrl(u) {
    try {
      const x = new URL(String(u || location.href));
      if (x.searchParams.has("suite_sid")) x.searchParams.set("suite_sid", "[redacted]");
      return x.origin + x.pathname + (x.search || "");
    } catch (e) {
      return String(u || "").replace(/suite_sid=[^&]+/gi, "suite_sid=[redacted]");
    }
  }
  function childHint(source) {
    const iframes = document.querySelectorAll("iframe");
    for (let i = 0; i < iframes.length; i++) {
      try {
        if (iframes[i].contentWindow === source) {
          return {
            child_iframe_dom_index: i,
            child_src: sanitizeUrl(iframes[i].src || ""),
          };
        }
      } catch (e) {}
    }
    return { child_iframe_dom_index: -1, child_src: "" };
  }
  function payloadKeyNames(d) {
    if (!d || typeof d !== "object") return [];
    try { return Object.keys(d).slice(0, 30); } catch (e) { return []; }
  }
  function onMsg(ev) {
    const d = ev && ev.data;
    const hint = childHint(ev.source);
    const val = d && d.value;
    const valStr = typeof val === "string" ? val : "";
    const row = {
      ts: Date.now(),
      sending_child_role: (valStr.indexOf("|minimal|") >= 0 ? "minimal_control" : (valStr ? "production_countdown" : "unknown")),
      sending_child_playwright_index: childMeta.child_playwright_index,
      receiving_parent_sanitized_url: sanitizeUrl(location.href),
      receiving_parent_frame_name: String(window.name || ""),
      event_origin: String((ev && ev.origin) || ""),
      data_type: typeof d,
      message_type: d && d.type ? String(d.type) : "",
      is_streamlit_message: !!(d && d.isStreamlitMessage),
      has_set_component_value: !!(d && d.type === "streamlit:setComponentValue"),
      payload_key_names: payloadKeyNames(d),
      value_equals_expected_token: false,
      value_preview: valStr.slice(0, 120),
      child_iframe_dom_index: hint.child_iframe_dom_index,
      child_src: hint.child_src,
    };
    const expected = String(childMeta.expected_token || "");
    if (expected && valStr === expected) row.value_equals_expected_token = true;
    window.__solo_immediate_parent_msgs.push(row);
    if (window.__solo_immediate_parent_msgs.length > 250) {
      window.__solo_immediate_parent_msgs = window.__solo_immediate_parent_msgs.slice(-200);
    }
  }
  window.addEventListener("message", onMsg, true);
  return { installed: true, count: window.__solo_immediate_parent_msgs.length };
}
"""

_COLLECT_MSGS_JS = """
() => {
  const out = [];
  function walk(win, depth) {
    if (!win || depth > 12) return;
    try {
      const msgs = win.__solo_immediate_parent_msgs;
      if (Array.isArray(msgs)) out.push(...msgs);
    } catch (e) {}
    try {
      const frames = win.frames;
      for (let i = 0; i < frames.length; i++) {
        try { walk(frames[i], depth + 1); } catch (e2) {}
      }
    } catch (e3) {}
  }
  walk(window.top, 0);
  return out.slice(-250);
}
"""


def sanitize_url(url: str) -> str:
    try:
        parts = urlparse(url)
        q = parse_qs(parts.query, keep_blank_values=True)
        if "suite_sid" in q:
            q["suite_sid"] = ["[redacted]"]
        return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, urlencode(q, doseq=True), parts.fragment))
    except Exception:
        return re.sub(r"suite_sid=[^&]+", "suite_sid=[redacted]", str(url or ""))


def collect_frame_topology(page) -> dict[str, Any]:
    frames = page.frames
    id_to_idx = {id(f): i for i, f in enumerate(frames)}
    nodes: list[dict[str, Any]] = []
    for i, fr in enumerate(frames):
        row: dict[str, Any] = {
            "frame_index": i,
            "sanitized_url": "",
            "frame_name": "",
            "parent_frame_index": None,
            "child_frame_indices": [],
            "has_ldr_ui": False,
            "has_production_countdown": False,
            "has_minimal_control": False,
            "has_parent_diag_listener": False,
            "probe_error": "",
        }
        parent = fr.parent_frame
        if parent is not None:
            row["parent_frame_index"] = id_to_idx.get(id(parent))
        try:
            flags = fr.evaluate(_FRAME_FLAGS_JS)
            if isinstance(flags, dict):
                row.update(
                    {
                        "sanitized_url": flags.get("sanitized_url") or sanitize_url(fr.url),
                        "frame_name": flags.get("frame_name") or fr.name,
                        "has_ldr_ui": bool(flags.get("has_ldr_ui")),
                        "has_production_countdown": bool(flags.get("has_production_countdown")),
                        "has_minimal_control": bool(flags.get("has_minimal_control")),
                        "has_parent_diag_listener": bool(flags.get("has_parent_diag_listener")),
                        "child_iframe_count": int(flags.get("child_iframe_count") or 0),
                    }
                )
        except Exception as exc:
            row["probe_error"] = type(exc).__name__
            row["sanitized_url"] = sanitize_url(fr.url)
            row["frame_name"] = fr.name
        nodes.append(row)

    for i, row in enumerate(nodes):
        pidx = row.get("parent_frame_index")
        if pidx is not None and 0 <= int(pidx) < len(nodes):
            parent = nodes[int(pidx)]
            children = list(parent.get("child_frame_indices") or [])
            children.append(i)
            parent["child_frame_indices"] = sorted(set(children))

    return {"frame_count": len(nodes), "frames": nodes}


def install_immediate_parent_listeners(
    page,
    *,
    expected_production_token: str = "",
    expected_minimal_token: str = "",
) -> dict[str, Any]:
    frames = page.frames
    installs: list[dict[str, Any]] = []
    for i, fr in enumerate(frames):
        role = ""
        try:
            flags = fr.evaluate(
                """() => ({
                  prod: !!document.getElementById('solo-expire-client'),
                  min: !!document.getElementById('repro-client'),
                })"""
            )
        except Exception:
            continue
        if not isinstance(flags, dict):
            continue
        if flags.get("min"):
            role = "minimal_control"
        elif flags.get("prod"):
            role = "production_countdown"
        else:
            continue
        parent = fr.parent_frame
        if parent is None:
            installs.append({"child_index": i, "role": role, "error": "no_parent_frame"})
            continue
        expected = expected_minimal_token if role == "minimal_control" else expected_production_token
        meta = {
            "child_playwright_index": i,
            "role": role,
            "expected_token": str(expected or "")[:400],
        }
        try:
            res = parent.evaluate(_INSTALL_IMMEDIATE_PARENT_JS, meta)
            installs.append({"child_index": i, "role": role, "parent_url": sanitize_url(parent.url), "result": res})
        except Exception as exc:
            installs.append({"child_index": i, "role": role, "error": type(exc).__name__})

    return {"installs": installs}


def scrape_immediate_parent_messages(page) -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(_COLLECT_MSGS_JS)
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
    except Exception:
        pass
    return []


def analyze_double_production_sends(iframe_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Explain duplicate production zero-cross / timer_armed cycles (no new delivery owner)."""
    prod_key = PRODUCTION_WIDGET_KEY
    stages_of_interest = (
        "timer_armed",
        "tick_cancelled",
        "component_script_loaded",
        "render_event_received",
        "transport_before_postMessage",
        "transport_postmessage_invoked",
        "component_value_sent",
    )
    rows: list[dict[str, Any]] = []
    for e in iframe_entries:
        if not isinstance(e, dict):
            continue
        stage = str(e.get("stage") or "")
        if stage not in stages_of_interest:
            continue
        extra_raw = str(e.get("extra") or "")
        widget = ""
        token = ""
        try:
            parsed = json.loads(extra_raw) if extra_raw.startswith("{") else {}
            if isinstance(parsed, dict):
                widget = str(parsed.get("widget_key") or "")
                token = str(parsed.get("token") or parsed.get("value") or "")
        except Exception:
            widget = prod_key if prod_key in extra_raw else ""
        if widget and widget != prod_key:
            continue
        if not widget and stage not in ("timer_armed", "tick_cancelled", "component_script_loaded"):
            continue
        rows.append(
            {
                "ts": e.get("ts"),
                "stage": stage,
                "widget_key": widget or prod_key,
                "token_preview": token[:120] if token else "",
                "extra_preview": extra_raw[:200],
            }
        )

    armed = [r for r in rows if r.get("stage") == "timer_armed"]
    sent = [r for r in rows if r.get("stage") in ("component_value_sent", "transport_postmessage_invoked")]
    tokens_sent = [r.get("token_preview") or "" for r in sent if r.get("token_preview")]
    same_token_twice = len(tokens_sent) >= 2 and tokens_sent[0] and tokens_sent[0] == tokens_sent[1]
    reload_hints = sum(1 for r in rows if r.get("stage") == "component_script_loaded")
    return {
        "production_timer_armed_count": len(armed),
        "production_send_stage_count": len(sent),
        "timer_armed_timestamps": [r.get("ts") for r in armed],
        "send_timestamps": [r.get("ts") for r in sent],
        "tokens_sent_previews": tokens_sent[:4],
        "same_expected_token_sent_twice": same_token_twice,
        "component_script_loaded_count": reload_hints,
        "likely_streamlit_rerender_vs_iframe_document_replace": (
            "multiple_timer_armed_with_tick_cancelled_suggests_streamlit_rerender_or_iframe_remount"
            if len(armed) >= 2
            else "single_arm_cycle"
        ),
        "timeline": rows[-40:],
    }
