"""Observability-only Stage 1 boundary canaries (solo_component_diag; no bind behavior changes)."""

from __future__ import annotations

import json
import time
from typing import Any

from live_draft_stage1_production_ledger import (
    bump_stage1_script_run_seq,
    ensure_stage1_run_id,
    note_stage1_event,
    stage1_production_ledger_enabled,
)
from live_draft_stage1_receipt_levels import PRODUCTION_WIDGET_KEY

GLOBAL_CANARY_SEQ_KEY = "_solo_stage1_global_canary_seq"
PRODUCTION_COUNTDOWN_COMPONENT_NAME = "solo_countdown_wake"


def stage1_boundary_canaries_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    return stage1_production_ledger_enabled(st, session)


def _deployment_sha(session: dict[str, Any]) -> str:
    sha = str(session.get("_solo_stage1_deployment_sha") or "").strip()
    if sha:
        return sha[:7]
    try:
        from suite_deploy_marker import resolve_git_commit_short

        return str(resolve_git_commit_short() or "")[:7]
    except ImportError:
        return ""


def _safe_streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and getattr(ctx, "session_id", None):
            sid = str(ctx.session_id)
            if len(sid) > 16:
                return sid[:8] + "…" + sid[-4:]
            return sid
    except Exception:
        pass
    return ""


def _widget_session_state_repr(st: Any | None, widget_key: str) -> str:
    if st is None or not widget_key:
        return ""
    try:
        if widget_key in st.session_state:
            return repr(st.session_state.get(widget_key))[:400]
    except Exception:
        pass
    return "missing"


def _room_and_token(session: dict[str, Any], room: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        live = {}
    tok = str(
        session.get("_solo_persistent_wake_last_token")
        or session.get("_solo_parity_expected_token")
        or ""
    )
    return live, tok


def _emit(
    session: dict[str, Any],
    event: str,
    *,
    st: Any | None,
    room: dict[str, Any] | None,
    widget_key: str,
    active_page: str,
    script_run_seq: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    live, expected_token = _room_and_token(session, room)
    rid = str(live.get("draft_room_id") or live.get("draft_id") or "").strip().upper()
    pick = live.get("current_pick_index")
    deadline = None
    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        if live:
            deadline = live_draft_timer_deadline(live)
    except ImportError:
        pass
    row: dict[str, Any] = {
        "event": event,
        "ts": time.time(),
        "script_run_seq": script_run_seq,
        "global_canary_seq": int(session.get(GLOBAL_CANARY_SEQ_KEY) or 0),
        "run_id": ensure_stage1_run_id(session),
        "streamlit_session_id_safe": _safe_streamlit_session_id(),
        "deployment_sha": _deployment_sha(session),
        "active_page": str(active_page or ""),
        "room_id": rid,
        "pick_index": pick,
        "deadline": deadline,
        "expected_token": expected_token[:400],
        "widget_key": str(widget_key or PRODUCTION_WIDGET_KEY),
        "session_state_widget_value": _widget_session_state_repr(st, widget_key or PRODUCTION_WIDGET_KEY),
    }
    if extra:
        row.update(extra)
    try:
        print(f"SOLO_STAGE1_BOUNDARY_CANARY|{json.dumps(row, default=str)}", flush=True)
    except Exception:
        pass
    note_stage1_event(
        session,
        event,
        st=st,
        room=live if live else None,
        widget_key=widget_key or PRODUCTION_WIDGET_KEY,
        extra={k: v for k, v in row.items() if k not in ("event", "ts")},
    )
    return row


def emit_production_global_script_run_canary(
    st: Any,
    session: dict[str, Any],
    *,
    active_page: str,
    widget_key: str = PRODUCTION_WIDGET_KEY,
) -> dict[str, Any]:
    if not stage1_boundary_canaries_enabled(st, session):
        return {}
    seq = bump_stage1_script_run_seq(session)
    gseq = int(session.get(GLOBAL_CANARY_SEQ_KEY) or 0) + 1
    session[GLOBAL_CANARY_SEQ_KEY] = gseq
    return _emit(
        session,
        "production_global_script_run_canary",
        st=st,
        room=session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None,
        widget_key=widget_key,
        active_page=active_page,
        script_run_seq=seq,
        extra={"global_canary_seq": gseq},
    )


def emit_production_live_draft_branch_canary(
    st: Any,
    session: dict[str, Any],
    *,
    active_page: str,
    widget_key: str = PRODUCTION_WIDGET_KEY,
) -> dict[str, Any]:
    if not stage1_boundary_canaries_enabled(st, session):
        return {}
    seq = int(session.get("_solo_stage1_script_run_seq") or 0)
    return _emit(
        session,
        "production_live_draft_branch_canary",
        st=st,
        room=session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None,
        widget_key=widget_key,
        active_page=active_page,
        script_run_seq=seq,
    )


def emit_production_countdown_declaration_pre(
    st: Any,
    session: dict[str, Any],
    *,
    room: dict[str, Any],
    widget_key: str,
    expected_token: str,
    declaration_eligibility: dict[str, Any] | None = None,
    iframe_instance: str = "",
) -> dict[str, Any]:
    if not stage1_boundary_canaries_enabled(st, session):
        return {}
    seq = int(session.get("_solo_stage1_script_run_seq") or 0)
    return _emit(
        session,
        "production_countdown_declaration_pre",
        st=st,
        room=room,
        widget_key=widget_key,
        active_page=str(session.get("active_page") or ""),
        script_run_seq=seq,
        extra={
            "expected_token": str(expected_token or "")[:400],
            "component_key": PRODUCTION_COUNTDOWN_COMPONENT_NAME,
            "direct_return_value": "",
            "declaration_eligibility": declaration_eligibility or {},
            "iframe_instance_observable": str(iframe_instance or "")[:120],
        },
    )


def emit_production_countdown_declaration_post(
    st: Any,
    session: dict[str, Any],
    *,
    room: dict[str, Any],
    widget_key: str,
    expected_token: str,
    direct_return: Any,
    declaration_eligibility: dict[str, Any] | None = None,
    iframe_instance: str = "",
) -> dict[str, Any]:
    if not stage1_boundary_canaries_enabled(st, session):
        return {}
    seq = int(session.get("_solo_stage1_script_run_seq") or 0)
    ss_val = _widget_session_state_repr(st, widget_key)
    return _emit(
        session,
        "production_countdown_declaration_post",
        st=st,
        room=room,
        widget_key=widget_key,
        active_page=str(session.get("active_page") or ""),
        script_run_seq=seq,
        extra={
            "expected_token": str(expected_token or "")[:400],
            "component_key": PRODUCTION_COUNTDOWN_COMPONENT_NAME,
            "direct_return_value": repr(direct_return)[:400] if direct_return is not None else "",
            "same_key_session_state_value": ss_val,
            "declaration_eligibility": declaration_eligibility or {},
            "iframe_instance_observable": str(iframe_instance or "")[:120],
        },
    )
