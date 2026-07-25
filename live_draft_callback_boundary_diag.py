"""Pre-script callback boundary ledger — survives live_draft_room loss from session_state."""

from __future__ import annotations

import base64
import inspect
import json
import time
import traceback
from typing import Any, Callable, TypeVar

LIVE_DRAFT_ROOM_KEY = "live_draft_room"
LIVE_DRAFT_STATE_KEY = "live_draft_state"
LIVE_DRAFT_PAGE_BLOCK = "Live Draft Room"

# Process-wide append-only store keyed by Streamlit session_id (not st.session_state).
_BOUNDARY_LEDGERS: dict[str, list[dict[str, Any]]] = {}
_BOUNDARY_SEQ: dict[str, int] = {}
_MAX_ROWS_PER_SESSION = 500


def _ledger_store() -> dict[str, list[dict[str, Any]]]:
    try:
        import streamlit as st

        @st.cache_resource
        def _cached_boundary_store() -> dict[str, list[dict[str, Any]]]:
            return _BOUNDARY_LEDGERS

        store = _cached_boundary_store()
        if store is not _BOUNDARY_LEDGERS:
            for sid, rows in _BOUNDARY_LEDGERS.items():
                if sid not in store:
                    store[sid] = rows
                else:
                    store[sid].extend(rows)
                    store[sid] = store[sid][-_MAX_ROWS_PER_SESSION:]
        return store
    except Exception:
        return _BOUNDARY_LEDGERS


def boundary_diag_enabled(session: dict[str, Any]) -> bool:
    if session.get("_live_draft_callback_boundary_force"):
        return True
    if session.get("_solo_delivery_diag_enabled"):
        return True
    if session.get("_solo_bridge_transition_enabled"):
        return True
    return False


def enable_callback_boundary_diag(session: dict[str, Any]) -> None:
    session["_live_draft_callback_boundary_force"] = True


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")
    except Exception:
        return ""


def _room_summary(room: Any) -> tuple[str, str, bool]:
    if not isinstance(room, dict):
        return "", "", False
    rid = str(room.get("draft_room_id") or room.get("draft_id") or "").strip()
    status = str(room.get("status") or "").strip().lower()
    present = bool(rid or room.get("draft_board") is not None)
    return rid, status, present


def _canonical_blob(session: dict[str, Any]) -> dict[str, Any] | None:
    blob = session.get(LIVE_DRAFT_STATE_KEY)
    if isinstance(blob, dict) and blob.get("draft_room_id"):
        return blob
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(LIVE_DRAFT_PAGE_BLOCK)
        if isinstance(block, dict):
            legacy = block.get(LIVE_DRAFT_ROOM_KEY)
            if isinstance(legacy, dict) and legacy.get("draft_room_id"):
                return legacy
    return None


def _page_filter_room(session: dict[str, Any]) -> dict[str, Any] | None:
    pf = session.get("page_filter_state")
    if not isinstance(pf, dict):
        return None
    block = pf.get(LIVE_DRAFT_PAGE_BLOCK)
    if not isinstance(block, dict):
        return None
    room = block.get(LIVE_DRAFT_ROOM_KEY)
    return room if isinstance(room, dict) else None


def _auth_fields(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "auth_enabled": False,
        "authenticated": False,
        "auth_email": "",
        "auth_user_id": "",
    }
    try:
        from suite_auth import AUTH_USER_ID_KEY, is_auth_enabled, is_authenticated

        out["auth_enabled"] = bool(is_auth_enabled())
        out["authenticated"] = bool(is_authenticated(session))
        out["auth_user_id"] = str(session.get(AUTH_USER_ID_KEY) or "")[:40]
        out["auth_email"] = str(session.get("_suite_auth_user_email") or "")[:80]
    except ImportError:
        pass
    return out


def _restore_fields(session: dict[str, Any]) -> dict[str, Any]:
    blocked = str(session.get("_live_draft_restore_blocked_reason") or "")
    blob = _canonical_blob(session)
    allowed = True
    reason = ""
    if blob:
        try:
            from live_draft_state import live_draft_restore_allowed

            allowed, reason = live_draft_restore_allowed(session, blob, source="callback_boundary")
        except ImportError:
            allowed, reason = True, "live_draft_restore_allowed_missing"
    return {
        "restore_allowed": allowed,
        "restore_block_reason": reason,
        "restore_blocked_reason": blocked,
    }


def snapshot_room_context(session: dict[str, Any]) -> dict[str, Any]:
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    rid, status, present = _room_summary(room)
    canon = _canonical_blob(session)
    c_rid, c_status, _ = _room_summary(canon)
    pf_room = _page_filter_room(session)
    pf_rid, pf_status, pf_present = _room_summary(pf_room)
    key_in_session = LIVE_DRAFT_ROOM_KEY in session
    return {
        "live_draft_room_present": present,
        "live_draft_room_key_in_session": key_in_session,
        "live_draft_room_id": rid,
        "live_draft_room_status": status,
        "live_draft_state_room_id": c_rid,
        "live_draft_state_status": c_status,
        "page_filter_room_present": pf_present,
        "page_filter_room_id": pf_rid,
        "page_filter_room_status": pf_status,
        "active_page": str(session.get("active_page") or ""),
        "post_create_open": bool(session.get("_live_draft_post_create_open")),
        **_auth_fields(session),
        **_restore_fields(session),
    }


def get_boundary_ledger(session_id: str) -> list[dict[str, Any]]:
    if not session_id:
        return []
    store = _ledger_store()
    return list(store.get(session_id) or [])


def analyze_first_room_disappearance(session_id: str) -> dict[str, Any] | None:
    rows = get_boundary_ledger(session_id)
    prev: dict[str, Any] | None = None
    for row in rows:
        if (
            prev
            and prev.get("live_draft_room_present")
            and not row.get("live_draft_room_present")
        ):
            return {"prior": prev, "first_absent": row}
        prev = row
    return None


def record_callback_boundary(
    session: dict[str, Any],
    point: str,
    *,
    st: Any = None,
    token: str = "",
    function: str = "",
    helper: str = "",
    phase: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    if not boundary_diag_enabled(session):
        return
    sid = _streamlit_session_id()
    if not sid:
        sid = str(session.get("_solo_bridge_transition_streamlit_session_id") or "unknown")
    store = _ledger_store()
    seq = _BOUNDARY_SEQ.get(sid, 0) + 1
    _BOUNDARY_SEQ[sid] = seq
    if not function:
        function = inspect.stack()[1].function
    stack_tail = [line.strip() for line in traceback.format_stack(limit=8)[:-2]][-5:]
    row: dict[str, Any] = {
        "ts": time.time(),
        "seq": seq,
        "streamlit_session_id": sid,
        "point": point,
        "phase": phase,
        "helper": helper,
        "function": function,
        "callback_token": str(token or "")[:400],
        "stack_tail": stack_tail,
        **snapshot_room_context(session),
    }
    if extra:
        row.update(extra)
    ledger = list(store.get(sid) or [])
    ledger.append(row)
    store[sid] = ledger[-_MAX_ROWS_PER_SESSION:]


def record_script_beginning(session: dict[str, Any], *, st: Any = None) -> None:
    record_callback_boundary(
        session,
        "streamlit_app_script_beginning",
        st=st,
        phase="script_begin",
        function="streamlit_app",
    )


T = TypeVar("T")


def trace_helper(
    session: dict[str, Any],
    helper_name: str,
    fn: Callable[..., T],
    *args: Any,
    st: Any = None,
    callback_token: str = "",
    **kwargs: Any,
) -> T:
    record_callback_boundary(
        session,
        f"before_helper:{helper_name}",
        st=st,
        token=callback_token,
        helper=helper_name,
        phase="before_helper",
        function=fn.__name__,
    )
    try:
        return fn(*args, **kwargs)
    finally:
        record_callback_boundary(
            session,
            f"after_helper:{helper_name}",
            st=st,
            token=callback_token,
            helper=helper_name,
            phase="after_helper",
            function=fn.__name__,
        )


def _b64_json(payload: Any) -> str:
    return base64.b64encode(json.dumps(payload, default=str).encode("utf-8")).decode("ascii")


def render_callback_boundary_probe(st: Any, session: dict[str, Any]) -> None:
    if not boundary_diag_enabled(session):
        return
    sid = _streamlit_session_id() or str(session.get("_solo_bridge_transition_streamlit_session_id") or "")
    rows = get_boundary_ledger(sid)[-120:]
    analysis = analyze_first_room_disappearance(sid)
    payload = {
        "streamlit_session_id": sid,
        "rows": rows,
        "first_room_disappearance": analysis,
        "row_count": len(rows),
    }
    b64 = _b64_json(payload)
    st.markdown(
        f'<div id="solo-callback-boundary-diag" '
        f'data-present="1" '
        f'data-callback-boundary-b64="{b64}" '
        f'data-streamlit-session-id="{sid.replace(chr(34), chr(39))}" '
        f'></div>',
        unsafe_allow_html=True,
    )


def callback_boundary_b64_for_session(session: dict[str, Any]) -> str:
    sid = _streamlit_session_id() or str(session.get("_solo_bridge_transition_streamlit_session_id") or "")
    payload = {
        "streamlit_session_id": sid,
        "rows": get_boundary_ledger(sid)[-120:],
        "first_room_disappearance": analyze_first_room_disappearance(sid),
    }
    return _b64_json(payload)
