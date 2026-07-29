"""Production Solo expiration wake — early LDR entry, persistent widget key."""

from __future__ import annotations

from typing import Any

SOLO_PERSISTENT_WAKE_LATCH_KEY = "_solo_persistent_wake_early_latch"
SOLO_PERSISTENT_WAKE_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
SOLO_PERSISTENT_WAKE_TOKEN_KEY = "_solo_persistent_wake_last_token"
SOLO_PERSISTENT_WAKE_SESSION_PREFIX = "_solo_persistent_wake_"
SOLO_INERT_EXPIRE_TOKEN = ""
SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY = "_solo_persistent_wake_actionable"
SOLO_PERSISTENT_WAKE_DECLARED_ON_SETUP_KEY = "_solo_persistent_wake_declared_on_setup"
SOLO_PERSISTENT_WAKE_PICK_LATCH_KEY = "_solo_persistent_wake_pick_latch"


def solo_persistent_wake_widget_key(_session: dict[str, Any] | None = None) -> str:
    """One stable Streamlit widget key for the entire Solo draft session."""
    return SOLO_PERSISTENT_WAKE_WIDGET_KEY


def solo_persistent_chain_persist_key(session: dict[str, Any], room: dict[str, Any] | None) -> str:
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    rid = str((live or {}).get("draft_room_id") or (live or {}).get("draft_id") or "setup").strip()
    return f"solo_prod_expire_chain_{rid}"


SOLO_SKIP_LATE_FLUSH_TOKEN_KEY = "_solo_skip_late_flush_token"
SOLO_PENDING_CALLBACK_SOURCE_KEY = "_solo_pending_callback_source"
SOLO_PERSISTENT_RETURN_VALUE_DELIVERY_KEY = "_solo_persistent_return_value_delivery"


def resolve_production_component_delivery_mode(
    st: Any,
    session: dict[str, Any],
    deliver_callback: Any,
) -> str:
    """Production persistent wake: return_value (default) vs on_change (P6 R0–R2 controls only)."""
    if deliver_callback is None:
        return "on_change"
    if getattr(deliver_callback, "__name__", "") != "_production_deliver_callback":
        return "on_change"
    try:
        from live_draft_solo_parity_p6_persistent_diag import p6_persistent_diag_active
        from live_draft_solo_p6_declaration_audit import resolve_p6_callback_control

        if p6_persistent_diag_active(st, session):
            ctrl = resolve_p6_callback_control(st, session)
            if ctrl in ("R0", "R1", "R2"):
                return "on_change"
    except ImportError:
        pass
    return "return_value"


def production_return_value_delivery_active(session: dict[str, Any]) -> bool:
    return bool(session.get(SOLO_PERSISTENT_RETURN_VALUE_DELIVERY_KEY))


def _production_expire_token_matches_state(
    session: dict[str, Any],
    token: str,
    live: dict[str, Any] | None,
) -> tuple[bool, str]:
    tok = str(token or "").strip()
    if not tok:
        return False, "empty_raw"
    if tok == SOLO_INERT_EXPIRE_TOKEN:
        return False, "empty_raw"
    if not isinstance(live, dict):
        return False, "wrong_room"
    try:
        from solo_countdown_component import parse_solo_expire_token

        parsed = parse_solo_expire_token(tok)
        if not parsed:
            return False, "malformed_token"
        live_draft_id = str(live.get("draft_room_id") or live.get("draft_id") or "").strip()
        if parsed["draft_id"] and live_draft_id and parsed["draft_id"] != live_draft_id:
            return False, "wrong_room"
        if int(live.get("current_pick_index") or 0) != int(parsed["pick_index"]):
            return False, "wrong_pick"
        from live_draft_timer_logic import live_draft_timer_deadline

        live_deadline = live_draft_timer_deadline(live)
        if live_deadline is None and live.get("timer_deadline") is not None:
            live_deadline = float(live.get("timer_deadline") or 0.0)
        tok_deadline = float(parsed.get("deadline") or 0.0)
        if live_deadline is not None and tok_deadline > 0:
            if abs(float(live_deadline) - tok_deadline) > 0.75:
                return False, "stale_deadline"
        armed = str(session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or "").strip()
        if armed and tok != armed:
            try:
                from solo_countdown_component import build_solo_expire_token

                canonical = build_solo_expire_token(live)
            except ImportError:
                canonical = ""
            if canonical and tok != canonical:
                return False, "expected_token_mismatch"
    except ImportError:
        armed = str(session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or "").strip()
        if not armed or tok != armed:
            return False, "expected_token_mismatch"
    return True, ""


def process_production_expire_token(
    st: Any,
    session: dict[str, Any],
    *,
    raw_token: Any,
    widget_key: str,
    source: str = "native_component_return",
    declaration_room: dict[str, Any] | None = None,
) -> bool:
    """Validate component return value against live production state; route to delivery owner."""
    live = _resolve_room(session, None)
    live_dict = live if isinstance(live, dict) else None
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

        if stage1_production_ledger_enabled(st, session):
            note_stage1_event(
                session,
                "production_stage1_process_production_expire_token_entry",
                st=st,
                room=live_dict,
                widget_key=widget_key,
                extra={"source": source, "raw_preview": repr(raw_token)[:200]},
            )
    except ImportError:
        pass
    from live_draft_solo_heartbeat import _coerce_wake_token

    token = _coerce_wake_token(raw_token)
    try:
        from live_draft_solo_declaration_room_context import (
            _deadline_for_room,
            _room_fingerprint,
            get_registered_declaration_room,
            resolve_effective_production_room,
            restore_production_room_from_declaration,
        )

        reg_room = declaration_room if isinstance(declaration_room, dict) else get_registered_declaration_room(session)
        resolved_live, resolution_source, resolution_meta = resolve_effective_production_room(
            st,
            session,
            declaration_room=reg_room,
            token=token,
        )
        if isinstance(resolved_live, dict):
            resolution_meta.setdefault("deadline", _deadline_for_room(resolved_live))
            resolution_meta.setdefault("room_fingerprint", _room_fingerprint(resolved_live))
        try:
            from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

            if stage1_production_ledger_enabled(st, session):
                note_stage1_event(
                    session,
                    "production_stage1_room_resolution",
                    st=st,
                    room=resolved_live if isinstance(resolved_live, dict) else live_dict,
                    widget_key=widget_key,
                    extra={
                        "resolution_source": resolution_source,
                        "live_room_id": resolution_meta.get("live_room_id") or "",
                        "canonical_room_id": resolution_meta.get("canonical_room_id") or "",
                        "declaration_room_id": resolution_meta.get("declaration_room_id") or "",
                        "resolved_room_id": resolution_meta.get("resolved_room_id") or "",
                        "room_status": str((resolved_live or {}).get("status") or ""),
                        "pick_index": (resolved_live or {}).get("current_pick_index"),
                        "deadline": resolution_meta.get("deadline"),
                        "room_fingerprint": resolution_meta.get("room_fingerprint") or "",
                        "expected_token": str(session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or "")[:400],
                        "supplied_token": str(token or "")[:400],
                        "declaration_validation_ok": resolution_meta.get("declaration_validation_ok"),
                        "declaration_validation_reason": resolution_meta.get("declaration_validation_reason") or "",
                    },
                )
        except ImportError:
            pass
        session_had_live = bool(live_dict)
        if (
            resolution_source == "validated_declaration_room"
            and isinstance(resolved_live, dict)
            and not session_had_live
        ):
            restored_ok, restore_detail = restore_production_room_from_declaration(
                st, session, resolved_live, token=token
            )
            try:
                from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

                if stage1_production_ledger_enabled(st, session):
                    note_stage1_event(
                        session,
                        "production_stage1_room_restored_from_declaration_context",
                        st=st,
                        room=session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None,
                        widget_key=widget_key,
                        extra=restore_detail,
                    )
            except ImportError:
                pass
            if not restored_ok:
                return False
            live_dict = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else resolved_live
        elif isinstance(resolved_live, dict):
            live_dict = resolved_live
        elif resolution_source == "declaration_room_rejected":
            return False
    except ImportError:
        pass
    gate_ctx: dict[str, Any] = {}
    try:
        from live_draft_stage1_process_token_gate import (
            build_process_token_gate_context,
            note_process_token_gate,
        )

        gate_ctx = build_process_token_gate_context(
            st,
            session,
            raw_token=raw_token,
            normalized_token=str(token or ""),
            widget_key=widget_key,
            source=source,
            live=live_dict,
        )
        note_process_token_gate(
            session,
            st=st,
            gate_name="process_token_after_entry",
            gate_result="entered",
            decision="continue",
            widget_key=widget_key,
            live=live_dict,
            context=gate_ctx,
        )
    except ImportError:
        pass
    if not token:
        try:
            from live_draft_stage1_process_token_gate import note_process_token_gate

            note_process_token_gate(
                session,
                st=st,
                gate_name="coerce_wake_token",
                gate_result="empty",
                decision="return",
                return_reason="empty_raw",
                widget_key=widget_key,
                live=live_dict,
                context=gate_ctx,
            )
        except ImportError:
            pass
        return False
    ok, reject_code = _production_expire_token_matches_state(session, token, live_dict)
    if not ok:
        try:
            from live_draft_stage1_process_token_gate import note_process_token_gate

            note_process_token_gate(
                session,
                st=st,
                gate_name="expire_token_matches_state",
                gate_result=str(reject_code or "rejected"),
                decision="return",
                return_reason=str(reject_code or "rejected"),
                widget_key=widget_key,
                live=live_dict,
                context=gate_ctx,
            )
        except ImportError:
            pass
        try:
            from live_draft_solo_expire_chain import note_solo_expire_chain

            note_solo_expire_chain(
                session,
                "return_value_rejected",
                source="persistent_wake",
                reason=reject_code,
                token=str(token or "")[:400],
            )
        except ImportError:
            pass
        if reject_code not in ("empty_raw", "expected_token_mismatch"):
            try:
                from live_draft_stage1_expire_audit import (
                    mark_wake_token_rejected,
                    record_callback_invocation,
                )

                record_callback_invocation(
                    st,
                    session,
                    callback_source=source,
                    raw_value=raw_token,
                    room=live_dict,
                    reject_code=reject_code,
                    delivery_claimed=False,
                )
                mark_wake_token_rejected(session, token, reject_code)
            except ImportError:
                pass
        return False
    try:
        from live_draft_stage1_process_token_gate import note_process_token_gate

        note_process_token_gate(
            session,
            st=st,
            gate_name="expire_token_matches_state",
            gate_result="ok",
            decision="continue",
            widget_key=widget_key,
            live=live_dict,
            context=gate_ctx,
        )
        note_process_token_gate(
            session,
            st=st,
            gate_name="invoke_production_deliver_callback",
            gate_result="pending",
            decision="continue",
            widget_key=widget_key,
            live=live_dict,
            context=gate_ctx,
        )
    except ImportError:
        pass
    session[SOLO_PENDING_CALLBACK_SOURCE_KEY] = source
    _production_deliver_callback(st, session, raw_token, widget_key)
    return True


def solo_persistent_wake_active(session: dict[str, Any]) -> bool:
    """True when early-route production wake owns expiration (Cloud wake owner)."""
    if not session.get(SOLO_PERSISTENT_WAKE_LATCH_KEY):
        return False
    try:
        from live_draft_solo_expire_chain import solo_expire_owner

        return solo_expire_owner(session) == "wake"
    except ImportError:
        return bool(session.get(SOLO_PERSISTENT_WAKE_LATCH_KEY))


def _diag_blocks_persistent_wake(st: Any, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_wiring_matrix_diag import wiring_matrix_active

        if wiring_matrix_active(st, session):
            return True
    except ImportError:
        pass
    try:
        from live_draft_solo_bridge_transition_diag import bridge_transition_active

        if bridge_transition_active(st, session):
            return True
    except ImportError:
        pass
    try:
        from live_draft_solo_early_bridge_diag import early_bridge_active

        if early_bridge_active(st, session):
            return True
    except ImportError:
        pass
    try:
        from live_draft_solo_placement_micro import micro_isolation_active

        if micro_isolation_active(st, session):
            return True
    except ImportError:
        pass
    try:
        from live_draft_solo_placement_ladder import placement_ladder_active

        if placement_ladder_active(st, session):
            return True
    except ImportError:
        pass
    try:
        from live_draft_solo_persistent_parity_ladder import parity_control

        if parity_control(st, session) in ("P0", "P1", "P2", "P3", "P4", "P5"):
            return True
    except ImportError:
        pass
    try:
        from live_draft_solo_delivery_diag import delivery_diag_active, delivery_matrix_cell

        if delivery_diag_active(st, session) and delivery_matrix_cell(st) > 0:
            return True
    except ImportError:
        pass
    return False


def _resolve_room(session: dict[str, Any], room: Any) -> dict[str, Any] | None:
    live = session.get("live_draft_room")
    if isinstance(live, dict) and live:
        return live
    if isinstance(room, dict) and room:
        return room
    return None


def build_solo_idle_expire_token(*, draft_id: str = "idle") -> str:
    """Legacy idle token — do not use for production inert mount (use SOLO_INERT_EXPIRE_TOKEN)."""
    return SOLO_INERT_EXPIRE_TOKEN


def resolve_persistent_wake_mount(
    session: dict[str, Any], room: dict[str, Any] | None
) -> tuple[bool, str, dict[str, Any], str]:
    """Return (actionable, expire_token, props_room, lifecycle_phase)."""
    from solo_countdown_component import build_solo_expire_token

    setup_props: dict[str, Any] = {
        "draft_room_id": "",
        "draft_id": "",
        "current_pick_index": 0,
        "status": "setup",
        "config": {"draft_setup_mode": "solo"},
    }
    if not room:
        return False, SOLO_INERT_EXPIRE_TOKEN, setup_props, "setup"

    try:
        from live_draft_solo_timer import is_solo_live_draft

        if not is_solo_live_draft(session, room):
            return False, SOLO_INERT_EXPIRE_TOKEN, {**setup_props, **room, "status": "setup"}, "setup"
    except ImportError:
        pass

    if str(room.get("status") or "") != "in_progress":
        phase = "paused" if str(room.get("status") or "") == "paused" else "setup"
        return False, SOLO_INERT_EXPIRE_TOKEN, {**room, "status": str(room.get("status") or "setup")}, phase

    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        deadline = live_draft_timer_deadline(room)
    except ImportError:
        deadline = None
    if deadline is None:
        raw = room.get("timer_deadline")
        deadline = float(raw) if raw is not None else None
    if deadline is None:
        try:
            from live_draft_solo_timer import is_solo_live_draft

            if is_solo_live_draft(session, room):
                token = build_solo_expire_token(room)
                return True, token, room, "active"
        except ImportError:
            pass
        return False, SOLO_INERT_EXPIRE_TOKEN, room, "setup"

    token = build_solo_expire_token(room)
    return True, token, room, "active"


def _apply_actionable_hold(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    actionable: bool,
    expire_token: str,
    props_room: dict[str, Any],
    phase: str,
) -> tuple[bool, str, dict[str, Any], str]:
    """Keep the same active mount through transient reruns while a pick timer is expiring."""
    if actionable:
        session[SOLO_PERSISTENT_WAKE_PICK_LATCH_KEY] = int(props_room.get("current_pick_index") or 0)
        return actionable, expire_token, props_room, phase
    if not session.get(SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY):
        return actionable, expire_token, props_room, phase
    if not isinstance(room, dict) or str(room.get("status") or "") != "in_progress":
        return actionable, expire_token, props_room, phase
    latched = session.get(SOLO_PERSISTENT_WAKE_PICK_LATCH_KEY)
    pick = int(room.get("current_pick_index") or 0)
    if latched is None or int(latched) != pick:
        return actionable, expire_token, props_room, phase
    held_token = str(session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or "").strip()
    if not held_token or held_token == SOLO_INERT_EXPIRE_TOKEN:
        return actionable, expire_token, props_room, phase
    return True, held_token, room, "active"


def expire_token_for_persistent_wake(
    session: dict[str, Any], room: dict[str, Any] | None
) -> tuple[str, dict[str, Any]]:
    """Test/helper wrapper — returns (expire_token, props_room) only."""
    _actionable, token, props, _phase = resolve_persistent_wake_mount(session, room)
    return token, props


def _should_mount_persistent_wake(st: Any, session: dict[str, Any]) -> bool:
    diag_block = _diag_blocks_persistent_wake(st, session)
    if diag_block:
        try:
            from live_draft_solo_rv3_phase import trace_rv3_decl

            trace_rv3_decl(
                st,
                session,
                "should_mount_persistent_wake",
                allowed=False,
                reason="diag_blocks_persistent_wake",
            )
        except ImportError:
            pass
        return False
    try:
        from live_draft_solo_expire_chain import solo_expire_owner

        owner = solo_expire_owner(session)
        if owner != "wake":
            try:
                from live_draft_solo_rv3_phase import trace_rv3_decl

                trace_rv3_decl(
                    st,
                    session,
                    "should_mount_persistent_wake",
                    allowed=False,
                    reason="solo_expire_owner_not_wake",
                    solo_expire_owner=owner,
                )
            except ImportError:
                pass
            return False
    except ImportError:
        return False
    try:
        from live_draft_solo_rv3_phase import trace_rv3_decl

        trace_rv3_decl(st, session, "should_mount_persistent_wake", allowed=True)
    except ImportError:
        pass
    return True


def _actionable_solo_timer(session: dict[str, Any], room: dict[str, Any] | None) -> bool:
    actionable, _, _, _ = resolve_persistent_wake_mount(session, room)
    return actionable


def render_persistent_wake_lifecycle_probe(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    actionable: bool,
    phase: str,
    expire_token: str,
) -> None:
    if not session.get(SOLO_PERSISTENT_WAKE_DECLARED_ON_SETUP_KEY) and not actionable:
        session[SOLO_PERSISTENT_WAKE_DECLARED_ON_SETUP_KEY] = True
    st.markdown(
        f'<div id="solo-persistent-wake-lifecycle-diag" '
        f'data-key="{widget_key}" '
        f'data-actionable="{1 if actionable else 0}" '
        f'data-phase="{phase}" '
        f'data-declared-on-setup="{1 if session.get(SOLO_PERSISTENT_WAKE_DECLARED_ON_SETUP_KEY) else 0}" '
        f'data-token="{str(expire_token or "").replace(chr(34), chr(39))}" '
        f'data-same-key="{1 if widget_key == SOLO_PERSISTENT_WAKE_WIDGET_KEY else 0}"></div>',
        unsafe_allow_html=True,
    )


def _production_deliver_callback(st: Any, session: dict[str, Any], raw: Any, key: str) -> None:
    deliver_gate_ctx: dict[str, Any] = {}
    note_process_token_gate = None
    note_try_claim_about_to_call = None
    note_try_claim_result = None
    try:
        from live_draft_solo_parity_p6_persistent_diag import p6_persistent_diag_active, resolve_p6_run_id

        if p6_persistent_diag_active(st, session):
            resolve_p6_run_id(st, session)
    except ImportError:
        pass
    try:
        from live_draft_solo_parity_p6_persistent_diag import (
            p6_persistent_diag_active,
            record_p6_callback_entry,
        )

        if p6_persistent_diag_active(st, session):
            record_p6_callback_entry(
                session,
                raw=raw,
                widget_key=key,
                expected_token=str(session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or ""),
                st=st,
            )
            try:
                from live_draft_solo_parity_p6_persistent_diag import record_p6_raw_widget_value

                record_p6_raw_widget_value(session, raw=raw, st=st)
            except ImportError:
                pass
    except ImportError:
        pass
    try:
        from live_draft_solo_persistent_parity_ladder import parity_p6_active, record_p6_production_callback_event

        if parity_p6_active(session):
            record_p6_production_callback_event(
                session,
                "callback_entry",
                raw=raw,
                widget_key=key,
                expected_token=str(session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or ""),
            )
    except ImportError:
        pass
    try:
        from live_draft_solo_transport_boundary_diag import record_transport_python_run, transport_boundary_active

        if transport_boundary_active(st, session):
            record_transport_python_run(
                st,
                session,
                production_key=key,
                expected_token=str(session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or ""),
                phase="production_on_change",
                on_change_registered=True,
            )
            from live_draft_solo_transport_boundary_diag import PRODUCTION_CALLBACK_FLAG

            session[f"{PRODUCTION_CALLBACK_FLAG}_count"] = int(session.get(f"{PRODUCTION_CALLBACK_FLAG}_count") or 0) + 1
    except ImportError:
        pass
    from live_draft_solo_heartbeat import _coerce_wake_token, process_solo_component_wake

    delivery_via = str(session.pop(SOLO_PENDING_CALLBACK_SOURCE_KEY, "") or "native_component_on_change")
    token = _coerce_wake_token(raw)
    live = _resolve_room(session, None)
    live_dict = live if isinstance(live, dict) else None
    try:
        from live_draft_stage1_process_token_gate import (
            build_process_token_gate_context,
            note_process_token_gate as _note_gate,
            note_try_claim_about_to_call as _note_about,
            note_try_claim_result as _note_result,
        )

        note_process_token_gate = _note_gate
        note_try_claim_about_to_call = _note_about
        note_try_claim_result = _note_result
        deliver_gate_ctx = build_process_token_gate_context(
            st,
            session,
            raw_token=raw,
            normalized_token=str(token or ""),
            widget_key=key,
            source=delivery_via,
            live=live_dict,
        )
        note_process_token_gate(
            session,
            st=st,
            gate_name="production_deliver_callback_entered",
            gate_result="entered",
            decision="continue",
            widget_key=key,
            live=live_dict,
            context=deliver_gate_ctx,
        )
    except ImportError:
        pass

    try:
        from live_draft_stage1_expire_audit import (
            clear_persistent_wake_widget_value,
            map_legacy_reject_reason,
            mark_wake_token_rejected,
            record_callback_invocation,
            try_claim_token_delivery,
        )

        skip_claim = bool(session.get("_solo_parity_skip_delivery_claim"))
        try:
            from live_draft_solo_parity_p6_persistent_diag import (
                append_p6_ledger_row,
                p6_persistent_diag_active,
            )

            if p6_persistent_diag_active(st, session):
                append_p6_ledger_row(
                    session,
                    "ownership_attempted",
                    st=st,
                    expected_token=str(token or "")[:400],
                    actual_token=str(token or "")[:400],
                    delivery_via=delivery_via,
                    widget_key=key,
                )
        except ImportError:
            pass
        if skip_claim:
            try:
                if note_process_token_gate is not None:
                    note_process_token_gate(
                        session,
                        st=st,
                        gate_name="skip_delivery_claim_flag",
                        gate_result="true",
                        decision="continue",
                        return_reason="",
                        widget_key=key,
                        live=live_dict,
                        context=deliver_gate_ctx,
                    )
            except Exception:
                pass
            claimed, reject_code = True, ""
        else:
            try:
                if note_try_claim_about_to_call is not None:
                    note_try_claim_about_to_call(
                        session,
                        st=st,
                        token=str(token or ""),
                        delivery_via=delivery_via,
                        widget_key=key,
                        live=live_dict,
                        context=deliver_gate_ctx,
                    )
            except Exception:
                pass
            claimed, reject_code = try_claim_token_delivery(session, token, delivery_via)
            try:
                if note_try_claim_result is not None:
                    note_try_claim_result(
                        session,
                        st=st,
                        token=str(token or ""),
                        delivery_via=delivery_via,
                        accepted=bool(claimed),
                        reject_code=str(reject_code or ""),
                        widget_key=key,
                        live=live_dict,
                    )
            except Exception:
                pass
        try:
            from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

            if stage1_production_ledger_enabled(st, session):
                from live_draft_stage1_production_ledger import note_stage1_event

                note_stage1_event(
                    session,
                    "production_stage1_token_claim_attempt",
                    st=st,
                    room=live_dict,
                    extra={"token": str(token or "")[:400], "source": delivery_via},
                )
        except ImportError:
            pass
        record_callback_invocation(
            st,
            session,
            callback_source=delivery_via,
            raw_value=raw,
            room=live if isinstance(live, dict) else None,
            reject_code=reject_code if not skip_claim else "",
            token_already_consumed=not claimed and reject_code in ("already_consumed", "callback_source_not_allowed"),
            delivery_claimed=claimed,
        )
        try:
            from live_draft_solo_parity_p6_persistent_diag import (
                note_p6_delivery_completed,
                p6_persistent_diag_active,
                record_p6_ownership_claim,
            )

            if p6_persistent_diag_active(st, session):
                record_p6_ownership_claim(
                    session,
                    attempted=True,
                    accepted=claimed if skip_claim or claimed else False,
                    reject_code=reject_code if not skip_claim else "",
                    token=token,
                    delivery_via=delivery_via,
                    st=st,
                )
                if claimed:
                    note_p6_delivery_completed(session, token=token, st=st)
        except ImportError:
            pass
        try:
            from live_draft_solo_persistent_parity_ladder import parity_p6_active, record_p6_production_callback_event

            if parity_p6_active(session):
                record_p6_production_callback_event(
                    session,
                    "ownership_claim",
                    raw=raw,
                    widget_key=key,
                    delivery_via=delivery_via,
                    expected_token=token,
                    claimed=claimed,
                    reject_code=reject_code if not skip_claim else "",
                )
        except ImportError:
            pass
        if not claimed:
            try:
                if note_process_token_gate is not None:
                    note_process_token_gate(
                        session,
                        st=st,
                        gate_name="try_claim_token_delivery",
                        gate_result=str(reject_code or "rejected"),
                        decision="return",
                        return_reason=str(reject_code or "claim_rejected"),
                        widget_key=key,
                        live=live_dict,
                        context=deliver_gate_ctx,
                    )
            except Exception:
                pass
            try:
                from live_draft_solo_expire_chain import note_solo_expire_chain

                note_solo_expire_chain(
                    session,
                    "expire_rejected",
                    source="persistent_wake",
                    reason=reject_code,
                    token=token[:400],
                    delivery_via=delivery_via,
                )
            except ImportError:
                pass
            if reject_code not in ("empty_raw",):
                mark_wake_token_rejected(session, token, reject_code)
                clear_persistent_wake_widget_value(st, session, token)
            try:
                from live_draft_solo_parity_p6_persistent_diag import (
                    p6_persistent_diag_active,
                    record_p6_callback_return,
                )

                if p6_persistent_diag_active(st, session):
                    record_p6_callback_return(
                        session,
                        reason="claim_rejected",
                        raw=raw,
                    )
            except ImportError:
                pass
            try:
                from live_draft_solo_persistent_parity_ladder import parity_p6_active, record_p6_production_callback_event

                if parity_p6_active(session):
                    record_p6_production_callback_event(
                        session,
                        "callback_return",
                        raw=raw,
                        widget_key=key,
                        expected_token=token,
                        claimed=False,
                        reject_code=reject_code,
                        return_reason="claim_rejected",
                    )
            except ImportError:
                pass
            return
    except ImportError:
        claimed = True
        reject_code = ""
        try:
            from live_draft_stage1_process_token_gate import note_process_token_gate

            note_process_token_gate(
                session,
                st=st,
                gate_name="try_claim_import_unavailable",
                gate_result="ImportError",
                decision="continue",
                return_reason="expire_audit_import_failed_assume_claimed",
                widget_key=key,
                live=live_dict,
                context=deliver_gate_ctx,
            )
        except ImportError:
            pass

    try:
        from live_draft_callback_boundary_diag import (
            boundary_diag_enabled,
            record_callback_boundary,
            trace_helper,
        )
    except ImportError:
        boundary_diag_enabled = lambda s: False  # type: ignore[assignment,misc]
        record_callback_boundary = lambda *a, **k: None  # type: ignore[assignment,misc]
        trace_helper = None  # type: ignore[assignment,misc]

    if boundary_diag_enabled(session):
        record_callback_boundary(
            session,
            "persistent_wake_deliver_callback_entry",
            st=st,
            token=str(raw or "")[:400],
            phase="callback_entry",
            function="_production_deliver_callback",
            extra={"widget_key": key, "delivery_via": delivery_via},
        )

    try:
        from live_draft_solo_expire_chain import note_solo_expire_chain

        if boundary_diag_enabled(session) and trace_helper is not None:
            trace_helper(
                session,
                "note_solo_expire_chain_entry",
                note_solo_expire_chain,
                session,
                "on_change_callback_entry",
                source="persistent_wake",
                widget_key=key,
                delivery_via=delivery_via,
                st=st,
                callback_token=str(raw or "")[:400],
            )
            trace_helper(
                session,
                "note_solo_expire_chain_raw",
                note_solo_expire_chain,
                session,
                "session_state_raw_received",
                source="persistent_wake",
                widget_key=key,
                raw_type=type(raw).__name__ if raw is not None else "NoneType",
                delivery_via=delivery_via,
                st=st,
                callback_token=str(raw or "")[:400],
            )
        else:
            note_solo_expire_chain(
                session,
                "on_change_callback_entry",
                source="persistent_wake",
                widget_key=key,
                delivery_via=delivery_via,
            )
            note_solo_expire_chain(
                session,
                "session_state_raw_received",
                source="persistent_wake",
                widget_key=key,
                raw_type=type(raw).__name__ if raw is not None else "NoneType",
                delivery_via=delivery_via,
            )
    except ImportError:
        pass
    if boundary_diag_enabled(session) and trace_helper is not None:
        token = trace_helper(
            session,
            "_coerce_wake_token",
            _coerce_wake_token,
            raw,
            st=st,
            callback_token=str(raw or "")[:400],
        )
    else:
        token = _coerce_wake_token(raw)
    if not session.get(SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY):
        try:
            from live_draft_stage1_process_token_gate import note_process_token_gate

            note_process_token_gate(
                session,
                st=st,
                gate_name="persistent_wake_actionable",
                gate_result="false",
                decision="return",
                return_reason="not_actionable",
                widget_key=key,
                live=live_dict if isinstance(live, dict) else None,
                context=deliver_gate_ctx if deliver_gate_ctx else None,
            )
        except ImportError:
            pass
        if boundary_diag_enabled(session):
            record_callback_boundary(
                session,
                "persistent_wake_deliver_callback_return",
                st=st,
                token=str(token or "")[:400],
                phase="callback_return",
                extra={"reason": "not_actionable"},
            )
        return
    if not token or token == SOLO_INERT_EXPIRE_TOKEN:
        if boundary_diag_enabled(session):
            record_callback_boundary(
                session,
                "persistent_wake_deliver_callback_return",
                st=st,
                token=str(token or "")[:400],
                phase="callback_return",
                extra={"reason": "inert_token"},
            )
        return
    live = _resolve_room(session, None)
    if not isinstance(live, dict):
        if boundary_diag_enabled(session):
            record_callback_boundary(
                session,
                "persistent_wake_deliver_callback_return",
                st=st,
                token=str(token or "")[:400],
                phase="callback_return",
                extra={"reason": "no_live_room"},
            )
        return
    try:
        from live_draft_solo_persistent_parity_ladder import parity_p6_pick_processing_disabled, record_p6_production_callback_event

        if parity_p6_pick_processing_disabled(session):
            session[SOLO_SKIP_LATE_FLUSH_TOKEN_KEY] = token
            try:
                from live_draft_solo_parity_p6_persistent_diag import (
                    record_p6_callback_return,
                    record_p6_diagnostic_pick_skipped,
                )

                record_p6_diagnostic_pick_skipped(
                    session,
                    reason="parity_p6_pick_processing_disabled",
                    token=str(token or ""),
                    st=st,
                )
                record_p6_callback_return(
                    session,
                    reason="parity_p6_pick_processing_disabled",
                    pick_processing_skipped=True,
                    raw=raw,
                    st=st,
                )
            except ImportError:
                pass
            try:
                from live_draft_solo_persistent_parity_ladder import record_p6_production_callback_event

                record_p6_production_callback_event(
                    session,
                    "callback_return",
                    raw=raw,
                    widget_key=key,
                    expected_token=token,
                    pick_processing_disabled=True,
                    return_reason="parity_p6_pick_processing_disabled",
                )
            except ImportError:
                pass
            if boundary_diag_enabled(session):
                record_callback_boundary(
                    session,
                    "persistent_wake_deliver_callback_return",
                    st=st,
                    token=str(token or "")[:400],
                    phase="callback_return",
                    function="_production_deliver_callback",
                    extra={"reason": "parity_p6_pick_disabled"},
                )
            return
    except ImportError:
        pass
    if boundary_diag_enabled(session) and trace_helper is not None:
        from functools import partial

        trace_helper(
            session,
            "process_solo_component_wake",
            partial(
                process_solo_component_wake,
                st,
                session,
                live,
                token,
                delivery_via=delivery_via,
            ),
            st=st,
            callback_token=str(token or "")[:400],
        )
    else:
        process_solo_component_wake(st, session, live, token, delivery_via=delivery_via)
    session[SOLO_SKIP_LATE_FLUSH_TOKEN_KEY] = token
    session.pop(SOLO_PERSISTENT_WAKE_PICK_LATCH_KEY, None)
    if boundary_diag_enabled(session):
        record_callback_boundary(
            session,
            "persistent_wake_deliver_callback_return",
            st=st,
            token=str(token or "")[:400],
            phase="callback_return",
            function="_production_deliver_callback",
            extra={"reason": "ok"},
        )


def flush_persistent_wake_delivery(st: Any, session: dict[str, Any]) -> None:
    """After widget values bind, deliver expire token from session_state (on_change equivalent)."""
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

        if stage1_production_ledger_enabled(st, session):
            key_probe = solo_persistent_wake_widget_key(session)
            ss_val = ""
            if production_return_value_delivery_active(session):
                try:
                    ss_val = repr(st.session_state.get(key_probe))[:300]
                except Exception:
                    pass
            note_stage1_event(
                session,
                "production_stage1_flush_persistent_wake_delivery_entry",
                st=st,
                widget_key=key_probe,
                extra={
                    "return_value_delivery_active": production_return_value_delivery_active(session),
                    "session_state_value": ss_val,
                },
            )
    except ImportError:
        pass
    if production_return_value_delivery_active(session):
        if not solo_persistent_wake_active(session):
            return
        key = solo_persistent_wake_widget_key(session)
        raw = st.session_state.get(key)
        if raw is None:
            return
        from live_draft_solo_heartbeat import SOLO_COMPONENT_WAKE_SEEN_KEY, _coerce_wake_token

        token = _coerce_wake_token(raw)
        if not token or token == SOLO_INERT_EXPIRE_TOKEN:
            return
        if token == str(session.get(SOLO_SKIP_LATE_FLUSH_TOKEN_KEY) or ""):
            return
        if token == str(session.get(SOLO_COMPONENT_WAKE_SEEN_KEY) or ""):
            return
        try:
            from live_draft_stage1_expire_audit import try_claim_token_delivery

            owners = session.get("_solo_token_delivery_owner") or {}
            if isinstance(owners, dict) and token in owners:
                return
        except ImportError:
            pass
        try:
            from live_draft_solo_declaration_room_context import get_registered_declaration_room
        except ImportError:
            get_registered_declaration_room = lambda _s: None  # type: ignore[assignment,misc]
        process_production_expire_token(
            st,
            session,
            raw_token=raw,
            widget_key=key,
            source="return_value_session_bind",
            declaration_room=get_registered_declaration_room(session),
        )
        try:
            from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

            if stage1_production_ledger_enabled(st, session):
                note_stage1_event(
                    session,
                    "production_stage1_return_value_session_bind_entry",
                    st=st,
                    widget_key=key,
                    extra={"token_preview": repr(raw)[:200]},
                )
        except ImportError:
            pass
        return
    if session.get("_solo_persistent_wake_flush_disabled"):
        return
    try:
        from live_draft_solo_bridge_transition_diag import bridge_transition_active

        if bridge_transition_active(st, session):
            return
    except ImportError:
        pass
    if not solo_persistent_wake_active(session):
        return
    key = solo_persistent_wake_widget_key(session)
    raw = st.session_state.get(key)
    if raw is None:
        return
    from live_draft_solo_heartbeat import SOLO_COMPONENT_WAKE_SEEN_KEY, _coerce_wake_token

    token = _coerce_wake_token(raw)
    if not token or token == SOLO_INERT_EXPIRE_TOKEN:
        return
    if token == str(session.get(SOLO_SKIP_LATE_FLUSH_TOKEN_KEY) or ""):
        return
    if token == str(session.get(SOLO_COMPONENT_WAKE_SEEN_KEY) or ""):
        return
    try:
        from live_draft_stage1_expire_audit import try_claim_token_delivery

        owners = session.get("_solo_token_delivery_owner") or {}
        if isinstance(owners, dict) and token in owners:
            return
    except ImportError:
        pass
    session[SOLO_PENDING_CALLBACK_SOURCE_KEY] = "late_page_flush"
    _production_deliver_callback(st, session, raw, key)


def _mount_persistent_wake_micro_controlled(
    st: Any,
    session: dict[str, Any],
    *,
    location: str,
    draft_id: str,
    widget_key: str,
    props_room: dict[str, Any],
    expire_token: str,
    actionable: bool,
    delivery_only: bool,
    chain_persist_key: str,
    isolated_mode: str,
) -> Any:
    """Production micro mount with P6-only callback-registration controls (R0–R3)."""
    from solo_countdown_wake_micro_core import render_micro_isolation_once

    deliver = _production_deliver_callback
    suppress = True
    control = "R0"
    try:
        from live_draft_solo_parity_p6_persistent_diag import p6_persistent_diag_active

        if p6_persistent_diag_active(st, session):
            from live_draft_solo_p6_declaration_audit import (
                build_b2_reference_declaration_snapshot,
                build_production_declaration_snapshot,
                mount_r3_b2_helper_at_p6,
                resolve_p6_callback_control,
                store_declaration_diff,
                wrap_p6_sentinel_deliver,
            )

            control = resolve_p6_callback_control(st, session)
            if control == "R1":
                suppress = False
            if control == "R2":
                deliver = wrap_p6_sentinel_deliver(_production_deliver_callback)
            prod_snap = build_production_declaration_snapshot(
                widget_key=widget_key,
                expire_token=expire_token,
                chain_persist_key=chain_persist_key,
                deliver_callback=deliver,
                suppress_immediate_session_on_change=suppress,
                location=location,
                production_delivery_only=delivery_only,
                isolated_mode=isolated_mode,
            )
            b2_snap = build_b2_reference_declaration_snapshot(
                widget_key=widget_key,
                expire_token=expire_token,
                chain_persist_key=chain_persist_key,
                deliver_callback=_production_deliver_callback,
                control="B2",
            )
            store_declaration_diff(session, production=prod_snap, b2_reference=b2_snap)
            try:
                from live_draft_solo_parity_p6_persistent_diag import append_p6_ledger_row

                append_p6_ledger_row(
                    session,
                    "declaration_diff_recorded",
                    st=st,
                    callback_control=control,
                    diff_field_count=len(session.get("_solo_p6_declaration_diff", {}).get("differences") or []),
                )
            except ImportError:
                pass
            if control == "R3":
                try:
                    from live_draft_solo_rv3_phase import trace_rv3_decl

                    trace_rv3_decl(
                        st,
                        session,
                        "mount_micro_controlled",
                        exit="p6_r3_b2_helper",
                        p6_callback_control=control,
                    )
                except ImportError:
                    pass
                return mount_r3_b2_helper_at_p6(
                    st,
                    session,
                    widget_key=widget_key,
                    expire_token=expire_token,
                    chain_persist_key=chain_persist_key,
                    deliver_callback=deliver,
                )
            try:
                from live_draft_solo_rv3_phase import trace_rv3_decl

                trace_rv3_decl(
                    st,
                    session,
                    "mount_micro_controlled",
                    p6_persistent_diag=True,
                    p6_callback_control=control,
                )
            except ImportError:
                pass
    except ImportError:
        pass

    delivery_mode = resolve_production_component_delivery_mode(st, session, deliver)
    if delivery_mode == "return_value":
        session[SOLO_PERSISTENT_RETURN_VALUE_DELIVERY_KEY] = True
    else:
        session.pop(SOLO_PERSISTENT_RETURN_VALUE_DELIVERY_KEY, None)

    if str(session.get("_solo_rv_ladder_step") or "") == "RV3":

        try:
            from live_draft_solo_rv3_phase import RV3_MOUNT_BLOCK_REASON_KEY

            blocked = str(session.get(RV3_MOUNT_BLOCK_REASON_KEY) or "").strip()
            if blocked:
                try:
                    from live_draft_solo_rv3_phase import trace_rv3_decl

                    trace_rv3_decl(
                        st,
                        session,
                        "mount_micro_controlled",
                        exit=False,
                        reason="rv3_mount_block_reason",
                        rv3_mount_block_reason=blocked,
                    )
                except ImportError:
                    pass
                return False
        except ImportError:
            pass

        try:
            from live_draft_solo_rv3_phase import trace_rv3_decl

            trace_rv3_decl(
                st,
                session,
                "mount_micro_controlled",
                before="mount_with_rv_control_declaration",
                expire_token=str(expire_token or "")[:120],
                widget_key=widget_key,
                location=location,
            )
        except ImportError:
            pass

        def _rv3_production_mount() -> Any:
            return render_micro_isolation_once(
                st,
                session,
                placement="PROD",
                location=location,
                draft_id=draft_id,
                route=True,
                persistent=True,
                session_prefix=SOLO_PERSISTENT_WAKE_SESSION_PREFIX,
                widget_key=widget_key,
                production_room=props_room,
                production_expire_token=expire_token,
                production_actionable=actionable,
                production_delivery_only=delivery_only,
                deliver_callback=deliver,
                suppress_immediate_session_on_change=suppress,
                chain_persist_key=chain_persist_key,
                production_use_return_value_delivery=(delivery_mode == "return_value"),
            )

        from live_draft_solo_rv_control_probe import mount_with_rv_control_declaration

        session["_solo_persistent_wake_last_token"] = expire_token
        session["_solo_parity_expected_token"] = expire_token
        return mount_with_rv_control_declaration(
            st,
            session,
            props_room,
            widget_key=widget_key,
            mount_fn=_rv3_production_mount,
            control_name="RV3",
            location=location,
            probe_placeholder=None,
        )

    return render_micro_isolation_once(
        st,
        session,
        placement="PROD",
        location=location,
        draft_id=draft_id,
        route=True,
        persistent=True,
        session_prefix=SOLO_PERSISTENT_WAKE_SESSION_PREFIX,
        widget_key=widget_key,
        production_room=props_room,
        production_expire_token=expire_token,
        production_actionable=actionable,
        production_delivery_only=delivery_only,
        deliver_callback=deliver,
        suppress_immediate_session_on_change=suppress,
        chain_persist_key=chain_persist_key,
        production_use_return_value_delivery=(delivery_mode == "return_value"),
    )


def try_solo_persistent_wake_ldr_entry(st: Any, session: dict[str, Any], room: Any) -> bool:
    """Mount/update the Solo wake at LDR page entry. Never st.stop(). Returns True when handled."""
    try:
        from live_draft_solo_rv3_phase import trace_rv3_decl

        trace_rv3_decl(st, session, "try_persistent_wake_ldr_entry", entered=True)
    except ImportError:
        pass
    if not _should_mount_persistent_wake(st, session):
        try:
            from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

            if stage1_production_ledger_enabled(st, session):
                note_stage1_event(
                    session,
                    "production_stage1_persistent_wake_eligibility",
                    st=st,
                    room=room if isinstance(room, dict) else None,
                    extra={"eligible": False, "reason": "should_mount_false"},
                )
        except ImportError:
            pass
        try:
            from live_draft_solo_rv3_phase import trace_rv3_decl

            trace_rv3_decl(st, session, "try_persistent_wake_ldr_entry", exit=False, reason="should_mount_false")
        except ImportError:
            pass
        return False

    try:
        from live_draft_solo_rv3_phase import rv3_active, rv3_allows_full_ldr_countdown, rv3_blocks_diag_countdowns

        if rv3_active(session) and rv3_blocks_diag_countdowns(session):
            try:
                from live_draft_solo_rv3_phase import trace_rv3_decl

                trace_rv3_decl(st, session, "try_persistent_wake_ldr_entry", exit=False, reason="rv3_blocks_diag_countdowns")
            except ImportError:
                pass
            return False
    except ImportError:
        pass

    try:
        from live_draft_solo_parity_p6_persistent_diag import p6_persistent_diag_active, resolve_p6_run_id

        if p6_persistent_diag_active(st, session) and str(session.get("_solo_rv_ladder_step") or "") != "RV3":
            resolve_p6_run_id(st, session)
    except ImportError:
        pass

    try:
        from live_draft_solo_transport_boundary_diag import (
            bootstrap_transport_diagnostics,
            mount_transport_minimal_control,
            paired_transport_minimal_control_enabled,
            record_production_component_declaration,
            record_transport_python_run,
            render_transport_boundary_probe,
            render_transport_parent_listener,
            transport_boundary_active,
            transport_isolated_mode,
            mount_transport_isolated_minimal_only,
        )
    except ImportError:
        bootstrap_transport_diagnostics = lambda *a, **k: None  # type: ignore[assignment,misc]
        transport_boundary_active = lambda _s, _sess: False  # type: ignore[assignment,misc]
        render_transport_parent_listener = lambda _st: None  # type: ignore[assignment,misc]
        record_transport_python_run = lambda *a, **k: None  # type: ignore[assignment,misc]
        record_production_component_declaration = lambda *a, **k: None  # type: ignore[assignment,misc]
        mount_transport_minimal_control = lambda *a, **k: None  # type: ignore[assignment,misc]
        render_transport_boundary_probe = lambda *a, **k: None  # type: ignore[assignment,misc]
        transport_isolated_mode = lambda _s, _sess: ""  # type: ignore[assignment,misc]
        mount_transport_isolated_minimal_only = lambda *a, **k: None  # type: ignore[assignment,misc]
        paired_transport_minimal_control_enabled = lambda *a, **k: False  # type: ignore[assignment,misc]

    bootstrap_transport_diagnostics(st, session)

    from live_draft_solo_delivery_diag import render_parent_postmessage_listener

    render_parent_postmessage_listener(st)
    if transport_boundary_active(st, session):
        render_transport_parent_listener(st)

    isolated = transport_isolated_mode(st, session)
    try:
        from live_draft_solo_rv3_phase import rv3_active, rv3_allows_full_ldr_countdown

        if rv3_active(session):
            if not rv3_allows_full_ldr_countdown(session):
                try:
                    from live_draft_solo_rv3_phase import get_rv3_phase, trace_rv3_decl

                    trace_rv3_decl(
                        st,
                        session,
                        "try_persistent_wake_ldr_entry",
                        exit=False,
                        reason="rv3_disallows_full_ldr_countdown",
                        rv3_phase=get_rv3_phase(session),
                        rv3_hydrated=bool(session.get("_solo_rv_rv3_real_room_hydrated")),
                    )
                except ImportError:
                    pass
                return False
            if isolated == "minimal":
                isolated = "production"
            try:
                from live_draft_solo_rv3_phase import trace_rv3_decl

                trace_rv3_decl(st, session, "try_persistent_wake_rv3_isolated", isolated=isolated)
            except ImportError:
                pass
    except ImportError:
        pass
    if isolated == "production":
        session.pop("_solo_persistent_wake_flush_disabled", None)
    elif isolated == "minimal":
        session["_solo_persistent_wake_flush_disabled"] = True

    from solo_countdown_wake_micro_core import render_micro_isolation_once

    room_dict = _resolve_room(session, room)
    session[SOLO_PERSISTENT_WAKE_LATCH_KEY] = True
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

        if stage1_production_ledger_enabled(st, session):
            note_stage1_event(
                session,
                "production_stage1_persistent_wake_eligibility",
                st=st,
                room=room_dict if isinstance(room_dict, dict) else None,
                extra={"eligible": True, "location": "ldr_page_entry_early_persistent"},
            )
            note_stage1_event(
                session,
                "production_stage1_room_checkpoint",
                st=st,
                room=room_dict if isinstance(room_dict, dict) else None,
                extra={"checkpoint": "before_persistent_mount"},
            )
    except ImportError:
        pass

    key = solo_persistent_wake_widget_key(session)
    from live_draft_solo_heartbeat import _coerce_wake_token

    pending_raw = st.session_state.get(key)
    pending_token = _coerce_wake_token(pending_raw)
    try:
        from live_draft_solo_heartbeat import SOLO_COMPONENT_WAKE_SEEN_KEY
    except ImportError:
        SOLO_COMPONENT_WAKE_SEEN_KEY = "_solo_component_wake_seen_token"  # type: ignore[misc,assignment]
    rejected = session.get("_solo_wake_rejected_tokens") or {}
    pending_consumed = pending_token and (
        pending_token == str(session.get(SOLO_COMPONENT_WAKE_SEEN_KEY) or "")
        or (isinstance(rejected, dict) and pending_token in rejected)
    )
    delivery_only = bool(
        pending_token
        and pending_token != SOLO_INERT_EXPIRE_TOKEN
        and pending_raw is not None
        and not pending_consumed
        and session.get(SOLO_PERSISTENT_WAKE_LATCH_KEY)
    )
    if delivery_only and str(session.get("_solo_rv_ladder_step") or "").strip():
        try:
            from live_draft_solo_rv_declaration_ledger import note_browser_send_observed

            note_browser_send_observed(session)
        except ImportError:
            pass
    if pending_token and pending_token != SOLO_INERT_EXPIRE_TOKEN:
        props_room = room_dict if isinstance(room_dict, dict) else {}
        actionable = True
        expire_token = pending_token
        phase = "active"
    else:
        actionable, expire_token, props_room, phase = resolve_persistent_wake_mount(session, room_dict)
        actionable, expire_token, props_room, phase = _apply_actionable_hold(
            session, room_dict, actionable, expire_token, props_room, phase
        )
    session[SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY] = actionable
    session[SOLO_PERSISTENT_WAKE_TOKEN_KEY] = expire_token
    key = solo_persistent_wake_widget_key(session)
    did = str(props_room.get("draft_room_id") or props_room.get("draft_id") or "")

    persist_key = solo_persistent_chain_persist_key(session, room_dict)
    minimal_token_expected = ""
    if actionable and expire_token and expire_token != SOLO_INERT_EXPIRE_TOKEN:
        try:
            from live_draft_solo_transport_boundary_diag import build_minimal_control_token

            minimal_token_expected = build_minimal_control_token(expire_token)
        except ImportError:
            minimal_token_expected = ""

    record_transport_python_run(
        st,
        session,
        production_key=key,
        expected_token=expire_token,
        phase="pre_mount",
        on_change_registered=isolated != "minimal",
        expected_minimal_token=minimal_token_expected,
    )

    if isolated == "minimal":
        from live_draft_solo_transport_boundary_diag import (
            MINIMAL_WIDGET_KEY,
            build_minimal_control_token,
        )

        min_tok = minimal_token_expected or build_minimal_control_token(expire_token)
        mount_transport_isolated_minimal_only(st, session, expire_token=expire_token)
        record_transport_python_run(
            st,
            session,
            production_key=MINIMAL_WIDGET_KEY,
            expected_token=min_tok,
            phase="post_mount_minimal_isolated",
            on_change_registered=True,
            expected_minimal_token=min_tok,
        )
        render_transport_boundary_probe(st, session)
        render_persistent_wake_lifecycle_probe(
            st,
            session,
            widget_key=MINIMAL_WIDGET_KEY,
            actionable=True,
            phase="minimal_isolated",
            expire_token=minimal_token_expected or expire_token,
        )
        return True

    if isolated == "production":
        _ = _mount_persistent_wake_micro_controlled(
            st,
            session,
            location="ldr_page_entry_early_persistent",
            draft_id=did,
            widget_key=key,
            props_room=props_room,
            expire_token=expire_token,
            actionable=actionable,
            delivery_only=delivery_only,
            chain_persist_key=persist_key,
            isolated_mode=isolated,
        )
        if transport_boundary_active(st, session):
            from live_draft_solo_transport_boundary_diag import PRODUCTION_CALLBACK_FLAG

            session[PRODUCTION_CALLBACK_FLAG] = True
        comp_return = st.session_state.get(key) if key in st.session_state else None
        record_production_component_declaration(
            st,
            session,
            widget_key=key,
            expire_token=expire_token,
            actionable=actionable,
            component_return=comp_return,
            default_value=None,
            mount_location="ldr_page_entry_isolated_production",
        )
        try:
            from live_draft_solo_parity_p6_persistent_diag import (
                p6_persistent_diag_active,
                record_p6_component_declaration,
            )

            if p6_persistent_diag_active(st, session):
                record_p6_component_declaration(
                    session,
                    widget_key=key,
                    expire_token=expire_token,
                    component_return=comp_return,
                    mount_location="ldr_page_entry_isolated_production",
                    st=st,
                    component_default=None,
                )
        except ImportError:
            pass
        record_transport_python_run(
            st,
            session,
            production_key=key,
            expected_token=expire_token,
            phase="post_mount",
            on_change_registered=True,
            expected_minimal_token="",
        )
        render_transport_boundary_probe(st, session)
        render_persistent_wake_lifecycle_probe(
            st,
            session,
            widget_key=key,
            actionable=actionable,
            phase=phase,
            expire_token=expire_token,
        )
        return True

    micro_result = _mount_persistent_wake_micro_controlled(
        st,
        session,
        location="ldr_page_entry_early_persistent",
        draft_id=did,
        widget_key=key,
        props_room=props_room,
        expire_token=expire_token,
        actionable=actionable,
        delivery_only=delivery_only,
        chain_persist_key=persist_key,
        isolated_mode=isolated or "",
    )
    if transport_boundary_active(st, session):
        from live_draft_solo_transport_boundary_diag import PRODUCTION_CALLBACK_FLAG

        session[PRODUCTION_CALLBACK_FLAG] = True
    comp_return = getattr(micro_result, "component_return", None)
    if comp_return is None and key in st.session_state:
        comp_return = st.session_state.get(key)
    record_production_component_declaration(
        st,
        session,
        widget_key=key,
        expire_token=expire_token,
        actionable=actionable,
        component_return=comp_return,
        default_value=None,
        mount_location="ldr_page_entry_early_persistent",
    )
    try:
        from live_draft_solo_parity_p6_persistent_diag import (
            p6_persistent_diag_active,
            record_p6_component_declaration,
        )

        if p6_persistent_diag_active(st, session):
            record_p6_component_declaration(
                session,
                widget_key=key,
                expire_token=expire_token,
                component_return=comp_return,
                mount_location="ldr_page_entry_early_persistent",
                st=st,
                component_default=None,
            )
    except ImportError:
        pass
    if actionable and expire_token and expire_token != SOLO_INERT_EXPIRE_TOKEN:
        if paired_transport_minimal_control_enabled(st, session, isolated=isolated):
            mount_transport_minimal_control(
                st,
                session,
                props_room if isinstance(props_room, dict) else {},
                production_expire_token=expire_token,
                chain_persist_key=persist_key,
            )
    record_transport_python_run(
        st,
        session,
        production_key=key,
        expected_token=expire_token,
        phase="post_mount",
        on_change_registered=not production_return_value_delivery_active(session),
        expected_minimal_token=minimal_token_expected,
    )
    render_transport_boundary_probe(st, session)
    render_persistent_wake_lifecycle_probe(
        st,
        session,
        widget_key=key,
        actionable=actionable,
        phase=phase,
        expire_token=expire_token,
    )
    try:
        from live_draft_solo_component_diagnostics import (
            record_solo_component_mount_attempt,
            solo_component_diag_enabled,
        )

        if solo_component_diag_enabled(st, session):
            record_solo_component_mount_attempt(
                session,
                props_room,
                key=solo_persistent_wake_widget_key(session),
                mounted=True,
                reason="persistent_early",
                expire_token=expire_token,
            )
    except ImportError:
        pass
    try:
        from live_draft_solo_expire_chain import note_solo_expire_chain

        note_solo_expire_chain(
            session,
            "persistent_wake_mounted",
            source="persistent_wake",
            widget_key=solo_persistent_wake_widget_key(session),
            expire_token=expire_token,
            room_status=str((room_dict or {}).get("status") or ""),
        )
    except ImportError:
        pass
    return True
