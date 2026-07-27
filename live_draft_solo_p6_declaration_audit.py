"""P6 declaration audit and one-variable callback-registration controls (R0–R3)."""

from __future__ import annotations

import inspect
from typing import Any, Callable

P6_CALLBACK_CONTROL_QP = "solo_p6_callback_control"
P6_CALLBACK_CONTROL_SESSION_KEY = "_solo_p6_callback_control"
P6_DECLARATION_DIFF_KEY = "_solo_p6_declaration_diff"
VALID_CONTROLS = frozenset({"R0", "R1", "R2", "R3", "R4", "R5"})


def _qp_get(st: Any | None, name: str) -> str:
    if st is None:
        return ""
    try:
        from live_draft_cloud_diagnostics import _qp_get as get_qp

        return get_qp(st, name)
    except ImportError:
        return ""


def resolve_p6_callback_control(st: Any | None, session: dict[str, Any]) -> str:
    raw = (_qp_get(st, P6_CALLBACK_CONTROL_QP) or str(session.get(P6_CALLBACK_CONTROL_SESSION_KEY) or "R0")).strip().upper()
    if raw not in VALID_CONTROLS:
        raw = "R0"
    session[P6_CALLBACK_CONTROL_SESSION_KEY] = raw
    return raw


def _callback_meta(fn: Any) -> dict[str, Any]:
    if fn is None:
        return {"callback_present": False, "callback_name": "", "callback_module": "", "callback_id": ""}
    try:
        return {
            "callback_present": True,
            "callback_name": getattr(fn, "__name__", repr(fn)),
            "callback_qualname": getattr(fn, "__qualname__", ""),
            "callback_module": getattr(fn, "__module__", ""),
            "callback_id": hex(id(fn)),
        }
    except Exception:
        return {"callback_present": bool(fn), "callback_name": repr(fn)[:200], "callback_module": "", "callback_id": ""}


def build_b2_reference_declaration_snapshot(
    *,
    widget_key: str,
    expire_token: str,
    chain_persist_key: str,
    deliver_callback: Any,
    control: str = "B2",
) -> dict[str, Any]:
    """Static snapshot of parity-ladder B2 micro-wrapper declaration (no mount)."""
    room_deadline = 0.0
    if expire_token.count("|") >= 2:
        try:
            room_deadline = float(expire_token.split("|")[-1])
        except ValueError:
            pass
    on_change_wrapper = "solo_countdown_wake_micro_core._prod_on_change (closure)"
    return {
        "path": "parity_ladder._mount_b2_style -> render_micro_isolation_once",
        "component_callable": "solo_countdown_component.mount_solo_countdown_wake_with_token",
        "component_module": "solo_countdown_component",
        "wrapper_helper": "solo_countdown_wake_micro_core.render_micro_isolation_once",
        "widget_key": widget_key,
        "default_value": None,
        "expire_token": expire_token,
        "on_change_argument": on_change_wrapper,
        "on_change_registers_streamlit": True,
        "deliver_callback": _callback_meta(deliver_callback),
        "component_kwargs": {
            "expire_token": expire_token,
            "actionable": True,
            "chain_persist_key": chain_persist_key,
            "widget_key": widget_key,
            "key": widget_key,
            "default": None,
        },
        "render_micro_isolation_once_kwargs": {
            "placement": control,
            "location": f"parity_ladder_{control.lower()}",
            "draft_id": "PARITY",
            "route": True,
            "persistent": control in ("P3", "P4", "P5"),
            "session_prefix": f"_solo_parity_micro_{control.lower()}_",
            "production_room": {
                "draft_room_id": "PARITY",
                "draft_id": "PARITY",
                "timer_deadline": room_deadline,
            },
            "production_expire_token": expire_token,
            "production_actionable": True,
            "production_delivery_only": False,
            "suppress_immediate_session_on_change": True,
            "chain_persist_key": chain_persist_key,
        },
        "conditional_omits_on_change": False,
    }


def build_production_declaration_snapshot(
    *,
    widget_key: str,
    expire_token: str,
    chain_persist_key: str,
    deliver_callback: Any,
    suppress_immediate_session_on_change: bool,
    location: str,
    production_delivery_only: bool,
    isolated_mode: str,
) -> dict[str, Any]:
    on_change_wrapper = "solo_countdown_wake_micro_core._prod_on_change (closure)"
    snap: dict[str, Any] = {
        "path": "try_solo_persistent_wake_ldr_entry -> render_micro_isolation_once",
        "component_callable": "solo_countdown_component.mount_solo_countdown_wake_with_token",
        "component_module": "solo_countdown_component",
        "wrapper_helper": "solo_countdown_wake_micro_core.render_micro_isolation_once",
        "widget_key": widget_key,
        "default_value": None,
        "expire_token": expire_token,
        "on_change_argument": on_change_wrapper,
        "on_change_registers_streamlit": True,
        "deliver_callback": _callback_meta(deliver_callback),
        "component_kwargs": {
            "expire_token": expire_token,
            "actionable": True,
            "chain_persist_key": chain_persist_key,
            "widget_key": widget_key,
            "key": widget_key,
            "default": None,
        },
        "render_micro_isolation_once_kwargs": {
            "placement": "PROD",
            "location": location,
            "draft_id": "(room draft id)",
            "route": True,
            "persistent": True,
            "session_prefix": "_solo_persistent_wake_",
            "production_expire_token": expire_token,
            "production_actionable": True,
            "production_delivery_only": production_delivery_only,
            "suppress_immediate_session_on_change": suppress_immediate_session_on_change,
            "chain_persist_key": chain_persist_key,
        },
        "suppress_immediate_session_on_change": suppress_immediate_session_on_change,
        "force_flag": None,
        "transport_isolated_mode": isolated_mode,
        "conditional_omits_on_change": isolated_mode == "minimal",
    }
    if isolated_mode == "minimal":
        snap["conditional_branch"] = "isolated minimal mounts mount_transport_isolated_minimal_only; production on_change skipped"
    return snap


def store_declaration_diff(session: dict[str, Any], *, production: dict[str, Any], b2_reference: dict[str, Any]) -> None:
    diffs: list[dict[str, Any]] = []
    keys = sorted(set(production.keys()) | set(b2_reference.keys()))
    for k in keys:
        pv = production.get(k)
        bv = b2_reference.get(k)
        if pv != bv:
            diffs.append({"field": k, "production": pv, "b2_reference": bv})
    session[P6_DECLARATION_DIFF_KEY] = {
        "production": production,
        "b2_reference": b2_reference,
        "differences": diffs,
    }


def record_declaration_attempt(
    session: dict[str, Any],
    *,
    st: Any | None,
    widget_key: str,
    default: Any,
    expected_token: str,
    on_change_fn: Any,
    deliver_callback: Any,
    suppress_flag: bool,
    force_flag: Any,
    component_kwargs: dict[str, Any],
    session_state_before: str,
) -> None:
    from live_draft_solo_parity_p6_persistent_diag import append_p6_ledger_row

    oc = _callback_meta(on_change_fn)
    dc = _callback_meta(deliver_callback)
    append_p6_ledger_row(
        session,
        "declaration_attempt",
        st=st,
        widget_key=widget_key,
        expected_token=str(expected_token or "")[:400],
        component_default=repr(default)[:200],
        callback_present=oc.get("callback_present"),
        callback_callable_name=str(oc.get("callback_name") or ""),
        callback_module=str(oc.get("callback_module") or ""),
        callback_object_identity=str(oc.get("callback_id") or ""),
        deliver_callback_name=str(dc.get("callback_name") or ""),
        deliver_callback_module=str(dc.get("callback_module") or ""),
        deliver_callback_identity=str(dc.get("callback_id") or ""),
        suppress_immediate_session_on_change=suppress_flag,
        force_flag=force_flag,
        component_kwargs_json=str(component_kwargs)[:1200],
        session_state_before=session_state_before[:400],
        callback_args=(),
        callback_kwargs={},
    )


def record_declaration_returned(
    session: dict[str, Any],
    *,
    st: Any | None,
    widget_key: str,
    expected_token: str,
    component_return: Any,
    session_state_after: str,
) -> None:
    from live_draft_solo_parity_p6_persistent_diag import append_p6_ledger_row

    flag_count = 0
    try:
        from live_draft_solo_transport_boundary_diag import PRODUCTION_CALLBACK_FLAG

        flag_count = int(session.get(f"{PRODUCTION_CALLBACK_FLAG}_count") or 0)
    except ImportError:
        pass
    append_p6_ledger_row(
        session,
        "declaration_returned",
        st=st,
        widget_key=widget_key,
        expected_token=str(expected_token or "")[:400],
        component_return=repr(component_return)[:400],
        returned_raw_value=repr(component_return)[:400],
        session_state_raw_value=session_state_after[:400],
        production_callback_flag_count=flag_count,
    )


def record_sentinel_callback_entry(session: dict[str, Any], *, st: Any | None, widget_key: str, raw: Any) -> None:
    from live_draft_solo_parity_p6_persistent_diag import append_p6_ledger_row

    append_p6_ledger_row(
        session,
        "sentinel_callback_entry",
        st=st,
        widget_key=widget_key,
        raw_widget_value=repr(raw)[:400],
        actual_token=str(raw).strip("'\"")[:400] if raw is not None else "",
    )


def wrap_p6_sentinel_deliver(
    deliver: Callable[[Any, dict[str, Any], Any, str], None],
) -> Callable[[Any, dict[str, Any], Any, str], None]:
    def _wrapped(st: Any, session: dict[str, Any], raw: Any, key: str) -> None:
        record_sentinel_callback_entry(session, st=st, widget_key=key, raw=raw)
        deliver(st, session, raw, key)

    return _wrapped


def mount_r3_b2_helper_at_p6(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    expire_token: str,
    chain_persist_key: str,
    deliver_callback: Callable[[Any, dict[str, Any], Any, str], None],
) -> Any:
    """B2 _mount_b2_style declaration at P6 location (production key/token/deliver)."""
    from live_draft_solo_persistent_parity_ladder import _mount_b2_style

    return _mount_b2_style(
        st,
        session,
        control="B2",
        key=widget_key,
        token=expire_token,
        ls_key=chain_persist_key,
        deliver=deliver_callback,
    )


def p6_declaration_audit_active(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_parity_p6_persistent_diag import p6_persistent_diag_active

        return p6_persistent_diag_active(st, session)
    except ImportError:
        return False
