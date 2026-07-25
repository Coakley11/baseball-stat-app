"""Early-route persistent active-draft bridge — architectural confirmation (query-gated only)."""

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

BRIDGE_PLACEMENT = "BRIDGE"
BRIDGE_LOCATION = "ldr_page_entry_early_bridge"
BRIDGE_SESSION_PREFIX = "_solo_early_bridge_"
SESSION_BRIDGE_ENABLED = "_solo_early_bridge_enabled"
KEY_BEFORE_START = "_solo_early_bridge_key_before_start"
KEY_AFTER_START = "_solo_early_bridge_key_after_start"
RUN_BEFORE_START = "_solo_early_bridge_run_before_start"
RUN_AFTER_START = "_solo_early_bridge_run_after_start"
PHASE_KEY = "_solo_early_bridge_phase"


def _qp_flag(st: Any, name: str) -> bool:
    try:
        from live_draft_cloud_diagnostics import _qp_flag as _flag

        return _flag(st, name)
    except ImportError:
        return False


def early_bridge_active(st: Any | None, session: dict[str, Any]) -> bool:
    if session.get(SESSION_BRIDGE_ENABLED):
        return True
    return st is not None and _qp_flag(st, "solo_early_bridge")


def enable_early_bridge_from_query(st: Any, session: dict[str, Any]) -> None:
    if _qp_flag(st, "solo_delivery_diag") or _qp_flag(st, "solo_early_bridge"):
        session["_solo_delivery_diag_enabled"] = True
    if _qp_flag(st, "solo_early_bridge"):
        session[SESSION_BRIDGE_ENABLED] = True


def _script_run_id(session: dict[str, Any]) -> str:
    try:
        from app_page_generation import current_script_run_id

        return str(current_script_run_id(session) or "")
    except ImportError:
        return str(session.get("_live_draft_script_run_id") or "")


def _room_active(session: dict[str, Any], room: dict[str, Any]) -> bool:
    if str(room.get("status") or "") != "in_progress":
        return False
    try:
        from live_draft_solo_timer import is_solo_live_draft

        return bool(is_solo_live_draft(session, room))
    except ImportError:
        return True


def _record_stage_factory(session: dict[str, Any]) -> Any:
    reserved = frozenset({"placement", "early_bridge", "stage", "session"})

    def _record(stage: str, fields: dict[str, Any] | None = None) -> None:
        payload = dict(fields or {})
        for key in reserved:
            payload.pop(key, None)
        note_delivery_stage(
            session,
            stage,
            placement=BRIDGE_PLACEMENT,
            early_bridge=True,
            **payload,
        )

    return _record


def _snapshot_phase(session: dict[str, Any], room: dict[str, Any], widget_key: str) -> None:
    run_id = _script_run_id(session)
    if _room_active(session, room):
        if session.get(PHASE_KEY) != "active":
            session[PHASE_KEY] = "active"
            session[KEY_AFTER_START] = widget_key
            session[RUN_AFTER_START] = run_id
            note_delivery_stage(
                session,
                "bridge_room_became_active",
                placement=BRIDGE_PLACEMENT,
                early_bridge=True,
                room_id=str(room.get("draft_room_id") or room.get("draft_id") or ""),
                script_run=run_id,
                widget_key=widget_key,
            )
    elif not session.get(KEY_BEFORE_START):
        session[PHASE_KEY] = "setup"
        session[KEY_BEFORE_START] = widget_key
        session[RUN_BEFORE_START] = run_id


def render_early_bridge_probe(
    st: Any,
    session: dict[str, Any],
    *,
    result: Any,
    log: list[dict[str, Any]],
) -> None:
    from solo_countdown_wake_micro_core import _session_keys

    sk = _session_keys(BRIDGE_SESSION_PREFIX)
    stages = [str(r.get("stage") or "") for r in log if isinstance(r, dict)]
    chain = "|".join(stages[-80:])
    reruns = list(session.get(sk["rerun_log"]) or [])
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    st.markdown(
        f'<div id="solo-early-bridge-diag" '
        f'data-present="1" '
        f'data-source="live_draft_solo_early_bridge_diag.try_early_bridge_ldr_entry" '
        f'data-key-before="{str(session.get(KEY_BEFORE_START) or "").replace(chr(34), chr(39))}" '
        f'data-key-after="{str(session.get(KEY_AFTER_START) or "").replace(chr(34), chr(39))}" '
        f'data-key-current="{result.widget_key.replace(chr(34), chr(39))}" '
        f'data-run-before="{str(session.get(RUN_BEFORE_START) or "").replace(chr(34), chr(39))}" '
        f'data-run-after="{str(session.get(RUN_AFTER_START) or "").replace(chr(34), chr(39))}" '
        f'data-mount-run="{str(session.get(sk["mount_run"]) or "").replace(chr(34), chr(39))}" '
        f'data-expire-run="{str(session.get(sk["expire_run"]) or "").replace(chr(34), chr(39))}" '
        f'data-phase="{str(session.get(PHASE_KEY) or "").replace(chr(34), chr(39))}" '
        f'data-room-active="{1 if _room_active(session, room) else 0}" '
        f'data-room-id="{str(room.get("draft_room_id") or room.get("draft_id") or "").replace(chr(34), chr(39))}" '
        f'data-token="{result.token.replace(chr(34), chr(39))}" '
        f'data-stages="{chain.replace(chr(34), chr(39))}" '
        f'data-reruns="{len(reruns)}" '
        f'data-rerun-log="{json.dumps(reruns, default=str)[:6000].replace(chr(34), chr(39))}" '
        f'data-complete="{1 if result.delivered else 0}" '
        f'data-on-change="{1 if result.on_change_fired else 0}" '
        f'data-raw-received="{1 if result.raw_received else 0}" '
        f'data-same-key="{1 if session.get(KEY_BEFORE_START) and session.get(KEY_BEFORE_START) == session.get(KEY_AFTER_START, session.get(KEY_BEFORE_START)) else 0}" '
        f'></div>',
        unsafe_allow_html=True,
    )


def try_early_bridge_ldr_entry(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    """Mount at LDR early entry; never st.stop — active draft may render underneath."""
    try:
        from live_draft_solo_bridge_transition_diag import bridge_transition_active

        if bridge_transition_active(st, session):
            return False
    except ImportError:
        pass
    if not early_bridge_active(st, session):
        return False
    if not delivery_diag_active(st, session):
        return False

    room_dict = room if isinstance(room, dict) else {}
    session["_solo_placement_ladder_block_picks"] = True
    session[SOLO_DELIVERY_META_KEY] = {
        **dict(session.get(SOLO_DELIVERY_META_KEY) or {}),
        "early_bridge": True,
        "mount_location": BRIDGE_LOCATION,
        "rerun_count": bump_delivery_rerun(session),
    }
    record = _record_stage_factory(session)
    render_parent_postmessage_listener(st)

    did = "DIAGBRIDGE"
    if room_dict.get("draft_room_id") or room_dict.get("draft_id"):
        did = str(room_dict.get("draft_room_id") or room_dict.get("draft_id") or did)

    from solo_countdown_wake_micro_core import render_micro_isolation_once

    result = render_micro_isolation_once(
        st,
        session,
        placement=BRIDGE_PLACEMENT,
        location=BRIDGE_LOCATION,
        record_stage=record,
        draft_id=did,
        route=True,
        persistent=True,
        session_prefix=BRIDGE_SESSION_PREFIX,
    )
    _snapshot_phase(session, room_dict, result.widget_key)
    log = list(session.get(SOLO_DELIVERY_LOG_KEY) or [])
    render_early_bridge_probe(st, session, result=result, log=log)
    return True
