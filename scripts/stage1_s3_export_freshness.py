"""S3 DOM export freshness / correlation helpers (harness-only, diagnostic)."""

from __future__ import annotations

import time
from typing import Any

INGRESS_SUMMARY_KEYS = (
    "runtime_backmsg",
    "appsession_backmsg",
    "appsession_request_rerun",
    "safe_sessionstate_receive",
    "server_receive",
    "server_state_applied",
)


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _summary_slice(summary: dict[str, Any] | None) -> dict[str, Any]:
    s = dict(summary or {})
    return {
        "total_count": int(s.get("total_count") or 0),
        "latest_event_id": str(s.get("latest_event_id") or "")[:16],
        "latest_server_ts": s.get("latest_server_ts"),
        "latest_routing_sid": str(s.get("latest_routing_sid") or "")[:64],
        "latest_routing_source": str(s.get("latest_routing_source") or "")[:64],
    }


def extract_export_freshness_from_scrape(
    scrape: dict[str, Any],
    *,
    local_scrape_ts: float | None = None,
) -> dict[str, Any]:
    """Extract generation / ingress summaries from an S3 ledger DOM scrape."""
    payload = scrape.get("payload") if isinstance(scrape.get("payload"), dict) else {}
    meta = payload.get("export_meta") if isinstance(payload.get("export_meta"), dict) else {}
    summaries = payload.get("latest_ingress_summaries") if isinstance(payload.get("latest_ingress_summaries"), dict) else {}

    export_generation = _coerce_int(
        scrape.get("export_generation")
        or payload.get("export_generation")
        or meta.get("export_generation")
    )
    export_generated_server_ts = _coerce_float(
        scrape.get("export_generated_server_ts")
        or payload.get("export_generated_server_ts")
        or meta.get("export_generated_server_ts")
    )
    local_ts = float(local_scrape_ts if local_scrape_ts is not None else time.time())
    offset = None
    if export_generated_server_ts is not None:
        offset = float(export_generated_server_ts) - local_ts

    out: dict[str, Any] = {
        "found": bool(scrape.get("found")),
        "parse_ok": bool(scrape.get("parse_ok")),
        "export_generation": export_generation,
        "export_generated_server_ts": export_generated_server_ts,
        "local_scrape_ts": local_ts,
        "server_local_ts_offset": offset,
        "streamlit_session_id": str(
            payload.get("streamlit_session_id") or scrape.get("streamlit_session_id") or ""
        )[:64],
        "script_run_seq": _coerce_int(payload.get("script_run_seq") or meta.get("script_run_seq")),
        "diagnostic_run_id": str(payload.get("diagnostic_run_id") or meta.get("diagnostic_run_id") or "")[:64],
        "module_ledger_total_count": _coerce_int(
            payload.get("module_ledger_total_count") or meta.get("module_ledger_total_count")
        ),
        "critical_ledger_total_count": _coerce_int(
            payload.get("critical_ledger_total_count") or meta.get("critical_ledger_total_count")
        ),
        "unrouted_ledger_total_count": _coerce_int(
            payload.get("unrouted_ledger_total_count") or meta.get("unrouted_ledger_total_count")
        ),
        "unrouted_count": _coerce_int(
            (payload.get("unrouted_events") or {}).get("event_count")
            if isinstance(payload.get("unrouted_events"), dict)
            else None
        )
        or _coerce_int(meta.get("unrouted_ledger_total_count")),
    }
    for key in INGRESS_SUMMARY_KEYS:
        out[key] = _summary_slice(summaries.get(key) if isinstance(summaries.get(key), dict) else {})
    return out


def compare_export_freshness(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare two freshness baselines using generation and event IDs/counts (not wall clock)."""
    gen_before = _coerce_int(before.get("export_generation")) or 0
    gen_after = _coerce_int(after.get("export_generation")) or 0
    counts_advanced: dict[str, bool] = {}
    latest_event_ids_changed: dict[str, bool] = {}
    for key in INGRESS_SUMMARY_KEYS:
        b = before.get(key) if isinstance(before.get(key), dict) else {}
        a = after.get(key) if isinstance(after.get(key), dict) else {}
        counts_advanced[key] = int(a.get("total_count") or 0) > int(b.get("total_count") or 0)
        latest_event_ids_changed[key] = bool(a.get("latest_event_id")) and a.get("latest_event_id") != b.get(
            "latest_event_id"
        )
    unrouted_before = _coerce_int(before.get("unrouted_count")) or 0
    unrouted_after = _coerce_int(after.get("unrouted_count")) or 0
    return {
        "export_generation_before": gen_before,
        "export_generation_after": gen_after,
        "generation_advanced": gen_after > gen_before,
        "export_generation_delta": gen_after - gen_before,
        "counts_advanced": counts_advanced,
        "latest_event_ids_changed": latest_event_ids_changed,
        "unrouted_count_before": unrouted_before,
        "unrouted_count_after": unrouted_after,
        "unrouted_count_advanced": unrouted_after > unrouted_before,
        "module_ledger_total_before": _coerce_int(before.get("module_ledger_total_count")) or 0,
        "module_ledger_total_after": _coerce_int(after.get("module_ledger_total_count")) or 0,
        "module_ledger_total_advanced": (_coerce_int(after.get("module_ledger_total_count")) or 0)
        > (_coerce_int(before.get("module_ledger_total_count")) or 0),
    }


def wait_for_export_generation_after(
    page,
    *,
    min_generation: int,
    max_wait_s: float = 30.0,
    poll_interval_ms: int = 600,
) -> dict[str, Any]:
    """Poll S3 ledger until export_generation exceeds min_generation."""
    from stage1_s3_server_registry_scrape import scrape_s3_server_diag_ledger

    deadline = time.time() + max_wait_s
    last_scrape: dict[str, Any] = {"found": False}
    last_freshness: dict[str, Any] = {}
    polls = 0
    while time.time() < deadline:
        polls += 1
        local_ts = time.time()
        last_scrape = scrape_s3_server_diag_ledger(page)
        last_freshness = extract_export_freshness_from_scrape(last_scrape, local_scrape_ts=local_ts)
        gen = _coerce_int(last_freshness.get("export_generation")) or 0
        if last_scrape.get("found") and last_scrape.get("parse_ok") and gen > int(min_generation or 0):
            return {
                "ok": True,
                "poll_count": polls,
                "scrape": last_scrape,
                "freshness": last_freshness,
                "wait_s": time.time() - (deadline - max_wait_s),
            }
        page.wait_for_timeout(poll_interval_ms)
    return {
        "ok": False,
        "poll_count": polls,
        "scrape": last_scrape,
        "freshness": last_freshness,
        "min_generation_required": int(min_generation or 0),
        "wait_s": max_wait_s,
    }
