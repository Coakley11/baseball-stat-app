"""P6 R4/R5 — V1 custom component return-value controls (no on_change, no bridge)."""

from __future__ import annotations

from typing import Any

from live_draft_solo_persistent_wake import SOLO_PERSISTENT_WAKE_WIDGET_KEY


def _declaration_identity(session: dict[str, Any], *, widget_key: str, control: str) -> str:
    if control == "R5":
        return "solo_p6_v1_template_component.mount_template_once"
    return "solo_countdown_component.mount_solo_countdown_wake_with_token"


def _coerce_return_token(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, dict):
        for k in ("token", "expire_token", "value"):
            v = str(raw.get(k) or "").strip()
            if v:
                return v
    return str(raw).strip().strip("'\"")


def record_v1_return_value_observation(
    session: dict[str, Any],
    *,
    st: Any | None,
    control: str,
    widget_key: str,
    expected_token: str,
    raw_component_value: Any,
    session_state_raw: str,
    first_run_after_browser_delivery: bool,
    declaration_identity: str,
) -> None:
    from live_draft_solo_parity_p6_persistent_diag import append_p6_ledger_row, bump_p6_script_run

    run_n = bump_p6_script_run(st, session) if st is not None else int(session.get("_solo_p6_script_run") or 0)
    act = _coerce_return_token(raw_component_value)
    stage = "r5_component_return_value" if control == "R5" else "r4_component_return_value"
    append_p6_ledger_row(
        session,
        stage,
        st=st,
        widget_key=widget_key,
        expected_token=str(expected_token or "")[:400],
        actual_token=act[:400],
        raw_component_value=repr(raw_component_value)[:400],
        session_state_raw_value=session_state_raw[:400],
        callback_control=control,
        component_declaration_identity=declaration_identity,
        script_run=run_n,
        first_run_after_browser_delivery=bool(first_run_after_browser_delivery),
        return_matches_expected=bool(expected_token and act == expected_token),
    )


def mount_p6_v1_return_value_control(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    run_id: str,
    control: str,
    expire_token: str,
    chain_persist_key: str = "",
) -> Any:
    """
    R4: production countdown component, on_change=None, direct return value.
    R5: minimal official V1 template component, same token contract.
    """
    from live_draft_solo_p6_declaration_audit import resolve_p6_callback_control

    control = resolve_p6_callback_control(st, session) if control not in ("R4", "R5") else control
    expected = str(expire_token or session.get("_solo_parity_expected_token") or "")[:400]
    widget_key = SOLO_PERSISTENT_WAKE_WIDGET_KEY if control == "R4" else "solo_p6_v1_template_wake"
    session["_solo_p6_v1_control_active"] = control
    session["_solo_p6_v1_widget_key"] = widget_key

    try:
        from live_draft_solo_parity_p6_persistent_diag import append_p6_ledger_row

        append_p6_ledger_row(
            session,
            "r4_mount_begin",
            st=st,
            callback_control=control,
            widget_key=widget_key,
            expected_token=expected,
        )
    except ImportError:
        pass

    delivery_seen = bool(session.get("_solo_p6_browser_delivery_seen"))
    first_after = delivery_seen and not session.get("_solo_p6_v1_return_logged_after_delivery")

    if control == "R5":
        from solo_p6_v1_template_component import mount_p6_v1_template_once

        raw = mount_p6_v1_template_once(
            expected,
            key=widget_key,
            on_change=None,
        )
    else:
        from solo_countdown_component import mount_solo_countdown_wake_with_token

        raw = mount_solo_countdown_wake_with_token(
            room if isinstance(room, dict) else {},
            key=widget_key,
            expire_token=expected,
            actionable=True,
            on_change=None,
            chain_persist_key=str(chain_persist_key or session.get("_solo_parity_ls_key") or ""),
        )

    append_p6_component_declared_for_v1(
        session, st=st, widget_key=widget_key, expire_token=expected, raw=raw, control=control
    )

    ss_raw = repr(st.session_state.get(widget_key))[:400] if widget_key in st.session_state else "missing"
    ident = _declaration_identity(session, widget_key=widget_key, control=control)
    record_v1_return_value_observation(
        session,
        st=st,
        control=control,
        widget_key=widget_key,
        expected_token=expected,
        raw_component_value=raw,
        session_state_raw=ss_raw,
        first_run_after_browser_delivery=first_after,
        declaration_identity=ident,
    )
    if _coerce_return_token(raw) == expected:
        session["_solo_p6_v1_return_value_pass"] = True
    if first_after and _coerce_return_token(raw) == expected:
        session["_solo_p6_v1_return_after_delivery"] = True

    return raw


def append_p6_component_declared_for_v1(
    session: dict[str, Any],
    *,
    st: Any | None,
    widget_key: str,
    expire_token: str,
    raw: Any,
    control: str,
) -> None:
    from live_draft_solo_parity_p6_persistent_diag import record_p6_component_declaration

    if not session.get("_solo_p6_v1_component_declared_logged"):
        record_p6_component_declaration(
            session,
            widget_key=widget_key,
            expire_token=expire_token,
            component_return=raw,
            mount_location=f"p6_v1_return_value_{control.lower()}",
            st=st,
            component_default=None,
        )
        session["_solo_p6_v1_component_declared_logged"] = True


def note_p6_browser_delivery_for_v1(session: dict[str, Any]) -> None:
    session["_solo_p6_browser_delivery_seen"] = True
