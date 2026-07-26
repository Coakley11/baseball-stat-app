"""Shared Playwright scoring for synthetic wiring matrix (distinct event counts)."""

from __future__ import annotations

import json
import time
from typing import Any

INSTALL_PARENT_CAPTURE_JS = """
(childMeta) => {
  const NS = "__solo_wiring_matrix_parent_v1";
  if (!window[NS]) {
    window[NS] = { rows: [], installed: true };
    window.addEventListener("message", function (ev) {
      const d = ev && ev.data;
      if (!d || d.type !== "streamlit:setComponentValue") return;
      const val = typeof d.value === "string" ? d.value : "";
      const keys = [];
      try { keys.push(...Object.keys(d)); } catch (e) {}
      window[NS].rows.push({
        ts: Date.now(),
        value_preview: val.slice(0, 200),
        payload_keys: keys,
        origin: String((ev && ev.origin) || ""),
      });
      if (window[NS].rows.length > 80) window[NS].rows = window[NS].rows.slice(-60);
    }, true);
  }
  return { count: window[NS].rows.length };
}
"""

SCRAPE_REPRO_EVENTS_JS = """
() => {
  const out = {
    repro_chain: "",
    repro_console: "",
    minimal_iframes: 0,
    production_iframes: 0,
    stage_counts: {},
  };
  function bump(s) {
    out.stage_counts[s] = (out.stage_counts[s] || 0) + 1;
  }
  for (const f of document.querySelectorAll("iframe")) {
    try {
      const doc = f.contentDocument;
      if (!doc) continue;
      if (doc.querySelector("#repro-client")) {
        out.minimal_iframes += 1;
        const el = doc.querySelector("#repro-client");
        out.repro_chain = el.getAttribute("data-chain") || out.repro_chain;
        out.repro_console = el.getAttribute("data-console") || out.repro_console;
        for (const s of String(out.repro_chain || "").split("|")) {
          if (s.trim()) bump(s.trim());
        }
      }
      if (doc.querySelector("#solo-expire-client")) {
        out.production_iframes += 1;
      }
    } catch (e) {}
  }
  return out;
}
"""

COLLECT_PARENT_ROWS_JS = """
() => {
  const rows = [];
  function walk(win, depth) {
    if (!win || depth > 14) return;
    try {
      const bag = win.__solo_wiring_matrix_parent_v1;
      if (bag && Array.isArray(bag.rows)) rows.push(...bag.rows);
    } catch (e) {}
    try {
      for (let i = 0; i < win.frames.length; i++) walk(win.frames[i], depth + 1);
    } catch (e2) {}
  }
  walk(window.top, 0);
  return rows.slice(-80);
}
"""


def install_parent_capture(page, *, expected_token: str = "") -> None:
    for fr in page.frames:
        try:
            fr.evaluate(INSTALL_PARENT_CAPTURE_JS, {"expected_token": expected_token[:200]})
        except Exception:
            pass


SCRAPE_FRAME_CHAIN_JS = """
() => {
  const out = { repro_chain: "", repro_console: "", solo_chain: "", has_repro: false, has_solo: false };
  try {
    const el = document.getElementById("repro-client");
    if (el) {
      out.has_repro = true;
      out.repro_chain = el.getAttribute("data-chain") || "";
      out.repro_console = el.getAttribute("data-console") || "";
    }
    const solo = document.getElementById("solo-expire-client");
    if (solo) {
      out.has_solo = true;
      out.solo_chain = solo.getAttribute("data-chain") || "";
    }
  } catch (e) {}
  return out;
}
"""


def scrape_repro_events(page) -> dict[str, Any]:
    out: dict[str, Any] = {
        "repro_chain": "",
        "repro_console": "",
        "minimal_iframes": 0,
        "production_iframes": 0,
        "stage_counts": {},
    }

    def bump(s: str) -> None:
        sc = out["stage_counts"]
        sc[s] = int(sc.get(s) or 0) + 1

    for fr in page.frames:
        try:
            part = fr.evaluate(SCRAPE_FRAME_CHAIN_JS)
        except Exception:
            continue
        if not isinstance(part, dict):
            continue
        if part.get("has_repro"):
            out["minimal_iframes"] += 1
            chain = str(part.get("repro_chain") or "")
            if len(chain) > len(str(out.get("repro_chain") or "")):
                out["repro_chain"] = chain
                out["repro_console"] = str(part.get("repro_console") or "")
        if part.get("has_solo"):
            out["production_iframes"] += 1
            chain = str(part.get("solo_chain") or "")
            for s in chain.split("|"):
                if s.strip():
                    bump(s.strip())

    try:
        raw = page.evaluate(SCRAPE_REPRO_EVENTS_JS)
        if isinstance(raw, dict):
            out["minimal_iframes"] = max(int(out["minimal_iframes"]), int(raw.get("minimal_iframes") or 0))
            out["production_iframes"] = max(
                int(out["production_iframes"]), int(raw.get("production_iframes") or 0)
            )
            if len(str(raw.get("repro_chain") or "")) > len(str(out.get("repro_chain") or "")):
                out["repro_chain"] = raw.get("repro_chain") or out["repro_chain"]
                out["repro_console"] = raw.get("repro_console") or out["repro_console"]
    except Exception:
        pass

    for s in str(out.get("repro_chain") or "").split("|"):
        if s.strip():
            bump(s.strip())
    solo_chain = ""
    try:
        solo_chain = page.evaluate(
            """() => {
              for (const f of document.querySelectorAll('iframe')) {
                try {
                  const el = f.contentDocument && f.contentDocument.querySelector('#solo-expire-client');
                  if (el) return el.getAttribute('data-chain')||'';
                } catch(e) {}
              }
              return '';
            }"""
        )
    except Exception:
        solo_chain = ""
    for s in str(solo_chain or "").split("|"):
        if s.strip():
            bump(s.strip())
    return out


def _scrape_repro_events_legacy(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(SCRAPE_REPRO_EVENTS_JS)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def scrape_repro_events_page_only(page) -> dict[str, Any]:
    """Alias for scrape_repro_events (multi-frame)."""
    return scrape_repro_events(page)


def collect_parent_messages(page) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fr in page.frames:
        try:
            part = fr.evaluate(COLLECT_PARENT_ROWS_JS)
            if isinstance(part, list):
                rows.extend(part)
        except Exception:
            pass
    rows.sort(key=lambda r: int(r.get("ts") or 0))
    return rows[-80:]


def count_stage(stage_counts: dict[str, Any], name: str) -> int:
    return int(stage_counts.get(name) or 0)


def merge_peak_distinct(peak: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Keep max event counts across polls (iframe may disappear after Streamlit rerun)."""
    if not peak:
        return dict(current)
    out = dict(peak)
    for key in (
        "timer_armed",
        "browser_deadline_crossed",
        "setComponentValue_invocation",
        "logical_send_postmessage",
        "parent_message",
        "python_raw_receipt",
        "on_change_callback",
        "minimal_iframes",
        "production_iframes",
    ):
        out[key] = max(int(out.get(key) or 0), int(current.get(key) or 0))
    out["session_raw_matches"] = bool(out.get("session_raw_matches")) or bool(current.get("session_raw_matches"))
    out["pre_send_callback"] = bool(out.get("pre_send_callback")) or bool(current.get("pre_send_callback"))
    out["pre_send_session_token"] = bool(out.get("pre_send_session_token")) or bool(
        current.get("pre_send_session_token")
    )
    if len(current.get("callback_log") or []) >= len(out.get("callback_log") or []):
        out["callback_log"] = current.get("callback_log")
    if len(current.get("parent_rows_captured") or []) >= len(out.get("parent_rows_captured") or []):
        out["parent_rows_captured"] = current.get("parent_rows_captured")
    sc_peak = dict(out.get("stage_counts") or {})
    sc_cur = dict(current.get("stage_counts") or {})
    for k, v in sc_cur.items():
        sc_peak[k] = max(int(sc_peak.get(k) or 0), int(v or 0))
    out["stage_counts"] = sc_peak
    if current.get("browser_send_ts") and not out.get("browser_send_ts"):
        out["browser_send_ts"] = current.get("browser_send_ts")
    if current.get("parent_message_ts_ms") and not out.get("parent_message_ts_ms"):
        out["parent_message_ts_ms"] = current.get("parent_message_ts_ms")
    if current.get("parent_payload_keys") and not out.get("parent_payload_keys"):
        out["parent_payload_keys"] = current.get("parent_payload_keys")
    return out


CELL_SPEC: dict[str, dict[str, Any]] = {
    "A1": {
        "frontend": "minimal_wake_repro",
        "declaration": "minimal_component_wake_repro_core.mount_single_for_transport",
        "minimal_iframes": 1,
        "production_iframes": 0,
        "iframe_identity": "#repro-client",
    },
    "B1": {
        "frontend": "solo_countdown_wake",
        "declaration": "solo_countdown_component.mount_solo_countdown_wake_direct",
        "minimal_iframes": 0,
        "production_iframes": 1,
        "iframe_identity": "#solo-expire-client",
    },
    "A2": {
        "frontend": "minimal_wake_repro",
        "declaration": "minimal_frontend + micro_isolation_callback_wrapper",
        "minimal_iframes": 1,
        "production_iframes": 0,
        "iframe_identity": "#repro-client",
    },
    "B2": {
        "frontend": "solo_countdown_wake",
        "declaration": "solo_countdown_wake_micro_core.render_micro_isolation_once",
        "minimal_iframes": 0,
        "production_iframes": 1,
        "iframe_identity": "#solo-expire-client",
    },
}


def set_component_invocation_count(sc: dict[str, Any]) -> int:
    return max(
        count_stage(sc, "setComponentValue_invoked"),
        count_stage(sc, "setComponentValue_called"),
        count_stage(sc, "iframe_setComponentValue_called"),
    )


def score_matrix_cell(distinct: dict[str, Any], *, cell: str, expected_token: str) -> dict[str, Any]:
    _ = expected_token
    req = {
        "timer_armed": distinct.get("timer_armed") == 1,
        "browser_deadline_crossed": distinct.get("browser_deadline_crossed") == 1,
        "setComponentValue_invocation": distinct.get("setComponentValue_invocation") == 1,
        "transport_postmessage_invoked": distinct.get("logical_send_postmessage") == 1,
        "parent_message": distinct.get("parent_message") == 1,
        "session_raw_matches": distinct.get("session_raw_matches") is True,
        "on_change_callback": distinct.get("on_change_callback") == 1,
    }
    invalid: list[str] = []
    if distinct.get("pre_send_callback") is True:
        invalid.append("callback_before_browser_send")
    if distinct.get("pre_send_session_token") is True:
        invalid.append("session_token_before_browser_send")
    spec = CELL_SPEC.get(cell.upper()) or CELL_SPEC["A1"]
    if distinct.get("minimal_iframes") != spec["minimal_iframes"]:
        invalid.append("isolation_failed")
    if int(distinct.get("production_iframes") or 0) != int(spec["production_iframes"]):
        invalid.append("isolation_failed")
    if (
        int(distinct.get("timer_armed") or 0) > 1
        or int(distinct.get("setComponentValue_invocation") or 0) > 1
        or int(distinct.get("logical_send_postmessage") or 0) > 1
        or int(distinct.get("on_change_callback") or 0) > 1
    ):
        invalid.append("duplicate_callback_or_remount_delivery")
    missing = [k for k, v in req.items() if not v]
    if invalid:
        invalid.extend(f"missing_{k}" for k in missing)
        return {"outcome": "INVALID", "invalid_reasons": sorted(set(invalid)), "requirements": req}
    if missing:
        return {"outcome": "VALID FAIL", "invalid_reasons": [], "requirements": req, "missing": missing}
    return {"outcome": "PASS", "requirements": req}


def score_a1(distinct: dict[str, Any], *, expected_token: str) -> dict[str, Any]:
    return score_matrix_cell(distinct, cell="A1", expected_token=expected_token)


def build_distinct_counts(
    *,
    repro: dict[str, Any],
    parent_rows: list[dict[str, Any]],
    expected_token: str,
    session_raw: str,
    callback_log: list[dict[str, Any]],
    browser_send_ts: float | None,
) -> dict[str, Any]:
    sc = repro.get("stage_counts") if isinstance(repro.get("stage_counts"), dict) else {}
    token_prefix = expected_token.split("|")[0] if expected_token else ""
    matching_parent = [
        r
        for r in parent_rows
        if token_prefix and str(r.get("value_preview") or "").startswith(token_prefix)
    ]
    seen_parent: set[tuple[Any, Any]] = set()
    unique_parent: list[dict[str, Any]] = []
    for r in matching_parent:
        dedupe_key = (r.get("ts"), r.get("value_preview"))
        if dedupe_key in seen_parent:
            continue
        seen_parent.add(dedupe_key)
        unique_parent.append(r)
    raw = session_raw.strip("'\"")
    callbacks = [c for c in callback_log if isinstance(c, dict)]
    pre_send_cb = False
    pre_send_session = False
    send_n = set_component_invocation_count(sc)
    setcomp_n = count_stage(sc, "transport_postmessage_invoked")
    first_parent_ms = min((int(r.get("ts") or 0) for r in unique_parent), default=0)
    first_parent_sec = first_parent_ms / 1000.0 if first_parent_ms else None
    if raw == expected_token and send_n == 0 and setcomp_n == 0:
        observed = int(repro.get("minimal_iframes") or 0) + int(repro.get("production_iframes") or 0)
        if observed >= 1:
            pre_send_session = True
    enriched_callbacks: list[dict[str, Any]] = []
    for c in callbacks:
        cb_sec = float(c.get("ts") or 0)
        cb_ms = int(cb_sec * 1000)
        prior_parent = bool(first_parent_ms and cb_ms >= first_parent_ms - 50)
        if first_parent_ms and cb_ms < first_parent_ms - 50:
            pre_send_cb = True
        row = dict(c)
        row["parent_send_ts_ms"] = first_parent_ms or None
        row["callback_ts_sec"] = cb_sec
        row["callback_after_parent_send"] = prior_parent if first_parent_ms else None
        enriched_callbacks.append(row)
    payload_keys: list[str] = []
    widget_key_in_parent = False
    if unique_parent:
        payload_keys = list(unique_parent[0].get("payload_keys") or [])
        widget_key_in_parent = any("widget_key" in (r.get("payload_keys") or []) for r in unique_parent)
    lifecycle = {
        "timer_armed_count": count_stage(sc, "timer_armed"),
        "iframe_remount_count": count_stage(sc, "iframe_remount"),
        "tick_cancelled_count": count_stage(sc, "tick_cancelled"),
        "component_script_loaded_count": count_stage(sc, "component_script_loaded"),
        "countdown_started_count": count_stage(sc, "countdown_started"),
    }
    if callbacks and expected_token and raw != expected_token:
        for c in callbacks:
            if expected_token in str(c.get("actual_raw") or ""):
                raw = expected_token
                break
    session_matches = raw == expected_token
    return {
        "timer_armed": count_stage(sc, "timer_armed"),
        "browser_deadline_crossed": count_stage(sc, "browser_deadline_crossed"),
        "setComponentValue_invocation": set_component_invocation_count(sc),
        "logical_send_postmessage": count_stage(sc, "transport_postmessage_invoked"),
        "parent_message": len(unique_parent),
        "python_raw_receipt": 1 if session_matches else 0,
        "on_change_callback": len(callbacks),
        "session_raw_matches": session_matches,
        "session_state_raw": raw,
        "pre_send_callback": pre_send_cb,
        "pre_send_session_token": pre_send_session,
        "minimal_iframes": int(repro.get("minimal_iframes") or 0),
        "production_iframes": int(repro.get("production_iframes") or 0),
        "stage_counts": sc,
        "parent_rows_captured": unique_parent,
        "parent_message_ts_ms": first_parent_ms or None,
        "callback_log": enriched_callbacks,
        "parent_payload_keys": payload_keys,
        "widget_key_in_parent_payload": widget_key_in_parent,
        "browser_send_ts": browser_send_ts or first_parent_sec,
        "lifecycle": lifecycle,
    }


def dual_verdicts(distinct: dict[str, Any], *, cell: str, expected_token: str) -> dict[str, Any]:
    spec = CELL_SPEC.get(cell.upper()) or CELL_SPEC["A1"]
    sc = distinct.get("stage_counts") if isinstance(distinct.get("stage_counts"), dict) else {}
    lc = distinct.get("lifecycle") if isinstance(distinct.get("lifecycle"), dict) else {}
    pre_send = distinct.get("pre_send_callback") or distinct.get("pre_send_session_token")
    isolation_ok = (
        distinct.get("minimal_iframes") == spec["minimal_iframes"]
        and int(distinct.get("production_iframes") or 0) == int(spec["production_iframes"])
    )
    transport_req = {
        "browser_deadline_crossed": int(distinct.get("browser_deadline_crossed") or 0) == 1,
        "setComponentValue_invocation": int(distinct.get("setComponentValue_invocation") or 0) == 1,
        "transport_postmessage_invoked": int(distinct.get("logical_send_postmessage") or 0) == 1,
        "parent_message": int(distinct.get("parent_message") or 0) == 1,
        "python_receipt": bool(distinct.get("session_raw_matches")) or int(distinct.get("python_raw_receipt") or 0) == 1,
        "on_change_callback": int(distinct.get("on_change_callback") or 0) == 1,
    }
    dup_send = (
        int(distinct.get("setComponentValue_invocation") or 0) > 1
        or int(distinct.get("logical_send_postmessage") or 0) > 1
        or int(distinct.get("parent_message") or 0) > 1
        or int(distinct.get("on_change_callback") or 0) > 1
    )
    if pre_send or not isolation_ok:
        transport_outcome = "INVALID"
    elif all(transport_req.values()) and not dup_send:
        transport_outcome = "PASS"
    elif dup_send:
        transport_outcome = "INVALID"
    else:
        transport_outcome = "FAIL"
    timer_n = int(lc.get("timer_armed_count") or distinct.get("timer_armed") or 0)
    remount_n = int(lc.get("iframe_remount_count") or count_stage(sc, "iframe_remount"))
    tick_cancel_n = int(lc.get("tick_cancelled_count") or count_stage(sc, "tick_cancelled"))
    lifecycle_notes: list[str] = []
    if timer_n > 1:
        lifecycle_notes.append(f"timer_armed={timer_n}")
    if remount_n >= 1:
        lifecycle_notes.append(f"iframe_remount={remount_n}")
    if tick_cancel_n >= 1:
        lifecycle_notes.append(f"tick_cancelled={tick_cancel_n}")
    if dup_send:
        lifecycle_outcome = "FAIL"
    elif lifecycle_notes:
        lifecycle_outcome = "WARN"
    elif timer_n == 1 and remount_n == 0:
        lifecycle_outcome = "PASS"
    else:
        lifecycle_outcome = "PASS" if timer_n <= 1 else "WARN"
    return {
        "transport_verdict": transport_outcome,
        "transport_requirements": transport_req,
        "lifecycle_verdict": lifecycle_outcome,
        "lifecycle_detail": {
            "production_iframe_peak_count": int(distinct.get("production_iframes") or 0),
            "minimal_iframe_peak_count": int(distinct.get("minimal_iframes") or 0),
            "timer_armed_count": timer_n,
            "iframe_remount_count": remount_n,
            "tick_cancelled_count": tick_cancel_n,
            "component_script_loaded_count": int(lc.get("component_script_loaded_count") or 0),
            "duplicate_send_or_callback": dup_send,
            "notes": lifecycle_notes,
        },
    }


def attach_dual_verdicts(scored: dict[str, Any], peak: dict[str, Any], *, cell: str, expected_token: str) -> dict[str, Any]:
    dual = dual_verdicts(peak, cell=cell, expected_token=expected_token)
    scored["transport_verdict"] = dual["transport_verdict"]
    scored["lifecycle_verdict"] = dual["lifecycle_verdict"]
    scored["transport_requirements"] = dual["transport_requirements"]
    scored["lifecycle_detail"] = dual["lifecycle_detail"]
    return scored


def build_cell_record(
    *,
    cell: str,
    scored: dict[str, Any],
    peak: dict[str, Any],
    expected_token: str,
    widget_key: str,
    ls_key: str,
    cloud_sha: str,
    cloud_build: str,
    required_sha: str,
) -> dict[str, Any]:
    spec = CELL_SPEC.get(cell.upper()) or {}
    cb_log = peak.get("callback_log") or []
    cb_ts = float(cb_log[0].get("callback_ts_sec") or cb_log[0].get("ts") or 0) if cb_log else None
    return {
        **scored,
        "cell": cell,
        "frontend": spec.get("frontend"),
        "declaration_wrapper": spec.get("declaration"),
        "fresh_widget_key": widget_key,
        "fresh_local_storage_key": ls_key,
        "expected_token": expected_token,
        "cloud_sha": cloud_sha,
        "cloud_build": cloud_build,
        "required_sha": required_sha,
        "iframe_identity": spec.get("iframe_identity"),
        "iframe_counts": {
            "minimal": int(peak.get("minimal_iframes") or 0),
            "production": int(peak.get("production_iframes") or 0),
        },
        "timestamps": {
            "parent_message_ms": peak.get("parent_message_ts_ms"),
            "callback_sec": cb_ts,
            "authoritative_ordering": "parent_message_ms precedes callback => not pre-send",
        },
        "distinct": peak,
        "artifact_note": f"data/solo_wiring_{cell.lower()}_baseline.json",
    }
