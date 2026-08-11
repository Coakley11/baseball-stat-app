"""Repo-backed Streamlit static serving probe helpers (harness-only)."""

from __future__ import annotations

import json
import time
from typing import Any

REPO_STATIC_PROBE_RELATIVE_PATH = "/app/static/s3_oob/__repo_static_probe_v1.json"
REPO_STATIC_PROBE_SENTINEL_PROBE = "s3_oob_repo_static_probe_v1"
REPO_STATIC_PROBE_SENTINEL_SOURCE = "git_committed_static_file"
S3_STATIC_SERVING_REPO_CONTROL_PASS = "S3_STATIC_SERVING_REPO_CONTROL_PASS"
S3_STATIC_SERVING_REPO_CONTROL_NOT_SERVED = "S3_STATIC_SERVING_REPO_CONTROL_NOT_SERVED"


def build_repo_static_probe_url(origin: str, *, cache_bust: bool = True) -> str:
    base = str(origin or "").rstrip("/")
    path = REPO_STATIC_PROBE_RELATIVE_PATH
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base}{path}"
    if cache_bust:
        url = f"{url}?cb={int(time.time() * 1000)}"
    return url


def fetch_repo_static_probe_via_page(page, *, cache_bust: bool = True) -> dict[str, Any]:
    origin = str(page.evaluate("() => location.origin") or "").rstrip("/")
    url = build_repo_static_probe_url(origin, cache_bust=cache_bust)
    out: dict[str, Any] = {
        "requested_path": REPO_STATIC_PROBE_RELATIVE_PATH,
        "url": url,
        "ok": False,
        "http_ok": False,
        "parse_ok": False,
        "probe_marker_match": False,
        "source_marker_match": False,
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
        out["parsed_object"] = dict(parsed) if isinstance(parsed, dict) else None
        if isinstance(parsed, dict):
            out["probe_marker_match"] = str(parsed.get("probe") or "") == REPO_STATIC_PROBE_SENTINEL_PROBE
            out["source_marker_match"] = str(parsed.get("source") or "") == REPO_STATIC_PROBE_SENTINEL_SOURCE
            out["ok"] = bool(
                out["http_ok"]
                and out["parse_ok"]
                and out["probe_marker_match"]
                and out["source_marker_match"]
            )
        if not out["ok"] and not out.get("body_preview"):
            out["body_preview"] = body[:200]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}:{exc}"[:200]
    return out


def classify_repo_static_probe_result(fetch: dict[str, Any]) -> tuple[str, str, bool]:
    fetch = dict(fetch or {})
    if fetch.get("ok"):
        return S3_STATIC_SERVING_REPO_CONTROL_PASS, "repo_static_probe_served_json", True
    if fetch.get("http_ok") and not fetch.get("parse_ok"):
        return S3_STATIC_SERVING_REPO_CONTROL_NOT_SERVED, "repo_static_probe_returned_non_json", False
    if fetch.get("parse_ok") and not fetch.get("probe_marker_match"):
        return S3_STATIC_SERVING_REPO_CONTROL_NOT_SERVED, "repo_static_probe_sentinel_mismatch", False
    if fetch.get("parse_ok") and not fetch.get("source_marker_match"):
        return S3_STATIC_SERVING_REPO_CONTROL_NOT_SERVED, "repo_static_probe_source_mismatch", False
    return S3_STATIC_SERVING_REPO_CONTROL_NOT_SERVED, "repo_static_probe_fetch_failed", False
