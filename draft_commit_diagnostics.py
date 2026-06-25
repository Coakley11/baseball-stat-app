"""Diagnostics for manual draft pick commit (single-user + shared room)."""

from __future__ import annotations

from typing import Any

DRAFT_COMMIT_DIAG_KEY = "_draft_pick_commit_diag"
LIVE_DRAFT_PICK_NOTICE_KEY = "_live_draft_pick_notice"
LIVE_DRAFT_SUCCESS_SHOWN_KEY = "_live_draft_success_shown_keys"
SUCCESS_MESSAGE_KEY = "_success_message_key"


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


def set_live_draft_pick_notice(
    session: dict[str, Any],
    level: str,
    message: str,
    *,
    pick_key: str | None = None,
) -> None:
    text = str(message or "").strip()
    if text:
        session[LIVE_DRAFT_PICK_NOTICE_KEY] = (str(level or "info").strip().lower(), text)
        if pick_key:
            session[SUCCESS_MESSAGE_KEY] = str(pick_key)


def pop_live_draft_pick_notice(session: dict[str, Any]) -> tuple[str, str] | None:
    raw = session.pop(LIVE_DRAFT_PICK_NOTICE_KEY, None)
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return str(raw[0]), str(raw[1])
    return None


def render_live_draft_pick_notice(st: Any, session: dict[str, Any]) -> None:
    """Show at most one success/error notice per committed pick."""
    notice = pop_live_draft_pick_notice(session)
    if not notice:
        session.pop("_live_draft_pick_flash", None)
        session.pop("_live_draft_pick_flash_error", None)
        return
    level, text = notice
    pick_key = str(session.pop(SUCCESS_MESSAGE_KEY, None) or text)
    shown_raw = session.get(LIVE_DRAFT_SUCCESS_SHOWN_KEY)
    shown: list[str] = list(shown_raw) if isinstance(shown_raw, list) else []
    duplicate = level == "success" and pick_key in shown
    record_draft_commit_diagnostics(
        session,
        success_message_key=pick_key,
        success_message_rendered_once=not duplicate,
        duplicate_success_message_suppressed=duplicate,
    )
    session.pop("_live_draft_pick_flash", None)
    session.pop("_live_draft_pick_flash_error", None)
    if duplicate:
        return
    if level == "success":
        if pick_key not in shown:
            shown.append(pick_key)
            session[LIVE_DRAFT_SUCCESS_SHOWN_KEY] = shown[-48:]
        st.success(text)
    else:
        st.error(text)
