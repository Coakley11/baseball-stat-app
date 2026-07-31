"""Harness-only live sender iframe + post-send Streamlit rerun trace (no production bind changes)."""

from __future__ import annotations

import json
import time
from typing import Any

PRODUCTION_WIDGET_KEY = "solo_countdown_wake_solo_persistent"

# Navigation-independent trace store (browser-side, harness only).
P8_SENDER_RERUN_INIT_SCRIPT = """
(function () {
  if (window.__p8SenderRerunTrace) return;
  function sanitizeUrl(u) {
    try {
      var x = new URL(String(u || location.href));
      if (x.searchParams.has("suite_sid")) x.searchParams.set("suite_sid", "[redacted]");
      return x.origin + x.pathname + (x.search || "");
    } catch (e) {
      return String(u || "");
    }
  }
  function classifyIframe(el, source) {
    var row = {
      iframe_dom_index: -1,
      iframe_src: "",
      iframe_name: "",
      iframe_is_connected: false,
      iframe_instance_id: "",
      widget_key: "",
      component_name: "",
      is_production_countdown: false,
      is_minimal_wake_repro: false,
      room_id: "",
      pick_index: "",
      expected_token: "",
      creation_wall_ts: null,
      disconnected_wall_ts: null,
    };
    var target = el;
    if (!target && source) {
      var iframes = document.querySelectorAll("iframe");
      for (var i = 0; i < iframes.length; i++) {
        try {
          if (iframes[i].contentWindow === source) {
            target = iframes[i];
            row.iframe_dom_index = i;
            break;
          }
        } catch (e) {}
      }
    }
    if (target) {
      row.iframe_src = sanitizeUrl(target.src || "");
      row.iframe_name = String(target.getAttribute("name") || target.title || "");
      row.iframe_is_connected = !!target.isConnected;
      try {
        var doc = target.contentDocument;
        var solo = doc && doc.getElementById("solo-expire-client");
        var repro = doc && doc.getElementById("repro-client");
        if (solo) {
          row.is_production_countdown = true;
          row.iframe_instance_id = String(solo.getAttribute("data-iframe-instance") || "");
          row.widget_key = String(solo.getAttribute("data-widget-key") || "");
        }
        if (repro) {
          row.is_minimal_wake_repro = true;
          row.component_name = "minimal_wake_repro";
        }
      } catch (e2) {}
    }
    return row;
  }
  window.__p8SenderRerunTrace = {
    iframe_registry: {},
    send_events: [],
    scv_receipts: [],
    iframe_seq: 0,
  };
  var store = window.__p8SenderRerunTrace;

  function regKey(el, idx) {
    try {
      var doc = el.contentDocument;
      var solo = doc && doc.getElementById("solo-expire-client");
      var inst = solo ? String(solo.getAttribute("data-iframe-instance") || "") : "";
      return inst || ("dom_" + idx + "_" + sanitizeUrl(el.src || "").slice(-40));
    } catch (e) {
      return "dom_" + idx;
    }
  }

  function scanIframes(reason) {
    var iframes = document.querySelectorAll("iframe");
    for (var i = 0; i < iframes.length; i++) {
      var el = iframes[i];
      var key = regKey(el, i);
      var now = Date.now();
      if (!store.iframe_registry[key]) {
        store.iframe_seq += 1;
        var info = classifyIframe(el, null);
        info.iframe_dom_index = i;
        info.creation_wall_ts = now;
        info.registry_id = key;
        info.registry_seq = store.iframe_seq;
        store.iframe_registry[key] = info;
      } else {
        var cur = store.iframe_registry[key];
        cur.iframe_is_connected = !!el.isConnected;
        cur.iframe_dom_index = i;
        if (!el.isConnected && !cur.disconnected_wall_ts) cur.disconnected_wall_ts = now;
      }
    }
  }

  scanIframes("init");
  try {
    var mo = new MutationObserver(function () { scanIframes("mutation"); });
    mo.observe(document.documentElement, { childList: true, subtree: true });
  } catch (e3) {}

  window.addEventListener("message", function (ev) {
    var d = ev && ev.data;
    if (!d || typeof d !== "object") return;
    var mt = String(d.type || "");
    if (mt !== "streamlit:setComponentValue" && mt !== "solo:stage1ImmediateParentProbe") return;
    scanIframes("pre_message");
    var assoc = classifyIframe(null, ev.source);
    var candidates = [];
    var iframes = document.querySelectorAll("iframe");
    for (var j = 0; j < iframes.length; j++) {
      try {
        var c = classifyIframe(iframes[j], null);
        c.iframe_dom_index = j;
        if (c.is_production_countdown || c.is_minimal_wake_repro) candidates.push(c);
      } catch (e4) {}
    }
    var val = d.value != null ? String(d.value) : "";
    var rec = {
      receipt_wall_ts: Date.now(),
      message_type: mt,
      value_or_token: val.slice(0, 400),
      sending_iframe: assoc,
      connected_candidates: candidates,
      production_countdown_match: !!assoc.is_production_countdown,
      minimal_repro_match: !!assoc.is_minimal_wake_repro,
      event_origin: String((ev && ev.origin) || ""),
      receiver_url: sanitizeUrl(location.href),
    };
    if (mt === "streamlit:setComponentValue") store.scv_receipts.push(rec);
  }, true);

  window.__p8SenderRerunTraceExport = function () {
    scanIframes("export");
    return {
      iframe_registry: store.iframe_registry,
      send_events: store.send_events.slice(-40),
      scv_receipts: store.scv_receipts.slice(-40),
    };
  };
})();
"""


def normalize_epoch_ts(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v > 1e12:
        return v / 1000.0
    if v > 1e9:
        return v
    return None


def collect_iframe_lifecycle_entries(page) -> list[dict[str, Any]]:
    from run_production_solo_soak import scrape_iframe_lifecycle

    life = scrape_iframe_lifecycle(page) or {}
    entries: list[dict[str, Any]] = []
    for fr in life.get("frames") or []:
        if not isinstance(fr, dict):
            continue
        for block in fr.get("logs") or []:
            if isinstance(block, dict):
                entries.extend(block.get("entries") or [])
    return [e for e in entries if isinstance(e, dict)]


def find_production_send_boundary(
    entries: list[dict[str, Any]], *, wall_fallback: float | None = None
) -> dict[str, Any]:
    """Return first production transport_before_postMessage with real browser timestamp."""
    prod_key = PRODUCTION_WIDGET_KEY
    best: dict[str, Any] | None = None
    for e in entries:
        stage = str(e.get("stage") or "")
        if stage != "transport_before_postMessage":
            continue
        extra_raw = str(e.get("extra") or "")
        widget = prod_key
        token = ""
        iframe_inst = ""
        try:
            if extra_raw.startswith("{"):
                parsed = json.loads(extra_raw)
                if isinstance(parsed, dict):
                    widget = str(parsed.get("widget_key") or widget)
                    token = str(parsed.get("token") or parsed.get("value") or "")
                    iframe_inst = str(parsed.get("iframe_instance_id") or parsed.get("iframe_instance") or "")
        except json.JSONDecodeError:
            pass
        if widget and widget != prod_key:
            continue
        ts = normalize_epoch_ts(e.get("ts"))
        if ts is None and wall_fallback is not None:
            ts = wall_fallback
        row = {
            "stage": stage,
            "ts_epoch": ts,
            "token": token,
            "widget_key": widget,
            "iframe_instance_id": iframe_inst,
            "extra_preview": extra_raw[:300],
            "entry": e,
        }
        if best is None:
            best = row
    return best or {}


def scrape_trace_export(page) -> dict[str, Any]:
    try:
        raw = page.evaluate("() => (window.__p8SenderRerunTraceExport ? window.__p8SenderRerunTraceExport() : {})")
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def mirror_script_begin_durable(
    rows: list[dict[str, Any]], *, capture_wall_ts: float, deployment_sha: str
) -> list[dict[str, Any]]:
    """Harness mirror of production_stage1_script_begin_durable (no deploy required)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("event") or "") != "production_stage1_script_begin":
            continue
        out.append(
            {
                "event": "production_stage1_script_begin_durable",
                "source": "harness_mirror_from_production_ledger",
                "capture_wall_ts": capture_wall_ts,
                "server_ts": row.get("ts"),
                "diagnostic_run_id": row.get("run_id"),
                "room_id": row.get("room_id"),
                "deployment_sha": deployment_sha or row.get("deployment_sha"),
                "script_run_seq": row.get("script_run_seq"),
                "session_state_widget_value": row.get("session_state_value") or row.get("pending_session_state_value"),
                "room_status": row.get("room_status"),
                "pick_index": row.get("pick_index"),
                "deadline": row.get("deadline"),
                "expected_token": row.get("expected_token"),
                "active_page": row.get("active_page"),
                "declaration_eligibility_hint": row.get("actionable_mount_eligible"),
            }
        )
    return out


def merge_peak_ledger_rows(collector: Any, exp: dict[str, Any]) -> list[dict[str, Any]]:
    from stage1_parent_observer_probe import merge_ledger_rows

    rows: list[dict[str, Any]] = []
    rows = merge_ledger_rows(rows, list(collector.peak_rows() or []))
    rows = merge_ledger_rows(rows, list(exp.get("peak_merged_server_ledger") or []))
    rows = merge_ledger_rows(rows, list(exp.get("merged_server_ledger") or []))
    meta = exp.get("ledger_meta") or {}
    rows = merge_ledger_rows(rows, list(meta.get("merged_server_ledger") or []))
    return rows


def poll_post_send_trace(
    page,
    *,
    send_epoch: float,
    room_id: str,
    deployment_sha: str,
    collector: Any,
    parent_sink: Any,
    pre_window_s: float = 5.0,
    post_window_s: float = 15.0,
    poll_ms: int = 250,
) -> dict[str, Any]:
    from p8_ledger_observability import capture_all_ledger_sources
    from stage1_parent_observer_probe import merge_ledger_rows

    start_wall = send_epoch - pre_window_s
    end_wall = send_epoch + post_window_s
    samples: list[dict[str, Any]] = []
    durable_script_begins: list[dict[str, Any]] = []
    seen_begin: set[str] = set()
    merged_peak: list[dict[str, Any]] = []

    while time.time() < end_wall:
        now = time.time()
        if now >= start_wall:
            cap = capture_all_ledger_sources(page, audit={})
            collector.absorb_capture(cap, label=f"trace_poll_{len(samples)}")
            merged_peak = merge_peak_ledger_rows(collector, {})
            for row in merged_peak:
                eid = str(row.get("event_id") or "")
                if eid and eid not in seen_begin and row.get("event") == "production_stage1_script_begin":
                    seen_begin.add(eid)
                    durable_script_begins.extend(
                        mirror_script_begin_durable([row], capture_wall_ts=now, deployment_sha=deployment_sha)
                    )
            trace = scrape_trace_export(page)
            iframe_entries = collect_iframe_lifecycle_entries(page)
            samples.append(
                {
                    "wall_ts": now,
                    "t_rel_send_s": round(now - send_epoch, 3),
                    "ledger_row_count_peak": len(merged_peak),
                    "iframe_lifecycle_entry_count": len(iframe_entries),
                    "trace_scv_count": len(trace.get("scv_receipts") or []),
                    "parent_sink_raw_count": len(getattr(parent_sink, "raw_events", []) or []),
                }
            )
        page.wait_for_timeout(poll_ms)

    post_send_begins = [
        r
        for r in durable_script_begins
        if normalize_epoch_ts(r.get("server_ts")) is not None
        and float(r["server_ts"]) >= send_epoch - 0.05
    ]
    post_send_begins += [
        r
        for r in durable_script_begins
        if r not in post_send_begins and float(r.get("capture_wall_ts") or 0) >= send_epoch - 0.05
    ]

    decl_after = [
        r
        for r in merged_peak
        if str(r.get("event") or "") == "production_stage1_declaration_returned"
        and normalize_epoch_ts(r.get("ts")) is not None
        and float(r["ts"]) >= send_epoch - 0.05
        and (not room_id or str(r.get("room_id") or "") in ("", room_id))
    ]
    return {
        "send_epoch": send_epoch,
        "window": {"pre_s": pre_window_s, "post_s": post_window_s},
        "poll_samples": samples,
        "peak_ledger_rows": merged_peak,
        "durable_script_begin_mirror": durable_script_begins,
        "post_send_script_begins": post_send_begins,
        "post_send_declaration_returned": decl_after,
        "final_trace_export": scrape_trace_export(page),
        "final_iframe_entries": collect_iframe_lifecycle_entries(page),
    }


def classify_live_sender_rerun(trace: dict[str, Any], *, exact_token: str) -> dict[str, Any]:
    send = trace.get("send_boundary") or {}
    send_epoch = send.get("ts_epoch")
    poll = trace.get("post_send_poll") or {}
    peak = list(poll.get("peak_ledger_rows") or [])
    export = poll.get("final_trace_export") or {}
    scvs = list(export.get("scv_receipts") or [])
    iframe_entries = list(poll.get("final_iframe_entries") or [])

    iframe_inst = str(send.get("iframe_instance_id") or "")
    prod_send = bool(send.get("token") or exact_token in str(send.get("extra_preview") or ""))
    sending_iframe = (trace.get("send_iframe_snapshot") or {}).get("sending_iframe") or {}
    if not sending_iframe and iframe_inst:
        sending_iframe = {
            "iframe_instance_id": iframe_inst,
            "is_production_countdown": True,
            "widget_key": send.get("widget_key"),
        }
    is_prod_iframe = bool(sending_iframe.get("is_production_countdown")) or bool(iframe_inst)
    is_min_iframe = bool(sending_iframe.get("is_minimal_wake_repro"))

    prod_scv = [r for r in scvs if r.get("production_countdown_match")]
    min_scv = [r for r in scvs if r.get("minimal_repro_match") and not r.get("production_countdown_match")]

    post_begins = list(poll.get("post_send_script_begins") or [])
    first_post_begin = post_begins[0] if post_begins else None
    decl_after = list(poll.get("post_send_declaration_returned") or [])
    first_decl = decl_after[0] if decl_after else None

    post_send_iframe_events = [
        e
        for e in iframe_entries
        if normalize_epoch_ts(e.get("ts")) is not None and float(normalize_epoch_ts(e.get("ts")) or 0) >= float(send_epoch or 0) - 0.05
    ]
    tick_cancel_render = [
        e
        for e in post_send_iframe_events
        if str(e.get("stage") or "") == "tick_cancelled" and "streamlit_render" in str(e.get("extra") or "")
    ]

    def norm_tok(row: dict[str, Any] | None) -> str:
        if not row:
            return ""
        for k in ("coalesced_value", "direct_component_return", "session_state_value"):
            v = str(row.get(k) or "").strip().strip("'")
            if v and v != "None":
                return v
        return ""

    bound_after = any(norm_tok(r) == exact_token for r in decl_after)

    code = "LIFECYCLE11"
    rationale = "Insufficient evidence for a narrower lifecycle class."
    first_diff = ""

    if not send_epoch:
        return {
            "code": "LIFECYCLE11",
            "label": "LIFECYCLE11 — OTHER",
            "rationale": "No transport_before_postMessage timestamp captured from production iframe lifecycle.",
            "first_causally_meaningful_difference": "",
            "evidence": {},
        }

    if is_min_iframe and not is_prod_iframe and min_scv and not prod_scv:
        code = "LIFECYCLE7"
        rationale = "Send attributed to minimal/stale iframe; no production SCV receipt."
        first_diff = "send_iframe_not_production_countdown"
    elif min_scv and not prod_scv and prod_send and not is_prod_iframe:
        code = "LIFECYCLE9"
        rationale = "Harness parent listener saw minimal iframe SCV only despite production lifecycle send."
        first_diff = "parent_scv_minimal_not_production"
    elif not post_begins:
        if tick_cancel_render and prod_send and is_prod_iframe:
            code = "LIFECYCLE1"
            rationale = (
                "Connected production countdown sent exact token; streamlit_render tick_cancelled/remount "
                "occurred after send; peak ledger captured no script_begin at or after send_epoch."
            )
            first_diff = "post_send_streamlit_render_without_server_script_begin"
        else:
            code = "LIFECYCLE10"
            rationale = "No production_stage1_script_begin (durable mirror) at or after exact send timestamp."
            first_diff = "no_post_send_script_begin_in_peak_ledger"
    elif first_decl and not bound_after:
        if is_prod_iframe and (prod_scv or prod_send):
            code = "LIFECYCLE8"
            rationale = (
                "Post-send Streamlit script and declaration occurred but direct return / Session State "
                "did not carry exact token."
            )
            first_diff = "post_send_declaration_empty_return"
        else:
            code = "LIFECYCLE3"
            rationale = "Post-send script run without bound declaration_returned coalesced token."
            first_diff = "declaration_skipped_or_empty_on_post_send_rerun"
    elif bound_after:
        code = "LIFECYCLE11"
        rationale = "Unexpected exact-token bind after send on d73bcf3; manual review."

    if code == "LIFECYCLE8":
        ok = all([prod_send and is_prod_iframe, bool(post_begins), first_decl is not None, not bound_after])
        if not ok:
            code = "LIFECYCLE11"
            rationale = "LIFECYCLE8 preconditions not all satisfied."

    labels = {
        "LIFECYCLE1": "LIFECYCLE1 — SENDING_IFRAME_REPLACED_BEFORE_BIND",
        "LIFECYCLE7": "LIFECYCLE7 — BROWSER_SEND_CAME_FROM_STALE_OR_DIAGNOSTIC_IFRAME",
        "LIFECYCLE8": "LIFECYCLE8 — PRODUCTION SEND RECEIVED BUT NO STREAMLIT BIND OCCURRED",
        "LIFECYCLE9": "LIFECYCLE9 — HARNESS MISATTRIBUTED MINIMAL-IFRAME ACTIVITY AS PRODUCTION",
        "LIFECYCLE10": "LIFECYCLE10 — NO_POST_SEND_STREAMLIT_RERUN",
        "LIFECYCLE11": "LIFECYCLE11 — OTHER",
        "LIFECYCLE3": "LIFECYCLE3 — COMPONENT_DECLARATION_SKIPPED_ON_POST_SEND_RERUN",
    }

    return {
        "code": code,
        "label": labels.get(code, code),
        "rationale": rationale,
        "first_causally_meaningful_difference": first_diff,
        "evidence": {
            "send_epoch": send_epoch,
            "production_send_token": send.get("token") or exact_token,
            "sending_iframe_instance_id": iframe_inst,
            "sending_iframe": sending_iframe,
            "prod_scv_receipts": len(prod_scv),
            "minimal_scv_receipts": len(min_scv),
            "post_send_script_begin_count": len(post_begins),
            "first_post_send_script_begin": first_post_begin,
            "first_post_send_declaration_returned": first_decl,
            "exact_token_bound_after_send": bound_after,
            "post_send_tick_cancel_streamlit_render": tick_cancel_render[:3],
            "max_peak_ledger_server_ts": max(
                (normalize_epoch_ts(r.get("ts")) or 0 for r in peak), default=0
            ),
        },
    }


def wait_for_send_then_trace(
    page,
    *,
    timeout_s: float = 95.0,
    parent_sink: Any,
    collector: Any,
    room_id: str,
    deployment_sha: str,
    exact_token: str,
    ws_capture: Any | None = None,
    diagnostic_run_id: str = "",
    pick_index: int | None = None,
    canary_pre_trace_validated: bool = False,
) -> dict[str, Any]:
    """Poll until production send, keep capturing from 5s before send through 15s after."""
    from p8_boundary_instrumentation import (
        build_unified_timeline,
        classify_first_missing_boundary,
        correlate_websocket_boundary,
        enrich_post_send_server_audit,
        install_production_immediate_parent_listener,
        scrape_immediate_parent_boundary_log,
    )
    from p8_ledger_observability import capture_all_ledger_sources

    t0 = time.time()
    send_boundary: dict[str, Any] = {}
    send_epoch: float | None = None
    capture_end: float | None = None
    samples: list[dict[str, Any]] = []
    durable_script_begins: list[dict[str, Any]] = []
    seen_begin: set[str] = set()
    merged_peak: list[dict[str, Any]] = []
    send_snapshot: dict[str, Any] = {}
    immediate_install_log: list[dict[str, Any]] = []

    while time.time() - t0 < timeout_s:
        now = time.time()
        if capture_end is not None and now >= capture_end:
            break

        inst = install_production_immediate_parent_listener(
            page,
            deployment_sha=deployment_sha,
            diagnostic_run_id=diagnostic_run_id or room_id,
            expected_token=exact_token,
            room_id=room_id,
            pick_index=pick_index,
            widget_key=PRODUCTION_WIDGET_KEY,
        )
        if inst.get("ok") and ws_capture is not None:
            try:
                ws_capture.set_page_correlation_meta(
                    page,
                    expected_token=exact_token,
                    widget_key=PRODUCTION_WIDGET_KEY,
                    diagnostic_run_id=diagnostic_run_id or room_id,
                    room_id=room_id,
                    deployment_sha=deployment_sha,
                )
            except Exception:
                pass
        if inst.get("ok"):
            immediate_install_log.append({"wall_ts": now, **inst})

        iframe_entries = collect_iframe_lifecycle_entries(page)
        if send_epoch is None:
            cand = find_production_send_boundary(iframe_entries, wall_fallback=None)
            if cand.get("stage") == "transport_before_postMessage":
                send_epoch = normalize_epoch_ts((cand.get("entry") or {}).get("ts")) or now
                cand["ts_epoch"] = send_epoch
                cand["ts_source"] = (
                    "iframe_lifecycle_ts" if normalize_epoch_ts((cand.get("entry") or {}).get("ts")) else "harness_wall_at_send_detect"
                )
                send_boundary = cand
                capture_end = send_epoch + 15.0
                send_snapshot = {
                    "trace_export": scrape_trace_export(page),
                    "iframe_entries_at_send": iframe_entries[-40:],
                    "immediate_parent_at_send": scrape_immediate_parent_boundary_log(page),
                }

        if send_epoch is not None and now >= send_epoch - 5.0:
            cap = capture_all_ledger_sources(page, audit={})
            collector.absorb_capture(cap, label=f"trace_poll_{len(samples)}")
            merged_peak = merge_peak_ledger_rows(collector, {})
            for row in merged_peak:
                eid = str(row.get("event_id") or "")
                if eid and eid not in seen_begin and row.get("event") == "production_stage1_script_begin":
                    seen_begin.add(eid)
                    durable_script_begins.extend(
                        mirror_script_begin_durable([row], capture_wall_ts=now, deployment_sha=deployment_sha)
                    )
            samples.append(
                {
                    "wall_ts": now,
                    "t_rel_send_s": round(now - send_epoch, 3) if send_epoch else None,
                    "ledger_row_count_peak": len(merged_peak),
                    "iframe_lifecycle_entry_count": len(iframe_entries),
                    "immediate_parent_records": len((scrape_immediate_parent_boundary_log(page).get("records") or [])),
                }
            )

        page.wait_for_timeout(250)

    if not send_epoch:
        return {"ok": False, "reason": "send_not_observed", "poll_samples": samples, "immediate_install_log": immediate_install_log}

    post_send_begins = [
        r
        for r in durable_script_begins
        if (normalize_epoch_ts(r.get("server_ts")) or 0) >= send_epoch - 0.05
    ]
    decl_after = [
        r
        for r in merged_peak
        if str(r.get("event") or "") == "production_stage1_declaration_returned"
        and (normalize_epoch_ts(r.get("ts")) or 0) >= send_epoch - 0.05
        and (not room_id or str(r.get("room_id") or "") in ("", room_id))
    ]

    final_iframe_entries = collect_iframe_lifecycle_entries(page)
    immediate_final = scrape_immediate_parent_boundary_log(page)
    post_send_server = enrich_post_send_server_audit(
        merged_peak, send_epoch=send_epoch, deployment_sha=deployment_sha
    )
    if ws_capture is None:
        from p8_boundary_instrumentation import WebSocketBoundaryCapture

        ws_capture = WebSocketBoundaryCapture()
    ws_frames = ws_capture.merged_frames(page) if hasattr(ws_capture, "merged_frames") else list(getattr(ws_capture, "frames", []) or [])

    parent_receipt_ts: float | None = None
    for r in list(immediate_final.get("records") or []):
        if r.get("message_type") != "streamlit:setComponentValue":
            continue
        if exact_token not in str(r.get("exact_payload_preview") or ""):
            continue
        wt_ms = float(r.get("receipt_wall_ts") or 0)
        parent_receipt_ts = wt_ms / 1000.0 if wt_ms > 1e12 else wt_ms
        break

    ws_correlation = correlate_websocket_boundary(
        ws_frames,
        send_epoch=send_epoch,
        parent_receipt_epoch=parent_receipt_ts,
        exact_token=exact_token,
        widget_key=PRODUCTION_WIDGET_KEY,
        diagnostic_run_id=diagnostic_run_id or room_id,
        room_id=room_id,
        deployment_sha=deployment_sha,
    )

    poll = {
        "send_epoch": send_epoch,
        "window": {"pre_s": 5.0, "post_s": 15.0},
        "poll_samples": samples,
        "peak_ledger_rows": merged_peak,
        "durable_script_begin_mirror": durable_script_begins,
        "post_send_script_begins": post_send_begins,
        "post_send_declaration_returned": decl_after,
        "post_send_server_audit": post_send_server,
        "final_trace_export": scrape_trace_export(page),
        "final_iframe_entries": final_iframe_entries,
        "immediate_parent_final": immediate_final,
        "immediate_parent_install_log": immediate_install_log,
        "websocket_frames": ws_frames,
        "websocket_correlation": ws_correlation,
        "unified_timeline": build_unified_timeline(
            send_epoch=send_epoch,
            send_boundary=send_boundary,
            iframe_entries=final_iframe_entries,
            immediate_records=list(immediate_final.get("records") or []),
            ws_frames=ws_frames,
            post_send_server=post_send_server,
            ws_correlation=ws_correlation,
        ),
    }

    send_snapshot["sending_iframe"] = {
        "iframe_instance_id": send_boundary.get("iframe_instance_id"),
        "widget_key": send_boundary.get("widget_key"),
        "is_production_countdown": True,
    }

    body = {
        "send_boundary": send_boundary,
        "send_iframe_snapshot": send_snapshot,
        "post_send_poll": poll,
        "accepted_live_facts": {
            "production_countdown_emitted_exact_token": True,
            "connected_at_transport_before_postMessage": True,
            "not_minimal_wake_repro_send": True,
            "provisional_boundary": "PRODUCTION_POSTMESSAGE_EMITTED_BUT_NO_BACKEND_RERUN_OBSERVED",
        },
    }
    boundary_class = classify_first_missing_boundary(
        send_epoch=send_epoch,
        exact_token=exact_token,
        send_boundary=send_boundary,
        immediate_log=immediate_final,
        ws_capture=ws_capture,
        post_send_server=post_send_server,
        peak_rows=merged_peak,
        iframe_entries=final_iframe_entries,
        ws_correlation=ws_correlation,
        page=page,
        canary_pre_trace_validated=bool(canary_pre_trace_validated),
    )
    return {
        "ok": True,
        **body,
        "boundary_classification": boundary_class,
        "classification": boundary_class,
    }
