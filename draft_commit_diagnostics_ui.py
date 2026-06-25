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
            "draft_candidate_widget_key",
            "draft_candidate_widget_value",
            "visible_draft_candidate_name",
            "visible_draft_candidate_id",
            "queued_manual_pick_player_name",
            "queued_manual_pick_player_id",
            "pending_manual_pick_exists",
            "pending_manual_pick_player_name",
            "pending_manual_pick_player_id",
            "queue_manual_draft_pick_entered",
            "process_pending_manual_draft_pick_entered",
            "selected_player_at_click",
            "selected_player_name",
            "selected_player_id",
            "candidate_source",
            "pool_source",
            "player_still_available_at_click",
            "draft_player_called",
            "manual_pick_attempted",
            "manual_pick_success",
            "manual_pick_error",
            "manual_pick_commit_path",
            "commit_function_entered",
            "commit_function_returned",
            "commit_path",
            "commit_shared_room_pick_called",
            "shared_room_commit_called",
            "validate_participant_may_draft_result",
            "validate_participant_may_draft_message",
            "validate_participant_may_draft_entered",
            "validate_participant_may_draft_reason",
            "validation_participant_team",
            "validation_on_clock_team",
            "validation_is_my_turn",
            "validation_saved_status",
            "validation_computed_status",
            "validation_board_size",
            "validation_total_picks",
            "validation_current_pick_index",
            "validation_manual_recovery_available",
            "validation_safe_mode_active",
            "validation_draft_state_error",
            "validation_player_available",
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
            "manual_commit_overwritten_after_success",
            "overwrite_source",
            "runtime_room_preferred",
            "canonical_room_preferred",
            "local_dirty_before_commit",
            "local_dirty_after_commit",
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
            "local_revision",
            "remote_revision",
            "live_poll_enabled",
            "live_poll_interval_ms",
            "remote_update_detected",
            "remote_update_applied",
            "poll_suppressed_reason",
            "success_message_key",
            "success_message_rendered_once",
            "duplicate_success_message_suppressed",
            "rerun_after_commit",
            "autopick_triggered",
            "autopick_reason",
        )
        for key in keys:
            val = raw.get(key)
            st.text(f"{key}: {val if val is not None and val != '' else '—'}")
