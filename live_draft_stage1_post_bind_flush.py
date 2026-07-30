"""Post-bind orchestration: delivery-only observation then actionable flush (P8 transport)."""

from __future__ import annotations

from typing import Any

SOLO_POST_BIND_FLUSH_DISPATCHED_KEY = "_solo_stage1_post_bind_flush_dispatched_token"


def post_bind_flush_already_dispatched(session: dict[str, Any], token: str) -> bool:
    tok = str(token or "").strip()
    if not tok:
        return False
    return str(session.get(SOLO_POST_BIND_FLUSH_DISPATCHED_KEY) or "").strip() == tok


def mark_post_bind_flush_dispatched(session: dict[str, Any], token: str) -> None:
    tok = str(token or "").strip()
    if tok:
        session[SOLO_POST_BIND_FLUSH_DISPATCHED_KEY] = tok


def widget_bound_token(
    *,
    raw_component_value: Any,
    session_state_value: Any,
) -> str:
    from live_draft_solo_persistent_wake import SOLO_INERT_EXPIRE_TOKEN
    from live_draft_solo_heartbeat import _coerce_wake_token

    bound = _coerce_wake_token(raw_component_value) or _coerce_wake_token(session_state_value)
    if not bound or bound == SOLO_INERT_EXPIRE_TOKEN:
        return ""
    return str(bound)


def bound_token_matches_mount_expire(bound_token: str, mount_expire_token: str) -> bool:
    from live_draft_solo_heartbeat import _coerce_wake_token

    bound = _coerce_wake_token(bound_token)
    expected = _coerce_wake_token(mount_expire_token)
    if not bound:
        return False
    if not expected:
        return True
    return bound == expected


def complete_delivery_only_observation_and_actionable_flush(
    st: Any,
    session: dict[str, Any],
    *,
    bound_token: str,
    mount_expire_token: str,
    widget_key: str,
    production_room: dict[str, Any] | None,
    raw_component_value: Any = None,
) -> bool:
    """
    After Streamlit binds the exact expiration token on the widget:
    observation (zero claims) → mark completed → actionable flush on same rerun.
    """
    if not bound_token_matches_mount_expire(bound_token, mount_expire_token):
        return False
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

    if not delivery_only_observation_completed(session, bound_token):
        mark_delivery_only_observation_completed(
            session,
            bound_token,
            source="return_value_session_bind",
        )
        try:
            from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

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
                    "bound_token": bound_token[:400],
                    "mount_expire_token": str(mount_expire_token or "")[:400],
                    "raw_component_return": repr(raw_component_value)[:200],
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
    return True
