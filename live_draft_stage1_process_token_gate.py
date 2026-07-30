"""Stage 1A process_production_expire_token gate ledger (diagnostic only)."""

from __future__ import annotations

import time
from typing import Any

SOLO_STAGE1_DELIVERY_ONLY_OBSERVED_KEY = "_solo_stage1_delivery_only_observed_tokens"


def _active_page(st: Any | None) -> str:
    if st is None:
        return ""
    try:
        from app_page_generation import current_active_page

        return str(current_active_page(st) or "")
    except ImportError:
        pass
    try:
        qp = getattr(st, "query_params", None)
        if qp is not None:
            ap = qp.get("active_page")
            if isinstance(ap, list):
                return str(ap[0] or "")
            return str(ap or "")
    except Exception:
        pass
    return ""


def _parse_token_fields(token: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "token_parse_ok": False,
        "token_room_id": "",
        "token_pick_index": None,
        "token_deadline": None,
    }
    tok = str(token or "").strip()
    if not tok:
        return out
    try:
        from solo_countdown_component import parse_solo_expire_token

        parsed = parse_solo_expire_token(tok)
        if not parsed:
            return out
        out["token_parse_ok"] = True
        out["token_room_id"] = str(parsed.get("draft_id") or "")
        out["token_pick_index"] = parsed.get("pick_index")
        out["token_deadline"] = parsed.get("deadline")
    except ImportError:
        pass
    return out


def build_process_token_gate_context(
    st: Any | None,
    session: dict[str, Any],
    *,
    raw_token: Any,
    normalized_token: str,
    widget_key: str,
    source: str,
    live: dict[str, Any] | None = None,
    delivery_only: bool | None = None,
) -> dict[str, Any]:
    live_room = live if isinstance(live, dict) else session.get("live_draft_room")
    if not isinstance(live_room, dict):
        live_room = {}
    deadline = None
    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        if live_room:
            deadline = live_draft_timer_deadline(live_room)
    except ImportError:
        if live_room.get("timer_deadline") is not None:
            deadline = float(live_room.get("timer_deadline") or 0.0)
    expected = str(session.get("_solo_persistent_wake_last_token") or session.get("_solo_parity_expected_token") or "")
    owners = session.get("_solo_token_delivery_owner") or {}
    prior_claimed = ""
    if isinstance(owners, dict) and normalized_token and normalized_token in owners:
        prior_claimed = str(owners.get(normalized_token) or "")
    diag_flags: dict[str, Any] = {}
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        diag_flags["solo_component_diag"] = bool(solo_component_diag_enabled(st, session))
    except ImportError:
        diag_flags["solo_component_diag"] = False
    try:
        from live_draft_solo_parity_p6_persistent_diag import p6_persistent_diag_active

        diag_flags["p6_persistent_diag"] = bool(p6_persistent_diag_active(st, session))
    except ImportError:
        diag_flags["p6_persistent_diag"] = False
    rv3 = str(session.get("_solo_rv_ladder_step") or "").strip()
    parsed = _parse_token_fields(normalized_token)
    try:
        from live_draft_stage1_expire_audit import canonical_production_source, is_token_action_complete

        original_source, canonical_source = canonical_production_source(source)
    except ImportError:
        original_source, canonical_source = str(source or ""), str(source or "")
    delivery_only_val = (
        delivery_only if delivery_only is not None else bool(session.get("_solo_stage1_last_delivery_only"))
    )
    return {
        "source": source,
        "original_source": original_source,
        "canonical_source": canonical_source,
        "raw_token": repr(raw_token)[:400],
        "normalized_token": str(normalized_token or "")[:400],
        "expected_token": expected[:400],
        "token_parse_ok": parsed["token_parse_ok"],
        "token_room_id": parsed["token_room_id"],
        "token_pick_index": parsed["token_pick_index"],
        "token_deadline": parsed["token_deadline"],
        "current_room_id": str(live_room.get("draft_room_id") or live_room.get("draft_id") or "").strip(),
        "current_pick_index": live_room.get("current_pick_index"),
        "current_deadline": deadline,
        "active_page": _active_page(st),
        "room_status": str(live_room.get("status") or ""),
        "live_draft_room_present": bool(live_room),
        "canonical_live_draft_state_present": bool(session.get("live_draft_room")),
        "return_value_delivery_active": bool(session.get("_solo_persistent_return_value_delivery")),
        "delivery_only": delivery_only_val,
        "observation_completed": delivery_only_observation_completed(session, normalized_token),
        "actionable_eligible": bool(session.get("_solo_persistent_wake_actionable"))
        and not delivery_only_val,
        "action_complete": is_token_action_complete(session, normalized_token),
        "suppress_flag": bool(session.get("_solo_suppress_immediate_session_on_change")),
        "persistent_wake_eligible": bool(session.get("_solo_persistent_wake_early_latch")),
        "widget_key": widget_key,
        "prior_claimed_or_delivered_source": prior_claimed,
        "setup_or_diag_flags": diag_flags,
        "rv_ladder_step": rv3,
    }


def note_process_token_gate(
    session: dict[str, Any],
    *,
    st: Any | None,
    gate_name: str,
    gate_result: str,
    decision: str,
    return_reason: str = "",
    widget_key: str = "",
    live: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled
    except ImportError:
        return
    if not stage1_production_ledger_enabled(st, session):
        return
    extra = dict(context or {})
    extra.update(
        {
            "gate_name": gate_name,
            "gate_result": gate_result,
            "decision": decision,
            "return_reason": return_reason or "",
        }
    )
    note_stage1_event(
        session,
        "production_stage1_process_token_gate",
        st=st,
        room=live if isinstance(live, dict) else None,
        widget_key=widget_key,
        extra=extra,
    )


def note_try_claim_about_to_call(
    session: dict[str, Any],
    *,
    st: Any | None,
    token: str,
    delivery_via: str,
    widget_key: str,
    live: dict[str, Any] | None,
    context: dict[str, Any] | None = None,
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled
    except ImportError:
        return
    if not stage1_production_ledger_enabled(st, session):
        return
    extra = dict(context or {})
    extra.update({"token": str(token or "")[:400], "delivery_via": delivery_via, "widget_key": widget_key})
    note_stage1_event(
        session,
        "production_stage1_try_claim_about_to_call",
        st=st,
        room=live if isinstance(live, dict) else None,
        widget_key=widget_key,
        extra=extra,
    )


def delivery_only_observation_completed(session: dict[str, Any], token: str) -> bool:
    tok = str(token or "").strip()
    if not tok:
        return False
    observed = session.get(SOLO_STAGE1_DELIVERY_ONLY_OBSERVED_KEY) or {}
    return isinstance(observed, dict) and tok in observed


def mark_delivery_only_observation_completed(
    session: dict[str, Any],
    token: str,
    *,
    source: str,
) -> None:
    tok = str(token or "").strip()
    if not tok:
        return
    observed = dict(session.get(SOLO_STAGE1_DELIVERY_ONLY_OBSERVED_KEY) or {})
    observed[tok] = {"source": str(source or ""), "ts": time.time()}
    session[SOLO_STAGE1_DELIVERY_ONLY_OBSERVED_KEY] = observed


def clear_delivery_only_observation(session: dict[str, Any], token: str) -> None:
    tok = str(token or "").strip()
    if not tok:
        return
    observed = session.get(SOLO_STAGE1_DELIVERY_ONLY_OBSERVED_KEY) or {}
    if not isinstance(observed, dict) or tok not in observed:
        return
    updated = dict(observed)
    del updated[tok]
    session[SOLO_STAGE1_DELIVERY_ONLY_OBSERVED_KEY] = updated


def compute_pending_session_delivery_only(
    session: dict[str, Any],
    *,
    pending_token: str,
    pending_raw: Any,
    latch_active: bool,
    inert_token: str = "",
) -> bool:
    """True when the pending session bind is observation-only (must not claim)."""
    tok = str(pending_token or "").strip()
    if not tok or tok == str(inert_token or ""):
        return False
    if pending_raw is None:
        return False
    if not latch_active:
        return False
    if delivery_only_observation_completed(session, tok):
        return False
    try:
        from live_draft_solo_heartbeat import SOLO_COMPONENT_WAKE_SEEN_KEY
    except ImportError:
        SOLO_COMPONENT_WAKE_SEEN_KEY = "_solo_component_wake_seen_token"  # type: ignore[misc,assignment]
    rejected = session.get("_solo_wake_rejected_tokens") or {}
    pending_consumed = tok == str(session.get(SOLO_COMPONENT_WAKE_SEEN_KEY) or "") or (
        isinstance(rejected, dict) and tok in rejected
    )
    if pending_consumed:
        return False
    return True


def _script_run_seq(session: dict[str, Any]) -> int:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _orchestration_extra(
    st: Any | None,
    session: dict[str, Any],
    *,
    token: str = "",
    widget_key: str = "",
    delivery_only: bool | None = None,
    pending_raw: Any = None,
    next_location: str = "",
) -> dict[str, Any]:
    live = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    ss_val = ""
    if st is not None and widget_key:
        try:
            ss_val = repr(st.session_state.get(widget_key))[:300]
        except Exception:
            pass
    return {
        "script_run_seq": _script_run_seq(session),
        "token": str(token or "")[:400],
        "room_id": str((live or {}).get("draft_room_id") or (live or {}).get("draft_id") or ""),
        "delivery_only": delivery_only,
        "pending_session_state_value": ss_val,
        "room_restored": bool(session.get("live_draft_room")),
        "delivery_only_observation_completed": delivery_only_observation_completed(session, token),
        "persistent_wake_actionable": bool(session.get("_solo_persistent_wake_actionable")),
        "next_intended_location": next_location,
        "page_execution_continues": True,
    }


def note_stage1_orchestration_event(
    session: dict[str, Any],
    event: str,
    *,
    st: Any | None = None,
    widget_key: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled
    except ImportError:
        return
    if not stage1_production_ledger_enabled(st, session):
        return
    note_stage1_event(
        session,
        event,
        st=st,
        widget_key=widget_key,
        extra=dict(extra or {}),
    )


def note_delivery_only_observation_completed(
    session: dict[str, Any],
    *,
    st: Any | None,
    token: str,
    widget_key: str,
    source: str,
    deliver_gate_ctx: dict[str, Any] | None = None,
    live: dict[str, Any] | None = None,
) -> None:
    extra = dict(deliver_gate_ctx or {})
    if live and isinstance(live, dict):
        extra.setdefault("room_status", str(live.get("status") or ""))
        extra.setdefault("pick_index", live.get("current_pick_index"))
    extra.update(
        _orchestration_extra(
            st,
            session,
            token=token,
            widget_key=widget_key,
            delivery_only=True,
            next_location="actionable_mount_or_flush",
        )
    )
    extra.update(
        {
            "source": source,
            "raw_received": True,
            "coalesced_value": str(token or "")[:400],
            "actionable_declaration_eligible": True,
        }
    )
    note_stage1_orchestration_event(
        session,
        "production_stage1_delivery_only_observation_completed",
        st=st,
        widget_key=widget_key,
        extra=extra,
    )


def note_actionable_mount_eligibility(
    session: dict[str, Any],
    *,
    st: Any | None,
    widget_key: str,
    pending_token: str,
    pending_raw: Any,
    delivery_only: bool,
    actionable: bool,
    skip_gate: str = "",
    skip_reason: str = "",
) -> None:
    extra = _orchestration_extra(
        st,
        session,
        token=pending_token,
        widget_key=widget_key,
        delivery_only=delivery_only,
        pending_raw=pending_raw,
        next_location="ldr_page_entry_early_persistent",
    )
    extra.update(
        {
            "actionable_mount_eligible": bool(actionable and not delivery_only),
            "delivery_only_mount": bool(delivery_only),
            "skip_gate": skip_gate,
            "skip_reason": skip_reason,
            "token_remains_available": pending_raw is not None and bool(str(pending_token or "").strip()),
            "room_state_restored": bool(session.get("live_draft_room")),
        }
    )
    note_stage1_orchestration_event(
        session,
        "production_stage1_actionable_mount_eligibility",
        st=st,
        widget_key=widget_key,
        extra=extra,
    )


def note_actionable_declaration_about_to_mount(
    session: dict[str, Any],
    *,
    st: Any | None,
    widget_key: str,
    token: str,
    delivery_only: bool,
) -> None:
    extra = _orchestration_extra(
        st,
        session,
        token=token,
        widget_key=widget_key,
        delivery_only=delivery_only,
        next_location="_mount_persistent_wake_micro_controlled",
    )
    note_stage1_orchestration_event(
        session,
        "production_stage1_actionable_declaration_about_to_mount",
        st=st,
        widget_key=widget_key,
        extra=extra,
    )


def note_actionable_declaration_skipped(
    session: dict[str, Any],
    *,
    st: Any | None,
    widget_key: str,
    token: str,
    skip_gate: str,
    skip_reason: str,
    pending_raw: Any = None,
) -> None:
    extra = _orchestration_extra(
        st,
        session,
        token=token,
        widget_key=widget_key,
        pending_raw=pending_raw,
    )
    extra.update(
        {
            "skip_gate": skip_gate,
            "skip_reason": skip_reason,
            "token_remains_available": pending_raw is not None and bool(str(token or "").strip()),
            "room_state_restored": bool(session.get("live_draft_room")),
        }
    )
    note_stage1_orchestration_event(
        session,
        "production_stage1_actionable_declaration_skipped",
        st=st,
        widget_key=widget_key,
        extra=extra,
    )


def note_after_early_persistent_wake(
    session: dict[str, Any],
    *,
    st: Any | None,
    widget_key: str,
    token: str,
    delivery_only: bool,
    actionable: bool,
) -> None:
    extra = _orchestration_extra(
        st,
        session,
        token=token,
        widget_key=widget_key,
        delivery_only=delivery_only,
        next_location="flush_persistent_wake_delivery_or_page_continue",
    )
    extra.update({"actionable": actionable, "delivery_only_mount": delivery_only})
    note_stage1_orchestration_event(
        session,
        "production_stage1_after_early_persistent_wake",
        st=st,
        widget_key=widget_key,
        extra=extra,
    )


def _auto_pick_processing_enabled(session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_persistent_parity_ladder import parity_p6_pick_processing_disabled

        if parity_p6_pick_processing_disabled(session):
            return False
    except ImportError:
        pass
    return True


def build_post_claim_context(
    st: Any | None,
    session: dict[str, Any],
    *,
    deliver_gate_ctx: dict[str, Any],
    live: dict[str, Any] | None,
    token: str,
    widget_key: str,
    claimed: bool,
    reject_code: str,
) -> dict[str, Any]:
    live_room = live if isinstance(live, dict) else {}
    ctx = dict(deliver_gate_ctx or {})
    ctx.update(
        {
            "claim_accepted": bool(claimed),
            "claim_reason": str(reject_code or ""),
            "room_id": str(live_room.get("draft_room_id") or live_room.get("draft_id") or ""),
            "pick_index": live_room.get("current_pick_index"),
            "deadline": ctx.get("current_deadline"),
            "token": str(token or "")[:400],
            "room_status": str(live_room.get("status") or ""),
            "solo_persistent_wake_actionable": bool(session.get("_solo_persistent_wake_actionable")),
            "auto_pick_processing_enabled": _auto_pick_processing_enabled(session),
        }
    )
    return ctx


def note_post_claim_entered(
    session: dict[str, Any],
    *,
    st: Any | None,
    deliver_gate_ctx: dict[str, Any],
    live: dict[str, Any] | None,
    token: str,
    widget_key: str,
    claimed: bool,
    reject_code: str,
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled
    except ImportError:
        return
    if not stage1_production_ledger_enabled(st, session):
        return
    extra = build_post_claim_context(
        st,
        session,
        deliver_gate_ctx=deliver_gate_ctx,
        live=live,
        token=token,
        widget_key=widget_key,
        claimed=claimed,
        reject_code=reject_code,
    )
    note_stage1_event(
        session,
        "production_stage1_post_claim_entered",
        st=st,
        room=live if isinstance(live, dict) else None,
        widget_key=widget_key,
        extra=extra,
    )


def note_post_claim_gate(
    session: dict[str, Any],
    *,
    st: Any | None,
    gate_name: str,
    gate_result: str,
    decision: str,
    return_reason: str = "",
    deliver_gate_ctx: dict[str, Any] | None = None,
    live: dict[str, Any] | None = None,
    widget_key: str = "",
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled
    except ImportError:
        return
    if not stage1_production_ledger_enabled(st, session):
        return
    extra = dict(deliver_gate_ctx or {})
    extra.update(
        {
            "gate_name": gate_name,
            "gate_result": gate_result,
            "decision": decision,
            "return_reason": return_reason or "",
        }
    )
    note_stage1_event(
        session,
        "production_stage1_post_claim_gate",
        st=st,
        room=live if isinstance(live, dict) else None,
        widget_key=widget_key,
        extra=extra,
    )


def note_autopick_about_to_enter(
    session: dict[str, Any],
    *,
    st: Any | None,
    live: dict[str, Any] | None,
    token: str,
    delivery_via: str,
    widget_key: str,
    deliver_gate_ctx: dict[str, Any] | None = None,
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled
    except ImportError:
        return
    if not stage1_production_ledger_enabled(st, session):
        return
    extra = dict(deliver_gate_ctx or {})
    extra.update({"token": str(token or "")[:400], "delivery_via": delivery_via})
    note_stage1_event(
        session,
        "production_stage1_autopick_about_to_enter",
        st=st,
        room=live if isinstance(live, dict) else None,
        widget_key=widget_key,
        extra=extra,
    )


def pre_claim_actionable_eligible(
    st: Any | None,
    session: dict[str, Any],
    deliver_gate_ctx: dict[str, Any],
) -> tuple[bool, str]:
    """Observation-only paths must not consume the sole actionable expiration claim."""
    delivery_via = str(
        deliver_gate_ctx.get("canonical_source")
        or deliver_gate_ctx.get("source")
        or ""
    ).strip()
    try:
        from live_draft_stage1_expire_audit import note_callback_source_boundary

        note_callback_source_boundary(
            st,
            session,
            source=delivery_via,
            delivery_only=bool(deliver_gate_ctx.get("delivery_only")),
            token=str(deliver_gate_ctx.get("normalized_token") or ""),
            widget_key=str(deliver_gate_ctx.get("widget_key") or ""),
            call_site="pre_claim_actionable_eligible",
            callback_function="_production_deliver_callback",
            module_name=__name__,
        )
    except ImportError:
        pass
    if bool(deliver_gate_ctx.get("delivery_only")):
        return False, "delivery_only_observation"
    if delivery_via == "return_value_session_bind" and bool(
        deliver_gate_ctx.get("return_value_delivery_active")
    ):
        if bool(deliver_gate_ctx.get("persistent_wake_eligible")) or session.get(
            "_solo_persistent_wake_early_latch"
        ):
            if not _auto_pick_processing_enabled(session):
                return False, "diagnostic_pick_processing_disabled"
            return True, ""
    if not session.get("_solo_persistent_wake_actionable"):
        return False, "not_actionable"
    if not _auto_pick_processing_enabled(session):
        return False, "diagnostic_pick_processing_disabled"
    return True, ""


def note_post_action_duplicate_suppressed(
    session: dict[str, Any],
    *,
    st: Any | None,
    token: str,
    widget_key: str,
    source: str,
    live: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled
        from live_draft_stage1_expire_audit import get_token_action_complete
    except ImportError:
        return
    if not stage1_production_ledger_enabled(st, session):
        return
    extra = dict(context or {})
    extra.update(
        {
            "token": str(token or "")[:400],
            "source": source,
            "action_complete": get_token_action_complete(session, token),
        }
    )
    note_stage1_event(
        session,
        "production_stage1_post_action_duplicate_suppressed",
        st=st,
        room=live if isinstance(live, dict) else None,
        widget_key=widget_key,
        extra=extra,
    )


def note_production_source_boundary(
    session: dict[str, Any],
    *,
    st: Any | None,
    widget_key: str,
    context: dict[str, Any] | None = None,
    live: dict[str, Any] | None = None,
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled
    except ImportError:
        return
    if not stage1_production_ledger_enabled(st, session):
        return
    note_stage1_event(
        session,
        "production_stage1_production_source_boundary",
        st=st,
        room=live if isinstance(live, dict) else None,
        widget_key=widget_key,
        extra=dict(context or {}),
    )


def note_token_action_complete_marker(
    session: dict[str, Any],
    *,
    st: Any | None,
    marker: dict[str, Any],
    widget_key: str = "",
    live: dict[str, Any] | None = None,
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled
    except ImportError:
        return
    if not stage1_production_ledger_enabled(st, session):
        return
    note_stage1_event(
        session,
        "production_stage1_token_action_complete",
        st=st,
        room=live if isinstance(live, dict) else None,
        widget_key=widget_key,
        extra=dict(marker or {}),
    )


def note_try_claim_result(
    session: dict[str, Any],
    *,
    st: Any | None,
    token: str,
    delivery_via: str,
    accepted: bool,
    reject_code: str,
    widget_key: str,
    live: dict[str, Any] | None,
    claim_call_site: str = "_production_deliver_callback",
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled
    except ImportError:
        return
    if not stage1_production_ledger_enabled(st, session):
        return
    note_stage1_event(
        session,
        "production_stage1_token_claim_result",
        st=st,
        room=live if isinstance(live, dict) else None,
        widget_key=widget_key,
        extra={
            "token": str(token or "")[:400],
            "source": delivery_via,
            "delivery_via": delivery_via,
            "accepted": accepted,
            "reject_code": reject_code or "",
            "claim_call_site": claim_call_site,
        },
    )


def classify_claim_diagnostic(
    session: dict[str, Any],
    *,
    post_send_seq: int | None = None,
) -> str:
    """C1–C8 from merged ledger rows after post-send process entry."""
    rows = list(session.get("_solo_stage1_production_ledger_merged") or [])
    if post_send_seq is not None:
        rows = [r for r in rows if int(r.get("script_run_seq") or 0) >= post_send_seq]
    events = [str(r.get("event") or "") for r in rows if isinstance(r, dict)]
    gates = [r for r in rows if isinstance(r, dict) and r.get("event") == "production_stage1_process_token_gate"]
    about = any(e == "production_stage1_try_claim_about_to_call" for e in events)
    result_rows = [r for r in rows if r.get("event") == "production_stage1_token_claim_result"]
    if about and not result_rows:
        return "C2"
    if about and result_rows:
        rej = str(result_rows[-1].get("reject_code") or "")
        acc = bool(result_rows[-1].get("accepted"))
        if acc:
            return "C8" if rej else "C8"
        if rej == "already_consumed":
            return "C7"
        return "C8"
    if not about:
        for g in reversed(gates):
            gn = str(g.get("gate_name") or "")
            dec = str(g.get("decision") or "")
            if dec != "return":
                continue
            gr = str(g.get("gate_result") or "")
            rr = str(g.get("return_reason") or gr)
            if "coerce" in gn or gr == "empty_raw":
                return "C4"
            if "wrong_room" in rr or "wrong_pick" in rr or "stale_deadline" in rr:
                return "C5"
            if "delivery_only" in gn or "suppress" in gn:
                return "C6"
            if "already" in rr or "consumed" in rr:
                return "C7"
            if gn == "expire_token_matches_state":
                return "C5"
            return "C1"
        return "C3"
    return "C1"
