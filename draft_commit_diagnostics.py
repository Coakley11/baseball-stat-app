"""Diagnostics for manual draft pick commit (single-user + shared room)."""

from __future__ import annotations

from typing import Any

DRAFT_COMMIT_DIAG_KEY = "_draft_pick_commit_diag"
LIVE_DRAFT_PICK_NOTICE_KEY = "_live_draft_pick_notice"


def record_draft_commit_diagnostics(
    session: dict[str, Any],
    updates: dict[str, Any] | None = None,
    /,
    **fields: Any,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if updates:
        merged.update(updates)
    merged.update(fields)
    diag = dict(session.get(DRAFT_COMMIT_DIAG_KEY) or {})
    diag.update(merged)
    session[DRAFT_COMMIT_DIAG_KEY] = diag
    return diag


def set_live_draft_pick_notice(session: dict[str, Any], level: str, message: str) -> None:
    text = str(message or "").strip()
    if text:
        session[LIVE_DRAFT_PICK_NOTICE_KEY] = (str(level or "info").strip().lower(), text)


def pop_live_draft_pick_notice(session: dict[str, Any]) -> tuple[str, str] | None:
    raw = session.pop(LIVE_DRAFT_PICK_NOTICE_KEY, None)
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return str(raw[0]), str(raw[1])
    return None
