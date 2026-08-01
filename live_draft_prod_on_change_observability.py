"""Durable Stage 1 callback observability (_prod_on_change / Case A control). Notification only."""

from __future__ import annotations

import inspect
import time
import uuid
from typing import Any

DECLARATION_INVOCATION_SESSION_KEY = "_solo_stage1_declaration_invocation_by_widget"
LAST_DECLARATION_ORDER_KEY = "_solo_stage1_declaration_order_counter"

PROD_ON_CHANGE_ENTERED = "production_stage1_prod_on_change_entered"
PROD_ON_CHANGE_EXITED = "production_stage1_prod_on_change_exited"
CONTROL_ON_CHANGE_ENTERED = "production_stage1_control_on_change_entered"
CONTROL_ON_CHANGE_EXITED = "production_stage1_control_on_change_exited"
CALLBACK_REGISTRATION = "production_stage1_callback_registration"


def _obs_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        return bool(stage1_production_ledger_enabled(st, session))
    except ImportError:
        return False


def new_callback_invocation_id() -> str:
    return uuid.uuid4().hex[:12]


def new_declaration_invocation_id() -> str:
    return uuid.uuid4().hex[:12]


def _deployment_sha(session: dict[str, Any]) -> str:
    sha = str(session.get("_solo_stage1_deployment_sha") or "").strip()
    if sha:
        return sha[:7]
    try:
        from suite_deploy_marker import resolve_git_commit_short

        return str(resolve_git_commit_short() or "")[:7]
    except ImportError:
        return ""


def _script_run_seq(session: dict[str, Any]) -> int:
    return int(session.get("_solo_stage1_script_run_seq") or 0)


def _diagnostic_run_id(session: dict[str, Any], room: dict[str, Any] | None) -> str:
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if isinstance(live, dict):
        rid = str(live.get("draft_room_id") or live.get("draft_id") or "").strip().upper()
        if rid:
            return rid
    try:
        from live_draft_stage1_production_ledger import ensure_stage1_run_id

        return str(ensure_stage1_run_id(session) or "")[:16]
    except ImportError:
        return ""


def _active_page(session: dict[str, Any]) -> str:
    return str(session.get("active_page") or "")


def _room_snapshot(room: dict[str, Any] | None, session: dict[str, Any]) -> dict[str, Any]:
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        live = {}
    deadline = None
    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        if live:
            deadline = live_draft_timer_deadline(live)
    except ImportError:
        pass
    tok = str(
        session.get("_solo_persistent_wake_last_token")
        or session.get("_solo_parity_expected_token")
        or ""
    )
    return {
        "room_id": str(live.get("draft_room_id") or live.get("draft_id") or "").strip().upper(),
        "pick_index": live.get("current_pick_index"),
        "deadline": deadline,
        "expected_token": tok[:400],
        "room_status": str(live.get("status") or ""),
    }


def safe_session_state_inventory(st: Any | None, user_key: str) -> dict[str, Any]:
    """Safe key inventory for widget binding diagnosis (no secrets)."""
    out: dict[str, Any] = {"user_key": user_key, "related_keys": []}
    if st is None:
        return out
    try:
        keys = list(getattr(st.session_state, "keys", lambda: [])())
    except Exception:
        return out
    needles = (
        "solo_countdown",
        "persistent",
        "solo_persistent",
        "countdown_wake",
        user_key,
    )
    suffix = user_key.split("_")[-1] if user_key else ""
    for k in keys:
        ks = str(k)
        kl = ks.lower()
        if any(n.lower() in kl for n in needles if n):
            try:
                val = st.session_state.get(k)
                out["related_keys"].append(
                    {
                        "key": ks[:160],
                        "type": type(val).__name__,
                        "repr": repr(val)[:200],
                    }
                )
            except Exception as exc:
                out["related_keys"].append(
                    {"key": ks[:160], "type": "error", "repr": type(exc).__name__}
                )
        elif suffix and ks.endswith(suffix):
            try:
                val = st.session_state.get(k)
                out["related_keys"].append(
                    {
                        "key": ks[:160],
                        "type": type(val).__name__,
                        "repr": repr(val)[:200],
                    }
                )
            except Exception:
                pass
    out["related_keys"] = out["related_keys"][:40]
    return out


def _widget_identity_fields(
    st: Any | None, session: dict[str, Any], user_key: str, room: dict[str, Any] | None
) -> dict[str, Any]:
    try:
        from live_draft_stage1_widget_identity import stage1_widget_identity_snapshot

        snap = stage1_widget_identity_snapshot(
            st,
            session,
            user_key=user_key,
            component_name="solo_countdown_wake",
            room=room if isinstance(room, dict) else None,
            expected_token="",
            active_page=_active_page(session),
            after_mount=True,
        )
        return {
            "actual_registered_internal_widget_id": str(
                snap.get("actual_registered_widget_id") or snap.get("generated_internal_widget_id") or ""
            )[:200],
            "actual_registered_id_source": str(snap.get("actual_registered_id_source") or "")[:80],
            "predicted_element_id": str(snap.get("predicted_element_id") or "")[:200],
        }
    except ImportError:
        return {}


def _emit_row(
    session: dict[str, Any],
    event: str,
    *,
    st: Any | None,
    room: dict[str, Any] | None,
    widget_key: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import json

    base = {
        "event": event,
        "ts": time.time(),
        "deployment_sha": _deployment_sha(session),
        "diagnostic_run_id": _diagnostic_run_id(session, room),
        "script_run_seq": _script_run_seq(session),
        "widget_key": widget_key,
        "active_page": _active_page(session),
        **_room_snapshot(room, session),
    }
    if extra:
        base.update(extra)
    try:
        print(f"SOLO_STAGE1_BOUNDARY_CANARY|{json.dumps(base, default=str)}", flush=True)
    except Exception:
        pass
    try:
        from live_draft_stage1_production_ledger import note_stage1_event

        note_stage1_event(
            session,
            event,
            st=st,
            room=room if isinstance(room, dict) else None,
            widget_key=widget_key,
            extra={k: v for k, v in base.items() if k not in ("event", "ts")},
        )
    except ImportError:
        pass
    return base


def register_declaration_invocation(session: dict[str, Any], widget_key: str, invocation_id: str) -> None:
    by_key = dict(session.get(DECLARATION_INVOCATION_SESSION_KEY) or {})
    by_key[str(widget_key)] = str(invocation_id)
    session[DECLARATION_INVOCATION_SESSION_KEY] = by_key
    session["_solo_stage1_last_declaration_invocation_id"] = str(invocation_id)


def declaration_invocation_for_widget(session: dict[str, Any], widget_key: str) -> str:
    by_key = session.get(DECLARATION_INVOCATION_SESSION_KEY) or {}
    return str(by_key.get(widget_key) or session.get("_solo_stage1_last_declaration_invocation_id") or "")


def next_declaration_order(session: dict[str, Any]) -> int:
    n = int(session.get(LAST_DECLARATION_ORDER_KEY) or 0) + 1
    session[LAST_DECLARATION_ORDER_KEY] = n
    return n


def emit_callback_registration(
    st: Any,
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None,
    widget_key: str,
    declaration_invocation_id: str,
    on_change_fn: Any,
    on_change_registered: bool,
    direct_raw_return: Any,
    session_state_before: str,
    session_state_after: str,
    first_mount: bool,
    mount_guard_result: str,
    cached_raw_return: Any,
    delivery_only: bool,
    component_callable_identity: str = "mount_solo_countdown_wake_with_token",
    diagnostic_surface: str | None = None,
) -> dict[str, Any]:
    if not _obs_enabled(st, session):
        return {}
    on_id = ""
    try:
        on_id = getattr(on_change_fn, "__name__", repr(on_change_fn))[:120]
    except Exception:
        on_id = "unknown"
    register_declaration_invocation(session, widget_key, declaration_invocation_id)
    application_on_change_present = bool(on_change_registered) and on_change_fn is not None
    metadata_callback_present = False
    metadata_probe: dict[str, Any] = {}
    try:
        from live_draft_streamlit_widget_metadata_diag import (
            metadata_stores_callback,
            probe_after_declaration,
            resolve_diagnostic_surface,
            set_registration_diag_context,
            SURFACE_CASE_A_CONTROL,
            SURFACE_PRODUCTION,
        )

        surface = resolve_diagnostic_surface(
            explicit=diagnostic_surface,
            component_callable_identity=component_callable_identity,
            widget_key=widget_key,
        )
        session["_solo_stage1_last_metadata_surface"] = surface
        set_registration_diag_context(
            session,
            diagnostic_surface=surface,
            declaration_invocation_id=declaration_invocation_id,
            widget_key=widget_key,
            application_on_change_present=application_on_change_present,
            application_on_change_identity=getattr(on_change_fn, "__name__", "") if on_change_fn else "",
            component_callable_identity=component_callable_identity,
            script_run_seq=int(session.get("_solo_stage1_script_run_seq") or 0),
            active_page=str(session.get("active_page") or "")[:80],
            room=room,
        )
        metadata_probe = probe_after_declaration(
            st,
            session,
            user_key=widget_key,
            component_name="solo_countdown_wake"
            if surface == SURFACE_PRODUCTION
            else "minimal_wake_repro",
            application_on_change=on_change_fn,
            declaration_invocation_id=declaration_invocation_id,
            surface=surface,
            room=room,
            mount_guard_result=mount_guard_result,
        )
        metadata_callback_present = bool(metadata_probe.get("callback_registered_in_metadata"))
    except ImportError:
        metadata_callback_present = application_on_change_present
    return _emit_row(
        session,
        CALLBACK_REGISTRATION,
        st=st,
        room=room,
        widget_key=widget_key,
        extra={
            "declaration_invocation_id": declaration_invocation_id,
            "declaration_order_in_run": next_declaration_order(session),
            "on_change_callable_identity": on_id,
            "application_on_change_argument_present": application_on_change_present,
            "on_change_registered": metadata_callback_present,
            "metadata_callback_present": metadata_callback_present,
            "component_callable_identity": component_callable_identity[:120],
            "direct_raw_return_repr": repr(direct_raw_return)[:400] if direct_raw_return is not None else "",
            "session_state_before_declaration": session_state_before[:400],
            "session_state_after_declaration": session_state_after[:400],
            "first_mount": bool(first_mount),
            "mount_guard_result": str(mount_guard_result or "")[:80],
            "cached_raw_return_repr": repr(cached_raw_return)[:400] if cached_raw_return is not None else "",
            "delivery_only": bool(delivery_only),
            **_widget_identity_fields(st, session, widget_key, room),
        },
    )


def _callback_fn_identity(fn: Any) -> dict[str, str]:
    name = getattr(fn, "__name__", "unknown")
    mod = getattr(fn, "__module__", "")
    line = ""
    try:
        line = str(inspect.getsourcelines(fn)[1])
    except Exception:
        pass
    return {
        "callback_function_identity": str(name)[:80],
        "callback_source_module": str(mod)[:120],
        "callback_source_line": line,
    }


def emit_prod_on_change_entered(
    st: Any,
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None,
    widget_key: str,
    expected_token: str,
    on_change_fn: Any,
) -> tuple[str, bool]:
    inv = new_callback_invocation_id()
    session["_solo_stage1_active_callback_invocation_id"] = inv
    key_exists = False
    ss_repr = "missing"
    if st is not None and widget_key:
        try:
            key_exists = widget_key in st.session_state
            ss_repr = repr(st.session_state.get(widget_key))[:400] if key_exists else "missing"
        except Exception:
            ss_repr = "error"
    if not _obs_enabled(st, session):
        return inv, key_exists
    session["_solo_stage1_prod_on_change_entered_count"] = (
        int(session.get("_solo_stage1_prod_on_change_entered_count") or 0) + 1
    )
    _emit_row(
        session,
        PROD_ON_CHANGE_ENTERED,
        st=st,
        room=room,
        widget_key=widget_key,
        extra={
            "callback_invocation_id": inv,
            "expected_token": str(expected_token or "")[:400],
            "session_state_key_exists": key_exists,
            "session_state_value_repr": ss_repr,
            "declaration_invocation_id": declaration_invocation_for_widget(session, widget_key),
            "session_state_inventory": safe_session_state_inventory(st, widget_key),
            **_callback_fn_identity(on_change_fn),
            **_widget_identity_fields(st, session, widget_key, room),
        },
    )
    return inv, key_exists


def emit_prod_on_change_exited(
    st: Any,
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None,
    widget_key: str,
    callback_invocation_id: str,
    key_existed_at_entry: bool,
    t0: float,
    exception_status: str = "",
) -> dict[str, Any]:
    key_exists_exit = False
    ss_repr = "missing"
    key_appeared = False
    if st is not None and widget_key:
        try:
            key_exists_exit = widget_key in st.session_state
            ss_repr = repr(st.session_state.get(widget_key))[:400] if key_exists_exit else "missing"
            key_appeared = key_exists_exit and not key_existed_at_entry
        except Exception:
            ss_repr = "error"
    rerun_followed = bool(session.pop("_solo_stage1_callback_rerun_scheduled", False))
    if not _obs_enabled(st, session):
        return {}
    return _emit_row(
        session,
        PROD_ON_CHANGE_EXITED,
        st=st,
        room=room,
        widget_key=widget_key,
        extra={
            "callback_invocation_id": callback_invocation_id,
            "session_state_value_at_exit_repr": ss_repr,
            "session_state_key_exists_at_exit": key_exists_exit,
            "session_state_key_appeared_during_callback": key_appeared,
            "exception_status": str(exception_status or "")[:300],
            "elapsed_ms": round((time.time() - t0) * 1000.0, 2),
            "streamlit_rerun_followed": rerun_followed,
        },
    )


def emit_control_on_change_entered(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    expected_token: str,
    on_change_fn: Any,
    surface: str = "case_a_minimal_repro",
) -> tuple[str, bool]:
    inv = new_callback_invocation_id()
    key_exists = False
    ss_repr = "missing"
    if st is not None and widget_key:
        try:
            key_exists = widget_key in st.session_state
            ss_repr = repr(st.session_state.get(widget_key))[:400] if key_exists else "missing"
        except Exception:
            ss_repr = "error"
    if not _obs_enabled(st, session):
        return inv, key_exists
    _emit_row(
        session,
        CONTROL_ON_CHANGE_ENTERED,
        st=st,
        room=None,
        widget_key=widget_key,
        extra={
            "callback_invocation_id": inv,
            "expected_token": str(expected_token or "")[:400],
            "session_state_key_exists": key_exists,
            "session_state_value_repr": ss_repr,
            "control_surface": surface,
            "session_state_inventory": safe_session_state_inventory(st, widget_key),
            **_callback_fn_identity(on_change_fn),
        },
    )
    return inv, key_exists


def emit_control_on_change_exited(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    callback_invocation_id: str,
    key_existed_at_entry: bool,
    t0: float,
    exception_status: str = "",
) -> dict[str, Any]:
    key_exists_exit = False
    ss_repr = "missing"
    key_appeared = False
    if st is not None and widget_key:
        try:
            key_exists_exit = widget_key in st.session_state
            ss_repr = repr(st.session_state.get(widget_key))[:400] if key_exists_exit else "missing"
            key_appeared = key_exists_exit and not key_existed_at_entry
        except Exception:
            ss_repr = "error"
    if not _obs_enabled(st, session):
        return {}
    return _emit_row(
        session,
        CONTROL_ON_CHANGE_EXITED,
        st=st,
        room=None,
        widget_key=widget_key,
        extra={
            "callback_invocation_id": callback_invocation_id,
            "session_state_value_at_exit_repr": ss_repr,
            "session_state_key_exists_at_exit": key_exists_exit,
            "session_state_key_appeared_during_callback": key_appeared,
            "exception_status": str(exception_status or "")[:300],
            "elapsed_ms": round((time.time() - t0) * 1000.0, 2),
        },
    )
