"""Single-cycle micro isolation — one token, fixed 10s deadline, no pick processing."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from minimal_component_wake_repro_core import coerce_token, RecordStageFn

MICRO_SECONDS = 10
SESSION_PREFIX = "_solo_micro_iso_"
COMPLETE_KEY = f"{SESSION_PREFIX}complete"
MOUNTED_KEY = f"{SESSION_PREFIX}mounted"
MOUNT_RUN_KEY = f"{SESSION_PREFIX}mount_run"
EXPIRE_RUN_KEY = f"{SESSION_PREFIX}expire_run"
RERUN_LOG_KEY = f"{SESSION_PREFIX}rerun_log"
WIDGET_ID_MOUNT_KEY = f"{SESSION_PREFIX}widget_id_mount"
WIDGET_ID_SEND_KEY = f"{SESSION_PREFIX}widget_id_send"


def micro_widget_key(placement: str) -> str:
    slug = placement.strip().lower().replace(" ", "")
    return f"solo_countdown_wake_micro_{slug}"


def micro_token(placement: str) -> str:
    return f"DIAG{placement.upper()}|0|{time.time():.3f}"


def note_micro_rerun(session: dict[str, Any], *, source: str, entered: bool) -> None:
    log = list(session.get(RERUN_LOG_KEY) or [])
    try:
        from app_page_generation import current_script_run_id

        run_id = str(current_script_run_id(session) or "")
    except ImportError:
        run_id = str(session.get("_live_draft_script_run_id") or "")
    log.append(
        {
            "ts": time.time(),
            "source": source,
            "script_run": run_id,
            "diag_branch_entered": entered,
        }
    )
    session[RERUN_LOG_KEY] = log[-80:]


@dataclass
class MicroCycleResult:
    widget_key: str
    token: str
    delivered: bool
    raw_received: bool
    on_change_fired: bool
    stages: list[str]
    should_stop: bool = False
    component_return: Any = None


def _session_keys(prefix: str) -> dict[str, str]:
    p = prefix or SESSION_PREFIX
    return {
        "complete": f"{p}complete",
        "mounted": f"{p}mounted",
        "mount_run": f"{p}mount_run",
        "expire_run": f"{p}expire_run",
        "rerun_log": f"{p}rerun_log",
        "widget_id_mount": f"{p}widget_id_mount",
        "widget_id_send": f"{p}widget_id_send",
        "token": f"{p}token",
        "on_change": f"{p}on_change",
        "raw_received": f"{p}raw_received",
        "delivered": f"{p}delivered",
    }


def render_micro_isolation_once(
    st: Any,
    session: dict[str, Any],
    *,
    placement: str,
    location: str,
    record_stage: RecordStageFn | None = None,
    draft_id: str | None = None,
    route: bool = True,
    persistent: bool = False,
    session_prefix: str | None = None,
    widget_key: str | None = None,
    production_room: dict[str, Any] | None = None,
    deliver_callback: Callable[[Any, dict[str, Any], Any, str], None] | None = None,
    production_expire_token: str | None = None,
    production_actionable: bool = True,
    production_delivery_only: bool = False,
    suppress_immediate_session_on_change: bool = False,
    chain_persist_key: str = "",
    production_use_return_value_delivery: bool = False,
) -> MicroCycleResult:
    """Mount exactly once; retain probe after expiration without starting cycle 1."""
    from solo_countdown_component import build_solo_expire_token, mount_solo_countdown_wake_direct

    sk = _session_keys(session_prefix or SESSION_PREFIX)
    if not session_prefix:
        note_micro_rerun(session, source=location, entered=True)
    else:
        log_key = sk["rerun_log"]
        log = list(session.get(log_key) or [])
        try:
            from app_page_generation import current_script_run_id

            run_id = str(current_script_run_id(session) or "")
        except ImportError:
            run_id = str(session.get("_live_draft_script_run_id") or "")
        log.append(
            {
                "ts": time.time(),
                "source": location,
                "script_run": run_id,
                "diag_branch_entered": True,
            }
        )
        session[log_key] = log[-80:]
    key = widget_key or micro_widget_key(placement)
    stages: list[str] = []

    def _rec(stage: str, fields: dict[str, Any] | None = None) -> None:
        stages.append(stage)
        if record_stage:
            record_stage(stage, fields or {})

    if production_room is not None:
        from solo_countdown_component import build_solo_expire_token, mount_solo_countdown_wake_with_token

        token = (
            production_expire_token
            if production_expire_token is not None
            else build_solo_expire_token(production_room)
        )
        try:
            from live_draft_solo_declaration_room_context import register_production_countdown_declaration_context

            register_production_countdown_declaration_context(
                st,
                session,
                room=production_room,
                expected_token=token,
                widget_key=key,
            )
        except ImportError:
            pass
        session[sk["token"]] = token
        mounted_token_key = f"{sk['mounted']}_token"
        mount_sig_key = f"{sk['mounted']}_sig"
        prior_sig = str(session.get(mount_sig_key) or "")
        sig = f"{token}|actionable={1 if production_actionable else 0}"
        first_mount = not session.get(sk["mounted"])

        def _prod_on_change() -> None:
            try:
                from live_draft_callback_boundary_diag import (
                    boundary_diag_enabled,
                    record_callback_boundary,
                    trace_helper,
                )

                if boundary_diag_enabled(session):
                    raw_pre = st.session_state.get(key)
                    record_callback_boundary(
                        session,
                        "expiration_on_change_entry",
                        st=st,
                        token=str(raw_pre or "")[:400],
                        phase="callback_entry",
                        function="_prod_on_change",
                        extra={"widget_key": key},
                    )
            except ImportError:
                pass
            try:
                from app_page_generation import current_script_run_id

                session[sk["expire_run"]] = str(current_script_run_id(session) or "")
            except ImportError:
                session[sk["expire_run"]] = str(session.get("_live_draft_script_run_id") or "")
            raw = st.session_state.get(key)
            _rec(
                "on_change_callback_entry",
                {"widget_key": key, "raw_session_state": repr(raw)[:800]},
            )
            _rec(
                "session_state_raw_received",
                {"key": key, "raw_type": type(raw).__name__ if raw is not None else "NoneType"},
            )
            if deliver_callback is not None:
                try:
                    from live_draft_callback_boundary_diag import (
                        boundary_diag_enabled,
                        record_callback_boundary,
                        trace_helper,
                    )

                    if boundary_diag_enabled(session):

                        def _run_deliver() -> None:
                            if "_solo_pending_callback_source" not in session:
                                session["_solo_pending_callback_source"] = "native_component_on_change"
                            deliver_callback(st, session, raw, key)

                        trace_helper(
                            session,
                            "deliver_callback",
                            _run_deliver,
                            st=st,
                            callback_token=str(raw or "")[:400],
                        )
                    else:
                        if "_solo_pending_callback_source" not in session:
                            session["_solo_pending_callback_source"] = "native_component_on_change"
                        deliver_callback(st, session, raw, key)
                except ImportError:
                    if "_solo_pending_callback_source" not in session:
                        session["_solo_pending_callback_source"] = "native_component_on_change"
                    deliver_callback(st, session, raw, key)
            try:
                from live_draft_callback_boundary_diag import (
                    boundary_diag_enabled,
                    record_callback_boundary,
                )

                if boundary_diag_enabled(session):
                    record_callback_boundary(
                        session,
                        "expiration_on_change_return",
                        st=st,
                        token=str(raw or "")[:400],
                        phase="callback_return",
                        function="_prod_on_change",
                    )
            except ImportError:
                pass

        if production_delivery_only and session.get(sk["mounted"]) and not production_use_return_value_delivery:
            raw = st.session_state.get(key)
            if raw is not None:
                session["_solo_pending_callback_source"] = "post_mount_session_state_poll"
                _prod_on_change()
                return MicroCycleResult(
                    widget_key=key,
                    token=token,
                    delivered=False,
                    raw_received=True,
                    on_change_fired=True,
                    stages=stages,
                    should_stop=False,
                )

        use_return_delivery = bool(production_use_return_value_delivery)
        mount_on_change = None if use_return_delivery else _prod_on_change

        if first_mount:
            _rec(
                "component_declaration_loaded",
                {
                    "component_name": "solo_countdown_wake",
                    "widget_key": key,
                    "expire_token": token,
                    "mount_location": location,
                    "placement": placement,
                    "actionable": production_actionable,
                },
            )
        elif prior_sig != sig:
            _rec(
                "component_props_updated",
                {
                    "widget_key": key,
                    "expire_token": token,
                    "actionable": production_actionable,
                    "prior_sig": prior_sig[:120],
                },
            )
        session_state_before = repr(st.session_state.get(key))[:400] if key in st.session_state else "missing"
        on_change_label = "None" if use_return_delivery else "_prod_on_change"
        component_kwargs = {
            "room": "(production_room dict)",
            "key": key,
            "expire_token": token,
            "actionable": production_actionable,
            "on_change": on_change_label,
            "chain_persist_key": chain_persist_key,
        }
        try:
            from live_draft_solo_p6_declaration_audit import (
                p6_declaration_audit_active,
                record_declaration_attempt,
                record_declaration_returned,
            )

            if p6_declaration_audit_active(st, session):
                record_declaration_attempt(
                    session,
                    st=st,
                    widget_key=key,
                    default=None,
                    expected_token=token,
                    on_change_fn=mount_on_change,
                    deliver_callback=deliver_callback,
                    suppress_flag=bool(suppress_immediate_session_on_change),
                    force_flag=None,
                    component_kwargs=component_kwargs,
                    session_state_before=session_state_before,
                )
        except ImportError:
            pass
        try:
            from live_draft_stage1_parent_boundary import stage1_parent_boundary_probe_enabled

            boundary_probe = stage1_parent_boundary_probe_enabled(st, session)
        except ImportError:
            boundary_probe = False
        decl_eligibility = {
            "first_mount": first_mount,
            "production_actionable": production_actionable,
            "production_delivery_only": production_delivery_only,
            "use_return_delivery": use_return_delivery,
        }
        try:
            from live_draft_stage1_boundary_canaries import (
                emit_production_countdown_declaration_post,
                emit_production_countdown_declaration_pre,
            )

            emit_production_countdown_declaration_pre(
                st,
                session,
                room=production_room,
                widget_key=key,
                expected_token=token,
                declaration_eligibility=decl_eligibility,
            )
        except ImportError:
            pass
        raw_component_value = mount_solo_countdown_wake_with_token(
            production_room,
            key=key,
            expire_token=token,
            actionable=production_actionable,
            on_change=mount_on_change,
            chain_persist_key=chain_persist_key,
            stage1_parent_boundary_probe=boundary_probe,
        )
        try:
            from live_draft_stage1_boundary_canaries import emit_production_countdown_declaration_post

            emit_production_countdown_declaration_post(
                st,
                session,
                room=production_room,
                widget_key=key,
                expected_token=token,
                direct_return=raw_component_value,
                declaration_eligibility=decl_eligibility,
            )
        except ImportError:
            pass
        if use_return_delivery and raw_component_value is None and key in st.session_state:
            raw_component_value = st.session_state.get(key)
        comp_return = raw_component_value
        session_state_after = repr(st.session_state.get(key))[:400] if key in st.session_state else "missing"
        try:
            from live_draft_solo_p6_declaration_audit import (
                p6_declaration_audit_active,
                record_declaration_returned,
            )

            if p6_declaration_audit_active(st, session):
                record_declaration_returned(
                    session,
                    st=st,
                    widget_key=key,
                    expected_token=token,
                    component_return=comp_return,
                    session_state_after=session_state_after,
                )
        except ImportError:
            pass
        session[sk["mounted"]] = True
        session[mounted_token_key] = token
        session[mount_sig_key] = sig
        raw = raw_component_value
        if use_return_delivery and deliver_callback is not None:
            try:
                from live_draft_solo_component_diagnostics import (
                    record_solo_component_mount_attempt,
                    solo_component_diag_enabled,
                )

                if solo_component_diag_enabled(st, session):
                    from live_draft_solo_heartbeat import _coerce_wake_token

                    record_solo_component_mount_attempt(
                        session,
                        production_room,
                        key=key,
                        mounted=True,
                        reason="persistent_wake_return_value",
                        expire_token=token,
                        widget_return_type=type(raw_component_value).__name__
                        if raw_component_value is not None
                        else "NoneType",
                        returned_token=_coerce_wake_token(raw_component_value),
                    )
            except ImportError:
                pass
            try:
                from live_draft_solo_heartbeat import _coerce_wake_token
                from live_draft_stage1_production_ledger import (
                    note_stage1_declaration_returned,
                    note_stage1_event,
                    stage1_production_ledger_enabled,
                )

                if stage1_production_ledger_enabled(st, session):
                    session["_solo_stage1_last_delivery_only"] = bool(production_delivery_only)
                    coerced = _coerce_wake_token(raw_component_value) or _coerce_wake_token(
                        st.session_state.get(key)
                    )
                    note_stage1_event(
                        session,
                        "production_stage1_declaration_attempt",
                        st=st,
                        room=production_room,
                        widget_key=key,
                        extra={"expected_token": token, "delivery_only": production_delivery_only},
                    )
                    note_stage1_declaration_returned(
                        session,
                        st=st,
                        room=production_room,
                        widget_key=key,
                        expected_token=token,
                        direct_return=raw_component_value,
                        coalesced=str(coerced or ""),
                        raw_received=raw_component_value is not None,
                        delivered=False,
                    )
            except ImportError:
                pass
            try:
                from live_draft_solo_declaration_room_context import (
                    get_registered_declaration_room,
                    register_production_countdown_declaration_context,
                )
                from live_draft_stage1_post_bind_flush import (
                    complete_delivery_only_observation_and_actionable_flush,
                    evaluate_bound_token_gate,
                )

                register_production_countdown_declaration_context(
                    st,
                    session,
                    room=production_room,
                    expected_token=token,
                    widget_key=key,
                )
                pending_t = str(session.get("_solo_parity_expected_token") or session.get("_solo_persistent_wake_last_token") or "")
                if production_delivery_only:
                    complete_delivery_only_observation_and_actionable_flush(
                        st,
                        session,
                        expected_expiration_token=str(token or ""),
                        mount_expire_token=str(token or ""),
                        pending_token=pending_t,
                        widget_key=key,
                        production_room=production_room if isinstance(production_room, dict) else None,
                        raw_component_value=raw_component_value,
                    )
                else:
                    gate = evaluate_bound_token_gate(
                        st,
                        session,
                        expected_expiration_token=str(token or ""),
                        mount_expire_token=str(token or ""),
                        pending_token=pending_t,
                        raw_component_return=raw_component_value,
                        session_state_value=st.session_state.get(key) if key in st.session_state else None,
                        widget_key=key,
                        call_site="render_micro_isolation_once_return_delivery",
                    )
                    if gate.passed and gate.selected_bound_token:
                        from live_draft_solo_persistent_wake import process_production_expire_token

                        process_production_expire_token(
                            st,
                            session,
                            raw_token=raw_component_value
                            if raw_component_value is not None
                            else gate.selected_bound_token,
                            widget_key=key,
                            source="return_value_session_bind",
                            declaration_room=get_registered_declaration_room(session),
                        )
            except ImportError:
                try:
                    from live_draft_solo_persistent_wake import process_production_expire_token

                    process_production_expire_token(
                        st,
                        session,
                        raw_token=raw_component_value,
                        widget_key=key,
                        source="native_component_return",
                        declaration_room=production_room,
                    )
                except ImportError:
                    pass
        elif not suppress_immediate_session_on_change and raw is not None:
            _prod_on_change()

        return MicroCycleResult(
            widget_key=key,
            token=token,
            delivered=False,
            raw_received=raw is not None,
            on_change_fired=False,
            stages=stages,
            should_stop=False,
            component_return=raw_component_value,
        )

    if session.get(sk["complete"]):
        _rec("micro_complete_frozen", {"widget_key": key})
        return MicroCycleResult(
            widget_key=key,
            token=str(session.get(sk["token"]) or ""),
            delivered=bool(session.get(sk["delivered"])),
            raw_received=bool(session.get(sk["raw_received"])),
            on_change_fired=bool(session.get(sk["on_change"])),
            stages=stages,
            should_stop=False,
        )

    try:
        from app_page_generation import current_script_run_id

        mount_run = str(current_script_run_id(session) or "")
    except ImportError:
        mount_run = str(session.get("_live_draft_script_run_id") or "")
    session[sk["mount_run"]] = session.get(sk["mount_run"]) or mount_run

    token = str(session.get(sk["token"]) or "") or micro_token(placement)
    session[sk["token"]] = token
    deadline = time.time() + float(MICRO_SECONDS)
    did = (draft_id or "").strip() or f"DIAG{placement.upper()}"
    room = {
        "draft_room_id": did,
        "draft_id": did,
        "current_pick_index": 0,
        "status": "in_progress",
        "timer_deadline": deadline,
        "config": {"timer_seconds": MICRO_SECONDS},
        "_solo_diag_timer_seconds": MICRO_SECONDS,
    }

    def _on_change() -> None:
        try:
            from app_page_generation import current_script_run_id

            session[sk["expire_run"]] = str(current_script_run_id(session) or "")
        except ImportError:
            session[sk["expire_run"]] = str(session.get("_live_draft_script_run_id") or "")
        raw = st.session_state.get(key)
        _rec(
            "on_change_callback_entry",
            {"widget_key": key, "raw_session_state": repr(raw)[:800]},
        )
        session[sk["on_change"]] = True
        _rec(
            "session_state_raw_received",
            {
                "key": key,
                "raw_type": type(raw).__name__ if raw is not None else "NoneType",
            },
        )
        session[sk["raw_received"]] = raw is not None
        tok = coerce_token(raw, token)
        if tok:
            session[sk["delivered"]] = True
            session[sk["complete"]] = True
            _rec("on_change_delivery_complete", {"token": tok})

    if not session.get(sk["mounted"]):
        _rec(
            "component_declaration_loaded",
            {
                "component_name": "solo_countdown_wake",
                "widget_key": key,
                "expire_token": token,
                "mount_location": location,
                "placement": placement,
            },
        )
        mount_solo_countdown_wake_direct(room, key=key, on_change=_on_change)
        session[sk["mounted"]] = True
    else:
        raw = st.session_state.get(key)
        if raw is not None and not session.get(sk["complete"]):
            _on_change()

    if session.get(sk["complete"]):
        return MicroCycleResult(
            widget_key=key,
            token=token,
            delivered=True,
            raw_received=bool(session.get(sk["raw_received"])),
            on_change_fired=bool(session.get(sk["on_change"])),
            stages=stages,
            should_stop=False,
        )

    return MicroCycleResult(
        widget_key=key,
        token=token,
        delivered=False,
        raw_received=False,
        on_change_fired=False,
        stages=stages,
        should_stop=False if persistent else True,
    )
