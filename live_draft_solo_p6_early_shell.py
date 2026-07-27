"""Exclusive early P6 diagnostic shell — stops page before long LDR UI."""

from __future__ import annotations

from typing import Any

from live_draft_solo_persistent_parity_ladder import (
    PARITY_CONTROL_KEY,
    PARITY_HANDLED_WAKE_KEY,
    PARITY_MOUNTED_KEY,
    PARITY_P6_DISABLE_PICK_KEY,
    SOLO_PERSISTENT_WAKE_LATCH_KEY,
    ensure_p6_latched_production_token,
)
from live_draft_solo_persistent_wake import SOLO_PERSISTENT_WAKE_WIDGET_KEY

P6_EARLY_SHELL_ACTIVE_KEY = "_solo_p6_early_shell_active"
P6_EARLY_SHELL_COMPLETED_RUN_KEY = "_solo_p6_early_shell_completed_run"
P6_EARLY_SHELL_STOP_KEY = "_solo_p6_early_shell_stop_remainder"
P6_RUN_SCOPED_ROOM_KEY = "_solo_p6_run_scoped_room"


def _normalize_page(page: str) -> str:
    p = str(page or "").strip().replace("+", " ")
    if p.lower().replace("_", " ") == "live draft room":
        return "Live Draft Room"
    return p


def p6_early_shell_blocks_deep_parity(session: dict[str, Any]) -> bool:
    return bool(session.get(P6_EARLY_SHELL_STOP_KEY))


def try_p6_early_exclusive_shell(st: Any, session: dict[str, Any], *, ldr_branch: bool = False) -> bool:
    """Run P6 mount once inside Live Draft Room, keep writer probe alive, stop before main LDR UI."""
    from live_draft_solo_parity_p6_persistent_diag import (
        P6_DIAG_LATCHED_KEY,
        P6_MOUNTED_RUN_ID_KEY,
        append_p6_ledger_row,
        apply_p6_clear_once_hygiene,
        latch_p6_diag_mode,
        p6_persistent_diag_active,
        record_p6_token_latched,
        render_p6_writer_probe,
        resolve_p6_run_id,
        synthetic_room_id_for_run,
    )

    if not session.get(P6_DIAG_LATCHED_KEY) and not p6_persistent_diag_active(st, session):
        return False
    latch_p6_diag_mode(st, session)
    latched = str(session.get(PARITY_CONTROL_KEY) or session.get("_solo_parity_ladder_control") or "").strip().upper()
    if latched != "P6":
        return False
    run_id = resolve_p6_run_id(st, session)
    if not run_id:
        return False
    if ldr_branch:
        session["active_page"] = "Live Draft Room"
    if _normalize_page(str(session.get("active_page") or "")) != "Live Draft Room":
        return False

    session[P6_EARLY_SHELL_ACTIVE_KEY] = True
    session[P6_EARLY_SHELL_STOP_KEY] = True
    session[PARITY_CONTROL_KEY] = "P6"
    session["_solo_parity_ladder_control"] = "P6"
    session[PARITY_P6_DISABLE_PICK_KEY] = True
    session["_solo_delivery_diag_enabled"] = True

    if session.get(P6_EARLY_SHELL_COMPLETED_RUN_KEY) == run_id:
        from live_draft_solo_parity_p6_persistent_diag import get_p6_ledger_for_run

        prior = get_p6_ledger_for_run(session, run_id)
        if any(isinstance(r, dict) and r.get("stage") == "component_declared" for r in prior):
            render_p6_writer_probe(st, session)
            st.stop()
            return True
        session.pop(P6_EARLY_SHELL_COMPLETED_RUN_KEY, None)

    key = SOLO_PERSISTENT_WAKE_WIDGET_KEY
    session[P6_RUN_SCOPED_ROOM_KEY] = True
    apply_p6_clear_once_hygiene(st, session, widget_key=key)
    token, synth = ensure_p6_latched_production_token(session)
    room_id = synthetic_room_id_for_run(run_id)
    record_p6_token_latched(session, token=token, st=st)
    append_p6_ledger_row(
        session,
        "component_declaration_attempted",
        st=st,
        widget_key=key,
        expected_token=token,
        actual_token=token,
        synthetic_room_id=room_id,
        on_change_callback="_production_deliver_callback",
    )
    session[SOLO_PERSISTENT_WAKE_LATCH_KEY] = True
    session["_solo_expire_owner"] = "wake"
    session[PARITY_HANDLED_WAKE_KEY] = True
    session.pop("_solo_persistent_wake_flush_disabled", None)

    from live_draft_solo_persistent_wake import try_solo_persistent_wake_ldr_entry

    try_solo_persistent_wake_ldr_entry(st, session, synth)
    session[PARITY_MOUNTED_KEY] = True
    session[P6_MOUNTED_RUN_ID_KEY] = run_id
    session[P6_EARLY_SHELL_COMPLETED_RUN_KEY] = run_id
    render_p6_writer_probe(st, session)
    st.stop()
    return True
