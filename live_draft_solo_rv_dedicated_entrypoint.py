"""RV return-value binding ladder — dedicated early shell (diag-only)."""

from __future__ import annotations

from typing import Any

from live_draft_solo_rv_binding_ladder import (
    enable_rv_ladder_session,
    execute_rv_step_mount,
    rv2_mount_if_needed,
    rv_ladder_requested,
    rv_pre_app_shell_should_stop,
)
from live_draft_solo_rv_control_probe import (
    append_control_event,
    ensure_probe_placeholder,
    flush_control_probe,
)


def run_rv_pre_app_shell(st: Any, session: dict[str, Any]) -> bool:
    """Returns True when the app must st.stop() after RV0/RV1 shell mount."""
    if not rv_ladder_requested(st, session):
        return False
    step = enable_rv_ladder_session(st, session)
    if not step:
        return False
    if step == "RV3":
        return False
    if step == "RV2":
        rv2_mount_if_needed(st, session)
        st.caption(f"RV ladder {step}: initial mount complete; page continues.")
        return False
    ph = ensure_probe_placeholder(st, session)
    append_control_event(st, session, "rv_entrypoint_entered", control_name=step)
    flush_control_probe(st, session, ph)
    result = execute_rv_step_mount(st, session, step)
    flush_control_probe(st, session, ph)
    st.caption(f"RV ladder {step}: mount={'ok' if result.get('ok') else 'fail'} token={str(result.get('token') or '')[:60]}")
    if rv_pre_app_shell_should_stop(session):
        flush_control_probe(st, session, ph)
        return True
    return False


def rv3_on_ldr_entry(st: Any, session: dict[str, Any], room: Any, *, phase: str) -> None:
    from live_draft_solo_rv_binding_ladder import try_rv3_ldr_persistent_mount

    try_rv3_ldr_persistent_mount(st, session, room, phase=phase)
