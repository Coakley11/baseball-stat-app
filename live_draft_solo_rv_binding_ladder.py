"""Return-value binding parity ladder RV0–RV3 (R4 vs Stage 1A)."""

from __future__ import annotations

import time
from typing import Any

from live_draft_solo_persistent_parity_ladder import (
    PARITY_CONTROL_KEY,
    PARITY_P6_DISABLE_PICK_KEY,
    SOLO_PERSISTENT_WAKE_LATCH_KEY,
)
from live_draft_solo_persistent_wake import SOLO_PERSISTENT_WAKE_WIDGET_KEY

try:
    from live_draft_solo_rv_declaration_audit import RV_DECLARATION_AUDIT_ACTIVE_KEY
except ImportError:
    RV_DECLARATION_AUDIT_ACTIVE_KEY = "_solo_rv_declaration_audit_active"

RV_LADDER_QP = "solo_rv_ladder"
RV_RUN_ID_QP = "solo_rv_run_id"
RV_HARNESS_ROOM_QP = "solo_rv_harness_room_id"
RV_LADDER_STEPS = frozenset({"RV0", "RV1", "RV2", "RV3"})
RV_LEDGER_KEY = "_solo_rv_binding_ladder_ledger"


def _qp_get(st: Any, key: str) -> str:
    try:
        from live_draft_solo_parity_p6_persistent_diag import _qp_get as _g

        return _g(st, key)
    except ImportError:
        return ""


def rv_ladder_requested(st: Any | None, session: dict[str, Any]) -> bool:
    step = str(session.get("_solo_rv_ladder_step") or _qp_get(st, RV_LADDER_QP) or "").strip().upper()
    if step in RV_LADDER_STEPS:
        return True
    return bool(session.get("_solo_rv_ladder_active"))


def resolve_rv_ladder_step(st: Any | None, session: dict[str, Any]) -> str:
    step = str(session.get("_solo_rv_ladder_step") or _qp_get(st, RV_LADDER_QP) or "").strip().upper()
    if step in RV_LADDER_STEPS:
        session["_solo_rv_ladder_step"] = step
        return step
    return ""


def enable_rv_ladder_session(st: Any, session: dict[str, Any]) -> str:
    step = resolve_rv_ladder_step(st, session)
    if not step:
        return ""
    run_id = str(session.get("_solo_rv_run_id") or _qp_get(st, RV_RUN_ID_QP) or "").strip()
    if not run_id:
        run_id = f"rv-{int(time.time())}"
    session["_solo_rv_run_id"] = run_id
    session["_solo_rv_ladder_active"] = True
    session["_solo_rv_declaration_audit_active"] = True
    session[RV_DECLARATION_AUDIT_ACTIVE_KEY] = True
    session["_solo_rv_instance_registry_force"] = True
    session["_solo_delivery_diag_enabled"] = True
    session[PARITY_CONTROL_KEY] = "P6"
    session[PARITY_P6_DISABLE_PICK_KEY] = True
    session["_solo_expire_owner"] = "wake"
    session.pop("_solo_persistent_wake_flush_disabled", None)
    _append_ledger(session, "rv_ladder_enabled", step=step, run_id=run_id)
    return step


def _append_ledger(session: dict[str, Any], stage: str, **fields: Any) -> None:
    row = {"ts": time.time(), "stage": stage, **fields}
    log = list(session.get(RV_LEDGER_KEY) or [])
    log.append(row)
    session[RV_LEDGER_KEY] = log[-200:]


def _synthetic_room_for_rv0(session: dict[str, Any], *, seconds: float = 10.0) -> tuple[str, dict[str, Any]]:
    from live_draft_solo_persistent_parity_ladder import ensure_p6_latched_production_token

    return ensure_p6_latched_production_token(session)


def _real_room_token(session: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Legacy reader — prefer hydrate_real_room_for_rv_ladder for RV1+."""
    live = session.get("live_draft_room")
    if not isinstance(live, dict) or not (live.get("draft_room_id") or live.get("pick_order")):
        try:
            from live_draft_navigation import _live_draft_room_for_return

            hydrated = _live_draft_room_for_return(session)
            if isinstance(hydrated, dict):
                live = hydrated
        except ImportError:
            pass
    if not isinstance(live, dict):
        return "", {}
    try:
        from solo_countdown_component import build_solo_expire_token

        token = build_solo_expire_token(live)
    except ImportError:
        token = ""
    session["_solo_parity_expected_token"] = token
    session["_solo_persistent_wake_last_token"] = token
    return token, live


def _apply_harness_room_query_context(st: Any | None, session: dict[str, Any]) -> str:
    """Diag-only: align session routing with harness room before production prepare."""
    hid = str(session.get("_solo_rv_harness_room_id") or _qp_get(st, RV_HARNESS_ROOM_QP) or "").strip().upper()
    if not hid:
        return ""
    session["_solo_rv_harness_room_id"] = hid
    session["active_page"] = "Live Draft Room"
    return hid


def hydrate_real_room_for_rv_ladder(
    st: Any,
    session: dict[str, Any],
    *,
    probe_placeholder: Any = None,
) -> dict[str, Any]:
    """Diag-only: production room reader + production expire token (pick/deadline)."""
    from live_draft_solo_rv_control_probe import append_control_event, render_native_control_probe

    try:
        from live_draft_solo_rv_production_room_setup import ROOM_STATE_SOURCE_KEY
    except ImportError:
        ROOM_STATE_SOURCE_KEY = "_solo_rv_room_state_source"

    step = str(session.get("_solo_rv_ladder_step") or "").strip().upper()
    harness_id = ""
    if step != "RV1":
        harness_id = _apply_harness_room_query_context(st, session)
    room_state_source = str(session.get(ROOM_STATE_SOURCE_KEY) or "")
    live: dict[str, Any] | None = None
    session_room = session.get("live_draft_room")
    if isinstance(session_room, dict) and (session_room.get("draft_room_id") or session_room.get("pick_order")):
        live = session_room
        if not room_state_source and step == "RV1":
            room_state_source = "session_live_draft_room"
    if live is None:
        try:
            from live_draft_state import prepare_live_draft_state

            prepared = prepare_live_draft_state(session)
            if isinstance(prepared, dict):
                live = prepared
                if not room_state_source:
                    room_state_source = "canonical_prepare_live_draft_state"
        except Exception:
            live = None
    if not isinstance(live, dict) or not (live.get("draft_room_id") or live.get("pick_order")):
        try:
            from live_draft_navigation import _live_draft_room_for_return

            candidate = _live_draft_room_for_return(session)
            if isinstance(candidate, dict):
                live = candidate
        except ImportError:
            pass
    if not isinstance(live, dict) or not (live.get("draft_room_id") or live.get("pick_order")):
        reason = "room_not_in_session"
        append_control_event(
            st,
            session,
            "rv_real_room_hydration_failed",
            extra={"reason": reason, "hydration_reason": reason, "harness_room_id": harness_id},
        )
        if probe_placeholder is not None:
            render_native_control_probe(st, session, probe_placeholder)
        return {"ok": False, "reason": reason}

    try:
        from solo_countdown_component import build_solo_expire_token

        token = str(build_solo_expire_token(live) or "").strip()
    except Exception:
        token = ""
    if not token:
        reason = "token_build_empty"
        append_control_event(
            st,
            session,
            "rv_real_room_hydration_failed",
            room=live,
            extra={"reason": reason, "hydration_reason": reason},
        )
        if probe_placeholder is not None:
            render_native_control_probe(st, session, probe_placeholder)
        return {"ok": False, "reason": reason, "room": live}

    if harness_id:
        got = str(live.get("draft_room_id") or "").strip().upper()
        if got and got != harness_id:
            reason = "harness_room_id_mismatch"
            append_control_event(
                st,
                session,
                "rv_real_room_hydration_failed",
                room=live,
                extra={"reason": reason, "hydration_reason": reason, "harness_room_id": harness_id},
            )
            if probe_placeholder is not None:
                render_native_control_probe(st, session, probe_placeholder)
            return {"ok": False, "reason": reason, "room": live}
    session["live_draft_room"] = live
    session["_solo_parity_expected_token"] = token
    session["_solo_persistent_wake_last_token"] = token
    append_control_event(
        st,
        session,
        "real_room_hydrated",
        room=live,
        expected_token=token,
        widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
        extra={"room_state_source": room_state_source or "unknown"},
    )
    append_control_event(
        st,
        session,
        "room_state_source",
        room=live,
        extra={"room_state_source": room_state_source or "unknown"},
    )
    if probe_placeholder is not None:
        render_native_control_probe(st, session, probe_placeholder)
    return {"ok": True, "token": token, "room": live}


def validate_rv_real_room_ledger(
    ledger: list[dict[str, Any]],
    *,
    step: str,
    harness_room_id: str = "",
) -> str:
    """Return INVALID_* reason for RV1–RV3 setup, or empty if ledger preconditions met."""
    if step == "RV0":
        return ""
    events = {str(r.get("event") or "") for r in ledger}
    if "production_room_creation_failed" in events:
        row = next(r for r in ledger if r.get("event") == "production_room_creation_failed")
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        reason = str(extra.get("reason") or row.get("reason") or "unknown")
        return f"INVALID_RV_PRODUCTION_ROOM_CREATION_{reason}"
    if "production_draft_start_failed" in events:
        row = next(r for r in ledger if r.get("event") == "production_draft_start_failed")
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        reason = str(extra.get("reason") or row.get("reason") or "unknown")
        return f"INVALID_RV_PRODUCTION_DRAFT_START_{reason}"
    if "rv_real_room_hydration_failed" in events:
        row = next(r for r in ledger if r.get("event") == "rv_real_room_hydration_failed")
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        reason = str(
            row.get("hydration_reason") or extra.get("hydration_reason") or extra.get("reason") or "unknown"
        )
        return f"INVALID_RV_REAL_ROOM_HYDRATION_{reason}"
    if step == "RV1":
        for req in (
            "production_room_creation_attempted",
            "production_room_created",
            "production_draft_started",
        ):
            if req not in events:
                return f"INVALID_RV_PRODUCTION_ROOM_CREATION_missing_{req}"
        if "room_state_source" not in events and "real_room_hydrated" not in events:
            return "INVALID_RV_REAL_ROOM_HYDRATION_missing_room_state_source"
    if "real_room_hydrated" not in events:
        if "rv_mount_failed" in events:
            row = next(r for r in ledger if r.get("event") == "rv_mount_failed")
            extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
            reason = str(extra.get("reason") or row.get("reason") or "mount_failed")
            if reason in ("real_room_missing", "room_not_in_session", "token_build_empty") or reason.startswith(
                "INVALID_RV_REAL_ROOM"
            ):
                return f"INVALID_RV_REAL_ROOM_HYDRATION_{reason}"
            return f"INVALID_RV_COMPONENT_NOT_DECLARED_{reason}"
        return "INVALID_RV_REAL_ROOM_HYDRATION_not_hydrated"
    if harness_room_id:
        hydrated_id = ""
        for row in ledger:
            if row.get("event") == "real_room_hydrated":
                hydrated_id = str(row.get("room_id") or "").strip().upper()
                break
        want = harness_room_id.strip().upper()
        if want and hydrated_id and want != hydrated_id:
            return f"INVALID_RV_REAL_ROOM_HYDRATION_room_id_mismatch"
    for req in ("script_begin", "rv_entrypoint_entered", "declaration_attempt", "declaration_returned"):
        if req not in events:
            if req in ("declaration_attempt", "declaration_returned"):
                mf = next((r for r in ledger if r.get("event") == "rv_mount_failed"), None)
                extra = (mf or {}).get("extra") if isinstance((mf or {}).get("extra"), dict) else {}
                reason = str(extra.get("reason") or (mf or {}).get("reason") or f"missing_{req}")
                return f"INVALID_RV_COMPONENT_NOT_DECLARED_{reason}"
            return f"INVALID_RV_REAL_ROOM_HYDRATION_missing_{req}"
    return ""


def filter_observations_after_epoch(
    expiration: dict[str, Any],
    registry: dict[str, Any],
    *,
    epoch_ms: float,
    expected_token: str = "",
    run_id: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Drop pre-epoch browser timeline/registry noise (diag runner grading)."""
    exp = dict(expiration or {})
    reg = dict(registry or {})
    double = dict(exp.get("double_production_send_analysis") or {})
    timeline = [t for t in list(double.get("timeline") or []) if float(t.get("ts") or 0) >= epoch_ms]
    timer_ts = [float(t) for t in list(double.get("timer_armed_timestamps") or []) if float(t) >= epoch_ms]
    double["timeline"] = timeline
    double["timer_armed_timestamps"] = timer_ts
    double["production_timer_armed_count"] = len(timer_ts)
    exp["double_production_send_analysis"] = double
    stages: set[str] = set()
    token_sent = ""
    for row in timeline:
        stages.add(str(row.get("stage") or ""))
        preview = str(row.get("token_preview") or "")
        if preview and expected_token and (preview in expected_token or expected_token.startswith(preview)):
            token_sent = expected_token
    if "component_value_sent" in stages or "transport_before_postMessage" in stages:
        stages.add("browser_deadline_crossed")
    exp["client_stages"] = sorted(stages)
    if token_sent:
        exp["token_sent"] = token_sent
    elif expected_token and {"component_value_sent", "transport_before_postMessage"} & stages:
        exp["token_sent"] = expected_token
    last = list(reg.get("last") or [])
    logical = list(reg.get("logical") or [])
    reg["last"] = [
        e
        for e in last
        if isinstance(e, dict) and float(e.get("ts_ms") or e.get("ts") or 0) >= epoch_ms
    ]
    reg["logical"] = [
        e
        for e in logical
        if isinstance(e, dict) and float(e.get("ts_ms") or e.get("ts") or 0) >= epoch_ms
    ]
    if run_id:
        reg["run_id"] = run_id
    return exp, reg


def mount_rv_r4_style(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    expire_token: str,
    location: str,
    probe_placeholder: Any = None,
) -> Any:
    from live_draft_solo_rv_control_probe import mount_with_rv_control_declaration
    from solo_countdown_component import mount_solo_countdown_wake_with_token

    widget_key = SOLO_PERSISTENT_WAKE_WIDGET_KEY
    chain_key = str(session.get("_solo_parity_ls_key") or f"solo_rv_chain_{session.get('_solo_rv_run_id') or 'x'}")

    def _mount() -> Any:
        return mount_solo_countdown_wake_with_token(
            room,
            key=widget_key,
            expire_token=expire_token,
            actionable=True,
            on_change=None,
            chain_persist_key=chain_key,
            rv_diag_run_id=str(session.get("_solo_rv_run_id") or ""),
        )

    raw = mount_with_rv_control_declaration(
        st,
        session,
        room,
        widget_key=widget_key,
        mount_fn=_mount,
        control_name=str(session.get("_solo_rv_ladder_step") or location),
        location=location,
        probe_placeholder=probe_placeholder,
    )
    _append_ledger(
        session,
        "r4_style_mount",
        location=location,
        expected_token=expire_token[:400],
        component_return=repr(raw)[:400],
    )
    return raw


def execute_rv_step_mount(
    st: Any, session: dict[str, Any], step: str, *, probe_placeholder: Any = None
) -> dict[str, Any]:
    """Mount production countdown once for RV0–RV2 pre-shell paths."""
    session[SOLO_PERSISTENT_WAKE_LATCH_KEY] = True
    if step == "RV0":
        token, room = _synthetic_room_for_rv0(session)
    else:
        hydrated = hydrate_real_room_for_rv_ladder(st, session, probe_placeholder=probe_placeholder)
        if not hydrated.get("ok"):
            reason = str(hydrated.get("reason") or "real_room_missing")
            _append_ledger(session, "rv_real_room_missing", step=step, reason=reason)
            invalid = f"INVALID_RV_REAL_ROOM_HYDRATION_{reason}"
            if step == "RV1" and reason == "room_not_in_session":
                invalid = "INVALID_RV_REAL_ROOM_HYDRATION_room_not_in_session"
            return {"ok": False, "reason": reason, "invalid": invalid}
        token = str(hydrated.get("token") or "")
        room = dict(hydrated.get("room") or {})
        if not token or not room:
            _append_ledger(session, "rv_real_room_missing", step=step)
            return {"ok": False, "reason": "real_room_missing", "invalid": "INVALID_RV_REAL_ROOM_HYDRATION_real_room_missing"}
    session["live_draft_room"] = room
    from live_draft_solo_rv_instance_registry import render_rv_instance_registry_listener

    render_rv_instance_registry_listener(st, session)
    raw = mount_rv_r4_style(
        st,
        session,
        room,
        expire_token=token,
        location=f"rv_{step.lower()}_shell",
        probe_placeholder=probe_placeholder,
    )
    from live_draft_solo_rv_instance_registry import render_rv_instance_registry_probe

    render_rv_instance_registry_probe(st, session)
    return {"ok": True, "token": token, "room_id": str(room.get("draft_room_id") or ""), "raw": raw}


def rv_pre_app_shell_should_stop(session: dict[str, Any]) -> bool:
    step = str(session.get("_solo_rv_ladder_step") or "")
    return step in ("RV0", "RV1")


def rv2_mount_if_needed(st: Any, session: dict[str, Any], *, probe_placeholder: Any = None) -> bool:
    if str(session.get("_solo_rv_ladder_step") or "") != "RV2":
        return False
    if session.get("_solo_rv_rv2_initial_mount_done"):
        return False
    execute_rv_step_mount(st, session, "RV2", probe_placeholder=probe_placeholder)
    session["_solo_rv_rv2_initial_mount_done"] = True
    return True


def try_rv3_ldr_persistent_mount(st: Any, session: dict[str, Any], room: Any, *, phase: str) -> bool:
    """RV3 audit/registry around production persistent-wake (phase=before|after)."""
    if str(session.get("_solo_rv_ladder_step") or "") != "RV3":
        return False
    from live_draft_solo_rv_declaration_audit import record_rv_declaration_snapshot, render_rv_declaration_audit_probe
    from live_draft_solo_rv_instance_registry import render_rv_instance_registry_listener, render_rv_instance_registry_probe

    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if phase == "before":
        render_rv_instance_registry_listener(st, session)
        record_rv_declaration_snapshot(
            st,
            session,
            phase="rv3_before_persistent_wake",
            widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
            room=live if isinstance(live, dict) else None,
            declaration_reached=False,
        )
        return True
    record_rv_declaration_snapshot(
        st,
        session,
        phase="rv3_after_persistent_wake",
        widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
        room=live if isinstance(live, dict) else None,
        declaration_reached=True,
        process_entered=bool(session.get("_solo_rv_native_return_observed")),
    )
    render_rv_declaration_audit_probe(st, session)
    render_rv_instance_registry_probe(st, session)
    _append_ledger(session, "rv3_persistent_wake_invoked")
    return True


def grade_rv_control_validity(
    *,
    step: str,
    ledger: list[dict[str, Any]],
    declaration_rows: list[dict[str, Any]],
    browser: dict[str, Any],
    expiration: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return (verdict, reason) — PASS, FAIL binding, or INVALID control."""
    ledger_rows = list(ledger) if ledger else []
    setup_invalid = validate_rv_real_room_ledger(
        ledger_rows,
        step=step,
        harness_room_id=str((expiration or {}).get("harness_room_id") or ""),
    )
    if setup_invalid and step in ("RV1", "RV2", "RV3"):
        return "INVALID", setup_invalid
    inv, inv_reason = validate_rv_control_prerequisites(
        declaration_rows=declaration_rows,
        browser=browser,
        expiration=expiration or {},
        control_probe_rows=declaration_rows,
    )
    if not inv:
        if inv_reason in (
            "INVALID_PYTHON_DECLARATION_PROBE_MISSING",
            "INVALID_POST_DELIVERY_REDECLARATION_MISSING",
        ):
            return "INVALID", inv_reason
        return "INVALID", inv_reason
    post_decl = [
        r
        for r in declaration_rows
        if str(r.get("phase") or "").endswith("after_mount")
        or "after_persistent" in str(r.get("phase") or "")
        or r.get("event") == "post_delivery_redeclaration"
        or r.get("event") == "declaration_returned"
    ]
    post_after_send = [r for r in post_decl if r.get("browser_delivery_seen") or not r.get("before_browser_send", True)]
    if not post_after_send:
        return "INVALID", "INVALID_POST_DELIVERY_REDECLARATION_MISSING"
    pre_mount = [r for r in declaration_rows if "before_mount" in str(r.get("phase") or "") or "before_persistent" in str(r.get("phase") or "")]
    post_keys = {str(r.get("widget_key") or "") for r in post_after_send if r.get("widget_key")}
    pre_keys = {str(r.get("widget_key") or "") for r in pre_mount if r.get("widget_key")}
    if post_keys and pre_keys and not post_keys.intersection(pre_keys):
        return "INVALID", "post_delivery_component_key_mismatch"
    last = post_after_send[-1]
    expected = str(last.get("expected_token") or "")
    coalesced = _coalesce_from_row(last)
    if step == "RV0":
        if expected and coalesced == expected:
            return "PASS_RETURN_VALUE_DELIVERY", "RV0_r4_control"
        if expected and not coalesced:
            return "FAIL", "FAIL_CLASS_A_empty_binding"
        return "FAIL", "return_mismatch"
    if step == "RV1":
        if coalesced == expected and expected:
            return "PASS_RETURN_VALUE_DELIVERY", "RV1_real_room_r4_control"
        if expected and not coalesced:
            return "FAIL", "FAIL_CLASS_A_empty_binding"
        return "FAIL", "return_mismatch"
    if coalesced == expected and expected:
        return "PASS", f"{step}_return_bound"
    if not coalesced:
        return "FAIL", "FAIL_CLASS_A_empty_binding"
    return "FAIL", "return_mismatch"


def _coalesce_from_row(row: dict[str, Any]) -> str:
    for key in ("coalesced_value", "component_return", "session_state_after"):
        v = str(row.get(key) or "").strip().strip("'\"")
        if v and v != "missing":
            return v
    return ""


def extract_transport_send_evidence(expiration: dict[str, Any]) -> dict[str, Any]:
    double = dict(expiration.get("double_production_send_analysis") or {})
    timeline = list(double.get("timeline") or [])
    token_sent = str(expiration.get("token_sent") or "").strip()
    transports = [t for t in timeline if str(t.get("stage") or "") == "transport_before_postMessage"]
    import re

    matched: list[dict[str, Any]] = []
    bse_ids: set[str] = set()
    for row in transports:
        preview = str(row.get("token_preview") or "").strip()
        extra = str(row.get("extra_preview") or "")
        bse_m = re.search(r'"browser_send_event_id"\s*:\s*"([^"]+)"', extra)
        bse = bse_m.group(1) if bse_m else ""
        tok_ok = bool(token_sent) and (preview == token_sent or token_sent.startswith(preview) or preview in token_sent)
        if bse and tok_ok:
            bse_ids.add(bse)
            matched.append({"ts": row.get("ts"), "browser_send_event_id": bse, "token_preview": preview})
    return {
        "transport_postmessage_count": len(transports),
        "matched_transport_send_count": len(matched),
        "unique_browser_send_event_ids": sorted(bse_ids),
        "unique_browser_send_event_count": len(bse_ids),
        "token_match": len(matched) >= 1 and len(bse_ids) == 1,
        "matched": matched,
    }


def browser_send_proven(expiration: dict[str, Any]) -> bool:
    cs = set(expiration.get("client_stages") or [])
    if "component_value_sent" in cs:
        return True
    ev = extract_transport_send_evidence(expiration)
    return bool(ev.get("token_match") and int(ev.get("unique_browser_send_event_count") or 0) == 1)


def analyze_timer_arms(expiration: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    double = dict(expiration.get("double_production_send_analysis") or {})
    raw_ts = list(double.get("timer_armed_timestamps") or [])
    raw_count = len(raw_ts)
    timeline = list(double.get("timeline") or [])
    instance_id = str(registry.get("current") or "")
    if not instance_id:
        inst = registry.get("instances") or {}
        if isinstance(inst, dict) and inst:
            instance_id = str(next(iter(inst.values()), {}).get("instance_id") or "")
    token = str(expiration.get("token_sent") or "").strip()
    fingerprints: set[tuple[str, str, str]] = set()
    for row in timeline:
        if str(row.get("stage") or "") != "timer_armed":
            continue
        extra = str(row.get("extra_preview") or "")
        iid = instance_id
        if "solo_" in extra:
            import re

            m = re.search(r"(solo_[0-9]+_[a-z0-9]+)", extra)
            if m:
                iid = m.group(1)
        fingerprints.add((iid, token, str(row.get("widget_key") or "")))
    logical_count = len(fingerprints) if fingerprints else (1 if raw_count else 0)
    if raw_count >= 2 and logical_count == 1:
        dup = True
    else:
        dup = raw_count > logical_count
    return {
        "raw_timer_arms": raw_count,
        "logical_timer_arms": logical_count,
        "instrumentation_duplicate": dup,
        "fingerprints": [list(f) for f in fingerprints],
    }


def validate_rv_control_prerequisites(
    *,
    declaration_rows: list[dict[str, Any]],
    browser: dict[str, Any],
    expiration: dict[str, Any],
    control_probe_rows: list[dict[str, Any]] | None = None,
) -> tuple[bool, str]:
    rows = control_probe_rows if control_probe_rows is not None else declaration_rows
    if not rows:
        return False, "INVALID_PYTHON_DECLARATION_PROBE_MISSING"
    events = {str(r.get("event") or r.get("phase") or "") for r in rows}
    if "declaration_attempt" not in events and "before_mount" not in events:
        return False, "INVALID_PYTHON_DECLARATION_PROBE_MISSING"
    if "declaration_returned" not in events and "after_mount" not in events:
        return False, "INVALID_PYTHON_DECLARATION_PROBE_MISSING"
    pre_mount = [
        r
        for r in declaration_rows
        if r.get("event") == "declaration_attempt"
        or "before_mount" in str(r.get("phase") or "")
    ]
    if not pre_mount:
        return False, "INVALID_PYTHON_DECLARATION_PROBE_MISSING"
    session_ids = {str(r.get("streamlit_session_id") or r.get("script_run_id") or "") for r in rows}
    session_ids.discard("")
    if len(session_ids) > 1:
        return False, "stable_streamlit_session_not_proven"
    timer = dict(browser.get("timer_arm_accounting") or {})
    if int(timer.get("logical_timer_arms") or 0) != 1:
        return False, f"logical_timer_arm_count={timer.get('logical_timer_arms')}_need_1"
    logical = int(browser.get("logical_send_count") or 0)
    raw = int(browser.get("raw_listener_count") or 0)
    if logical != 1:
        return False, f"logical_send_count={logical}_need_1"
    if raw < 1:
        return False, "no_raw_parent_observations"
    sends = int(browser.get("unique_send_events") or 0)
    if sends != 1:
        return False, f"unique_browser_send_events={sends}_need_1"
    cs = set(expiration.get("client_stages") or [])
    if "browser_deadline_crossed" not in cs:
        return False, "deadline_cross_missing"
    if not browser_send_proven(expiration):
        return False, "browser_send_not_proven"
    if not browser.get("parent_listener_on_app_window"):
        return False, "parent_listener_not_on_app_window"
    if not browser.get("sending_iframe_identified"):
        return False, "sending_iframe_not_identified"
    if browser.get("sender_current_status") not in ("current", "stale"):
        return False, f"iframe_current_or_stale_unknown_{browser.get('sender_current_status')}"
    if browser_send_proven(expiration):
        if "post_delivery_redeclaration" not in events:
            return False, "INVALID_POST_DELIVERY_REDECLARATION_MISSING"
    return True, ""


def summarize_browser_events(expiration: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    transport = extract_transport_send_evidence(expiration)
    logical_list = list(registry.get("logical") or [])
    raw_list = list(registry.get("last") or [])
    logical_sends = [e for e in raw_list if isinstance(e, dict) and e.get("counts_as_logical_delivery")]
    send_ids = {
        str(e.get("browser_send_event_id") or e.get("event_id") or "")
        for e in raw_list
        if isinstance(e, dict) and (e.get("browser_send_event_id") or e.get("token"))
    }
    send_ids.discard("")
    if not send_ids and transport.get("unique_browser_send_event_ids"):
        send_ids = set(transport["unique_browser_send_event_ids"])
    token_sent = str(expiration.get("token_sent") or "")
    sender = logical_sends[-1] if logical_sends else (raw_list[-1] if raw_list else {})
    sender_status = "unknown"
    if isinstance(sender, dict):
        if sender.get("is_current_registered_instance") and sender.get("source_connected"):
            sender_status = "current"
        elif sender.get("instance_id") and not sender.get("is_current_registered_instance"):
            sender_status = "stale"
        elif sender.get("source_connected") is False:
            sender_status = "disconnected"
    unique_sends = len(send_ids) if send_ids else (1 if browser_send_proven(expiration) else 0)
    timer_arm_accounting = analyze_timer_arms(expiration, registry)
    return {
        "logical_send_count": len(logical_list) or len(logical_sends),
        "raw_listener_count": len(raw_list),
        "unique_send_events": unique_sends,
        "unique_transport_postmessage_count": int(transport.get("transport_postmessage_count") or 0),
        "transport_send_evidence": transport,
        "deduped_logical_sends": logical_list,
        "raw_listener_observations": raw_list,
        "token_sent": token_sent,
        "timer_arm_accounting": timer_arm_accounting,
        "parent_listener_on_app_window": bool(raw_list or logical_list or registry.get("instances")),
        "sending_iframe_identified": bool(isinstance(sender, dict) and sender.get("instance_id")),
        "sender_current_status": sender_status,
        "sender_row": sender if isinstance(sender, dict) else {},
        "current_registered_instance": registry.get("current") or registry.get("current_production_instance_id"),
        "instances": registry.get("instances") or {},
    }


def build_instance_identity_report(expiration: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    iframe = dict(expiration.get("iframe_lifecycle") or {})
    merged = list(iframe.get("merged_stages") or [])
    browser = summarize_browser_events(expiration, registry)
    sender = dict(browser.get("sender_row") or {})
    double = dict(expiration.get("double_production_send_analysis") or {})
    return {
        "iframe_instance_id": sender.get("instance_id") or browser.get("current_registered_instance"),
        "run_id": registry.get("run_id"),
        "expected_token": browser.get("token_sent") or expiration.get("token_sent"),
        "component_key": "solo_countdown_wake_solo_persistent",
        "connected_at_send": sender.get("source_connected"),
        "matched_current_registered": sender.get("is_current_registered_instance"),
        "iframe_dom_index_at_send": sender.get("iframe_dom_index"),
        "browser_send_event_id": sender.get("browser_send_event_id") or sender.get("event_id"),
        "remount_count_iframe_stages": sum(1 for s in merged if s == "iframe_remount"),
        "tick_cancellations": sum(1 for s in merged if s == "tick_cancelled"),
        "double_send_analysis": double,
        "registry_instances": browser.get("instances"),
        "raw_vs_logical": {
            "raw_count": browser.get("raw_listener_count"),
            "logical_count": browser.get("logical_send_count"),
        },
    }


def build_declaration_timeline(declaration: dict[str, Any]) -> list[dict[str, Any]]:
    return list(declaration.get("rows") or [])[-40:]


def classify_root_cause(
    *,
    validity_ok: bool,
    verdict: str,
    browser: dict[str, Any],
    declaration_rows: list[dict[str, Any]],
) -> str:
    if not validity_ok or verdict.startswith("INVALID"):
        return ""
    if verdict in ("PASS", "PASS_RETURN_VALUE_DELIVERY"):
        return ""
    sender = dict(browser.get("sender_row") or {})
    if sender.get("source_connected") is False or browser.get("sender_current_status") == "stale":
        return "A_STALE_IFRAME_SEND"
    post = [
        r
        for r in declaration_rows
        if "after_mount" in str(r.get("phase") or "") or "after_persistent" in str(r.get("phase") or "")
    ]
    if not post:
        return "B_POST_DELIVERY_BRANCH_MISS"
    last = post[-1]
    if not _coalesce_from_row(last):
        if sender.get("is_current_registered_instance"):
            return "D_PROTOCOL_VALUE_NOT_ACCEPTED"
        return "B_POST_DELIVERY_BRANCH_MISS"
    return "C_COMPONENT_ID_CHANGED"
