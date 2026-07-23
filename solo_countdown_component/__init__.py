"""Bidirectional Solo countdown — Streamlit component wake at deadline zero."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

_FRONTEND_DIR = (Path(__file__).resolve().parent / "frontend").resolve()
_COMPONENT = components.declare_component(
    "solo_countdown_wake",
    path=str(_FRONTEND_DIR),
)


def get_component_frontend_dir() -> Path:
    return _FRONTEND_DIR


def component_frontend_ready() -> bool:
    return (_FRONTEND_DIR / "index.html").is_file()


def build_solo_expire_token(room: dict[str, Any]) -> str:
    """Unique expiration token: draft_id|pick_index|deadline."""
    draft_id = str(room.get("draft_room_id") or room.get("draft_id") or "solo").strip()
    pick_index = int(room.get("current_pick_index") or 0)
    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        deadline = live_draft_timer_deadline(room)
        if deadline is None:
            deadline = float(room.get("timer_deadline") or 0.0)
        else:
            deadline = float(deadline)
    except ImportError:
        deadline = float(room.get("timer_deadline") or 0.0)
    return f"{draft_id}|{pick_index}|{deadline:.3f}"


def parse_solo_expire_token(token: str) -> dict[str, Any] | None:
    parts = str(token or "").strip().split("|")
    if len(parts) != 3:
        return None
    try:
        return {
            "draft_id": parts[0].strip(),
            "pick_index": int(parts[1]),
            "deadline": float(parts[2]),
        }
    except (TypeError, ValueError):
        return None


def _coerce_component_token(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("token", "expire_token", "value"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""
    return str(value).strip()


def render_solo_countdown_wake(
    st: Any,
    room: dict[str, Any],
    *,
    key: str,
    session: dict[str, Any] | None = None,
    on_change: Any | None = None,
) -> str | None:
    """Mount zero-height countdown component; returns expire token when deadline crosses zero."""
    if not component_frontend_ready():
        return None
    if str(room.get("status") or "") != "in_progress":
        return None
    try:
        from live_draft_timer_logic import live_draft_timer_deadline
    except ImportError:
        return None

    deadline = live_draft_timer_deadline(room)
    if deadline is None:
        raw_deadline = room.get("timer_deadline")
        if raw_deadline is not None:
            deadline = float(raw_deadline)
    if deadline is None:
        if isinstance(session, dict):
            try:
                from live_draft_solo_component_diagnostics import record_solo_component_mount_attempt

                record_solo_component_mount_attempt(
                    session,
                    room,
                    key=key,
                    mounted=False,
                    reason="no_deadline",
                )
            except ImportError:
                session["_solo_component_diag"] = {
                    "mounted": False,
                    "reason": "no_deadline",
                    "key": key,
                }
        return None

    expire_token = build_solo_expire_token(room)
    remaining_seconds = None
    try:
        from live_draft_timer_logic import live_draft_seconds_remaining

        remaining_seconds = live_draft_seconds_remaining(room)
    except ImportError:
        pass

    try:
        from live_draft_solo_component_diagnostics import record_solo_component_mount_attempt

        record_solo_component_mount_attempt(
            session if isinstance(session, dict) else {},
            room,
            key=key,
            mounted=False,
            reason="pre_mount",
            expire_token=expire_token,
            deadline=float(deadline),
            remaining_seconds=remaining_seconds,
        )
    except ImportError:
        pass

    value = _COMPONENT(
        expire_token=expire_token,
        key=key,
        default=None,
        on_change=on_change,
    )
    token = _coerce_component_token(value)
    if isinstance(session, dict):
        try:
            from live_draft_solo_component_diagnostics import record_solo_component_mount_attempt

            record_solo_component_mount_attempt(
                session,
                room,
                key=key,
                mounted=True,
                reason="",
                expire_token=expire_token,
                deadline=float(deadline),
                remaining_seconds=remaining_seconds,
                widget_return_type=type(value).__name__ if value is not None else "",
                returned_token=token,
            )
        except ImportError:
            session["_solo_component_diag"] = {
                "mounted": True,
                "key": key,
                "expire_token": expire_token,
                "returned_token": token,
                "raw_type": type(value).__name__ if value is not None else "",
                "component_api": "v1",
            }
    return token or None
