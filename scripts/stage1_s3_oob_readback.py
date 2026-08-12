"""Harness helpers for out-of-band S3 diagnostic JSON readback."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

INGRESS_SUMMARY_KEYS = (
    "runtime_backmsg",
    "appsession_backmsg",
    "appsession_request_rerun",
    "safe_sessionstate_receive",
    "server_receive",
    "server_state_applied",
)

OOB_LEDGER_PHASE = "S3_OOB_CHANNEL_REGISTERED"


def extract_oob_channel_from_readiness_scrape(scrape: dict[str, Any]) -> dict[str, Any]:
    """Extract channel fields from a readiness scrape (selected candidate or legacy payload)."""
    selected = scrape.get("selected_candidate") if isinstance(scrape.get("selected_candidate"), dict) else {}
    if selected:
        return {
            "found": bool(scrape.get("found")),
            "parse_ok": bool(selected.get("parse_ok")),
            "streamlit_session_id": str(selected.get("streamlit_session_id") or "")[:64],
            "diagnostic_token": str(selected.get("diagnostic_token") or "")[:32],
            "static_url_path": str(selected.get("static_url_path") or "")[:120],
            "snapshot_generation": selected.get("snapshot_generation"),
            "registered": bool(selected.get("oob_channel_registered")),
            "published": bool(selected.get("published")),
            "discovery_source": str(scrape.get("discovery_source") or "readiness_scrape")[:64],
        }
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
        "discovery_source": str(scrape.get("discovery_source") or "readiness_scrape")[:64],
    }


def iter_s3_ledger_rows(ledger_scrape: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = (ledger_scrape or {}).get("payload") if isinstance((ledger_scrape or {}).get("payload"), dict) else {}
    ledger = payload.get("ledger") if isinstance(payload.get("ledger"), dict) else {}
    collections = ("rows", "module_rows", "merged_rows", "critical_server_rows", "local_rows")
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for key in collections:
        rows = ledger.get(key) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            event_id = str(row.get("event_id") or "")
            if event_id:
                if event_id in seen:
                    continue
                seen.add(event_id)
            merged.append(dict(row))
    return merged


def _candidate_from_readiness_row(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {}
    channel = payload.get("oob_channel") if isinstance(payload.get("oob_channel"), dict) else {}
    sid = str(
        payload.get("streamlit_session_id")
        or candidate.get("streamlit_session_id")
        or candidate.get("dom_streamlit_session_id")
        or ""
    )[:64]
    return {
        "dom_index": candidate.get("dom_index"),
        "parse_ok": bool(candidate.get("parse_ok")),
        "streamlit_session_id": sid,
        "oob_channel_registered": bool(channel.get("registered")),
        "registered": bool(channel.get("registered")),
        "published": bool(channel.get("published")),
        "diagnostic_token": str(channel.get("diagnostic_token") or "")[:32],
        "static_url_path": str(channel.get("static_url_path") or "")[:120],
        "snapshot_generation": channel.get("snapshot_generation"),
    }


def select_valid_readiness_candidate(
    candidates: list[dict[str, Any]],
    *,
    expected_streamlit_sid: str = "",
) -> tuple[dict[str, Any] | None, str]:
    expected = str(expected_streamlit_sid or "").strip()[:64]
    valid: list[dict[str, Any]] = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        row = _candidate_from_readiness_row(raw)
        if not row.get("parse_ok"):
            continue
        sid = str(row.get("streamlit_session_id") or "")
        if expected and sid and sid != expected:
            continue
        if not row.get("oob_channel_registered"):
            continue
        if not str(row.get("diagnostic_token") or "").strip():
            continue
        if not str(row.get("static_url_path") or "").strip():
            continue
        valid.append(row)
    if not valid:
        return None, "no_valid_readiness_candidate"
    if len(valid) == 1:
        return valid[0], "single_valid_readiness_candidate"
    return valid[-1], "last_dom_order_valid_readiness_candidate"


def _channel_from_ledger_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "found": True,
        "parse_ok": True,
        "streamlit_session_id": str(row.get("streamlit_session_id") or "")[:64],
        "diagnostic_token": str(row.get("diagnostic_token") or "")[:32],
        "static_url_path": str(row.get("static_url_path") or "")[:120],
        "snapshot_generation": row.get("snapshot_generation"),
        "registered": bool(row.get("registered")),
        "published": bool(row.get("published")),
        "discovery_source": "ledger_s3_oob_channel_registered",
        "ledger_event_id": str(row.get("event_id") or "")[:16],
        "publish_source": str(row.get("publish_source") or "")[:64],
    }


def resolve_oob_channel_from_ledger(
    ledger_scrape: dict[str, Any] | None,
    *,
    expected_streamlit_sid: str,
) -> tuple[dict[str, Any] | None, str]:
    expected = str(expected_streamlit_sid or "").strip()[:64]
    matches: list[dict[str, Any]] = []
    for row in iter_s3_ledger_rows(ledger_scrape):
        if str(row.get("phase") or "") != OOB_LEDGER_PHASE:
            continue
        sid = str(row.get("streamlit_session_id") or "")[:64]
        if expected and sid and sid != expected:
            continue
        if not bool(row.get("registered")):
            continue
        token = str(row.get("diagnostic_token") or "").strip()
        path = str(row.get("static_url_path") or "").strip()
        if not token or not path:
            continue
        matches.append(row)
    if not matches:
        return None, "ledger_oob_event_missing"
    latest = sorted(matches, key=lambda r: float(r.get("ts") or 0))[-1]
    return _channel_from_ledger_event(latest), "ledger_s3_oob_channel_registered"


def validate_oob_channel_identity(
    channel: dict[str, Any],
    *,
    expected_streamlit_sid: str,
) -> tuple[bool, str]:
    expected = str(expected_streamlit_sid or "").strip()[:64]
    sid = str(channel.get("streamlit_session_id") or "").strip()[:64]
    token = str(channel.get("diagnostic_token") or "").strip()[:32]
    path = str(channel.get("static_url_path") or "").strip()[:120]
    if expected and sid and sid != expected:
        return False, "oob_channel_sid_mismatch"
    if not token or not path:
        return False, "oob_channel_discovery_missing"
    if token not in path:
        return False, "oob_token_path_mismatch"
    if not bool(channel.get("registered")):
        return False, "oob_channel_discovery_missing"
    return True, ""


def resolve_oob_channel(
    *,
    readiness_scrape: dict[str, Any] | None,
    ledger_scrape: dict[str, Any] | None,
    expected_streamlit_sid: str,
) -> dict[str, Any]:
    readiness = dict(readiness_scrape or {})
    candidates = list(readiness.get("candidates") or [])
    selected, readiness_reason = select_valid_readiness_candidate(
        candidates, expected_streamlit_sid=expected_streamlit_sid
    )
    out: dict[str, Any] = {
        "expected_streamlit_session_id": str(expected_streamlit_sid or "")[:64],
        "readiness_candidate_count": len(candidates),
        "readiness_candidates": candidates,
        "readiness_selection_reason": readiness_reason,
        "discovery_source": "",
        "selection_reason": "",
        "resolved_channel": {},
    }
    if selected is not None:
        channel = {
            "found": True,
            "parse_ok": True,
            "streamlit_session_id": str(selected.get("streamlit_session_id") or "")[:64],
            "diagnostic_token": str(selected.get("diagnostic_token") or "")[:32],
            "static_url_path": str(selected.get("static_url_path") or "")[:120],
            "snapshot_generation": selected.get("snapshot_generation"),
            "registered": bool(selected.get("registered")),
            "published": bool(selected.get("published")),
            "discovery_source": "readiness_candidate",
            "readiness_dom_index": selected.get("dom_index"),
        }
        ok, note = validate_oob_channel_identity(channel, expected_streamlit_sid=expected_streamlit_sid)
        if ok:
            out["discovery_source"] = "readiness_candidate"
            out["selection_reason"] = readiness_reason
            out["resolved_channel"] = channel
            return out
        out["identity_validation_note"] = note
    ledger_channel, ledger_reason = resolve_oob_channel_from_ledger(
        ledger_scrape, expected_streamlit_sid=expected_streamlit_sid
    )
    if ledger_channel is not None:
        ok, note = validate_oob_channel_identity(ledger_channel, expected_streamlit_sid=expected_streamlit_sid)
        if ok:
            out["discovery_source"] = "ledger_s3_oob_channel_registered"
            out["selection_reason"] = ledger_reason
            out["resolved_channel"] = ledger_channel
            return out
        out["identity_validation_note"] = note
    out["discovery_source"] = "none"
    out["selection_reason"] = out.get("identity_validation_note") or readiness_reason or ledger_reason
    return out


def validate_oob_snapshot_identity(
    snapshot: dict[str, Any] | None,
    *,
    expected_streamlit_sid: str,
    expected_token: str,
    fetch: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    fetch = dict(fetch or {})
    if fetch.get("reason") == "empty_static_url_path":
        return False, "oob_channel_discovery_missing"
    if fetch.get("reason") == "oob_connected_server_uri_unresolved":
        return False, "oob_connected_server_uri_unresolved"
    if fetch and fetch.get("http_ok") and not fetch.get("parse_ok"):
        return False, "oob_static_fetch_not_json"
    if not fetch.get("ok"):
        return False, "oob_channel_missing_or_unreadable"
    snap = dict(snapshot or {})
    expected_sid = str(expected_streamlit_sid or "").strip()[:64]
    expected_tok = str(expected_token or "").strip()[:32]
    snap_sid = str(snap.get("streamlit_session_id") or "").strip()[:64]
    snap_tok = str(snap.get("diagnostic_token") or "").strip()[:32]
    if expected_sid and snap_sid and snap_sid != expected_sid:
        return False, "oob_snapshot_sid_mismatch"
    if expected_tok and snap_tok and snap_tok != expected_tok:
        return False, "oob_snapshot_token_mismatch"
    if int(snap.get("snapshot_generation") or 0) < 1:
        return False, "oob_channel_missing_or_unreadable"
    if not str(snap.get("publish_source") or "").strip():
        return False, "oob_channel_missing_or_unreadable"
    return True, ""


def fetch_oob_snapshot_via_page(
    page,
    static_url_path: str,
    *,
    cache_bust: bool = True,
    connected_server_uri: str | None = None,
    require_connected_server_uri: bool = False,
    allow_origin_fallback: bool = True,
) -> dict[str, Any]:
    """Fetch OOB JSON via page.request.

    Production Cloud must pass connected_server_uri (e.g. .../~/+) and
    require_connected_server_uri=True so bare location.origin is never used.
    Local/unit tests may omit the URI and fall back to location.origin.
    """
    from stage1_s3_connected_server_uri import join_connected_server_static_url

    path = str(static_url_path or "").strip()
    if not path:
        return {
            "url": "",
            "ok": False,
            "reason": "empty_static_url_path",
            "http_ok": False,
            "parse_ok": False,
            "snapshot_present": False,
        }
    if not path.startswith("/"):
        path = "/" + path

    base = str(connected_server_uri or "").strip().rstrip("/")
    base_source = "connected_server_uri"
    if not base:
        if require_connected_server_uri or not allow_origin_fallback:
            return {
                "url": "",
                "ok": False,
                "reason": "oob_connected_server_uri_unresolved",
                "http_ok": False,
                "parse_ok": False,
                "snapshot_present": False,
                "http_request_attempted": False,
            }
        base = str(page.evaluate("() => location.origin") or "").rstrip("/")
        base_source = "location_origin_fallback"

    url = join_connected_server_static_url(base, path)
    if cache_bust:
        url = f"{url}?cb={int(time.time() * 1000)}"
    out: dict[str, Any] = {
        "url": url,
        "ok": False,
        "http_ok": False,
        "parse_ok": False,
        "snapshot_present": False,
        "connected_server_uri": base,
        "url_base_source": base_source,
        "static_url_path": path,
        "http_request_attempted": True,
    }
    try:
        response = page.request.get(url, timeout=30_000)
        status = int(getattr(response, "status", 0) or 0)
        out["status"] = status
        out["http_ok"] = 200 <= status < 300
        headers = getattr(response, "headers", {}) or {}
        out["content_type"] = str(headers.get("content-type") or headers.get("Content-Type") or "")[:120]
        body = response.text() or ""
        if not out["http_ok"]:
            out["body_preview"] = body[:200]
            return out
        try:
            parsed = json.loads(body)
        except Exception as exc:
            out["parse_error"] = f"{type(exc).__name__}:{exc}"[:200]
            out["body_preview"] = body[:200]
            return out
        out["parse_ok"] = isinstance(parsed, dict)
        out["snapshot_present"] = isinstance(parsed, dict)
        if isinstance(parsed, dict):
            out["snapshot"] = dict(parsed)
        out["ok"] = bool(out["http_ok"] and out["parse_ok"] and out["snapshot_present"])
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}:{exc}"[:200]
    return out


def run_oob_discovery_pipeline(
    *,
    readiness_scrape: dict[str, Any],
    ledger_scrape: dict[str, Any],
    expected_streamlit_sid: str,
    page=None,
    fetch_fn: Callable[..., dict[str, Any]] | None = None,
    connected_server_uri: str | None = None,
    require_connected_server_uri: bool = False,
) -> dict[str, Any]:
    resolution = resolve_oob_channel(
        readiness_scrape=readiness_scrape,
        ledger_scrape=ledger_scrape,
        expected_streamlit_sid=expected_streamlit_sid,
    )
    channel = dict(resolution.get("resolved_channel") or {})
    identity_ok, identity_note = validate_oob_channel_identity(
        channel, expected_streamlit_sid=expected_streamlit_sid
    )
    out: dict[str, Any] = {
        **resolution,
        "identity_ok": identity_ok,
        "identity_note": identity_note,
        "resolved_channel": channel,
        "initial_fetch": {"ok": False},
        "snapshot_validation_ok": False,
        "snapshot_validation_note": "",
        "ok": False,
        "connected_server_uri": str(connected_server_uri or ""),
        "require_connected_server_uri": bool(require_connected_server_uri),
    }
    if not identity_ok or not channel:
        out["snapshot_validation_note"] = identity_note or resolution.get("selection_reason") or "oob_channel_discovery_missing"
        return out
    if require_connected_server_uri and not str(connected_server_uri or "").strip():
        fetch = {
            "ok": False,
            "reason": "oob_connected_server_uri_unresolved",
            "http_ok": False,
            "parse_ok": False,
            "snapshot_present": False,
            "http_request_attempted": False,
        }
        out["initial_fetch"] = fetch
        out["snapshot_validation_ok"] = False
        out["snapshot_validation_note"] = "oob_connected_server_uri_unresolved"
        out["pre_oob_snapshot"] = {}
        return out
    fetch = {"ok": False, "reason": "fetch_not_requested"}
    if page is not None:
        fetcher = fetch_fn or fetch_oob_snapshot_via_page
        fetch = fetcher(
            page,
            str(channel.get("static_url_path") or ""),
            connected_server_uri=connected_server_uri,
            require_connected_server_uri=require_connected_server_uri,
            allow_origin_fallback=not require_connected_server_uri,
        )
    out["initial_fetch"] = fetch
    snapshot = fetch.get("snapshot") if isinstance(fetch.get("snapshot"), dict) else {}
    snap_ok, snap_note = validate_oob_snapshot_identity(
        snapshot,
        expected_streamlit_sid=expected_streamlit_sid,
        expected_token=str(channel.get("diagnostic_token") or ""),
        fetch=fetch,
    )
    out["snapshot_validation_ok"] = snap_ok
    out["snapshot_validation_note"] = snap_note
    out["pre_oob_snapshot"] = dict(snapshot)
    out["ok"] = bool(identity_ok and snap_ok and fetch.get("ok"))
    return out


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


def wait_for_oob_generation_after(
    page,
    *,
    static_url_path: str,
    min_generation: int,
    max_wait_s: float = 30.0,
    poll_interval_ms: int = 600,
    connected_server_uri: str | None = None,
    require_connected_server_uri: bool = False,
) -> dict[str, Any]:
    if require_connected_server_uri and not str(connected_server_uri or "").strip():
        return {
            "ok": False,
            "poll_count": 0,
            "fetch": {
                "ok": False,
                "reason": "oob_connected_server_uri_unresolved",
                "http_ok": False,
                "parse_ok": False,
                "snapshot_present": False,
                "http_request_attempted": False,
            },
            "freshness": {},
            "min_generation_required": int(min_generation or 0),
            "wait_s": 0.0,
            "reason": "oob_connected_server_uri_unresolved",
        }
    deadline = time.time() + max_wait_s
    last_fetch: dict[str, Any] = {"ok": False}
    last_freshness: dict[str, Any] = {}
    polls = 0
    while time.time() < deadline:
        polls += 1
        last_fetch = fetch_oob_snapshot_via_page(
            page,
            static_url_path,
            cache_bust=True,
            connected_server_uri=connected_server_uri,
            require_connected_server_uri=require_connected_server_uri,
            allow_origin_fallback=not require_connected_server_uri,
        )
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
