"""Reconcile lifecycle script_run_seq (app render trace) vs ledger/transport observers."""

from __future__ import annotations

import time
from typing import Any

QUEUE1C3A2O1 = "QUEUE1C3A2O1"
QUEUE1C3A2O2 = "QUEUE1C3A2O2"

_LEDGER_DIAG_SEQ_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  const out = [];
  for (const root of roots()) {
    const el = root.querySelector('#solo-production-ledger-diag');
    if (!el) continue;
    const href = (root.defaultView && root.defaultView.location && root.defaultView.location.href) || '';
    out.push({
      frame_href: href,
      script_run_seq: el.getAttribute('data-script-run-seq') || el.getAttribute('data-run-seq') || '',
      run_id: el.getAttribute('data-run-id') || '',
      streamlit_session_id: el.getAttribute('data-streamlit-session-id') || '',
    });
  }
  return out;
}"""


def _parse_int_seq(value: Any) -> int | None:
    try:
        s = str(value or "").strip()
        if not s:
            return None
        return int(s)
    except (TypeError, ValueError):
        return None


def scrape_ledger_diag_probes(page) -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(_LEDGER_DIAG_SEQ_JS) or []
        return [r for r in raw if isinstance(r, dict)]
    except Exception:
        return []


def pick_authoritative_ledger_probe(probes: list[dict[str, Any]], *, frame_url_hint: str = "") -> dict[str, Any]:
    hint = str(frame_url_hint or "").strip()
    if hint:
        for p in probes:
            href = str(p.get("frame_href") or "")
            if href and (hint in href or href in hint or "/~/" in href and "/~/" in hint):
                return p
    for p in probes:
        href = str(p.get("frame_href") or "")
        if "/~/" in href or "~/+" in href:
            return p
    return probes[0] if probes else {}


def scrape_ledger_row_seq_stats(page) -> dict[str, Any]:
    try:
        from p8_production_start_harness import scrape_stage1_ledger_rows

        rows = scrape_stage1_ledger_rows(page) or []
    except Exception:
        rows = []
    seqs: list[int] = []
    last_row_seq: int | None = None
    if rows:
        last_row_seq = _parse_int_seq(rows[-1].get("script_run_seq"))
    for r in rows:
        if not isinstance(r, dict):
            continue
        v = _parse_int_seq(r.get("script_run_seq"))
        if v is not None:
            seqs.append(v)
    return {
        "ledger_row_count": len(rows),
        "ledger_last_row_script_run_seq": last_row_seq,
        "ledger_max_script_run_seq": max(seqs) if seqs else None,
        "ledger_min_script_run_seq": min(seqs) if seqs else None,
        "ledger_last_row_seq_source": "scrape_stage1_ledger_rows[-1].script_run_seq",
        "ledger_max_seq_source": "max(scrape_stage1_ledger_rows[*].script_run_seq)",
    }


def lifecycle_seq_from_render_trace(trace: dict[str, Any] | None) -> dict[str, Any]:
    tr = trace if isinstance(trace, dict) else {}
    return {
        "lifecycle_current_script_run_seq": _parse_int_seq(tr.get("current_script_run_seq")),
        "lifecycle_actual_card_render_run_seq": _parse_int_seq(tr.get("actual_card_render_run_seq")),
        "lifecycle_widget_last_rendered_run_seq": _parse_int_seq(tr.get("widget_last_rendered_run_seq")),
        "lifecycle_source": "rec_card_render_trace_dom",
        "lifecycle_probe_source": str(tr.get("probe_source") or ""),
        "lifecycle_widget_liveness": str(tr.get("widget_liveness") or ""),
    }


def capture_run_binding_snapshot(
    page,
    *,
    frame_url_hint: str = "",
    lifecycle_render_trace: dict[str, Any] | None = None,
    phase: str = "pre_click",
) -> dict[str, Any]:
    """Single snapshot: lifecycle DOM seq vs ledger diag vs ledger row aggregates."""
    ts = time.time()
    lifecycle = lifecycle_seq_from_render_trace(lifecycle_render_trace)
    if lifecycle_render_trace is None:
        try:
            from stage1_rec_queue_click_trace_scrape import scrape_rec_queue_render_trace

            scraped = scrape_rec_queue_render_trace(page, player_name="")
            lifecycle = lifecycle_seq_from_render_trace(scraped)
        except ImportError:
            pass

    probes = scrape_ledger_diag_probes(page)
    auth_probe = pick_authoritative_ledger_probe(probes, frame_url_hint=frame_url_hint)
    row_stats = scrape_ledger_row_seq_stats(page)

    lifecycle_seq = lifecycle.get("lifecycle_current_script_run_seq")
    if lifecycle_seq is None:
        lifecycle_seq = lifecycle.get("lifecycle_actual_card_render_run_seq")

    ledger_diag_seq = _parse_int_seq(auth_probe.get("script_run_seq"))
    ledger_max = row_stats.get("ledger_max_script_run_seq")
    ledger_last = row_stats.get("ledger_last_row_script_run_seq")

    # Authoritative ledger generation for transport is diag attr on app frame, then max row seq.
    transport_grade_seq = ledger_diag_seq if ledger_diag_seq is not None else ledger_max

    consistent = False
    mismatch_reasons: list[str] = []
    if lifecycle_seq is None:
        mismatch_reasons.append("lifecycle_seq_missing")
    if transport_grade_seq is None:
        mismatch_reasons.append("ledger_transport_seq_missing")
    if lifecycle_seq is not None and transport_grade_seq is not None:
        if lifecycle_seq == transport_grade_seq:
            consistent = True
        else:
            mismatch_reasons.append(f"lifecycle_{lifecycle_seq}_vs_ledger_grade_{transport_grade_seq}")
    if ledger_last is not None and transport_grade_seq is not None and ledger_last != transport_grade_seq:
        mismatch_reasons.append(f"ledger_last_row_{ledger_last}_stale_vs_grade_{transport_grade_seq}")
    if lifecycle_seq is not None and ledger_last is not None and lifecycle_seq != ledger_last:
        mismatch_reasons.append(f"legacy_last_row_would_be_{ledger_last}")

    return {
        "phase": phase,
        "wall_ts": ts,
        "frame_url_hint": str(frame_url_hint or "")[:280],
        "streamlit_session_id": str(auth_probe.get("streamlit_session_id") or ""),
        "ledger_diag_frame_href": str(auth_probe.get("frame_href") or "")[:280],
        **lifecycle,
        **row_stats,
        "ledger_diag_script_run_seq": ledger_diag_seq,
        "ledger_transport_grade_script_run_seq": transport_grade_seq,
        "run_binding_consistent": consistent,
        "run_binding_mismatch_reasons": mismatch_reasons,
        "ledger_diag_probe_count": len(probes),
    }


def merge_run_binding_into_transport(transport: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    out = dict(transport)
    pre = binding.get("ledger_transport_grade_script_run_seq")
    post_binding = binding if binding.get("phase") == "post_click" else {}
    post_seq = post_binding.get("ledger_transport_grade_script_run_seq", pre)
    pre_s = str(pre) if pre is not None else ""
    post_s = str(post_seq) if post_seq is not None else ""
    out["run_binding"] = binding
    out["lifecycle_script_run_seq_before"] = binding.get("lifecycle_current_script_run_seq")
    out["ledger_transport_grade_seq_before"] = pre
    out["ledger_last_row_seq_before"] = binding.get("ledger_last_row_script_run_seq")
    out["run_binding_consistent"] = bool(binding.get("run_binding_consistent"))
    out["script_run_seq_before"] = pre_s
    out["ledger_script_run_seq_after"] = post_s
    seq_changed = False
    if pre_s and post_s:
        try:
            seq_changed = int(post_s) > int(pre_s)
        except ValueError:
            seq_changed = post_s != pre_s
    out["script_run_seq_changed"] = seq_changed
    if not out.get("run_binding_consistent"):
        out["python_rerun_started"] = False
        out["python_rerun_observability_blocked"] = True
    else:
        out["python_rerun_observability_blocked"] = False
        out["python_rerun_started"] = bool(seq_changed)
    return out


def classify_run_binding_observability(pre: dict[str, Any], *, dom_capture_ok: bool = True) -> str:
    if not pre.get("run_binding_consistent"):
        return QUEUE1C3A2O1
    if not dom_capture_ok:
        return QUEUE1C3A2O2
    return ""
