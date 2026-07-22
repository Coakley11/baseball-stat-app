"""Bidirectional Solo countdown — Streamlit component wake at deadline zero."""

from __future__ import annotations

import math
import os
from typing import Any

_COMPONENT_DIR = os.path.join(os.path.dirname(__file__), "solo_countdown_component", "frontend")

_solo_countdown_component = None


def _component():
    global _solo_countdown_component
    if _solo_countdown_component is None:
        import streamlit.components.v1 as components

        _solo_countdown_component = components.declare_component(
            "solo_countdown_wake",
            path=_COMPONENT_DIR,
        )
    return _solo_countdown_component


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


def render_solo_countdown_wake(
    st: Any,
    room: dict[str, Any],
    *,
    key: str,
) -> str | None:
    """Mount zero-height countdown component; returns expire token when deadline crosses zero."""
    if str(room.get("status") or "") != "in_progress":
        return None
    try:
        from live_draft_timer_logic import live_draft_timer_deadline
    except ImportError:
        return None
    deadline = live_draft_timer_deadline(room)
    if deadline is None:
        return None
    expire_token = build_solo_expire_token(room)
    draft_id = str(room.get("draft_room_id") or room.get("draft_id") or "solo").strip()
    pick_index = int(room.get("current_pick_index") or 0)
    deadline_arg = int(math.ceil(float(deadline)))
    value = _component()(
        draft_id=draft_id,
        pick_index=pick_index,
        deadline=deadline_arg,
        expire_token=expire_token,
        key=key,
        default=None,
    )
    if value is None:
        return None
    if isinstance(value, dict):
        token = str(value.get("value") or value.get("expire_token") or "").strip()
    else:
        token = str(value).strip()
    return token or None
