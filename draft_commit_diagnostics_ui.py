"""Render pick commit diagnostics expander."""

from __future__ import annotations

from typing import Any


def render_draft_commit_diagnostics(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    try:
        from draft_commit_diagnostics import DRAFT_COMMIT_DIAG_KEY
    except ImportError:
        return
    raw = session.get(DRAFT_COMMIT_DIAG_KEY)
    if not isinstance(raw, dict):
        return
    with st.expander("Pick commit diagnostics", expanded=developer_mode and not raw.get("supabase_commit_success")):
        keys = (
            "draft_button_clicked",
            "selected_player_at_click",
            "selected_player_name",
            "selected_player_id",
            "draft_player_called",
            "manual_pick_attempted",
            "manual_pick_success",
            "manual_pick_error",
            "manual_pick_commit_path",
            "commit_path",
            "commit_shared_room_pick_called",
            "shared_room_commit_called",
            "validate_participant_may_draft_result",
            "validate_shared_pick_commit_result",
            "validation_result",
            "board_size_before",
            "board_size_after",
            "board_size_before_manual_pick",
            "board_size_after_manual_pick",
            "current_pick_index_before",
            "current_pick_index_after",
            "current_pick_index_before_manual_pick",
            "current_pick_index_after_manual_pick",
            "on_clock_team_before",
            "on_clock_team_after",
            "current_pick_before",
            "current_pick_after",
            "next_team_resolved",
            "supabase_revision_before",
            "room_revision_before",
            "room_revision_after",
            "supabase_commit_success",
            "supabase_commit_error",
            "pick_saved_to_room",
            "realtime_update_sent",
            "realtime_update_received",
            "poll_refresh_detected",
            "rerun_after_commit",
            "autopick_triggered",
            "autopick_reason",
        )
        for key in keys:
            val = raw.get(key)
            st.text(f"{key}: {val if val is not None and val != '' else '—'}")
