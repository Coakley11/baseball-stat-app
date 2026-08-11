"""Harness helpers for out-of-band S3 diagnostic JSON readback."""

from __future__ import annotations

import json
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


def extract_oob_channel_from_readiness_scrape(scrape: dict[str, Any]) -> dict[str, Any]:
    payload = scrape.get("payload") if isinstance(scrape.get("payload"), dict) else {}
    channel = payload.get("oob_channel") if isinstance(payload.get("oob_channel"), dict) else {}
    return {
        "found": bool(scrape.get("found")),
        "parse_ok": bool(scrape.get("parse_ok")),
        "streamlit_session_id": str(payload.get("streamlit_session_id") or scrape.get("streamlit_session_id") or "")[:64],
        "diagnostic_token": str(channel.get("diagnostic_token") or "")[:32],
        "static_url_path": str(channel.get("static_url_path") or "")[:120],
        "snapshot_generation": channel.get("snapshot_generation"),
        "registered": bool(channel.get("registered")),
        "published": bool(channel.get("published")),
    }


def extract_oob_freshness_from_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    snap = dict(snapshot or {})
    summaries = snap.get("latest_ingress_summaries") if isinstance(snap.get("latest_ingress_summaries"), dict) else {}
    out: dict[str, Any] = {
        "snapshot_generation": snap.get("snapshot_generation"),
        "snapshot_server_ts": snap.get("snapshot_server_ts"),
        "streamlit_session_id": str(snap.get("streamlit_session_id") or "")[:64],
        "diagnostic_token": str(snap.get("diagnostic_token") or "")[:32],
        "publish_source": str(snap.get("publish_source") or "")[:64],
        "module_ledger_total_count": snap.get("module_ledger_total_count"),
        "critical_ledger_total_count": snap.get("critical_ledger_total_count"),
        "unrouted_event_count": snap.get("unrouted_event_count"),
        "server_wrapper_integrity_ok": snap.get("server_wrapper_integrity_ok"),
    }
    for key in INGRESS_SUMMARY_KEYS:
        row = summaries.get(key) if isinstance(summaries.get(key), dict) else {}
        out[key] = {
            "total_count": int(row.get("total_count") or 0),
            "latest_event_id": str(row.get("latest_event_id") or "")[:16],
            "latest_server_ts": row.get("latest_server_ts"),
            "latest_routing_sid": str(row.get("latest_routing_sid") or "")[:64],
            "latest_routing_source": str(row.get("latest_routing_source") or "")[:64],
        }
    return out


def compare_oob_freshness(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    gen_before = int(before.get("snapshot_generation") or 0)
    gen_after = int(after.get("snapshot_generation") or 0)
    counts_advanced = {}
    ids_changed = {}
    for key in INGRESS_SUMMARY_KEYS:
        b = before.get(key) if isinstance(before.get(key), dict) else {}
        a = after.get(key) if isinstance(after.get(key), dict) else {}
        counts_advanced[key] = int(a.get("total_count") or 0) > int(b.get("total_count") or 0)
        ids_changed[key] = bool(a.get("latest_event_id")) and a.get("latest_event_id") != b.get("latest_event_id")
    return {
        "snapshot_generation_before": gen_before,
        "snapshot_generation_after": gen_after,
        "generation_advanced": gen_after > gen_before,
        "snapshot_generation_delta": gen_after - gen_before,
        "counts_advanced": counts_advanced,
        "latest_event_ids_changed": ids_changed,
        "unrouted_count_before": int(before.get("unrouted_event_count") or 0),
        "unrouted_count_after": int(after.get("unrouted_event_count") or 0),
        "module_ledger_total_before": int(before.get("module_ledger_total_count") or 0),
        "module_ledger_total_after": int(after.get("module_ledger_total_count") or 0),
    }


def fetch_oob_snapshot_via_page(page, static_url_path: str, *, cache_bust: bool = True) -> dict[str, Any]:
    path = str(static_url_path or "").strip()
    if not path.startswith("/"):
        path = "/" + path
    origin = str(page.evaluate("() => location.origin") or "").rstrip("/")
    url = f"{origin}{path}"
    if cache_bust:
        url = f"{url}?cb={int(time.time() * 1000)}"
    out: dict[str, Any] = {"url": url, "ok": False}
    try:
        response = page.request.get(url, timeout=30_000)
        out["status"] = response.status
        out["ok"] = response.ok
        if response.ok:
            parsed = response.json()
            out["snapshot"] = dict(parsed) if isinstance(parsed, dict) else None
            out["parse_ok"] = isinstance(parsed, dict)
        else:
            out["body_preview"] = (response.text() or "")[:200]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}:{exc}"[:200]
    return out


def wait_for_oob_generation_after(
    page,
    *,
    static_url_path: str,
    min_generation: int,
    max_wait_s: float = 30.0,
    poll_interval_ms: int = 600,
) -> dict[str, Any]:
    deadline = time.time() + max_wait_s
    last_fetch: dict[str, Any] = {"ok": False}
    last_freshness: dict[str, Any] = {}
    polls = 0
    while time.time() < deadline:
        polls += 1
        last_fetch = fetch_oob_snapshot_via_page(page, static_url_path, cache_bust=True)
        snap = last_fetch.get("snapshot") if isinstance(last_fetch.get("snapshot"), dict) else {}
        last_freshness = extract_oob_freshness_from_snapshot(snap)
        gen = int(last_freshness.get("snapshot_generation") or 0)
        if last_fetch.get("ok") and gen > int(min_generation or 0):
            return {
                "ok": True,
                "poll_count": polls,
                "fetch": last_fetch,
                "freshness": last_freshness,
                "wait_s": time.time() - (deadline - max_wait_s),
            }
        page.wait_for_timeout(poll_interval_ms)
    return {
        "ok": False,
        "poll_count": polls,
        "fetch": last_fetch,
        "freshness": last_freshness,
        "min_generation_required": int(min_generation or 0),
        "wait_s": max_wait_s,
    }


def authoritative_rows_from_oob_snapshot(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    snap = dict(snapshot or {})
    module_rows = list(snap.get("module_ledger_rows") or [])
    critical_rows = list(snap.get("critical_ledger_rows") or [])
    seen: set[tuple] = set()
    merged: list[dict[str, Any]] = []
    for r in module_rows + critical_rows:
        if not isinstance(r, dict):
            continue
        key = (r.get("phase"), r.get("ts"), r.get("event_id"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(r))
    return sorted(merged, key=lambda r: float(r.get("ts") or 0))
