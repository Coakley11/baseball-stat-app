"""Diagnostic: is live_draft_room widget-owned vs normal session state? (query-gated)."""

from __future__ import annotations

import base64
import inspect
import json
import time
import traceback
from typing import Any

from live_draft_callback_boundary_diag import _ledger_store as _shared_ledger_store

TARGET_KEY = "live_draft_room"
LIVE_DRAFT_STATE_KEY = "live_draft_state"
LIVE_DRAFT_PAGE_BLOCK = "Live Draft Room"
LEDGER_SUFFIX = "_key_ownership"
MAX_ROWS = 400


def _ledger_key(session_id: str) -> str:
    return f"{session_id}{LEDGER_SUFFIX}"


def diag_enabled(session: dict[str, Any]) -> bool:
    if session.get("_live_draft_key_ownership_force"):
        return True
    if session.get("_solo_delivery_diag_enabled"):
        return True
    if session.get("_solo_bridge_transition_enabled"):
        return True
    return False


def enable_key_ownership_diag(session: dict[str, Any]) -> None:
    session["_live_draft_key_ownership_force"] = True


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")
    except Exception:
        return ""


def _script_run_label(session: dict[str, Any]) -> str:
    try:
        from app_page_generation import current_script_run_id

        rid = current_script_run_id(session)
        if rid:
            return str(rid)
    except ImportError:
        pass
    return str(session.get("_live_draft_room_mutation_script_run") or "")


def _room_id_status(room: Any) -> tuple[str, str]:
    if not isinstance(room, dict):
        return "", ""
    return (
        str(room.get("draft_room_id") or room.get("draft_id") or "").strip(),
        str(room.get("status") or "").strip().lower(),
    )


def _canonical_and_pf(session: dict[str, Any]) -> dict[str, Any]:
    canon = session.get(LIVE_DRAFT_STATE_KEY)
    c_id, c_st = _room_id_status(canon if isinstance(canon, dict) else None)
    pf = session.get("page_filter_state")
    pf_room = None
    if isinstance(pf, dict):
        block = pf.get(LIVE_DRAFT_PAGE_BLOCK)
        if isinstance(block, dict):
            pf_room = block.get(TARGET_KEY)
    pf_id, pf_st = _room_id_status(pf_room)
    return {
        "live_draft_state_room_id": c_id,
        "live_draft_state_status": c_st,
        "page_filter_room_id": pf_id,
        "page_filter_room_status": pf_st,
    }


def _widget_probe(session: dict[str, Any], user_key: str) -> dict[str, Any]:
    """Inspect Streamlit runtime widget registration for user_key."""
    out: dict[str, Any] = {
        "widget_registered_for_key": False,
        "widget_ids_for_key": [],
        "widget_states_matching_key": [],
        "is_new_state_value": None,
        "filtered_state_has_key": None,
        "internal_widget_state_keys_sample": [],
    }
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if not ctx or not getattr(ctx, "session_state", None):
            return out
        ss = ctx.session_state
        try:
            out["is_new_state_value"] = bool(ss.is_new_state_value(user_key))
        except Exception as exc:
            out["is_new_state_value_error"] = f"{type(exc).__name__}:{exc}"
        try:
            filt = ss.filtered_state
            out["filtered_state_has_key"] = user_key in filt if isinstance(filt, dict) else None
        except Exception:
            pass
        try:
            widgets = ss.get_widget_states() or []
            matches: list[dict[str, Any]] = []
            exact_suffix = f"-{user_key}"
            for w in widgets:
                wid = str(getattr(w, "id", "") or "")
                exact = wid == user_key or wid.endswith(exact_suffix)
                if exact:
                    out["widget_registered_for_key"] = True
                    out["widget_ids_for_key"].append(wid)
                    matches.append(
                        {
                            "id": wid,
                            "exact_user_key_match": True,
                            "value_type": type(getattr(w, "value", None)).__name__,
                            "value_repr": repr(getattr(w, "value", None))[:200],
                        }
                    )
                elif user_key in wid:
                    matches.append(
                        {
                            "id": wid,
                            "exact_user_key_match": False,
                            "substring_only": True,
                        }
                    )
            out["widget_states_matching_key"] = matches[:12]
            out["widget_exact_match_for_user_key"] = bool(
                any(m.get("exact_user_key_match") for m in matches if isinstance(m, dict))
            )
        except Exception as exc:
            out["widget_states_error"] = f"{type(exc).__name__}:{exc}"
        try:
            from streamlit.runtime.state.session_state import STREAMLIT_INTERNAL_KEY_PREFIX

            internal = [
                k
                for k in session.keys()
                if isinstance(k, str) and k.startswith(STREAMLIT_INTERNAL_KEY_PREFIX)
            ]
            out["internal_streamlit_key_count"] = len(internal)
        except Exception:
            pass
    except Exception as exc:
        out["probe_error"] = f"{type(exc).__name__}:{exc}"
    return out


def _repo_widget_key_audit() -> dict[str, Any]:
    """Static audit snapshot (compile-time); no live_draft_room Streamlit widget key in tree."""
    return {
        "repo_key_live_draft_room_widget_literal": False,
        "repo_note": (
            "grep key='live_draft_room' / key=\"live_draft_room\" finds no st.widget key=; "
            "session_key='live_draft_room' is diagnostics-only in record_start_path_diagnostics"
        ),
        "nearby_widget_keys_live_draft_prefix": [
            "live_draft_board",
            "live_draft_start_btn",
            "live_draft_timer",
            "solo_countdown_wake_solo_persistent",
        ],
    }


def snapshot_key_ownership(session: dict[str, Any], *, checkpoint: str) -> dict[str, Any]:
    room = session.get(TARGET_KEY)
    rid, status = _room_id_status(room)
    widget = _widget_probe(session, TARGET_KEY)
    auth: dict[str, Any] = {"auth_enabled": False, "authenticated": False}
    try:
        from suite_auth import is_auth_enabled, is_authenticated

        auth["auth_enabled"] = bool(is_auth_enabled())
        auth["authenticated"] = bool(is_authenticated(session))
    except ImportError:
        pass
    return {
        "checkpoint": checkpoint,
        "ts": time.time(),
        "streamlit_session_id": _streamlit_session_id(),
        "script_run": _script_run_label(session),
        "session_key_exists": TARGET_KEY in session,
        "session_value_is_dict": isinstance(room, dict),
        "live_draft_room_present": isinstance(room, dict) and bool(rid or room.get("draft_board") is not None),
        "live_draft_room_id": rid,
        "live_draft_room_status": status,
        **_canonical_and_pf(session),
        **widget,
        **auth,
        "active_page": str(session.get("active_page") or ""),
        "post_create_open": bool(session.get("_live_draft_post_create_open")),
    }


def record_key_ownership(
    session: dict[str, Any],
    checkpoint: str,
    *,
    st: Any = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not diag_enabled(session):
        return {}
    sid = _streamlit_session_id() or str(session.get("_solo_bridge_transition_streamlit_session_id") or "unknown")
    row = snapshot_key_ownership(session, checkpoint=checkpoint)
    if extra:
        row.update(extra)
    fn = inspect.stack()[1].function if len(inspect.stack()) > 1 else ""
    row["caller_function"] = fn
    row["stack_tail"] = [line.strip() for line in traceback.format_stack(limit=6)[:-2]][-4:]
    store = _shared_ledger_store()
    lk = _ledger_key(sid)
    ledger = list(store.get(lk) or [])
    row["seq"] = len(ledger) + 1
    ledger.append(row)
    store[lk] = ledger[-MAX_ROWS:]
    return row


def record_script_beginning_ownership(session: dict[str, Any], *, st: Any = None) -> None:
    record_key_ownership(session, "script_beginning", st=st)


def record_active_room_run_end(session: dict[str, Any], *, st: Any = None, source: str = "") -> None:
    room = session.get(TARGET_KEY)
    rid, _ = _room_id_status(room)
    if not rid:
        return
    record_key_ownership(
        session,
        "active_room_script_run_end",
        st=st,
        extra={"source": source, "repo_widget_audit": _repo_widget_key_audit()},
    )


def get_ownership_ledger(session_id: str) -> list[dict[str, Any]]:
    store = _shared_ledger_store()
    return list(store.get(_ledger_key(session_id)) or [])


def analyze_run_boundary_loss(session_id: str) -> dict[str, Any] | None:
    rows = get_ownership_ledger(session_id)
    last_end: dict[str, Any] | None = None
    for row in rows:
        cp = str(row.get("checkpoint") or "")
        if cp == "active_room_script_run_end" and row.get("live_draft_room_present"):
            last_end = row
        if cp == "script_beginning" and last_end and not row.get("live_draft_room_present"):
            return {"last_present_run_end": last_end, "first_absent_script_begin": row}
    return None


def first_widget_registration_for_key(session_id: str) -> dict[str, Any] | None:
    for row in get_ownership_ledger(session_id):
        if row.get("widget_exact_match_for_user_key"):
            return row
    return None


def _b64_json(payload: Any) -> str:
    return base64.b64encode(json.dumps(payload, default=str).encode("utf-8")).decode("ascii")


def ownership_payload_for_session(session: dict[str, Any]) -> dict[str, Any]:
    sid = _streamlit_session_id() or str(session.get("_solo_bridge_transition_streamlit_session_id") or "")
    rows = get_ownership_ledger(sid)
    return {
        "streamlit_session_id": sid,
        "repo_widget_audit": _repo_widget_key_audit(),
        "rows": rows[-120:],
        "run_boundary_loss": analyze_run_boundary_loss(sid),
        "first_widget_registration": first_widget_registration_for_key(sid),
    }


def render_key_ownership_probe(st: Any, session: dict[str, Any]) -> None:
    if not diag_enabled(session):
        return
    payload = ownership_payload_for_session(session)
    b64 = _b64_json(payload)
    st.markdown(
        f'<div id="solo-key-ownership-diag" '
        f'data-present="1" '
        f'data-key-ownership-b64="{b64}" '
        f'></div>',
        unsafe_allow_html=True,
    )


def key_ownership_b64_for_session(session: dict[str, Any]) -> str:
    return _b64_json(ownership_payload_for_session(session))
