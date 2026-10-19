"""Per-session, per-script-run guards for idempotent sidebar rendering.

Streamlit 1.59+ has no public ``script_run_id``. A process-global claim is not
safe because different browser sessions execute concurrently in different
threads. Instead, startup advances a generation stored in that browser's
``session_state`` and every claim is bound to that generation.
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

_RUN_GENERATION_KEY = "_sidebar_script_run_generation"
_CLAIM_GENERATION_PREFIX = "_sidebar_claim_generation::"
_DEV_MODE_MATERIALIZED_GENERATION_KEY = "_sidebar_dev_mode_materialized_generation"


def _run_generation(session_state: dict[str, Any]) -> int:
    try:
        generation = int(session_state.get(_RUN_GENERATION_KEY) or 0)
    except (TypeError, ValueError):
        generation = 0
    if generation < 1:
        generation = 1
        session_state[_RUN_GENERATION_KEY] = generation
    return generation


def reset_sidebar_run_guards(session_state: dict[str, Any]) -> None:
    """Advance this browser session to a new script-run generation."""
    session_state[_RUN_GENERATION_KEY] = _run_generation(session_state) + 1
    for key in ALL_GUARDS:
        session_state[key] = False
    session_state.pop(_DEV_MODE_MATERIALIZED_GENERATION_KEY, None)


def dev_mode_checkbox_materialized(session_state: dict[str, Any]) -> bool:
    """True after the Developer Mode sidebar checkbox was created this run."""
    return session_state.get(_DEV_MODE_MATERIALIZED_GENERATION_KEY) == _run_generation(session_state)


def mark_dev_mode_checkbox_materialized(session_state: dict[str, Any]) -> None:
    """Record that the Developer Mode checkbox widget was created."""
    session_state[_DEV_MODE_MATERIALIZED_GENERATION_KEY] = _run_generation(session_state)


def claim_sidebar_render(session_state: dict[str, Any], guard: str) -> bool:
    """Return True the first time a guard is claimed this script run."""
    generation = _run_generation(session_state)
    claim_key = f"{_CLAIM_GENERATION_PREFIX}{guard}"
    if session_state.get(claim_key) == generation:
        return False
    session_state[guard] = True
    session_state[claim_key] = generation
    return True


def reset_sidebar_run_guards_for_tests() -> None:
    """Compatibility no-op: execution claims now live in session state."""
