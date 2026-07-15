"""Per-script-run guards for sidebar chrome (idempotent render).

Streamlit 1.59+ has no ``script_run_id`` on ScriptRunContext. Falling back to
``session_id`` incorrectly treated an entire browser session as one execution,
so after the first rerun (e.g. sign-in) module-level claims stuck and the
Command Center / Saved session / Developer Mode controls never re-rendered.

Reset therefore always clears module claims. Call ``reset_sidebar_run_guards``
once near app startup each script run; mid-run duplicate protection uses
session_state flags only.
"""

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

# Module-level claims are valid only between reset_sidebar_run_guards() calls.
_CLAIMED_THIS_EXECUTION: set[str] = set()
_DEV_MODE_CHECKBOX_MATERIALIZED: bool = False


def reset_sidebar_run_guards(session_state: dict[str, Any]) -> None:
    """Call once near app startup — clears per-run claims for a new script run."""
    global _CLAIMED_THIS_EXECUTION, _DEV_MODE_CHECKBOX_MATERIALIZED
    for key in ALL_GUARDS:
        session_state[key] = False
    _CLAIMED_THIS_EXECUTION = set()
    _DEV_MODE_CHECKBOX_MATERIALIZED = False


def dev_mode_checkbox_materialized() -> bool:
    """True after the Developer Mode sidebar checkbox was created this run."""
    return _DEV_MODE_CHECKBOX_MATERIALIZED


def mark_dev_mode_checkbox_materialized() -> None:
    """Record that the Developer Mode checkbox widget was created."""
    global _DEV_MODE_CHECKBOX_MATERIALIZED
    _DEV_MODE_CHECKBOX_MATERIALIZED = True


def claim_sidebar_render(session_state: dict[str, Any], guard: str) -> bool:
    """Return True the first time a guard is claimed this script run."""
    if guard in _CLAIMED_THIS_EXECUTION:
        return False
    if session_state.get(guard):
        return False
    session_state[guard] = True
    _CLAIMED_THIS_EXECUTION.add(guard)
    return True


def reset_sidebar_run_guards_for_tests() -> None:
    """Test helper — clear module-level execution claims."""
    global _CLAIMED_THIS_EXECUTION, _DEV_MODE_CHECKBOX_MATERIALIZED
    _CLAIMED_THIS_EXECUTION = set()
    _DEV_MODE_CHECKBOX_MATERIALIZED = False
