"""Render expired-pick / auto-pick state machine diagnostics."""

from __future__ import annotations

from typing import Any


def render_autopick_diagnostics(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    try:
        from live_draft_expired_pick import AUTOPICK_DIAG_KEY
    except ImportError:
        return
    raw = session.get(AUTOPICK_DIAG_KEY)
    if not isinstance(raw, dict):
        return
    expanded = developer_mode or bool(raw.get("autopick_failure_backoff_active"))
    with st.expander("Auto-pick diagnostics", expanded=expanded):
        keys = (
            "expired_pick_detected",
            "autopick_attempted_for_index",
            "autopick_in_progress_lock",
            "autopick_success",
            "autopick_error",
            "autopick_commit_path",
            "board_size_before_autopick",
            "board_size_after_autopick",
            "current_pick_index_before_autopick",
            "current_pick_index_after_autopick",
            "autopick_failure_backoff_active",
            "rerun_loop_prevented",
        )
        for key in keys:
            val = raw.get(key)
            st.text(f"{key}: {val if val is not None and val != '' else '—'}")
