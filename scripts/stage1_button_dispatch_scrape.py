"""Scrape Stage1 button dispatch probe counters and dedicated event ledger."""

from __future__ import annotations

import json
from typing import Any


def scrape_button_dispatch_probe(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """() => {
            const docs = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { if (f.contentDocument) docs.push(f.contentDocument); } catch (e) {}
            }
            for (const doc of docs) {
              const el = doc.querySelector('#solo-stage1-button-dispatch-ledger');
              if (!el) continue;
              return {
                r0_count: el.getAttribute('data-r0-count') || '',
                o0_count: el.getAttribute('data-o0-count') || '',
                o1_count: el.getAttribute('data-o1-count') || '',
                o2_count: el.getAttribute('data-o2-count') || '',
                event_count: el.getAttribute('data-event-count') || '',
                last_source: el.getAttribute('data-last-source') || '',
                last_mode: el.getAttribute('data-last-mode') || '',
                last_event_id: el.getAttribute('data-last-event-id') || '',
                full_app_run_seq: el.getAttribute('data-full-app-run-seq') || '',
                streamlit_session_id: el.getAttribute('data-streamlit-session-id') || '',
                impl_rev: el.getAttribute('data-impl-rev') || '',
                json: el.getAttribute('data-json') || '',
              };
            }
            return {};
          }"""
        )
    except Exception as exc:
        return {"error": str(exc)[:200]}
    if not isinstance(raw, dict):
        return {}
    out = dict(raw)
    if out.get("json"):
        try:
            out["payload"] = json.loads(str(out["json"]).replace("'", '"'))
        except Exception:
            pass
    for key in ("r0_count", "o0_count", "o1_count", "o2_count", "event_count", "full_app_run_seq"):
        if out.get(key) not in (None, ""):
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError):
                pass
    return out


def count_for_mode(scrape: dict[str, Any], mode: str) -> int:
    m = str(mode or "").strip().upper()
    key = {"R0": "r0_count", "O0": "o0_count", "O1": "o1_count", "O2": "o2_count"}.get(m)
    if not key:
        return 0
    try:
        return int(scrape.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def dispatch_delta(before: dict[str, Any], after: dict[str, Any], mode: str) -> dict[str, Any]:
    mode_u = str(mode or "").strip().upper()
    count_key = {"R0": "r0_count", "O0": "o0_count", "O1": "o1_count", "O2": "o2_count"}.get(mode_u, "")
    before_c = int(before.get(count_key) or 0) if count_key else 0
    after_c = int(after.get(count_key) or 0) if count_key else 0
    before_ev = int(before.get("event_count") or 0)
    after_ev = int(after.get("event_count") or 0)
    last_row: dict[str, Any] = {}
    payload = after.get("payload") if isinstance(after.get("payload"), dict) else {}
    rows = list(payload.get("rows") or [])
    source = {"R0": "dispatch_r0", "O0": "dispatch_o0", "O1": "dispatch_o1", "O2": "dispatch_o2"}.get(mode_u, "")
    for row in reversed(rows):
        if isinstance(row, dict) and str(row.get("mode") or "") == mode_u:
            last_row = dict(row)
            break
    new_event = after_ev > before_ev or (after.get("last_mode") == mode_u and after.get("last_event_id") != before.get("last_event_id"))
    return {
        "count_before": before_c,
        "count_after": after_c,
        "count_delta": after_c - before_c,
        "event_count_before": before_ev,
        "event_count_after": after_ev,
        "new_dispatch_event": bool(new_event and last_row),
        "last_event": last_row,
        "full_app_run_seq_before": before.get("full_app_run_seq"),
        "full_app_run_seq_after": after.get("full_app_run_seq"),
    }
