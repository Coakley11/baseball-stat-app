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
  const out = { repro_chain: "", repro_console: "", has_repro: false, has_solo: false };
  try {
    const el = document.getElementById("repro-client");
    if (el) {
      out.has_repro = true;
      out.repro_chain = el.getAttribute("data-chain") || "";
      out.repro_console = el.getAttribute("data-console") || "";
    }
    if (document.getElementById("solo-expire-client")) out.has_solo = true;
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
    return out

    """One logical send = transport_postmessage_invoked with matching token (not lifecycle duplicates)."""
    n = count_stage(stage_counts, "transport_postmessage_invoked")
    if n == 0:
        n = sum(
            1
            for r in parent_rows
            if str(r.get("value_preview") or "").startswith(expected_token.split("|")[0])
        )
    return n


def score_a1(distinct: dict[str, Any], *, expected_token: str) -> dict[str, Any]:
    req = {
        "timer_armed": distinct.get("timer_armed") == 1,
        "browser_deadline_crossed": distinct.get("browser_deadline_crossed") == 1,
        "setComponentValue_invocation": distinct.get("setComponentValue_invocation") == 1,
        "transport_postmessage_invoked": distinct.get("logical_send_postmessage") == 1,
        "parent_message": distinct.get("parent_message") == 1,
        "session_raw_matches": distinct.get("session_raw_matches") is True,
        "on_change_callback": distinct.get("on_change_callback") == 1,
    }
    pre_send_invalid = distinct.get("pre_send_callback") is True or distinct.get("pre_send_session_token") is True
    invalid: list[str] = []
    if pre_send_invalid:
        invalid.append("callback_before_browser_send")
        if distinct.get("pre_send_session_token"):
            invalid.append("session_token_before_browser_send")
    if distinct.get("minimal_iframes") != 1 or distinct.get("production_iframes", 0) != 0:
        invalid.append("isolation_failed")
    dup_stages = (
        int(distinct.get("timer_armed") or 0) > 1
        or int(distinct.get("setComponentValue_invocation") or 0) > 1
        or int(distinct.get("logical_send_postmessage") or 0) > 1
        or int(distinct.get("on_change_callback") or 0) > 1
    )
    if dup_stages:
        invalid.append("duplicate_callback_or_remount_delivery")
    for k, v in req.items():
        if not v:
            invalid.append(f"missing_{k}")
    if invalid:
        return {"outcome": "INVALID", "invalid_reasons": invalid, "requirements": req}
    return {"outcome": "PASS", "requirements": req}


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
    raw = session_raw.strip("'\"")
    callbacks = [c for c in callback_log if isinstance(c, dict)]
    pre_send_cb = False
    pre_send_session = False
    send_n = count_stage(sc, "transport_postmessage_invoked")
    setcomp_n = count_stage(sc, "setComponentValue_invoked")
    if raw == expected_token and send_n == 0 and setcomp_n == 0:
        observed = int(repro.get("minimal_iframes") or 0) + int(repro.get("production_iframes") or 0)
        if observed >= 1:
            pre_send_session = True
    for c in callbacks:
        if browser_send_ts and float(c.get("ts") or 0) < float(browser_send_ts) - 0.05:
            pre_send_cb = True
    return {
        "timer_armed": count_stage(sc, "timer_armed"),
        "browser_deadline_crossed": count_stage(sc, "browser_deadline_crossed"),
        "setComponentValue_invocation": count_stage(sc, "setComponentValue_invoked"),
        "logical_send_postmessage": count_stage(sc, "transport_postmessage_invoked"),
        "parent_message": len(matching_parent),
        "python_raw_receipt": 1 if raw == expected_token else 0,
        "on_change_callback": len(callbacks),
        "session_raw_matches": raw == expected_token,
        "pre_send_callback": pre_send_cb,
        "pre_send_session_token": pre_send_session,
        "minimal_iframes": int(repro.get("minimal_iframes") or 0),
        "production_iframes": int(repro.get("production_iframes") or 0),
        "stage_counts": sc,
        "parent_rows_captured": matching_parent,
        "callback_log": callbacks,
        "browser_send_ts": browser_send_ts,
    }
