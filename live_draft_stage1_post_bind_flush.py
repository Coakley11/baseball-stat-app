"""Authoritative bound-token gate for post-bind observation/flush (P8 transport)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

SOLO_POST_BIND_FLUSH_DISPATCHED_KEY = "_solo_stage1_post_bind_flush_dispatched_token"


@dataclass(frozen=True)
class BoundTokenGateResult:
    passed: bool
    decision: str
    selected_bound_token: str
    candidate_source: str
    exact_match: bool
    invocation_id: str


def post_bind_flush_already_dispatched(session: dict[str, Any], token: str) -> bool:
    tok = str(token or "").strip()
    if not tok:
        return False
    return str(session.get(SOLO_POST_BIND_FLUSH_DISPATCHED_KEY) or "").strip() == tok


def mark_post_bind_flush_dispatched(session: dict[str, Any], token: str) -> None:
    tok = str(token or "").strip()
    if tok:
        session[SOLO_POST_BIND_FLUSH_DISPATCHED_KEY] = tok


def _coerce(value: Any) -> str:
    from live_draft_solo_heartbeat import _coerce_wake_token

    return str(_coerce_wake_token(value) or "").strip()


def deployment_sha_for_session(session: dict[str, Any]) -> str:
    sha = str(session.get("_solo_stage1_deployment_sha") or "").strip()
    if sha:
        return sha[:7]
    try:
        from suite_deploy_marker import resolve_git_commit_short

        return str(resolve_git_commit_short() or "")[:7]
    except ImportError:
        return ""


def _deployment_sha(session: dict[str, Any]) -> str:
    return deployment_sha_for_session(session)


def note_bound_token_gate(
    st: Any,
    session: dict[str, Any],
    *,
    gate: BoundTokenGateResult,
    expected_expiration_token: str,
    mount_expire_token: str,
    pending_token: str,
    raw_component_return: Any,
    session_state_value: Any,
    coalesced_value: str,
    widget_key: str,
    room_id: str,
    pick_index: Any,
    call_site: str,
    expected_token_source: str = "",
    declaration_context_token: str = "",
    same_key_session_state: str = "",
    deadline: Any = None,
    call_site_expected_token: str = "",
    snapshot_validation_ok: bool = False,
    snapshot_rejection_reason: str = "",
    extra_instrumentation: dict[str, Any] | None = None,
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

        if not stage1_production_ledger_enabled(st, session):
            return
    except ImportError:
        return
    note_stage1_event(
        session,
        "production_stage1_bound_token_gate",
        st=st,
        widget_key=widget_key,
        extra={
            "exact_expected_expiration_token": str(expected_expiration_token or "")[:400],
            "mount_token": str(mount_expire_token or "")[:400],
            "pending_token": str(pending_token or "")[:400],
            "direct_component_return": repr(raw_component_return)[:400],
            "session_state_value": repr(session_state_value)[:400],
            "coalesced_value": str(coalesced_value or "")[:400],
            "selected_bound_token": gate.selected_bound_token[:400],
            "candidate_source": gate.candidate_source,
            "exact_match": gate.exact_match,
            "widget_key": widget_key,
            "room_id": str(room_id or "")[:32],
            "pick_index": pick_index,
            "invocation_id": gate.invocation_id,
            "deployment_sha": _deployment_sha(session),
            "decision": gate.decision,
            "call_site": call_site,
            "expected_token": str(expected_expiration_token or "")[:400],
            "expected_token_source": str(expected_token_source or "")[:80],
            "declaration_context_token": str(declaration_context_token or "")[:400],
            "same_key_session_state": str(same_key_session_state or "")[:400],
            "deadline": deadline,
            "call_site_expected_token": str(call_site_expected_token or "")[:400],
            "snapshot_validation_ok": snapshot_validation_ok,
            "snapshot_rejection_reason": str(snapshot_rejection_reason or "")[:200],
            **(extra_instrumentation or {}),
        },
    )


def snapshot_validation_fields(
    session: dict[str, Any],
    snapshot: dict[str, Any] | None,
    *,
    widget_key: str,
    room_id: str,
    pick_index: Any,
    deadline: Any,
) -> dict[str, Any]:
    snap = snapshot if isinstance(snapshot, dict) else {}
    live = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    return {
        "snapshot_expected_token": str(snap.get("expected_token") or "")[:400],
        "snapshot_room_id": str(snap.get("room_id") or "")[:32],
        "snapshot_pick_index": snap.get("pick_index"),
        "snapshot_deadline": snap.get("deadline"),
        "snapshot_fingerprint": str(snap.get("room_fingerprint") or "")[:120],
        "snapshot_widget_key": str(snap.get("widget_key") or "")[:80],
        "snapshot_deployment_sha": str(snap.get("deployment_sha") or "")[:7],
        "snapshot_declaration_timestamp": snap.get("registered_at"),
        "current_room_id": str(
            room_id or live.get("draft_room_id") or live.get("draft_id") or ""
        )[:32],
        "current_pick_index": pick_index if pick_index is not None else live.get("current_pick_index"),
        "current_deadline": deadline if deadline is not None else live.get("timer_deadline"),
        "current_widget_key": str(widget_key or "")[:80],
        "current_deployment_sha": deployment_sha_for_session(session),
        "snapshot_consumed_token": str(session.get("_solo_stage1_expiration_snapshot_consumed_token") or "")[
            :400
        ],
    }


def evaluate_bound_token_gate(
    st: Any,
    session: dict[str, Any],
    *,
    expected_expiration_token: str,
    mount_expire_token: str,
    pending_token: str = "",
    raw_component_return: Any,
    session_state_value: Any,
    widget_key: str,
    call_site: str = "",
) -> BoundTokenGateResult:
    """Exact-token gate across direct return, session state, cache, and durable callback handoff."""
    invocation_id = uuid.uuid4().hex[:12]
    expected_call = _coerce(expected_expiration_token or mount_expire_token)
    direct = _coerce(raw_component_return) if raw_component_return is not None else ""
    ss_present = bool(widget_key and hasattr(st, "session_state") and widget_key in st.session_state)
    ss_val = st.session_state.get(widget_key) if ss_present else session_state_value
    ss = _coerce(ss_val) if ss_val is not None else ""

    cache_raw = ""
    try:
        cached = session.get(f"_solo_prod_raw_return_{widget_key}")
        cache_raw = _coerce(cached) if cached is not None else ""
    except Exception:
        cache_raw = ""

    handoff_raw = ""
    handoff_reject = ""
    try:
        from live_draft_prod_callback_handoff import get_handoff_record
        from live_draft_solo_heartbeat import _coerce_wake_token

        rec = get_handoff_record(session, widget_key)
        if isinstance(rec, dict):
            handoff_raw = str(_coerce_wake_token(rec.get("raw_token")) or "").strip()
    except ImportError:
        handoff_raw = ""
    call_site_expected = str(expected_expiration_token or "")[:400]
    expected_source = "call_site" if expected_call else ""
    declaration_context_token = ""
    snap = None
    snapshot_validation_ok = False
    snapshot_rejection_reason = ""
    expected = expected_call
    if not expected:
        try:
            from live_draft_solo_declaration_room_context import (
                get_declaration_context,
                resolve_gate_expected_from_declaration_snapshot,
            )

            snap = get_declaration_context(session)
            declaration_context_token = str((snap or {}).get("expected_token") or "")[:400]
            recovered, recovered_source, reject_reason = resolve_gate_expected_from_declaration_snapshot(
                session,
                widget_key=widget_key,
                direct_token=direct,
                session_state_token=ss,
            )
            snapshot_rejection_reason = reject_reason or ""
            if recovered:
                expected = recovered
                expected_source = recovered_source
                snapshot_validation_ok = recovered_source == "validated_declaration_snapshot"
            elif direct or ss:
                snapshot_validation_ok = False
                if not snapshot_rejection_reason:
                    snapshot_rejection_reason = "snapshot_validation_failed"
        except ImportError:
            pass
    elif expected_call:
        snapshot_validation_ok = True

    mount_t = _coerce(mount_expire_token)
    pending_t = _coerce(pending_token)

    coalesced = direct or ss or cache_raw or handoff_raw
    room_id = ""
    pick_index = None
    deadline = None
    try:
        live = session.get("live_draft_room")
        if isinstance(live, dict):
            room_id = str(live.get("draft_room_id") or live.get("draft_id") or "")
            pick_index = live.get("current_pick_index")
            deadline = live.get("timer_deadline")
    except Exception:
        pass
    if (not room_id or pick_index is None) and isinstance(snap, dict):
        room_id = room_id or str(snap.get("room_id") or "")
        if pick_index is None:
            pick_index = snap.get("pick_index")
        if deadline is None:
            deadline = snap.get("deadline")

    selected = ""
    source = ""
    decision = "reject_no_authoritative_surface"
    passed = False
    exact_match = False

    try:
        from live_draft_prod_callback_handoff import coalesce_expiration_token_candidates

        selected, source, decision = coalesce_expiration_token_candidates(
            expected_token=expected,
            direct_raw=direct,
            session_state_raw=ss,
            cache_raw=cache_raw,
            handoff_raw=handoff_raw,
        )
        passed = decision.startswith("pass_") and bool(selected)
        exact_match = passed and selected == expected
        if decision == "pass_exact_token" and source:
            decision = f"pass_{source}"
    except ImportError:
        if direct and expected and direct == expected:
            selected, source = direct, "direct_component_return"
            passed = True
            exact_match = True
            decision = "pass_direct_component_return"
        elif ss_present and ss and expected and ss == expected:
            selected, source = ss, "same_key_session_state"
            passed = True
            exact_match = True
            decision = "pass_same_key_session_state"
        elif expected and mount_t == expected and not direct and not ss:
            decision = "reject_mount_token_not_bound"
        elif pending_t and pending_t == expected and not direct and not ss:
            decision = "reject_pending_token_not_bound"
        elif (direct or ss) and expected and (direct or ss) != expected:
            decision = "reject_token_mismatch"

    if passed and source == "durable_callback_handoff" and expected:
        _rec, reject = "", handoff_reject
        try:
            from live_draft_prod_callback_handoff import validate_handoff_for_declaration

            _rec, reject = validate_handoff_for_declaration(
                session,
                widget_key=widget_key,
                expected_token=expected,
                st=st,
            )
        except ImportError:
            reject = ""
        if not _rec:
            passed = False
            exact_match = False
            selected = ""
            source = ""
            decision = f"reject_handoff_validation:{reject or handoff_reject or 'failed'}"
        else:
            try:
                from live_draft_prod_callback_handoff import emit_callback_handoff_selected

                emit_callback_handoff_selected(session, st=st, widget_key=widget_key, record=_rec)
            except ImportError:
                pass

    if not passed:
        if decision in ("reject_no_authoritative_surface", "reject_no_exact_candidate"):
            if expected and mount_t == expected and not direct and not ss and not handoff_raw and not cache_raw:
                decision = "reject_mount_token_not_bound"
            elif pending_t and pending_t == expected and not direct and not ss and not handoff_raw:
                decision = "reject_pending_token_not_bound"
            elif (direct or ss) and expected and (direct or ss) != expected:
                decision = "reject_token_mismatch"

    gate = BoundTokenGateResult(
        passed=passed,
        decision=decision,
        selected_bound_token=selected,
        candidate_source=source,
        exact_match=exact_match,
        invocation_id=invocation_id,
    )
    snap_fields = snapshot_validation_fields(
        session,
        snap if isinstance(snap, dict) else None,
        widget_key=widget_key,
        room_id=room_id,
        pick_index=pick_index,
        deadline=deadline,
    )
    if isinstance(snap, dict):
        try:
            live_fp = ""
            room_obj = snap.get("room")
            if isinstance(room_obj, dict):
                from live_draft_solo_declaration_room_context import _room_fingerprint

                live_fp = _room_fingerprint(room_obj)
            snap_fields["current_fingerprint"] = live_fp
        except Exception:
            pass
    note_bound_token_gate(
        st,
        session,
        gate=gate,
        expected_expiration_token=expected,
        mount_expire_token=mount_expire_token,
        pending_token=pending_token,
        raw_component_return=raw_component_return,
        session_state_value=ss_val,
        coalesced_value=coalesced,
        widget_key=widget_key,
        room_id=room_id,
        pick_index=pick_index,
        call_site=call_site or "evaluate_bound_token_gate",
        expected_token_source=expected_source,
        declaration_context_token=declaration_context_token,
        same_key_session_state=ss if ss_present else "",
        deadline=deadline,
        call_site_expected_token=call_site_expected,
        snapshot_validation_ok=snapshot_validation_ok,
        snapshot_rejection_reason=snapshot_rejection_reason,
        extra_instrumentation={
            **snap_fields,
            "handoff_candidate": str(handoff_raw or "")[:400],
            "raw_return_cache": str(cache_raw or "")[:400],
            "handoff_reject": str(handoff_reject or "")[:120],
        },
    )
    return gate


def complete_delivery_only_observation_and_actionable_flush(
    st: Any,
    session: dict[str, Any],
    *,
    expected_expiration_token: str,
    mount_expire_token: str,
    pending_token: str,
    widget_key: str,
    production_room: dict[str, Any] | None,
    raw_component_value: Any = None,
) -> bool:
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token=expected_expiration_token,
        mount_expire_token=mount_expire_token,
        pending_token=pending_token,
        raw_component_return=raw_component_value,
        session_state_value=st.session_state.get(widget_key) if widget_key in st.session_state else None,
        widget_key=widget_key,
        call_site="complete_delivery_only_observation_and_actionable_flush",
    )
    if not gate.passed or not gate.selected_bound_token:
        return False

    bound_token = gate.selected_bound_token
    if post_bind_flush_already_dispatched(session, bound_token):
        return False
    try:
        from live_draft_stage1_expire_audit import is_token_action_complete

        if is_token_action_complete(session, bound_token):
            return False
    except ImportError:
        pass

    from live_draft_stage1_process_token_gate import (
        delivery_only_observation_completed,
        mark_delivery_only_observation_completed,
        note_delivery_only_observation_completed,
    )

    obs_extra = {
        "bound_token": bound_token[:400],
        "bound_token_source": gate.candidate_source,
        "direct_return_value": repr(raw_component_value)[:400],
        "session_state_value": repr(st.session_state.get(widget_key))[:400]
        if widget_key in st.session_state
        else "missing",
        "coalesced_value": bound_token[:400],
        "expected_token": str(expected_expiration_token or mount_expire_token)[:400],
        "exact_match": gate.exact_match,
        "observation_invocation_id": gate.invocation_id,
    }

    if not delivery_only_observation_completed(session, bound_token):
        mark_delivery_only_observation_completed(
            session,
            bound_token,
            source="return_value_session_bind",
        )
        try:
            from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

            if stage1_production_ledger_enabled(st, session):
                note_delivery_only_observation_completed(
                    session,
                    st=st,
                    token=bound_token,
                    widget_key=widget_key,
                    source="return_value_session_bind",
                    deliver_gate_ctx={
                        "delivery_only": True,
                        "source": "return_value_session_bind",
                        "canonical_source": "return_value_session_bind",
                        **obs_extra,
                    },
                    live=production_room if isinstance(production_room, dict) else None,
                )
        except ImportError:
            pass

    session["_solo_stage1_last_delivery_only"] = False
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

        if stage1_production_ledger_enabled(st, session):
            note_stage1_event(
                session,
                "production_stage1_post_bind_actionable_flush",
                st=st,
                widget_key=widget_key,
                extra={
                    **obs_extra,
                    "mount_expire_token": str(mount_expire_token or "")[:400],
                },
            )
    except ImportError:
        pass
    try:
        from live_draft_solo_persistent_wake import flush_persistent_wake_delivery

        flush_persistent_wake_delivery(st, session)
    except ImportError:
        return False
    mark_post_bind_flush_dispatched(session, bound_token)
    try:
        from live_draft_solo_declaration_room_context import consume_expiration_validation_snapshot

        consume_expiration_validation_snapshot(session, bound_token, reason="post_bind_actionable_flush")
    except ImportError:
        pass
    return True
