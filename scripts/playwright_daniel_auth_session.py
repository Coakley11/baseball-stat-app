"""Load Daniel Cloud auth harness files (secrets stay on disk)."""

from __future__ import annotations

import json
from pathlib import Path
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


def save_session(*, suite_sid: str) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(
        json.dumps({"suite_sid": str(suite_sid or "").strip()}, indent=2),
        encoding="utf-8",
    )


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
