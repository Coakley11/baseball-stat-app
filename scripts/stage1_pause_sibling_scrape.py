"""Scrape Pause-sibling diagnostic probe from Streamlit app frame."""

from __future__ import annotations

import json
import time
from typing import Any

from streamlit_app_frame import resolve_streamlit_app_frame

PAUSE_SIBLING_IMPL_REV = "stage1_pause_sibling_probe_v1"
_LEDGER_JS = """() => {
  const el = document.querySelector('#solo-stage1-pause-sibling-ledger');
  if (!el) return { probe_found: false };
  return {
    probe_found: true,
    count: el.getAttribute('data-count') || '',
    event_count: el.getAttribute('data-event-count') || '',
    last_event_id: el.getAttribute('data-last-event-id') || '',
    streamlit_session_id: el.getAttribute('data-streamlit-session-id') || '',
    full_app_run_seq: el.getAttribute('data-full-app-run-seq') || '',
    impl_rev: el.getAttribute('data-impl-rev') || '',
    json: el.getAttribute('data-json') || '',
  };
}"""


def scrape_pause_sibling_probe(page, frame=None) -> dict[str, Any]:
    fr = frame if frame is not None else resolve_streamlit_app_frame(page)
    frame_url = str(fr.url or "")[:240]
    try:
        raw = fr.evaluate(_LEDGER_JS)
    except Exception as exc:
        return {"probe_found": False, "frame_url": frame_url, "error": str(exc)[:200]}
    if not isinstance(raw, dict):
        return {"probe_found": False, "frame_url": frame_url}
    out = dict(raw)
    out["frame_url"] = frame_url
    if not out.get("probe_found"):
        out["probe_found"] = False
        return out
    out["probe_found"] = True
    if out.get("json"):
        try:
            out["payload"] = json.loads(str(out["json"]).replace("'", '"'))
        except Exception:
            out["payload"] = None
    for key in ("count", "event_count", "full_app_run_seq"):
        if key in out and out[key] not in (None, ""):
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError):
                pass
    return out


def wait_for_pause_sibling_probe(
    page,
    frame,
    *,
    timeout_s: float = 20.0,
    min_count: int | None = None,
    session_id_hint: str = "",
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    attempts = 0
    last: dict[str, Any] = {"probe_found": False}
    while time.time() < deadline:
        attempts += 1
        scrape = scrape_pause_sibling_probe(page, frame=frame)
        last = scrape
        if not scrape.get("probe_found"):
            time.sleep(0.4)
            continue
        if str(scrape.get("impl_rev") or "") != PAUSE_SIBLING_IMPL_REV:
            time.sleep(0.4)
            continue
        sid = str(scrape.get("streamlit_session_id") or "")
        if session_id_hint and sid and sid != session_id_hint and not sid.startswith(session_id_hint[:8]):
            time.sleep(0.4)
            continue
        if min_count is not None and int(scrape.get("count") or 0) < min_count:
            time.sleep(0.4)
            continue
        return {"ready": True, "attempts": attempts, "scrape": scrape}
    return {"ready": False, "attempts": attempts, "scrape": last}


def sibling_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    if not before.get("probe_found"):
        return {"observability_abort": "before_probe_missing"}
    if not after.get("probe_found"):
        return {"observability_abort": "after_probe_missing"}
    bc = int(before.get("count") or 0)
    ac = int(after.get("count") or 0)
    be = int(before.get("event_count") or 0)
    ae = int(after.get("event_count") or 0)
    last_row: dict[str, Any] = {}
    payload = after.get("payload") if isinstance(after.get("payload"), dict) else {}
    for row in reversed(list(payload.get("rows") or [])):
        if isinstance(row, dict) and row.get("event_id"):
            last_row = dict(row)
            break
    return {
        "count_before": bc,
        "count_after": ac,
        "count_delta": ac - bc,
        "event_count_before": be,
        "event_count_after": ae,
        "new_event": ae > be and bool(last_row.get("event_id")),
        "last_event": last_row,
        "full_app_run_seq_before": before.get("full_app_run_seq"),
        "full_app_run_seq_after": after.get("full_app_run_seq"),
    }
