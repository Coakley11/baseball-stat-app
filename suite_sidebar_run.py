"""Per-script-run guards for sidebar chrome (idempotent render)."""

from __future__ import annotations

from typing import Any

GUARD_ACCOUNT = "_sidebar_account_rendered_this_run"
GUARD_COMMAND_CENTER = "_command_center_controls_rendered_this_run"
GUARD_SAVED_SESSION = "_saved_session_controls_rendered_this_run"
GUARD_DEV_TOGGLE = "_dev_mode_toggle_rendered_this_run"

ALL_GUARDS: tuple[str, ...] = (
    GUARD_ACCOUNT,
    GUARD_COMMAND_CENTER,
    GUARD_SAVED_SESSION,
    GUARD_DEV_TOGGLE,
)


def reset_sidebar_run_guards(session_state: dict[str, Any]) -> None:
    """Call once near app startup — session flags persist across Streamlit reruns."""
    for key in ALL_GUARDS:
        session_state[key] = False


def claim_sidebar_render(session_state: dict[str, Any], guard: str) -> bool:
    """Return True the first time a guard is claimed this script run."""
    if session_state.get(guard):
        return False
    session_state[guard] = True
    return True
