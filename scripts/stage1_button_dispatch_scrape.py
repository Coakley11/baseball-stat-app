"""Scrape Stage1 button dispatch probe counters and dedicated event ledger."""

from __future__ import annotations

import json
import time
from typing import Any

from streamlit_app_frame import resolve_streamlit_app_frame

DISPATCH_IMPL_REV = "stage1_button_dispatch_probe_v1"
DISPATCH_LEDGER_SELECTOR = "#solo-stage1-button-dispatch-ledger"

EXPECTED_SOURCE_BY_MODE = {
    "R0": "dispatch_r0",
    "O0": "dispatch_o0",
    "O1": "dispatch_o1",
    "O2": "dispatch_o2",
}

EXPECTED_KIND_BY_MODE = {
    "R0": "return_value",
    "O0": "on_click_direct",
    "O1": "on_click_args",
    "O2": "on_click_closure",
}

_LEDGER_EVAL_JS = """() => {
  const el = document.querySelector('#solo-stage1-button-dispatch-ledger');
  if (!el) {
    return { probe_found: false };
  }
  return {
    probe_found: true,
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
}"""

_CONTROL_PROBE_JS = """(mode) => {
  const sel = '.stage1-button-dispatch-control-probe[data-mode="' + mode + '"]';
  const el = document.querySelector(sel);
  if (!el) return { marker_found: false, mode };
  return {
    marker_found: true,
    mode,
    widget_key: el.getAttribute('data-widget-key') || '',
    r0_returned_true: el.getAttribute('data-r0-returned-true') || '',
    r0_branch_entered: el.getAttribute('data-r0-branch-entered') || '',
  };
}"""


def _normalize_scrape(raw: dict[str, Any], *, frame_url: str) -> dict[str, Any]:
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
    for key in ("r0_count", "o0_count", "o1_count", "o2_count", "event_count", "full_app_run_seq"):
        if key in out and out[key] not in (None, ""):
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError):
                pass
    return out


def scrape_button_dispatch_probe(page, frame=None) -> dict[str, Any]:
    fr = frame if frame is not None else resolve_streamlit_app_frame(page)
    frame_url = str(fr.url or "")[:240]
    try:
        raw = fr.evaluate(_LEDGER_EVAL_JS)
    except Exception as exc:
        return {"probe_found": False, "frame_url": frame_url, "error": str(exc)[:200]}
    return _normalize_scrape(raw if isinstance(raw, dict) else {}, frame_url=frame_url)


def scrape_dispatch_control_marker(frame, mode: str) -> dict[str, Any]:
    mode_u = str(mode or "").strip().upper()
    try:
        raw = frame.evaluate(_CONTROL_PROBE_JS, mode_u)
    except Exception as exc:
        return {"marker_found": False, "mode": mode_u, "error": str(exc)[:160]}
    return dict(raw) if isinstance(raw, dict) else {"marker_found": False, "mode": mode_u}


def _button_visible(frame, label: str) -> bool:
    try:
        loc = frame.get_by_role("button", name=label, exact=True)
        if loc.count() == 0:
            return False
        return bool(loc.first.is_visible())
    except Exception:
        return False


def scrape_dispatch_surface_continuity(
    page,
    frame,
    *,
    control_labels: dict[str, str],
) -> dict[str, Any]:
    ledger = scrape_button_dispatch_probe(page, frame=frame)
    modes = ("R0", "O0", "O1", "O2")
    markers = {m: scrape_dispatch_control_marker(frame, m) for m in modes}
    buttons = {m: _button_visible(frame, control_labels[m]) for m in modes}
    return {
        "aggregate_ledger_present": bool(ledger.get("probe_found")),
        "ledger_impl_rev": ledger.get("impl_rev"),
        "streamlit_session_id": ledger.get("streamlit_session_id"),
        "full_app_run_seq": ledger.get("full_app_run_seq"),
        "frame_url": str(frame.url or "")[:240],
        "markers": markers,
        "buttons_visible": buttons,
        "counters": {
            "r0": ledger.get("r0_count"),
            "o0": ledger.get("o0_count"),
            "o1": ledger.get("o1_count"),
            "o2": ledger.get("o2_count"),
            "event_count": ledger.get("event_count"),
        },
    }


def validate_pre_r0_ledger(scrape: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not scrape.get("probe_found"):
        reasons.append("ledger_not_found")
        return False, reasons
    if str(scrape.get("impl_rev") or "") != DISPATCH_IMPL_REV:
        reasons.append(f"impl_rev_mismatch:{scrape.get('impl_rev')}")
    if not str(scrape.get("streamlit_session_id") or "").strip():
        reasons.append("streamlit_session_id_empty")
    for key in ("r0_count", "o0_count", "o1_count", "o2_count", "event_count"):
        if key not in scrape or scrape[key] is None or scrape[key] == "":
            reasons.append(f"counter_unreadable:{key}")
    return (len(reasons) == 0, reasons)


def wait_for_dispatch_probe(
    page,
    frame,
    *,
    timeout_s: float = 20.0,
    session_id_hint: str = "",
    poll_ms: int = 400,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {"probe_found": False}
    attempts = 0
    while time.time() < deadline:
        attempts += 1
        scrape = scrape_button_dispatch_probe(page, frame=frame)
        last = scrape
        ok, _ = validate_pre_r0_ledger(scrape)
        sid = str(scrape.get("streamlit_session_id") or "")
        sid_ok = not session_id_hint or sid == session_id_hint or sid.startswith(session_id_hint[:8])
        if scrape.get("probe_found") and ok and sid_ok:
            return {"ready": True, "attempts": attempts, "scrape": scrape, "waited_s": timeout_s - (deadline - time.time())}
        time.sleep(poll_ms / 1000.0)
    return {"ready": False, "attempts": attempts, "scrape": last, "waited_s": timeout_s}


def dispatch_delta(
    before: dict[str, Any],
    after: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    mode_u = str(mode or "").strip().upper()
    count_key = {"R0": "r0_count", "O0": "o0_count", "O1": "o1_count", "O2": "o2_count"}.get(mode_u, "")
    out: dict[str, Any] = {"mode": mode_u, "observability_abort": None}

    if not before.get("probe_found"):
        out["observability_abort"] = "before_probe_missing"
        return out
    if not after.get("probe_found"):
        out["observability_abort"] = "after_probe_missing"
        return out

    before_c = int(before.get(count_key) or 0) if count_key else 0
    after_c = int(after.get(count_key) or 0) if count_key else 0
    before_ev = int(before.get("event_count") or 0)
    after_ev = int(after.get("event_count") or 0)
    last_row: dict[str, Any] = {}
    payload = after.get("payload") if isinstance(after.get("payload"), dict) else {}
    rows = list(payload.get("rows") or [])
    for row in reversed(rows):
        if isinstance(row, dict) and str(row.get("mode") or "") == mode_u:
            last_row = dict(row)
            break
    new_event = after_ev > before_ev and bool(last_row.get("event_id"))
    out.update(
        {
            "count_before": before_c,
            "count_after": after_c,
            "count_delta": after_c - before_c,
            "event_count_before": before_ev,
            "event_count_after": after_ev,
            "new_dispatch_event": new_event,
            "last_event": last_row,
            "full_app_run_seq_before": before.get("full_app_run_seq"),
            "full_app_run_seq_after": after.get("full_app_run_seq"),
        }
    )
    return out


def evaluate_dispatch_pass(
    delta: dict[str, Any],
    after: dict[str, Any],
    mode: str,
) -> tuple[bool, dict[str, Any]]:
    mode_u = str(mode or "").strip().upper()
    evidence: dict[str, Any] = {"mode": mode_u}
    if delta.get("observability_abort"):
        evidence["failure"] = delta["observability_abort"]
        return False, evidence
    if int(delta.get("count_delta") or 0) != 1:
        evidence["failure"] = "count_delta_not_one"
        evidence["count_delta"] = delta.get("count_delta")
        return False, evidence
    last = dict(delta.get("last_event") or {})
    if not last.get("event_id"):
        evidence["failure"] = "missing_event_id"
        return False, evidence
    if str(last.get("source") or "") != EXPECTED_SOURCE_BY_MODE.get(mode_u, ""):
        evidence["failure"] = "unexpected_source"
        evidence["source"] = last.get("source")
        return False, evidence
    if str(last.get("dispatch_kind") or "") != EXPECTED_KIND_BY_MODE.get(mode_u, ""):
        evidence["failure"] = "unexpected_dispatch_kind"
        evidence["dispatch_kind"] = last.get("dispatch_kind")
        return False, evidence
    evidence["event_id"] = last.get("event_id")
    evidence["source"] = last.get("source")
    evidence["dispatch_kind"] = last.get("dispatch_kind")

    if mode_u == "R0":
        payload = after.get("payload") if isinstance(after.get("payload"), dict) else {}
        r0_render = dict(payload.get("r0_last_render") or {})
        evidence["r0_last_render"] = r0_render

        def _truthy(v: Any) -> bool:
            return v is True or v == 1 or str(v).lower() in ("1", "true")

        if not _truthy(r0_render.get("returned_true")):
            evidence["failure"] = "returned_true_not_set"
            return False, evidence
        if not _truthy(r0_render.get("branch_entered")):
            evidence["failure"] = "branch_entered_not_set"
            return False, evidence

    return True, evidence
