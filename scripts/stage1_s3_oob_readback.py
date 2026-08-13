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


# Post-Pause OOB settling (harness-only). First advanced generation is not authoritative
# when runtime may publish further generations asynchronously after Pause.
OOB_SETTLE_POLL_INTERVAL_MS = 500
OOB_SETTLE_STABLE_POLLS_REQUIRED = 4
OOB_SETTLE_MIN_SETTLE_S = 2.0
OOB_SETTLE_MAX_WAIT_S_BEFORE_ADVANCE = 30.0
OOB_SETTLE_MAX_SETTLE_S_AFTER_ADVANCE = 12.0


def wait_for_oob_settled_after(
    page,
    *,
    static_url_path: str,
    min_generation: int,
    poll_interval_ms: int = OOB_SETTLE_POLL_INTERVAL_MS,
    stable_polls_required: int = OOB_SETTLE_STABLE_POLLS_REQUIRED,
    min_settle_s: float = OOB_SETTLE_MIN_SETTLE_S,
    max_wait_s_before_advance: float = OOB_SETTLE_MAX_WAIT_S_BEFORE_ADVANCE,
    max_settle_s_after_advance: float = OOB_SETTLE_MAX_SETTLE_S_AFTER_ADVANCE,
    connected_server_uri: str | None = None,
    require_connected_server_uri: bool = False,
    sleep_fn: Callable[[float], None] | None = None,
    time_fn: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Wait until OOB generation advances past min_generation and then becomes quiescent.

    Retains the newest valid snapshot. Does not treat the first advanced generation as final.
    Quiescence (stable generation across consecutive polls / min settle window) is authoritative;
    absence of a later publish_source does not block settling.
    """
    now = time_fn or time.time
    sleep = sleep_fn
    min_gen = int(min_generation or 0)
    stable_need = max(1, int(stable_polls_required or 1))
    poll_ms = max(1, int(poll_interval_ms or OOB_SETTLE_POLL_INTERVAL_MS))
    min_settle = float(min_settle_s or 0.0)
    max_before = float(max_wait_s_before_advance or 0.0)
    max_after = float(max_settle_s_after_advance or 0.0)

    def _fail_unresolved() -> dict[str, Any]:
        return {
            "ok": False,
            "min_generation_required": min_gen,
            "first_advanced_generation": None,
            "final_generation": None,
            "final_publish_source": "",
            "poll_count": 0,
            "wait_s": 0.0,
            "settle_reason": "oob_connected_server_uri_unresolved",
            "stable_poll_count": 0,
            "generations_observed": [],
            "publish_sources_observed": [],
            "fetch": {
                "ok": False,
                "reason": "oob_connected_server_uri_unresolved",
                "http_ok": False,
                "parse_ok": False,
                "snapshot_present": False,
                "http_request_attempted": False,
            },
            "freshness": {},
        }

    if require_connected_server_uri and not str(connected_server_uri or "").strip():
        return _fail_unresolved()

    started = now()
    first_advance_ts: float | None = None
    last_change_ts: float | None = None
    first_advanced_generation: int | None = None
    last_fetch: dict[str, Any] = {"ok": False}
    last_freshness: dict[str, Any] = {}
    last_ok_fetch: dict[str, Any] = {"ok": False}
    last_ok_freshness: dict[str, Any] = {}
    polls = 0
    stable_polls = 0
    current_gen = 0
    generations_observed: list[int] = []
    publish_sources_observed: list[str] = []

    def _deadline() -> float:
        if first_advance_ts is None:
            return started + max_before
        return first_advance_ts + max_after

    while now() < _deadline():
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
        pub = str(last_freshness.get("publish_source") or "")[:64]

        if last_fetch.get("ok") and gen > 0:
            last_ok_fetch = last_fetch
            last_ok_freshness = last_freshness
            if not generations_observed or generations_observed[-1] != gen:
                generations_observed.append(gen)
            if pub and (not publish_sources_observed or publish_sources_observed[-1] != pub):
                publish_sources_observed.append(pub)

            if gen > min_gen:
                if first_advanced_generation is None:
                    first_advanced_generation = gen
                    first_advance_ts = now()
                    last_change_ts = first_advance_ts
                    current_gen = gen
                    stable_polls = 1
                elif gen > current_gen:
                    current_gen = gen
                    last_change_ts = now()
                    stable_polls = 1
                elif gen == current_gen:
                    stable_polls += 1
                else:
                    # Generation went backwards — treat as a new observation point.
                    current_gen = gen
                    last_change_ts = now()
                    stable_polls = 1

                settle_elapsed = (now() - float(last_change_ts or now())) if last_change_ts is not None else 0.0
                if (
                    first_advanced_generation is not None
                    and stable_polls >= stable_need
                    and settle_elapsed >= min_settle
                ):
                    return {
                        "ok": True,
                        "min_generation_required": min_gen,
                        "first_advanced_generation": first_advanced_generation,
                        "final_generation": current_gen,
                        "final_publish_source": str(last_ok_freshness.get("publish_source") or "")[:64],
                        "poll_count": polls,
                        "wait_s": now() - started,
                        "settle_reason": "oob_generation_quiescent",
                        "stable_poll_count": stable_polls,
                        "generations_observed": list(generations_observed),
                        "publish_sources_observed": list(publish_sources_observed),
                        "fetch": last_ok_fetch,
                        "freshness": last_ok_freshness,
                    }

        if sleep is not None:
            sleep(poll_ms / 1000.0)
        else:
            page.wait_for_timeout(poll_ms)

    wait_s = now() - started
    final_gen = int(last_ok_freshness.get("snapshot_generation") or 0) or None
    final_pub = str(last_ok_freshness.get("publish_source") or "")[:64]
    if first_advanced_generation is None:
        reason = "oob_no_generation_advance"
    else:
        reason = "oob_settle_timeout_after_advance"
    return {
        "ok": False,
        "min_generation_required": min_gen,
        "first_advanced_generation": first_advanced_generation,
        "final_generation": final_gen if first_advanced_generation is not None else final_gen,
        "final_publish_source": final_pub,
        "poll_count": polls,
        "wait_s": wait_s,
        "settle_reason": reason,
        "stable_poll_count": stable_polls,
        "generations_observed": list(generations_observed),
        "publish_sources_observed": list(publish_sources_observed),
        "fetch": last_ok_fetch if last_ok_fetch.get("ok") else last_fetch,
        "freshness": last_ok_freshness if last_ok_freshness else last_freshness,
    }


def authoritative_rows_from_oob_snapshot(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    snap = dict(snapshot or {})
    module_rows = list(snap.get("module_ledger_rows") or [])
    critical_rows = list(snap.get("critical_ledger_rows") or [])
    by_phase = snap.get("critical_ledger_by_phase") if isinstance(snap.get("critical_ledger_by_phase"), dict) else {}
    extra: list[dict[str, Any]] = []
    for rows in by_phase.values():
        extra.extend([r for r in list(rows or []) if isinstance(r, dict)])
    seen: set[tuple] = set()
    merged: list[dict[str, Any]] = []
    for r in module_rows + critical_rows + extra:
        if not isinstance(r, dict):
            continue
        key = (r.get("phase"), r.get("ts"), r.get("event_id"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(r))
    return sorted(merged, key=lambda r: float(r.get("ts") or 0))


# ---------------------------------------------------------------------------
# Post-Pause TARGET Pause-evidence settle (harness-only).
# Global snapshot_generation is telemetry; settle on accumulated Pause rows.
# ---------------------------------------------------------------------------

TARGET_PAUSE_SCHEDULER_PHASES: tuple[str, ...] = (
    "RUNTIME_BACKMSG_ENTRY",
    "APPSESSION_BACKMSG_ENTRY",
    "APPSESSION_REQUEST_RERUN_ENTRY",
    "SCRIPTRUNNER_REQUEST_RERUN_ENTRY",
    "SCRIPTRUNNER_REQUEST_RERUN_RESULT",
    "SCRIPTREQUESTS_REQUEST_RERUN_ENTRY",
    "SCRIPTREQUESTS_RERUN_STORED",
    "SCRIPTREQUESTS_RERUN_COALESCED",
    "SCRIPTREQUESTS_ON_YIELD_ENTRY",
    "SCRIPTREQUESTS_ON_YIELD_RESULT",
    "SCRIPTREQUESTS_ON_READY_ENTRY",
    "SCRIPTREQUESTS_ON_READY_RESULT",
    "SCRIPTREQUESTS_RERUN_CONSUMED",
    "SCRIPTRUNNER_RUN_SCRIPT_ENTRY",
    "SAFE_SESSIONSTATE_RECEIVE_ENTRY",
    "SERVER_RECEIVE_ENTRY",
    "SERVER_STATE_APPLIED",
)

DOWNSTREAM_INGRESS_SETTLE_PHASES: tuple[str, ...] = (
    "SCRIPTREQUESTS_RERUN_CONSUMED",
    "SCRIPTRUNNER_RUN_SCRIPT_ENTRY",
    "SAFE_SESSIONSTATE_RECEIVE_ENTRY",
    "SERVER_RECEIVE_ENTRY",
    "SERVER_STATE_APPLIED",
)

_TARGET_PHASE_DEPTH: dict[str, int] = {p: i for i, p in enumerate(TARGET_PAUSE_SCHEDULER_PHASES)}

OOB_PAUSE_EVIDENCE_POLL_INTERVAL_MS = 500
OOB_PAUSE_EVIDENCE_STABLE_POLLS_REQUIRED = 6
OOB_PAUSE_EVIDENCE_MIN_STABLE_S = 3.0
OOB_PAUSE_EVIDENCE_MAX_WAIT_S_BEFORE_FIRST = 30.0
OOB_PAUSE_EVIDENCE_MAX_WAIT_S_AFTER_FIRST = 15.0

SETTLE_REASON_PAUSE_EVIDENCE_QUIESCENT = "oob_pause_evidence_quiescent"
SETTLE_REASON_PAUSE_EVIDENCE_NOT_OBSERVED = "oob_pause_evidence_not_observed"
SETTLE_REASON_PAUSE_EVIDENCE_SETTLE_TIMEOUT = "oob_pause_evidence_settle_timeout"


def oob_row_identity(row: dict[str, Any]) -> tuple[str, str]:
    """Stable dedupe key: prefer phase + event_id; fall back to phase + ts."""
    phase = str(row.get("phase") or "")
    eid = str(row.get("event_id") or "").strip()
    if eid:
        return (phase, eid)
    return (phase, f"ts:{float(row.get('ts') or 0):.6f}")


def _row_streamlit_sid(row: dict[str, Any]) -> str:
    for key in (
        "streamlit_session_id",
        "routing_sid",
        "appsession_sid",
        "appsession_id",
        "runtime_sid",
    ):
        sid = str(row.get(key) or "").strip()
        if sid:
            return sid[:64]
    return ""


def _pause_widget_ids_from_row(row: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    proto = row.get("pause_proto") if isinstance(row.get("pause_proto"), dict) else {}
    pid = str(proto.get("id") or "").strip()
    if pid:
        ids.add(pid)
    for trig in list(row.get("activated_triggers") or []):
        if isinstance(trig, dict):
            t = str(trig.get("id") or trig.get("widget_id") or "").strip()
        else:
            t = str(trig or "").strip()
        if t:
            ids.add(t)
    for key in (
        "previous_pending_pause",
        "incoming_pause",
        "resulting_coalesced_pause",
        "pause_state",
    ):
        blob = row.get(key)
        if isinstance(blob, dict):
            bid = str(blob.get("id") or blob.get("widget_id") or "").strip()
            if bid:
                ids.add(bid)
    return ids


def is_target_pause_scheduler_row(
    row: dict[str, Any],
    *,
    streamlit_session_id: str = "",
    pause_widget_id: str = "",
) -> bool:
    """True when row is a scheduler-phase Pause-relevant row for the target session/widget."""
    if not isinstance(row, dict):
        return False
    phase = str(row.get("phase") or "")
    if phase not in _TARGET_PHASE_DEPTH:
        return False
    want_sid = str(streamlit_session_id or "").strip()[:64]
    if want_sid:
        row_sid = _row_streamlit_sid(row)
        if row_sid and row_sid[:36] != want_sid[:36]:
            return False
    want_wid = str(pause_widget_id or "").strip()
    has_pause = bool(row.get("pause_present")) or bool(row.get("pause_trigger_from_deserialized"))
    row_wids = _pause_widget_ids_from_row(row)
    if want_wid:
        if want_wid in row_wids:
            return True
        # Some early phases only mark pause_present without embedding the widget id.
        if has_pause and not row_wids:
            return True
        return False
    return has_pause or bool(row_wids)


def merge_oob_rows_into_accumulator(
    accumulator: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]] | None,
) -> int:
    """Merge rows into accumulator keyed by oob_row_identity. Never deletes prior rows. Returns new inserts."""
    inserted = 0
    for row in list(rows or []):
        if not isinstance(row, dict):
            continue
        key = oob_row_identity(row)
        if key in accumulator:
            continue
        accumulator[key] = dict(row)
        inserted += 1
    return inserted


def merge_oob_snapshot_into_accumulator(
    accumulator: dict[str, dict[str, Any]],
    snapshot: dict[str, Any] | None,
) -> dict[str, int]:
    snap = dict(snapshot or {})
    module_rows = list(snap.get("module_ledger_rows") or [])
    critical_rows = list(snap.get("critical_ledger_rows") or [])
    by_phase = snap.get("critical_ledger_by_phase") if isinstance(snap.get("critical_ledger_by_phase"), dict) else {}
    phase_rows: list[dict[str, Any]] = []
    for rows in by_phase.values():
        phase_rows.extend([r for r in list(rows or []) if isinstance(r, dict)])
    crit_inserted = merge_oob_rows_into_accumulator(accumulator, critical_rows)
    crit_inserted += merge_oob_rows_into_accumulator(accumulator, phase_rows)
    return {
        "module_inserted": merge_oob_rows_into_accumulator(accumulator, module_rows),
        "critical_inserted": crit_inserted,
        "module_row_count_in_snapshot": len(module_rows),
        "critical_row_count_in_snapshot": len(critical_rows) + len(phase_rows),
    }


def downstream_ingress_fingerprint(snapshot: dict[str, Any] | None) -> tuple[tuple[str, str, str], ...]:
    """Stable identity of downstream ingress latest eids/ts — not Pause-authoritative by itself."""
    snap = dict(snapshot or {})
    summaries = snap.get("latest_ingress_summaries") if isinstance(snap.get("latest_ingress_summaries"), dict) else {}
    by_phase: dict[str, dict[str, Any]] = {}
    for val in summaries.values():
        if not isinstance(val, dict):
            continue
        phase = str(val.get("phase") or "").strip()
        if phase:
            by_phase[phase] = val
    out: list[tuple[str, str, str]] = []
    for phase in DOWNSTREAM_INGRESS_SETTLE_PHASES:
        summary = by_phase.get(phase) or {}
        eid = str(summary.get("latest_event_id") or "").strip()
        ts = summary.get("latest_server_ts")
        if not eid and ts is None:
            continue
        out.append((phase, eid, f"{float(ts or 0):.6f}"))
    return tuple(out)


def reconcile_ingress_summaries_with_rows(
    snapshot: dict[str, Any] | None,
    accumulator_rows: list[dict[str, Any]] | None,
    *,
    downstream_phases: tuple[str, ...] = DOWNSTREAM_INGRESS_SETTLE_PHASES,
) -> list[dict[str, Any]]:
    """Flag ingress latest events that are not present as rows (export truncation)."""
    snap = dict(snapshot or {})
    summaries = snap.get("latest_ingress_summaries") if isinstance(snap.get("latest_ingress_summaries"), dict) else {}
    acc = list(accumulator_rows or [])
    acc_ids = {(str(r.get("phase") or ""), str(r.get("event_id") or "").strip()) for r in acc if isinstance(r, dict)}
    module_ids = {
        (str(r.get("phase") or ""), str(r.get("event_id") or "").strip())
        for r in list(snap.get("module_ledger_rows") or [])
        if isinstance(r, dict)
    }
    crit_ids = {
        (str(r.get("phase") or ""), str(r.get("event_id") or "").strip())
        for r in list(snap.get("critical_ledger_rows") or [])
        if isinstance(r, dict)
    }
    by_phase = snap.get("critical_ledger_by_phase") if isinstance(snap.get("critical_ledger_by_phase"), dict) else {}
    for rows in by_phase.values():
        for r in list(rows or []):
            if isinstance(r, dict):
                crit_ids.add((str(r.get("phase") or ""), str(r.get("event_id") or "").strip()))
    by_summary_phase: dict[str, dict[str, Any]] = {}
    for val in summaries.values():
        if isinstance(val, dict) and str(val.get("phase") or "").strip():
            by_summary_phase[str(val.get("phase"))] = val
    out: list[dict[str, Any]] = []
    for phase in downstream_phases:
        summary = by_summary_phase.get(phase) or {}
        eid = str(summary.get("latest_event_id") or "").strip()
        ts = summary.get("latest_server_ts")
        if not eid:
            continue
        key = (phase, eid)
        row_in_acc = key in acc_ids
        row_in_crit = key in crit_ids
        row_in_mod = key in module_ids
        missing = not (row_in_acc or row_in_crit or row_in_mod)
        out.append(
            {
                "ingress_event_seen_but_row_missing": missing,
                "phase": phase,
                "latest_event_id": eid,
                "latest_ts": ts,
                "row_present_in_accumulator": row_in_acc,
                "row_present_in_critical_export": row_in_crit,
                "row_present_in_module_export": row_in_mod,
            }
        )
    return out


def settle_observability_fingerprint(
    rows: list[dict[str, Any]],
    snapshot: dict[str, Any] | None,
    *,
    streamlit_session_id: str = "",
    pause_widget_id: str = "",
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str, str], ...]]:
    return (
        target_pause_evidence_fingerprint(
            rows, streamlit_session_id=streamlit_session_id, pause_widget_id=pause_widget_id
        ),
        downstream_ingress_fingerprint(snapshot),
    )


def accumulated_rows_sorted(accumulator: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(accumulator.values(), key=lambda r: (float(r.get("ts") or 0), str(r.get("event_id") or "")))


def target_pause_evidence_fingerprint(
    rows: list[dict[str, Any]],
    *,
    streamlit_session_id: str = "",
    pause_widget_id: str = "",
) -> tuple[tuple[str, str], ...]:
    ids: list[tuple[str, str]] = []
    for row in rows:
        if is_target_pause_scheduler_row(
            row, streamlit_session_id=streamlit_session_id, pause_widget_id=pause_widget_id
        ):
            ids.append(oob_row_identity(row))
    return tuple(sorted(ids, key=lambda x: (_TARGET_PHASE_DEPTH.get(x[0], 999), x[0], x[1])))


def deepest_target_pause_phase(fingerprint: tuple[tuple[str, str], ...]) -> str:
    deepest = ""
    deepest_i = -1
    for phase, _eid in fingerprint:
        i = _TARGET_PHASE_DEPTH.get(phase, -1)
        if i > deepest_i:
            deepest_i = i
            deepest = phase
    return deepest


def wait_for_oob_pause_evidence_settled_after(
    page,
    *,
    static_url_path: str,
    min_generation: int,
    streamlit_session_id: str = "",
    pause_widget_id: str = "",
    poll_interval_ms: int = OOB_PAUSE_EVIDENCE_POLL_INTERVAL_MS,
    stable_polls_required: int = OOB_PAUSE_EVIDENCE_STABLE_POLLS_REQUIRED,
    min_stable_s: float = OOB_PAUSE_EVIDENCE_MIN_STABLE_S,
    max_wait_s_before_first_evidence: float = OOB_PAUSE_EVIDENCE_MAX_WAIT_S_BEFORE_FIRST,
    max_wait_s_after_first_evidence: float = OOB_PAUSE_EVIDENCE_MAX_WAIT_S_AFTER_FIRST,
    connected_server_uri: str | None = None,
    require_connected_server_uri: bool = False,
    sleep_fn: Callable[[float], None] | None = None,
    time_fn: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Settle when *target Pause evidence* is stable — not when global generation is quiet.

    Every successful fetch merges module+critical rows into a rolling accumulator that never
    drops earlier identities (bounded ledgers may evict them from later snapshots).
    """
    now = time_fn or time.time
    sleep = sleep_fn
    min_gen = int(min_generation or 0)
    stable_need = max(1, int(stable_polls_required or 1))
    poll_ms = max(1, int(poll_interval_ms or OOB_PAUSE_EVIDENCE_POLL_INTERVAL_MS))
    min_stable = float(min_stable_s or 0.0)
    max_before = float(max_wait_s_before_first_evidence or 0.0)
    max_after = float(max_wait_s_after_first_evidence or 0.0)
    want_sid = str(streamlit_session_id or "").strip()[:64]
    want_wid = str(pause_widget_id or "").strip()

    def _fail_unresolved() -> dict[str, Any]:
        return {
            "ok": False,
            "settle_reason": "oob_connected_server_uri_unresolved",
            "min_generation_required": min_gen,
            "first_snapshot_generation_after_pause": None,
            "final_snapshot_generation": None,
            "generations_observed": [],
            "publish_sources_observed": [],
            "poll_count": 0,
            "wait_s": 0.0,
            "target_pause_widget_id": want_wid,
            "target_streamlit_session_id": want_sid,
            "target_first_seen_poll": None,
            "target_first_seen_generation": None,
            "target_last_changed_poll": None,
            "target_last_changed_generation": None,
            "target_stable_poll_count": 0,
            "target_stable_duration_s": 0.0,
            "target_relevant_row_count": 0,
            "target_relevant_phases": [],
            "target_relevant_event_ids": [],
            "deepest_target_phase": "",
            "accumulated_authoritative_row_count": 0,
            "accumulated_critical_row_count": 0,
            "accumulated_module_row_count": 0,
            "accumulated_rows": [],
            "ingress_row_discrepancies": [],
            "ingress_downstream_fingerprint": [],
            "final_fetch": {
                "ok": False,
                "reason": "oob_connected_server_uri_unresolved",
                "http_ok": False,
                "parse_ok": False,
                "snapshot_present": False,
                "http_request_attempted": False,
            },
            "final_snapshot": {},
        }

    if require_connected_server_uri and not str(connected_server_uri or "").strip():
        return _fail_unresolved()

    started = now()
    first_target_ts: float | None = None
    last_target_change_ts: float | None = None
    first_advanced_generation: int | None = None
    accumulator: dict[str, dict[str, Any]] = {}
    last_fingerprint: tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str, str], ...]] = ((), ())
    stable_polls = 0
    polls = 0
    generations_observed: list[int] = []
    publish_sources_observed: list[str] = []
    last_fetch: dict[str, Any] = {"ok": False}
    last_ok_fetch: dict[str, Any] = {"ok": False}
    last_ok_snap: dict[str, Any] = {}
    target_first_seen_poll: int | None = None
    target_first_seen_generation: int | None = None
    target_last_changed_poll: int | None = None
    target_last_changed_generation: int | None = None
    module_insert_total = 0
    critical_insert_total = 0

    def _deadline() -> float:
        if first_target_ts is None:
            return started + max_before
        return float(last_target_change_ts or first_target_ts) + max_after

    def _result(*, ok: bool, settle_reason: str) -> dict[str, Any]:
        rows = accumulated_rows_sorted(accumulator)
        row_fp = target_pause_evidence_fingerprint(
            rows, streamlit_session_id=want_sid, pause_widget_id=want_wid
        )
        ingress_fp = downstream_ingress_fingerprint(last_ok_snap)
        discrepancies = reconcile_ingress_summaries_with_rows(last_ok_snap, rows)
        phases = sorted({p for p, _ in row_fp}, key=lambda p: _TARGET_PHASE_DEPTH.get(p, 999))
        eids = [eid for _p, eid in row_fp]
        final_gen = int(last_ok_snap.get("snapshot_generation") or 0) or None
        stable_duration = 0.0
        if last_target_change_ts is not None and row_fp:
            stable_duration = max(0.0, now() - float(last_target_change_ts))
        return {
            "ok": bool(ok),
            "settle_reason": settle_reason,
            "min_generation_required": min_gen,
            "first_snapshot_generation_after_pause": first_advanced_generation,
            "final_snapshot_generation": final_gen,
            "generations_observed": list(generations_observed),
            "publish_sources_observed": list(publish_sources_observed),
            "poll_count": polls,
            "wait_s": now() - started,
            "target_pause_widget_id": want_wid,
            "target_streamlit_session_id": want_sid,
            "target_first_seen_poll": target_first_seen_poll,
            "target_first_seen_generation": target_first_seen_generation,
            "target_last_changed_poll": target_last_changed_poll,
            "target_last_changed_generation": target_last_changed_generation,
            "target_stable_poll_count": stable_polls if fp else 0,
            "target_stable_duration_s": round(stable_duration, 3),
            "target_relevant_row_count": len(row_fp),
            "target_relevant_phases": phases,
            "target_relevant_event_ids": eids,
            "deepest_target_phase": deepest_target_pause_phase(row_fp),
            "accumulated_authoritative_row_count": len(rows),
            "accumulated_critical_row_count": critical_insert_total,
            "accumulated_module_row_count": module_insert_total,
            "accumulated_rows": rows,
            "ingress_row_discrepancies": discrepancies,
            "ingress_downstream_fingerprint": [list(x) for x in ingress_fp],
            "final_fetch": last_ok_fetch if last_ok_fetch.get("ok") else last_fetch,
            "final_snapshot": last_ok_snap,
            # Compatibility aliases used by older gate fields / telemetry.
            "first_advanced_generation": first_advanced_generation,
            "final_generation": final_gen,
            "final_publish_source": str(last_ok_snap.get("publish_source") or "")[:64],
            "stable_poll_count": stable_polls if fp else 0,
            "fetch": last_ok_fetch if last_ok_fetch.get("ok") else last_fetch,
            "freshness": extract_oob_freshness_from_snapshot(last_ok_snap) if last_ok_snap else {},
        }

    while now() < _deadline():
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
        gen = int(snap.get("snapshot_generation") or 0)
        pub = str(snap.get("publish_source") or "")[:64]

        if last_fetch.get("ok"):
            last_ok_fetch = last_fetch
            last_ok_snap = dict(snap)
            if gen > 0 and (not generations_observed or generations_observed[-1] != gen):
                generations_observed.append(gen)
            if pub and (not publish_sources_observed or publish_sources_observed[-1] != pub):
                publish_sources_observed.append(pub)
            if gen > min_gen and first_advanced_generation is None:
                first_advanced_generation = gen

            insert_stats = merge_oob_snapshot_into_accumulator(accumulator, snap)
            module_insert_total += int(insert_stats.get("module_inserted") or 0)
            critical_insert_total += int(insert_stats.get("critical_inserted") or 0)

            rows = accumulated_rows_sorted(accumulator)
            row_fp = target_pause_evidence_fingerprint(
                rows, streamlit_session_id=want_sid, pause_widget_id=want_wid
            )
            fp = settle_observability_fingerprint(
                rows,
                snap,
                streamlit_session_id=want_sid,
                pause_widget_id=want_wid,
            )
            if row_fp:
                if first_target_ts is None:
                    first_target_ts = now()
                    last_target_change_ts = first_target_ts
                    last_fingerprint = fp
                    stable_polls = 1
                    target_first_seen_poll = polls
                    target_first_seen_generation = gen or None
                    target_last_changed_poll = polls
                    target_last_changed_generation = gen or None
                elif fp != last_fingerprint:
                    last_fingerprint = fp
                    last_target_change_ts = now()
                    stable_polls = 1
                    target_last_changed_poll = polls
                    target_last_changed_generation = gen or None
                else:
                    stable_polls += 1

                stable_elapsed = now() - float(last_target_change_ts or now())
                if stable_polls >= stable_need and stable_elapsed >= min_stable:
                    return _result(ok=True, settle_reason=SETTLE_REASON_PAUSE_EVIDENCE_QUIESCENT)

        if sleep is not None:
            sleep(poll_ms / 1000.0)
        else:
            page.wait_for_timeout(poll_ms)

    if first_target_ts is None:
        return _result(ok=False, settle_reason=SETTLE_REASON_PAUSE_EVIDENCE_NOT_OBSERVED)
    return _result(ok=False, settle_reason=SETTLE_REASON_PAUSE_EVIDENCE_SETTLE_TIMEOUT)
