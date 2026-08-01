"""Temporary low-egress Solo countdown component diagnostics (query-param gated)."""

from __future__ import annotations

import json
import time
from typing import Any

SOLO_MOUNT_DIAG_KEY = "_solo_component_mount_diag"
SOLO_MOUNT_COUNTS_KEY = "_solo_component_mount_counts"
SOLO_DIAG_TIMER_SESSION_KEY = "_solo_diag_timer_seconds"
SOLO_DIAG_ENABLED_KEY = "_solo_component_diag_enabled"


def _qp_get(st: Any, name: str) -> str:
    try:
        from live_draft_cloud_diagnostics import _qp_get as _get

        return _get(st, name)
    except ImportError:
        return ""


def _qp_flag(st: Any, name: str) -> bool:
    try:
        from live_draft_cloud_diagnostics import _qp_flag as _flag

        return _flag(st, name)
    except ImportError:
        return False


def solo_component_diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    if session.get(SOLO_DIAG_ENABLED_KEY):
        return True
    if st is not None and _qp_flag(st, "solo_component_diag"):
        return True
    return bool(session.get(SOLO_MOUNT_DIAG_KEY))


def bootstrap_solo_component_diag(st: Any | None, session: dict[str, Any]) -> None:
    """Read ?solo_component_diag=1 and ?solo_diag_timer=10 from URL once per session."""
    try:
        from live_draft_solo_placement_ladder import current_placement

        if st is not None and current_placement(st, session) in ("P2", "P3", "P4", "P5"):
            session[SOLO_DIAG_ENABLED_KEY] = True
            timer_raw = _qp_get(st, "solo_diag_timer") if st is not None else ""
            if timer_raw.isdigit():
                session[SOLO_DIAG_TIMER_SESSION_KEY] = max(5, min(60, int(timer_raw)))
            return
    except ImportError:
        pass
    if st is not None and _qp_flag(st, "solo_component_diag"):
        session[SOLO_DIAG_ENABLED_KEY] = True
    timer_raw = _qp_get(st, "solo_diag_timer") if st is not None else ""
    if timer_raw.isdigit():
        session[SOLO_DIAG_TIMER_SESSION_KEY] = max(5, min(60, int(timer_raw)))
    try:
        from live_draft_streamlit_widget_metadata_diag import install_streamlit_callback_dispatch_probe

        install_streamlit_callback_dispatch_probe(st, session)
    except ImportError:
        pass


def solo_diag_timer_seconds(session: dict[str, Any], room: dict[str, Any] | None = None) -> int | None:
    if isinstance(room, dict):
        room_val = room.get("_solo_diag_timer_seconds")
        if room_val is not None:
            return int(room_val)
    val = session.get(SOLO_DIAG_TIMER_SESSION_KEY)
    return int(val) if val is not None else None


def apply_solo_diag_timer_to_room(session: dict[str, Any], room: dict[str, Any]) -> bool:
    """Apply test-only timer override to room config (query-param gated)."""
    sec = solo_diag_timer_seconds(session, room)
    if sec is None:
        return False
    if session.get(SOLO_DIAG_TIMER_SESSION_KEY) is None:
        return False
    room["_solo_diag_timer_seconds"] = int(sec)
    cfg = dict(room.get("config") or {})
    cfg["timer_seconds"] = int(sec)
    room["config"] = cfg
    return True


SOLO_DIAG_DEADLINE_KEY = "_solo_diag_deadline_applied"


def maybe_apply_solo_diag_timer_at_deadline_creation(
    st: Any | None,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    phase: str = "initial",
) -> bool:
    """Apply ?solo_diag_timer=N immediately before the first deadline is installed."""
    bootstrap_solo_component_diag(st, session)
    if session.get(SOLO_DIAG_TIMER_SESSION_KEY) is None:
        return False
    if not apply_solo_diag_timer_to_room(session, room):
        return False
    try:
        from live_draft_timer_logic import live_draft_timer_deadline
    except ImportError:
        live_draft_timer_deadline = None  # type: ignore[assignment,misc]
    row = {
        "phase": str(phase),
        "timer_seconds": int(session[SOLO_DIAG_TIMER_SESSION_KEY]),
        "applied_at": time.time(),
        "pick_index": int(room.get("current_pick_index") or 0),
    }
    session[SOLO_DIAG_DEADLINE_KEY] = row
    return True


def record_solo_diag_deadline_after_reset(session: dict[str, Any], room: dict[str, Any]) -> None:
    """Capture the server deadline immediately after live_draft_reset_timer."""
    if session.get(SOLO_DIAG_TIMER_SESSION_KEY) is None:
        return
    try:
        from live_draft_timer_logic import live_draft_seconds_remaining, live_draft_timer_deadline
    except ImportError:
        return
    deadline = live_draft_timer_deadline(room)
    remaining = live_draft_seconds_remaining(room) if str(room.get("status") or "") == "in_progress" else None
    row = dict(session.get(SOLO_DIAG_DEADLINE_KEY) or {})
    row.update(
        {
            "deadline": float(deadline) if deadline is not None else None,
            "remaining_seconds": remaining,
            "recorded_at": time.time(),
            "config_timer_seconds": int((room.get("config") or {}).get("timer_seconds") or 0),
        }
    )
    session[SOLO_DIAG_DEADLINE_KEY] = row


def record_solo_component_mount_attempt(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    key: str,
    mounted: bool,
    reason: str = "",
    expire_token: str = "",
    deadline: float | None = None,
    remaining_seconds: int | None = None,
    widget_return_type: str = "",
    returned_token: str = "",
) -> dict[str, Any]:
    """Track Python-side mount attempts for the current pick."""
    now = time.time()
    draft_id = str(room.get("draft_room_id") or room.get("draft_id") or "solo").strip()
    pick_index = int(room.get("current_pick_index") or 0)
    counts = dict(session.get(SOLO_MOUNT_COUNTS_KEY) or {})
    mount_count = int(counts.get(key) or 0) + 1
    counts[key] = mount_count
    session[SOLO_MOUNT_COUNTS_KEY] = counts

    prev = dict(session.get(SOLO_MOUNT_DIAG_KEY) or {})
    prev_key = str(prev.get("widget_key") or "")
    prev_deadline = prev.get("deadline")
    key_changed = bool(prev_key and prev_key != key)
    deadline_changed = False
    if prev_deadline is not None and deadline is not None:
        deadline_changed = abs(float(prev_deadline) - float(deadline)) > 0.05

    row = {
        "ts": now,
        "mount_attempted": True,
        "mounted": bool(mounted),
        "reason": str(reason or ""),
        "widget_key": key,
        "draft_id": draft_id,
        "pick_index": pick_index,
        "expire_token": expire_token,
        "deadline": float(deadline) if deadline is not None else None,
        "server_time": now,
        "remaining_seconds": remaining_seconds,
        "key_changed": key_changed,
        "deadline_changed": deadline_changed,
        "mount_count_for_pick": mount_count,
        "widget_return_type": widget_return_type,
        "returned_token": returned_token,
    }
    session[SOLO_MOUNT_DIAG_KEY] = row
    session["_solo_component_diag"] = {
        "mounted": bool(mounted),
        "key": key,
        "expire_token": expire_token,
        "returned_token": returned_token,
        "raw_type": widget_return_type,
        "reason": reason,
        "deadline": deadline,
        "remaining_seconds": remaining_seconds,
        "mount_count_for_pick": mount_count,
    }
    return row


def render_solo_component_mount_probe(st: Any, session: dict[str, Any], room: dict[str, Any] | None) -> None:
    """Hidden DOM probe for Playwright — always rendered when Solo room is active."""
    try:
        from live_draft_solo_placement_ladder import current_placement

        if current_placement(st, session) == "P2":
            return
    except ImportError:
        pass
    bootstrap_solo_component_diag(st, session)
    if not isinstance(room, dict):
        return
    try:
        from live_draft_solo_timer import is_solo_live_draft
    except ImportError:
        return
    if not is_solo_live_draft(session, room):
        return
    row = dict(session.get(SOLO_MOUNT_DIAG_KEY) or {})
    diag_deadline = dict(session.get(SOLO_DIAG_DEADLINE_KEY) or {})
    payload = json.dumps(row, default=str)[:3500]
    st.markdown(
        f'<div id="solo-component-mount-diag" '
        f'data-mounted="{1 if row.get("mounted") else 0}" '
        f'data-reason="{str(row.get("reason") or "").replace(chr(34), chr(39))}" '
        f'data-key="{str(row.get("widget_key") or "").replace(chr(34), chr(39))}" '
        f'data-draft-id="{str(row.get("draft_id") or "").replace(chr(34), chr(39))}" '
        f'data-pick-index="{int(row.get("pick_index") or 0)}" '
        f'data-deadline="{row.get("deadline") if row.get("deadline") is not None else ""}" '
        f'data-remaining="{row.get("remaining_seconds") if row.get("remaining_seconds") is not None else ""}" '
        f'data-mount-count="{int(row.get("mount_count_for_pick") or 0)}" '
        f'data-key-changed="{1 if row.get("key_changed") else 0}" '
        f'data-deadline-changed="{1 if row.get("deadline_changed") else 0}" '
        f'data-token="{str(row.get("expire_token") or "").replace(chr(34), chr(39))}" '
        f'data-diag-timer="{int(diag_deadline.get("timer_seconds") or 0)}" '
        f'data-diag-remaining="{diag_deadline.get("remaining_seconds") if diag_deadline.get("remaining_seconds") is not None else ""}" '
        f'data-diag-deadline="{diag_deadline.get("deadline") if diag_deadline.get("deadline") is not None else ""}" '
        f'data-json="{payload.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )
