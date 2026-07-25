"""Query-gated P1 / P2a–P2d single-cycle micro isolation (diagnostic only)."""

from __future__ import annotations

import json
import time
from typing import Any

from live_draft_solo_delivery_diag import (
    SOLO_DELIVERY_LOG_KEY,
    SOLO_DELIVERY_META_KEY,
    bump_delivery_rerun,
    delivery_diag_active,
    note_delivery_stage,
    render_parent_postmessage_listener,
)

MICRO_PLACEMENTS = ("P1", "P2A", "P2B", "P2C", "P2D")
SESSION_MICRO_KEY = "_solo_placement_micro_active"
REQUESTED_MICRO_KEY = "_solo_placement_micro_requested"
SOURCE_BY_PLACEMENT = {
    "P1": "live_draft_solo_placement_micro.try_micro_p1_ldr_entry",
    "P2A": "live_draft_solo_placement_micro.try_micro_p2a_before_early_reconcile",
    "P2B": "live_draft_solo_placement_micro.try_micro_p2b_after_early_reconcile",
    "P2C": "live_draft_solo_placement_micro.try_micro_p2c_before_owner_selection",
    "P2D": "live_draft_solo_placement_micro.try_micro_p2d_pre_owner_current",
}


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


def micro_isolation_active(st: Any | None, session: dict[str, Any]) -> bool:
    if session.get("_solo_micro_isolation_enabled"):
        return True
    return st is not None and _qp_flag(st, "solo_micro_isolation")


def micro_from_query(st: Any | None) -> str:
    raw = (_qp_get(st, "solo_placement_micro") if st is not None else "").strip().upper()
    if raw == "P2D":
        return "P2D"
    if raw in MICRO_PLACEMENTS:
        return raw
    return ""


def current_micro_placement(st: Any, session: dict[str, Any]) -> str:
    p = micro_from_query(st)
    if p not in MICRO_PLACEMENTS:
        p = str(session.get(REQUESTED_MICRO_KEY) or session.get(SESSION_MICRO_KEY) or "").upper()
    if p in MICRO_PLACEMENTS:
        session[SESSION_MICRO_KEY] = p
        return p
    return ""


def enable_micro_isolation_from_query(st: Any, session: dict[str, Any]) -> None:
    if not delivery_diag_active(st, session) and not _qp_flag(st, "solo_delivery_diag"):
        if _qp_flag(st, "solo_delivery_diag"):
            session["_solo_delivery_diag_enabled"] = True
    if _qp_flag(st, "solo_delivery_diag"):
        session["_solo_delivery_diag_enabled"] = True
    if not micro_isolation_active(st, session) and _qp_flag(st, "solo_micro_isolation"):
        session["_solo_micro_isolation_enabled"] = True
    p = micro_from_query(st)
    if p in MICRO_PLACEMENTS:
        session[REQUESTED_MICRO_KEY] = p
        session[SESSION_MICRO_KEY] = p
    try:
        from live_draft_solo_placement_ladder import render_latch_probe

        if session.get(REQUESTED_MICRO_KEY):
            session["_solo_placement_ladder_requested"] = session[REQUESTED_MICRO_KEY]
            render_latch_probe(st, session)
    except ImportError:
        pass


def _solo_in_progress_room(session: dict[str, Any], room: dict[str, Any]) -> bool:
    if str(room.get("status") or "") != "in_progress":
        return False
    try:
        from live_draft_solo_timer import is_solo_live_draft

        return bool(is_solo_live_draft(session, room))
    except ImportError:
        return True


_RECORD_RESERVED_FIELD_KEYS = frozenset({"placement", "micro_isolation", "stage", "session"})


def _record_stage_factory(session: dict[str, Any], placement: str) -> Any:
    def _record(stage: str, fields: dict[str, Any] | None = None) -> None:
        payload = dict(fields or {})
        for key in _RECORD_RESERVED_FIELD_KEYS:
            payload.pop(key, None)
        note_delivery_stage(
            session,
            stage,
            placement=placement,
            micro_isolation=True,
            **payload,
        )

    return _record


def _fragment_context(session: dict[str, Any]) -> str:
    try:
        from live_draft_cloud_diagnostics import fragment_owner_summary

        return str(fragment_owner_summary(session) or "")
    except ImportError:
        return ""


def _script_run_id(session: dict[str, Any]) -> str:
    try:
        from app_page_generation import current_script_run_id

        return str(current_script_run_id(session) or "")
    except ImportError:
        return str(session.get("_live_draft_script_run_id") or "")


def render_micro_probe(
    st: Any,
    session: dict[str, Any],
    *,
    placement: str,
    source: str,
    result: Any,
    log: list[dict[str, Any]],
) -> None:
    from solo_countdown_wake_micro_core import (
        EXPIRE_RUN_KEY,
        MOUNT_RUN_KEY,
        RERUN_LOG_KEY,
        WIDGET_ID_MOUNT_KEY,
        WIDGET_ID_SEND_KEY,
    )

    stages = [str(r.get("stage") or "") for r in log if isinstance(r, dict)]
    chain = "|".join(stages[-60:])
    reruns = list(session.get(RERUN_LOG_KEY) or [])
    mount_wid = str(session.get(WIDGET_ID_MOUNT_KEY) or "")
    send_wid = str(session.get(WIDGET_ID_SEND_KEY) or "")
    st.markdown(
        f'<div id="solo-micro-isolation-diag" '
        f'data-placement="{placement}" '
        f'data-source="{source.replace(chr(34), chr(39))}" '
        f'data-key="{result.widget_key.replace(chr(34), chr(39))}" '
        f'data-token="{result.token.replace(chr(34), chr(39))}" '
        f'data-mount-run="{str(session.get(MOUNT_RUN_KEY) or "").replace(chr(34), chr(39))}" '
        f'data-expire-run="{str(session.get(EXPIRE_RUN_KEY) or "").replace(chr(34), chr(39))}" '
        f'data-mount-widget-id="{mount_wid.replace(chr(34), chr(39))}" '
        f'data-send-widget-id="{send_wid.replace(chr(34), chr(39))}" '
        f'data-widget-ids-match="{1 if mount_wid and mount_wid == send_wid else 0}" '
        f'data-reruns="{len(reruns)}" '
        f'data-rerun-log="{json.dumps(reruns[-20:], default=str)[:4000].replace(chr(34), chr(39))}" '
        f'data-stages="{chain.replace(chr(34), chr(39))}" '
        f'data-fragment="{_fragment_context(session).replace(chr(34), chr(39))}" '
        f'data-complete="{1 if result.delivered else 0}" '
        f'data-on-change="{1 if result.on_change_fired else 0}" '
        f'data-raw-received="{1 if result.raw_received else 0}" '
        f'data-room-id="{str((session.get("live_draft_room") or {}).get("draft_room_id") or "")[:16]}" '
        f'></div>',
        unsafe_allow_html=True,
    )


def _run_micro(
    st: Any,
    session: dict[str, Any],
    *,
    placement: str,
    location: str,
    room: dict[str, Any] | None,
) -> bool:
    if current_micro_placement(st, session) != placement:
        return False
    if not micro_isolation_active(st, session):
        return False
    session["_solo_placement_ladder_block_picks"] = True
    session[SOLO_DELIVERY_META_KEY] = {
        **dict(session.get(SOLO_DELIVERY_META_KEY) or {}),
        "micro_isolation": placement,
        "mount_location": location,
        "rerun_count": bump_delivery_rerun(session),
    }
    record = _record_stage_factory(session, placement)
    render_parent_postmessage_listener(st)
    from solo_countdown_wake_micro_core import COMPLETE_KEY, render_micro_isolation_once

    did = f"DIAG{placement}"
    if isinstance(room, dict):
        rid = str(room.get("draft_room_id") or room.get("draft_id") or "")
        if rid:
            did = rid
    result = render_micro_isolation_once(
        st,
        session,
        placement=placement,
        location=location,
        record_stage=record,
        draft_id=did,
        route=placement != "P1",
    )
    log = list(session.get(SOLO_DELIVERY_LOG_KEY) or [])
    render_micro_probe(
        st,
        session,
        placement=placement,
        source=SOURCE_BY_PLACEMENT.get(placement, location),
        result=result,
        log=log,
    )
    if result.delivered or session.get(COMPLETE_KEY):
        st.stop()
    return True


def try_micro_p1_ldr_entry(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    return _run_micro(st, session, placement="P1", location="micro_p1_ldr_entry", room=room)


def try_micro_p2a_before_early_reconcile(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    if current_micro_placement(st, session) != "P2A":
        return False
    if not _solo_in_progress_room(session, room):
        return False
    return _run_micro(st, session, placement="P2A", location="micro_p2a_before_early_reconcile", room=room)


def try_micro_p2b_after_early_reconcile(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    if current_micro_placement(st, session) != "P2B":
        return False
    if not _solo_in_progress_room(session, room):
        return False
    return _run_micro(st, session, placement="P2B", location="micro_p2b_after_early_reconcile", room=room)


def try_micro_p2c_before_owner_selection(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    if current_micro_placement(st, session) != "P2C":
        return False
    if not _solo_in_progress_room(session, room):
        return False
    try:
        from live_draft_solo_expire_chain import solo_expire_owner

        note_delivery_stage(
            session,
            "micro_p2c_owner_snapshot",
            owner=solo_expire_owner(session),
            placement="P2C",
        )
    except ImportError:
        pass
    return _run_micro(st, session, placement="P2C", location="micro_p2c_before_owner_selection", room=room)


def try_micro_p2d_pre_owner_current(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    if current_micro_placement(st, session) != "P2D":
        return False
    if not _solo_in_progress_room(session, room):
        return False
    return _run_micro(st, session, placement="P2D", location="micro_p2d_pre_owner_current", room=room)


def micro_blocks_placement_ladder(session: dict[str, Any]) -> bool:
    return bool(session.get("_solo_micro_isolation_enabled") and session.get(SESSION_MICRO_KEY))
