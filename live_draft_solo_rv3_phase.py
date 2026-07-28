"""RV3 diagnostic-only state machine: setup → production mount → post-delivery."""

from __future__ import annotations

import time
from typing import Any

RV3_PHASE_KEY = "_solo_rv_rv3_phase"
RV3_PHASE_RUN_KEY = "_solo_rv_rv3_phase_run_id"
RV3_BLOCK_DIAG_KEY = "_solo_rv_rv3_block_diag_countdowns"
RV3_HYDRATED_KEY = "_solo_rv_rv3_real_room_hydrated"
RV3_DECLARED_THIS_RUN_KEY = "_solo_rv_rv3_production_declared_this_run"
RV3_SETUP_COMPLETE_KEY = "_solo_rv_rv3_setup_complete"
RV3_MOUNT_OK_THIS_RUN_KEY = "_solo_rv_rv3_mount_ok_this_run"
RV3_MOUNT_BLOCK_REASON_KEY = "_solo_rv_rv3_mount_block_reason"

RV3_PHASE_SETUP = "SETUP"
RV3_PHASE_PRODUCTION_MOUNT = "PRODUCTION_MOUNT"
RV3_PHASE_POST_DELIVERY = "POST_DELIVERY"

RV3_SETUP_LEDGER_TAIL = (
    "production_setup_owner_established",
    "rv3_setup_complete",
    "rv3_setup_rerun_requested",
)

RV3_MOUNT_LEDGER_HEAD = (
    "production_room_reused",
    "real_room_hydrated",
    "room_state_source",
    "rv3_production_placement_entered",
    "declaration_attempt",
    "declaration_returned",
)


def _run_id(session: dict[str, Any]) -> str:
    return str(session.get("_solo_rv_run_id") or "").strip()


def init_rv3_run_state(session: dict[str, Any], run_id: str) -> None:
    session[RV3_PHASE_KEY] = RV3_PHASE_SETUP
    session[RV3_PHASE_RUN_KEY] = run_id
    session[RV3_BLOCK_DIAG_KEY] = True
    session[RV3_HYDRATED_KEY] = False
    session.pop(RV3_DECLARED_THIS_RUN_KEY, None)
    session.pop(RV3_SETUP_COMPLETE_KEY, None)
    session.pop("_solo_rv_rv3_production_setup_done", None)
    session.pop("_solo_rv_prior_declaration_returned", None)


def get_rv3_phase(session: dict[str, Any]) -> str:
    if str(session.get("_solo_rv_ladder_step") or "") != "RV3":
        return ""
    rid = _run_id(session)
    bound = str(session.get(RV3_PHASE_RUN_KEY) or "")
    if bound and rid and bound != rid:
        init_rv3_run_state(session, rid)
    return str(session.get(RV3_PHASE_KEY) or RV3_PHASE_SETUP)


def set_rv3_phase(session: dict[str, Any], phase: str) -> None:
    session[RV3_PHASE_KEY] = phase


def rv3_active(session: dict[str, Any]) -> bool:
    return str(session.get("_solo_rv_ladder_step") or "") == "RV3"


def rv3_blocks_diag_countdowns(session: dict[str, Any]) -> bool:
    if not rv3_active(session):
        return False
    if not session.get(RV3_BLOCK_DIAG_KEY, True):
        return False
    if session.get(RV3_HYDRATED_KEY):
        return False
    phase = get_rv3_phase(session)
    return phase in (RV3_PHASE_SETUP, "")


def rv3_allows_full_ldr_countdown(session: dict[str, Any]) -> bool:
    if not rv3_active(session):
        return True
    phase = get_rv3_phase(session)
    return phase in (RV3_PHASE_PRODUCTION_MOUNT, RV3_PHASE_POST_DELIVERY)


def is_rv3_rejected_token(token: str) -> bool:
    t = str(token or "").strip()
    if not t:
        return False
    upper = t.upper()
    if "PARITY" in upper or "MINIMAL" in upper or "WIRING" in upper:
        return True
    return False


def token_matches_production_room(token: str, room_id: str) -> bool:
    rid = str(room_id or "").strip().upper()
    t = str(token or "").strip()
    if not rid or not t or is_rv3_rejected_token(t):
        return False
    parts = t.split("|")
    if len(parts) < 3:
        return False
    return str(parts[0]).strip().upper() == rid


def _owner_room_id(session: dict[str, Any]) -> str:
    try:
        from live_draft_solo_rv_production_room_setup import RV1_SETUP_OWNER_KEY

        owner = session.get(RV1_SETUP_OWNER_KEY) or {}
        if isinstance(owner, dict):
            return str(owner.get("room_id") or "").strip().upper()
    except ImportError:
        pass
    return ""


def rv3_declaration_allowed(
    session: dict[str, Any],
    *,
    expected_token: str,
    location: str,
) -> tuple[bool, str]:
    """Return (allowed, invalid_reason)."""
    if not rv3_active(session):
        return True, ""
    phase = get_rv3_phase(session)
    if phase == RV3_PHASE_SETUP:
        return False, "INVALID_RV3_PREMATURE_COMPONENT_DECLARATION"
    if not session.get(RV3_HYDRATED_KEY):
        return False, "INVALID_RV3_PREMATURE_COMPONENT_DECLARATION"
    if not session.get(RV3_MOUNT_OK_THIS_RUN_KEY):
        blocked = str(session.get(RV3_MOUNT_BLOCK_REASON_KEY) or "").strip()
        if blocked.startswith("INVALID_RV3"):
            return False, blocked
        return False, "INVALID_RV3_POST_DELIVERY_ROOM_STATE_LOST"
    rid = _owner_room_id(session)
    if is_rv3_rejected_token(expected_token):
        return False, "INVALID_RV3_PREMATURE_COMPONENT_DECLARATION"
    if rid and not token_matches_production_room(expected_token, rid):
        return False, "INVALID_RV3_PREMATURE_COMPONENT_DECLARATION"
    if phase not in (RV3_PHASE_PRODUCTION_MOUNT, RV3_PHASE_POST_DELIVERY):
        return False, "INVALID_RV3_PRODUCTION_DECLARATION_NOT_REACHED"
    if session.get(RV3_DECLARED_THIS_RUN_KEY) and phase == RV3_PHASE_PRODUCTION_MOUNT:
        return False, "INVALID_RV3_DUPLICATE_PRODUCTION_DECLARATION"
    return True, ""


def mark_rv3_production_declared(session: dict[str, Any]) -> None:
    session[RV3_DECLARED_THIS_RUN_KEY] = True


def mark_rv3_hydrated(session: dict[str, Any]) -> None:
    session[RV3_HYDRATED_KEY] = True
    session[RV3_BLOCK_DIAG_KEY] = False


def append_rv3_setup_complete(st: Any, session: dict[str, Any], *, probe_placeholder: Any = None) -> None:
    from live_draft_solo_rv_control_probe import append_control_event, render_native_control_probe

    session[RV3_SETUP_COMPLETE_KEY] = True
    append_control_event(st, session, "rv3_setup_complete", control_name="RV3")
    append_control_event(st, session, "rv3_setup_rerun_requested", control_name="RV3")
    set_rv3_phase(session, RV3_PHASE_PRODUCTION_MOUNT)
    session["_solo_rv_rv3_production_setup_done"] = True
    if probe_placeholder is not None:
        render_native_control_probe(st, session, probe_placeholder)


def prepare_rv3_production_mount(
    st: Any,
    session: dict[str, Any],
    *,
    probe_placeholder: Any = None,
) -> dict[str, Any]:
    """Reuse room, hydrate ledger fields, enter production placement (PRODUCTION_MOUNT / POST_DELIVERY)."""
    from live_draft_solo_rv_binding_ladder import hydrate_real_room_for_rv_ladder
    from live_draft_solo_rv_control_probe import append_control_event, render_native_control_probe
    from live_draft_solo_rv3_room_continuity import (
        record_rv3_room_checkpoint,
        restore_rv3_run_scoped_room,
        rv3_reuse_owned_room_only,
    )

    phase = get_rv3_phase(session)
    if phase not in (RV3_PHASE_PRODUCTION_MOUNT, RV3_PHASE_POST_DELIVERY):
        return {"ok": False, "reason": "wrong_phase", "invalid": "INVALID_RV3_PRODUCTION_DECLARATION_NOT_REACHED"}

    record_rv3_room_checkpoint(st, session, "before_prepare_rv3_production_mount", probe_placeholder=probe_placeholder)
    restore_rv3_run_scoped_room(session)

    if phase == RV3_PHASE_POST_DELIVERY:
        setup = rv3_reuse_owned_room_only(st, session, probe_placeholder=probe_placeholder)
    else:
        from live_draft_solo_rv_production_room_setup import ensure_rv1_production_solo_room

        setup = ensure_rv1_production_solo_room(st, session, probe_placeholder=probe_placeholder)
    if not setup.get("ok"):
        inv = str(setup.get("invalid") or "INVALID_RV3_REAL_ROOM_NOT_HYDRATED")
        session.pop(RV3_MOUNT_OK_THIS_RUN_KEY, None)
        session[RV3_MOUNT_BLOCK_REASON_KEY] = inv
        record_rv3_room_checkpoint(st, session, "after_prepare_rv3_production_mount_failed", probe_placeholder=probe_placeholder)
        return {"ok": False, "reason": str(setup.get("reason") or ""), "invalid": inv}

    hydrated = hydrate_real_room_for_rv_ladder(st, session, probe_placeholder=probe_placeholder)
    if not hydrated.get("ok"):
        inv = "INVALID_RV3_POST_DELIVERY_ROOM_STATE_LOST" if phase == RV3_PHASE_POST_DELIVERY else "INVALID_RV3_REAL_ROOM_NOT_HYDRATED"
        session.pop(RV3_MOUNT_OK_THIS_RUN_KEY, None)
        session[RV3_MOUNT_BLOCK_REASON_KEY] = inv
        record_rv3_room_checkpoint(st, session, "after_prepare_rv3_production_mount_failed", probe_placeholder=probe_placeholder)
        return {
            "ok": False,
            "reason": str(hydrated.get("reason") or "hydration_failed"),
            "invalid": inv,
        }

    owner_rid = _owner_room_id(session)
    token = str(hydrated.get("token") or "")
    live = dict(hydrated.get("room") or {})
    got_rid = str(live.get("draft_room_id") or "").strip().upper()
    if owner_rid and got_rid and owner_rid != got_rid:
        return {"ok": False, "reason": "room_id_mismatch", "invalid": "INVALID_RV3_REAL_ROOM_NOT_HYDRATED"}
    if not token_matches_production_room(token, owner_rid or got_rid):
        return {"ok": False, "reason": "token_mismatch", "invalid": "INVALID_RV3_PRODUCTION_DECLARATION_NOT_REACHED"}

    mark_rv3_hydrated(session)
    session[RV3_MOUNT_OK_THIS_RUN_KEY] = True
    session.pop(RV3_MOUNT_BLOCK_REASON_KEY, None)
    record_rv3_room_checkpoint(st, session, "after_prepare_rv3_production_mount", probe_placeholder=probe_placeholder)
    append_control_event(
        st,
        session,
        "rv3_production_placement_entered",
        control_name="RV3",
        room=live,
        expected_token=token,
        extra={
            "phase": phase,
            "source_module": "live_draft_solo_persistent_wake",
            "source_function": "try_solo_persistent_wake_ldr_entry",
            "location": "ldr_page_entry_early_persistent",
        },
    )
    if probe_placeholder is not None:
        render_native_control_probe(st, session, probe_placeholder)
    return {"ok": True, "token": token, "room": live, "room_id": got_rid}


def rv3_on_script_run_begin(session: dict[str, Any]) -> None:
    if rv3_active(session):
        session.pop(RV3_DECLARED_THIS_RUN_KEY, None)
        session.pop(RV3_MOUNT_OK_THIS_RUN_KEY, None)
        session.pop(RV3_MOUNT_BLOCK_REASON_KEY, None)
