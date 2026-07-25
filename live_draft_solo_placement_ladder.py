"""Diagnostic placement ladder for solo_countdown_wake (query-param gated)."""

from __future__ import annotations

import json
import time
from typing import Any

from live_draft_solo_delivery_diag import (
    SOLO_DELIVERY_LOG_KEY,
    SOLO_DELIVERY_META_KEY,
    SOLO_DELIVERY_RERUN_KEY,
    bump_delivery_rerun,
    delivery_diag_active,
    note_delivery_stage,
    render_parent_postmessage_listener,
)

PLACEMENTS = ("P0", "P1", "P2", "P3", "P4", "P5")
SESSION_PLACEMENT_KEY = "_solo_placement_ladder_active"
REQUESTED_PLACEMENT_KEY = "_solo_placement_ladder_requested"


def _qp_get(st: Any, name: str) -> str:
    try:
        from live_draft_cloud_diagnostics import _qp_get as _get

        return _get(st, name)
    except ImportError:
        return ""


def placement_from_query(st: Any | None) -> str:
    raw = (_qp_get(st, "solo_placement_ladder") if st is not None else "").strip().upper()
    if raw in PLACEMENTS:
        return raw
    return ""


def placement_ladder_active(st: Any, session: dict[str, Any]) -> bool:
    if not delivery_diag_active(st, session):
        return False
    p = (
        placement_from_query(st)
        or str(session.get(REQUESTED_PLACEMENT_KEY) or session.get(SESSION_PLACEMENT_KEY) or "").upper()
    )
    return p in PLACEMENTS


def latch_requested_placement(st: Any, session: dict[str, Any]) -> str:
    """Diagnostic-only: persist requested placement before query params may be stripped."""
    if not delivery_diag_active(st, session):
        return ""
    p = placement_from_query(st)
    if p in PLACEMENTS:
        session[REQUESTED_PLACEMENT_KEY] = p
        session[SESSION_PLACEMENT_KEY] = p
    return str(session.get(REQUESTED_PLACEMENT_KEY) or "")


def render_latch_probe(st: Any, session: dict[str, Any]) -> None:
    requested = str(session.get(REQUESTED_PLACEMENT_KEY) or "")
    if not requested:
        return
    qp = placement_from_query(st)
    st.markdown(
        f'<div id="solo-placement-latch-diag" '
        f'data-requested="{requested}" '
        f'data-query-placement="{qp.replace(chr(34), chr(39))}" '
        f'data-active="{str(session.get(SESSION_PLACEMENT_KEY) or "").replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )


def enable_placement_ladder_from_query(st: Any, session: dict[str, Any]) -> None:
    if delivery_diag_active(st, session):
        latch_requested_placement(st, session)
    elif str(session.get(REQUESTED_PLACEMENT_KEY) or "") in PLACEMENTS:
        session[SESSION_PLACEMENT_KEY] = session[REQUESTED_PLACEMENT_KEY]
    if str(session.get(REQUESTED_PLACEMENT_KEY) or "") in PLACEMENTS:
        render_latch_probe(st, session)


def current_placement(st: Any, session: dict[str, Any]) -> str:
    p = placement_from_query(st)
    if p not in PLACEMENTS:
        p = str(session.get(REQUESTED_PLACEMENT_KEY) or session.get(SESSION_PLACEMENT_KEY) or "").upper()
    if p in PLACEMENTS:
        session[SESSION_PLACEMENT_KEY] = p
        return p
    return ""


def _script_run_id(session: dict[str, Any]) -> str:
    try:
        from app_page_generation import current_script_run_id

        return str(current_script_run_id(session) or "")
    except ImportError:
        pass
    return str(session.get("_live_draft_script_run_id") or session.get("_page_generation") or "")


def _fragment_context(session: dict[str, Any]) -> str:
    try:
        from live_draft_cloud_diagnostics import fragment_owner_summary

        return str(fragment_owner_summary(session) or "")
    except ImportError:
        return str(session.get("_solo_heartbeat_fragment_id") or "")


def draft_id_for_placement(placement: str) -> str:
    return f"DIAG{placement}"


def _record_stage_factory(session: dict[str, Any], placement: str) -> Any:
    mount_run = _script_run_id(session)

    def _record(stage: str, fields: dict[str, Any]) -> None:
        note_delivery_stage(
            session,
            stage,
            placement=placement,
            mount_script_run=mount_run,
            fragment_context=_fragment_context(session),
            **fields,
        )

    return _record


def render_placement_probe(
    st: Any,
    session: dict[str, Any],
    *,
    placement: str,
    result: Any,
    passed: bool,
) -> None:
    from solo_countdown_wake_matrix_core import COMPONENT_NAME, REQUIRED_CYCLES

    log = list(session.get(SOLO_DELIVERY_LOG_KEY) or [])
    meta = dict(session.get(SOLO_DELIVERY_META_KEY) or {})
    stages = [str(r.get("stage") or "") for r in log if isinstance(r, dict)]
    chain = "|".join(stages[-80:])
    callbacks = getattr(result, "callbacks", None) or []
    payload = json.dumps(
        {
            "placement": placement,
            "log": log[-40:],
            "meta": meta,
            "callbacks": callbacks,
            "cycles_done": getattr(result, "cycles_done", 0),
            "required_cycles": REQUIRED_CYCLES,
            "passed": passed,
            "mount_count": getattr(result, "mount_count", 0),
            "mount_script_run": _script_run_id(session),
            "fragment_context": _fragment_context(session),
        },
        default=str,
    )[:8000]
    wkey = str(getattr(result, "widget_key", "") or "")
    token = str(getattr(result, "token", "") or "")
    st.markdown(
        f'<div id="solo-placement-ladder-diag" '
        f'data-p2-harness="v2" '
        f'data-placement="{placement}" '
        f'data-passed="{1 if passed else 0}" '
        f'data-callbacks="{len(callbacks)}" '
        f'data-component-name="{COMPONENT_NAME}" '
        f'data-key="{wkey.replace(chr(34), chr(39))}" '
        f'data-token="{token.replace(chr(34), chr(39))}" '
        f'data-stages="{chain.replace(chr(34), chr(39))}" '
        f'data-rerun="{int(meta.get("rerun_count") or session.get(SOLO_DELIVERY_RERUN_KEY) or 0)}" '
        f'data-mount-run="{_script_run_id(session).replace(chr(34), chr(39))}" '
        f'data-fragment="{_fragment_context(session).replace(chr(34), chr(39))}" '
        f'data-json="{payload.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )


def run_one_placement_cycle(
    st: Any,
    session: dict[str, Any],
    *,
    placement: str,
    location: str,
    countdown_seconds: int | None = None,
) -> tuple[Any, bool]:
    """Run one 5s (or override) diagnostic cycle. Returns (result, should_stop_page)."""
    from solo_countdown_wake_matrix_core import COMPONENT_NAME, REQUIRED_CYCLES, render_one_cycle

    session[SESSION_PLACEMENT_KEY] = placement
    session[SOLO_DELIVERY_META_KEY] = {
        **dict(session.get(SOLO_DELIVERY_META_KEY) or {}),
        "placement": placement,
        "mount_location": location,
        "component_name": COMPONENT_NAME,
        "rerun_count": bump_delivery_rerun(session),
        "mount_script_run": _script_run_id(session),
    }
    record = _record_stage_factory(session, placement)
    render_parent_postmessage_listener(st)
    result = render_one_cycle(
        st,
        session,
        route=True,
        record_stage=record,
        draft_id=draft_id_for_placement(placement),
        placement=placement,
        countdown_seconds=countdown_seconds,
    )
    passed = bool(result.passed_all)
    render_placement_probe(st, session, placement=placement, result=result, passed=passed)
    if result.should_rerun:
        st.rerun()
    # In-draft ladder steps must not fall through to production timer UI between cycles.
    if placement in ("P2", "P3", "P4", "P5") and not result.passed_all and not result.should_rerun:
        st.stop()
    # Keep P2 ladder active across reruns until four cycles complete (diagnostic re-entry).
    if placement == "P2" and not result.passed_all:
        session["_solo_p2_ladder_awaiting_cycles"] = True
    if placement == "P0":
        return result, True
    return result, bool(result.passed_all)


def try_placement_early_entry(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
) -> tuple[bool, bool]:
    """P0/P1 at Live Draft Room page entry. Returns (handled, should_st_stop)."""
    try:
        from live_draft_solo_placement_micro import micro_isolation_active, try_micro_p1_ldr_entry

        if micro_isolation_active(st, session):
            if try_micro_p1_ldr_entry(st, session, room):
                return True, True
            return False, False
    except ImportError:
        pass
    placement = current_placement(st, session)
    if placement not in ("P0", "P1"):
        return False, False
    _, stop = run_one_placement_cycle(
        st,
        session,
        placement=placement,
        location="ldr_page_entry_early",
    )
    if placement == "P1" and not stop:
        return True, False
    return True, stop

def try_placement_timer_pre_owner(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
) -> bool:
    """P2: immediately before production solo expire owner."""
    try:
        from live_draft_solo_placement_micro import micro_blocks_placement_ladder

        if micro_blocks_placement_ladder(session):
            return False
    except ImportError:
        pass
    if current_placement(st, session) != "P2":
        return False
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if not is_solo_live_draft(session, room):
            return False
    except ImportError:
        return False
    if str(room.get("status") or "") != "in_progress":
        return False
    render_latch_probe(st, session)
    result, _stop = run_one_placement_cycle(
        st,
        session,
        placement="P2",
        location="before_solo_expire_owner",
    )
    if not result.passed_all:
        st.stop()
    else:
        st.stop()
    return True


def try_placement_in_heartbeat_fragment(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
) -> bool:
    """P3: inside solo heartbeat fragment surface (local fragment owner)."""
    if current_placement(st, session) != "P3":
        return False
    try:
        from live_draft_solo_expire_chain import solo_expire_owner

        if solo_expire_owner(session) != "fragment":
            return False
    except ImportError:
        return False
    session["_solo_placement_ladder_suppress_heartbeat_tick"] = True
    _, stop = run_one_placement_cycle(
        st,
        session,
        placement="P3",
        location="solo_heartbeat_fragment_context",
    )
    if stop:
        st.stop()
    return True


def try_placement_wake_component_context(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
) -> bool:
    """P3 on Cloud wake owner: mount inside production countdown render context."""
    if current_placement(st, session) != "P3":
        return False
    _, stop = run_one_placement_cycle(
        st,
        session,
        placement="P3",
        location="solo_wake_component_context",
    )
    if stop:
        st.stop()
    return True


def try_placement_production_slot(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
) -> bool:
    """P4: production timer slot; direct diag mount, no pick processing."""
    if current_placement(st, session) != "P4":
        return False
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if not is_solo_live_draft(session, room):
            return False
    except ImportError:
        return False
    session["_solo_placement_ladder_block_picks"] = True
    _, stop = run_one_placement_cycle(
        st,
        session,
        placement="P4",
        location="production_timer_slot_diag_direct",
    )
    if stop:
        st.stop()
    return True


def try_placement_production_wake(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
) -> bool:
    """P5: production wrapper path with 10s diagnostic deadline; block pick commit."""
    if current_placement(st, session) != "P5":
        return False
    try:
        from live_draft_solo_timer import is_solo_live_draft
        from live_draft_solo_expire_chain import solo_expire_owner

        if not is_solo_live_draft(session, room):
            return False
        if solo_expire_owner(session) != "wake":
            return False
    except ImportError:
        return False
    session["_solo_placement_ladder_block_picks"] = True
    session["_solo_placement_ladder_p5_diag_only"] = True
    _, stop = run_one_placement_cycle(
        st,
        session,
        placement="P5",
        location="production_wake_wrapper",
        countdown_seconds=10,
    )
    if stop:
        st.stop()
    return True


def placement_blocks_pick_processing(session: dict[str, Any]) -> bool:
    return bool(
        session.get("_solo_placement_ladder_block_picks")
        or session.get("_solo_placement_ladder_p5_diag_only")
    )
