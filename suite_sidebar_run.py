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

# Module-level claims survive session_state restore mid-run (persistence sync).
_CLAIMED_THIS_EXECUTION: set[str] = set()
_EXECUTION_TOKEN: object | None = object()


def _execution_token() -> object | None:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx is None:
            return None
        return (
            getattr(ctx, "script_run_id", None)
            or getattr(ctx, "session_id", None)
            or id(ctx)
        )
    except Exception:
        return None


def _sync_execution_claims() -> None:
    global _CLAIMED_THIS_EXECUTION, _EXECUTION_TOKEN
    token = _execution_token()
    if token != _EXECUTION_TOKEN:
        _EXECUTION_TOKEN = token
        _CLAIMED_THIS_EXECUTION = set()


def reset_sidebar_run_guards(session_state: dict[str, Any]) -> None:
    """Call once near app startup — clears per-run claims and session flags."""
    global _CLAIMED_THIS_EXECUTION, _EXECUTION_TOKEN
    _EXECUTION_TOKEN = _execution_token()
    _CLAIMED_THIS_EXECUTION = set()
    for key in ALL_GUARDS:
        session_state[key] = False


def claim_sidebar_render(session_state: dict[str, Any], guard: str) -> bool:
    """Return True the first time a guard is claimed this script execution."""
    _sync_execution_claims()
    if guard in _CLAIMED_THIS_EXECUTION:
        return False
    if session_state.get(guard):
        return False
    session_state[guard] = True
    _CLAIMED_THIS_EXECUTION.add(guard)
    return True


def reset_sidebar_run_guards_for_tests() -> None:
    """Test helper — clear module-level execution claims."""
    global _CLAIMED_THIS_EXECUTION, _EXECUTION_TOKEN
    _CLAIMED_THIS_EXECUTION = set()
    _EXECUTION_TOKEN = object()
