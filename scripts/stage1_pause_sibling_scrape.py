"""Scrape Pause-sibling diagnostic probe from Streamlit app frame."""

from __future__ import annotations

import json
import time
from typing import Any

from streamlit_app_frame import resolve_streamlit_app_frame

PAUSE_SIBLING_IMPL_REV = "stage1_pause_sibling_probe_v1"
SIBLING_BUTTON_LABEL = "Stage1 Pause-Sibling Return Probe"

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

_GENERATION_JS = """() => {
  const ledger = document.querySelector('#solo-stage1-pause-sibling-ledger');
  const probe = document.querySelector('.stage1-pause-sibling-control-probe');
  let button = null;
  for (const b of document.querySelectorAll('button')) {
    const t = String(b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim();
    if (t === 'Stage1 Pause-Sibling Return Probe') { button = b; break; }
  }
  const btnRect = button ? button.getBoundingClientRect() : null;
  return {
    ledger_found: !!ledger,
    control_probe_found: !!probe,
    button_found: !!button,
    widget_key: probe ? (probe.getAttribute('data-widget-key') || '') : '',
    rendered: probe ? (probe.getAttribute('data-rendered') || '') : '',
    returned_true: probe ? (probe.getAttribute('data-returned-true') || '') : '',
    branch_entered: probe ? (probe.getAttribute('data-branch-entered') || '') : '',
    thread_fragment_id: probe ? (probe.getAttribute('data-thread-fragment-id') || '') : '',
    metadata_fragment_id: probe ? (probe.getAttribute('data-metadata-fragment-id') || '') : '',
    delta_path: probe ? (probe.getAttribute('data-delta-path') || '') : '',
    ledger_count: ledger ? (ledger.getAttribute('data-count') || '') : '',
    ledger_event_count: ledger ? (ledger.getAttribute('data-event-count') || '') : '',
    ledger_last_event_id: ledger ? (ledger.getAttribute('data-last-event-id') || '') : '',
    streamlit_session_id: ledger ? (ledger.getAttribute('data-streamlit-session-id') || '') : '',
    full_app_run_seq: ledger ? (ledger.getAttribute('data-full-app-run-seq') || '') : '',
    impl_rev: ledger ? (ledger.getAttribute('data-impl-rev') || '') : '',
    button_testid: button ? (button.getAttribute('data-testid') || '') : '',
    button_disabled: button ? !!button.disabled : null,
    button_visible: btnRect ? (btnRect.width > 0 && btnRect.height > 0) : false,
    button_dom_path_hint: button ? (button.closest('[data-testid=stElementContainer]') ? 'stElementContainer' : '') : '',
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


def scrape_pause_sibling_generation(page, frame=None) -> dict[str, Any]:
    """DOM generation snapshot for PRE/POST Pause comparison (non-authoritative vs counter)."""
    fr = frame if frame is not None else resolve_streamlit_app_frame(page)
    frame_url = str(fr.url or "")[:240]
    try:
        raw = fr.evaluate(_GENERATION_JS)
    except Exception as exc:
        return {"generation_found": False, "frame_url": frame_url, "error": str(exc)[:200]}
    if not isinstance(raw, dict):
        return {"generation_found": False, "frame_url": frame_url}
    out = dict(raw)
    out["frame_url"] = frame_url
    out["generation_found"] = bool(out.get("ledger_found") or out.get("control_probe_found"))
    for key in ("ledger_count", "ledger_event_count", "full_app_run_seq"):
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


def evaluate_sibling_click_pass(delta: dict[str, Any], *, expected_delta: int = 1) -> tuple[bool, dict[str, Any]]:
    if delta.get("observability_abort"):
        return False, {"failure": str(delta.get("observability_abort"))}
    last = dict(delta.get("last_event") or {})
    ok = (
        int(delta.get("count_delta") or 0) == expected_delta
        and bool(delta.get("new_event"))
        and bool(last.get("returned_true"))
        and bool(last.get("branch_entered"))
        and bool(last.get("event_id"))
    )
    ev = {
        "count_delta": delta.get("count_delta"),
        "new_event": delta.get("new_event"),
        "event_id": last.get("event_id"),
        "returned_true": last.get("returned_true"),
        "branch_entered": last.get("branch_entered"),
    }
    if not ok:
        ev["failure"] = "sibling_delivery_not_proven"
    return ok, ev


def generation_comparison(pre: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
    """Highlight fields that changed between PRE and POST Pause sibling snapshots."""
    keys = (
        "widget_key",
        "thread_fragment_id",
        "metadata_fragment_id",
        "delta_path",
        "streamlit_session_id",
        "full_app_run_seq",
        "button_testid",
        "ledger_last_event_id",
    )
    changed: dict[str, Any] = {}
    for k in keys:
        a, b = pre.get(k), post.get(k)
        if a != b:
            changed[k] = {"pre": a, "post": b}
    return {"changed_fields": changed, "pre": pre, "post": post}
