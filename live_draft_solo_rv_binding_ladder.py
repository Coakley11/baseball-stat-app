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
    live = session.get("live_draft_room")
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


def mount_rv_r4_style(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    expire_token: str,
    location: str,
) -> Any:
    from live_draft_solo_rv_declaration_audit import mount_with_rv_declaration_audit
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

    raw = mount_with_rv_declaration_audit(
        st,
        session,
        room,
        widget_key=widget_key,
        mount_fn=_mount,
        phase_prefix=location,
    )
    _append_ledger(
        session,
        "r4_style_mount",
        location=location,
        expected_token=expire_token[:400],
        component_return=repr(raw)[:400],
    )
    return raw


def execute_rv_step_mount(st: Any, session: dict[str, Any], step: str) -> dict[str, Any]:
    """Mount production countdown once for RV0–RV2 pre-shell paths."""
    session[SOLO_PERSISTENT_WAKE_LATCH_KEY] = True
    if step == "RV0":
        token, room = _synthetic_room_for_rv0(session)
    else:
        token, room = _real_room_token(session)
        if not token or not room:
            _append_ledger(session, "rv_real_room_missing", step=step)
            return {"ok": False, "reason": "real_room_missing"}
    session["live_draft_room"] = room
    from live_draft_solo_rv_instance_registry import render_rv_instance_registry_listener

    render_rv_instance_registry_listener(st, session)
    raw = mount_rv_r4_style(st, session, room, expire_token=token, location=f"rv_{step.lower()}_shell")
    from live_draft_solo_rv_declaration_audit import render_rv_declaration_audit_probe
    from live_draft_solo_rv_instance_registry import render_rv_instance_registry_probe

    render_rv_declaration_audit_probe(st, session)
    render_rv_instance_registry_probe(st, session)
    return {"ok": True, "token": token, "room_id": str(room.get("draft_room_id") or ""), "raw": raw}


def rv_pre_app_shell_should_stop(session: dict[str, Any]) -> bool:
    step = str(session.get("_solo_rv_ladder_step") or "")
    return step in ("RV0", "RV1")


def rv2_mount_if_needed(st: Any, session: dict[str, Any]) -> bool:
    if str(session.get("_solo_rv_ladder_step") or "") != "RV2":
        return False
    if session.get("_solo_rv_rv2_initial_mount_done"):
        return False
    execute_rv_step_mount(st, session, "RV2")
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
    inv, inv_reason = validate_rv_control_prerequisites(
        declaration_rows=declaration_rows,
        browser=browser,
        expiration=expiration or {},
    )
    if not inv:
        return "INVALID", inv_reason
    post_decl = [
        r
        for r in declaration_rows
        if str(r.get("phase") or "").endswith("after_mount")
        or "after_persistent" in str(r.get("phase") or "")
    ]
    post_after_send = [r for r in post_decl if r.get("browser_delivery_seen") or not r.get("before_browser_send", True)]
    if not post_after_send:
        return "INVALID", "INVALID_POST_DELIVERY_REDECLARATION_MISSING"
    last = post_after_send[-1]
    expected = str(last.get("expected_token") or "")
    coalesced = _coalesce_from_row(last)
    if step == "RV0":
        if expected and coalesced == expected:
            return "PASS_RETURN_VALUE_DELIVERY", "RV0_r4_control"
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


def validate_rv_control_prerequisites(
    *,
    declaration_rows: list[dict[str, Any]],
    browser: dict[str, Any],
    expiration: dict[str, Any],
) -> tuple[bool, str]:
    pre_mount = [r for r in declaration_rows if "before_mount" in str(r.get("phase") or "") or "before_persistent" in str(r.get("phase") or "")]
    if not pre_mount and not declaration_rows:
        return False, "component_declared_before_expiration_not_proven"
    logical = int(browser.get("logical_send_count") or 0)
    raw = int(browser.get("raw_listener_count") or 0)
    if logical != 1:
        return False, f"logical_send_count={logical}_need_1"
    if raw < 1:
        return False, "no_raw_parent_events"
    sends = int(browser.get("unique_send_events") or 0)
    if sends != 1:
        return False, f"unique_send_events={sends}_need_1"
    cs = set(expiration.get("client_stages") or [])
    if "timer_armed" not in cs:
        return False, "timer_armed_missing"
    if "browser_deadline_crossed" not in cs:
        return False, "deadline_cross_missing"
    if "component_value_sent" not in cs:
        return False, "component_value_sent_missing"
    if not browser.get("sending_iframe_identified"):
        return False, "sending_iframe_not_identified"
    if browser.get("sender_current_status") not in ("current", "stale", "unknown"):
        return False, "sender_current_status_unknown"
    return True, ""


def summarize_browser_events(expiration: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    cs = set(expiration.get("client_stages") or [])
    logical_list = list(registry.get("logical") or [])
    raw_list = list(registry.get("last") or [])
    logical_sends = [e for e in raw_list if isinstance(e, dict) and e.get("counts_as_logical_delivery")]
    send_ids = {
        str(e.get("browser_send_event_id") or e.get("event_id") or "")
        for e in raw_list
        if isinstance(e, dict) and (e.get("browser_send_event_id") or e.get("token"))
    }
    send_ids.discard("")
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
    return {
        "logical_send_count": len(logical_list) or len(logical_sends),
        "raw_listener_count": len(raw_list),
        "unique_send_events": len(send_ids) if send_ids else (1 if "component_value_sent" in cs else 0),
        "deduped_logical_sends": logical_list,
        "raw_listener_observations": raw_list,
        "token_sent": token_sent,
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
