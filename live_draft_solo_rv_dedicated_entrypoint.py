"""RV return-value binding ladder — dedicated early shell (diag-only)."""

from __future__ import annotations

from typing import Any

from live_draft_solo_rv_binding_ladder import (
    enable_rv_ladder_session,
    execute_rv_step_mount,
    rv2_mount_if_needed,
    rv_ladder_requested,
    rv_pre_app_shell_should_stop,
    try_rv3_ldr_persistent_mount,
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
    result = execute_rv_step_mount(st, session, step)
    st.caption(f"RV ladder {step}: mount={'ok' if result.get('ok') else 'fail'} token={str(result.get('token') or '')[:60]}")
    if rv_pre_app_shell_should_stop(session):
        return True
    return False


def rv3_on_ldr_entry(st: Any, session: dict[str, Any], room: Any, *, phase: str) -> None:
    from live_draft_solo_rv_binding_ladder import try_rv3_ldr_persistent_mount

    try_rv3_ldr_persistent_mount(st, session, room, phase=phase)
