"""Render live draft safe-mode and rerun diagnostics."""

from __future__ import annotations

from typing import Any


def render_safe_mode_diagnostics(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    if not developer_mode:
        return
    try:
        from page_diagnostics import suppress_inline_diagnostics

        if suppress_inline_diagnostics(developer_mode):
            return
    except ImportError:
        pass
    try:
        from live_draft_safe_mode import RERUN_DIAG_KEY, SAFE_MODE_DIAG_KEY
    except ImportError:
        return

    safe = session.get(SAFE_MODE_DIAG_KEY)
    rerun = session.get(RERUN_DIAG_KEY)
    if not isinstance(safe, dict) and not isinstance(rerun, dict):
        return

    expanded = developer_mode and bool(
        isinstance(safe, dict) and (safe.get("safe_mode_active") or safe.get("false_complete_detected"))
    )
    with st.expander("Draft state / rerun diagnostics", expanded=expanded):
        keys = (
            "draft_state_error",
            "draft_state_error_reason",
            "safe_mode_active",
            "manual_recovery_available",
            "timer_fragment_active",
            "timer_should_run",
            "false_complete_detected",
            "saved_draft_status",
            "computed_draft_status",
            "draft_status_source",
            "completion_source",
            "stale_draft_status_detected",
            "stale_current_pick_index_detected",
            "board_size",
            "total_expected_picks",
            "current_pick_index",
            "current_pick_index_before_reconcile",
            "current_pick_index_after_reconcile",
            "draft_status_before",
            "draft_status_after",
            "rerun_source",
            "rerun_allowed",
            "rerun_blocked_reason",
        )
        merged = {}
        if isinstance(safe, dict):
            merged.update(safe)
        if isinstance(rerun, dict):
            merged.update(rerun)
        for key in keys:
            val = merged.get(key)
            st.text(f"{key}: {val if val is not None and val != '' else '—'}")
