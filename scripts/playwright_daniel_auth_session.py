"""Load Daniel Cloud auth harness files (secrets stay on disk)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
STORAGE_PATH = ROOT / "data" / "playwright_daniel_auth.storage.json"
SESSION_PATH = ROOT / "data" / "playwright_daniel_auth.session.json"


def load_suite_sid() -> str:
    if not SESSION_PATH.is_file():
        return ""
    try:
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("suite_sid") or "").strip()


def save_session(*, suite_sid: str, metadata: dict[str, Any] | None = None) -> None:
    """Legacy helper — prefer ``atomic_write_harness_files`` for strict capture."""
    payload: dict[str, Any] = {"suite_sid": str(suite_sid or "").strip()}
    if metadata:
        payload.update(metadata)
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def atomic_write_harness_files(
    *,
    suite_sid: str,
    storage_writer,
    capture_metadata: dict[str, Any],
) -> None:
    """Write storage + session metadata atomically after strict capture success."""
    sid = str(suite_sid or "").strip()
    payload = {"suite_sid": sid, **capture_metadata}
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    storage_tmp = STORAGE_PATH.with_suffix(".storage.tmp.json")
    session_tmp = SESSION_PATH.with_suffix(".session.tmp.json")
    storage_writer(storage_tmp)
    session_tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(storage_tmp, STORAGE_PATH)
    os.replace(session_tmp, SESSION_PATH)


def utc_capture_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def append_suite_sid_to_url(url: str, suite_sid: str | None = None) -> str:
    sid = (suite_sid if suite_sid is not None else load_suite_sid()).strip()
    if not sid:
        return url
    parts = urlparse(url)
    q = parse_qs(parts.query, keep_blank_values=True)
    q["suite_sid"] = [sid]
    new_query = urlencode(q, doseq=True)
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))


def harness_ready() -> bool:
    return STORAGE_PATH.is_file() and bool(load_suite_sid())
