"""Per-page filter persistence for sidebar navigation (not contextual transfers)."""

from __future__ import annotations

import copy

# Widget session keys (+ prefixes) owned by each page (stable names used by widgets).
PAGE_STATE_REGISTRY = {
    "Historical Explorer": {
        "exact": [
            "historical_year_range_filter", "historical_sort_stat_filter", "historical_sort_order_filter",
            "historical_batting_hand_filter", "historical_position_filter_mode", "historical_position_filter",
            "historical_team_filter", "historical_combine_split_seasons_filter",
            "hist_year", "hist_sort_stat", "hist_sort_order", "hist_bats", "hist_position_filter_mode",
            "hist_pos", "hist_team", "hist_combine_split_seasons",
        ],
        "prefixes": ["historical_", "hist_"],
    },
    "Career Totals": {
        "exact": [
            "career_year_range_filter", "career_sort_stat_filter", "career_batting_hand_filter",
            "career_position_filter_mode", "career_position_filter", "career_team_filter",
            "career_by_team_toggle_filter",
            "career_year", "career_sort", "career_bats", "career_position_filter_mode",
            "career_pos", "career_team", "career_by_team_toggle",
        ],
        "prefixes": ["career_"],
    },
    "Leaderboards": {
        "exact": ["leaders_year_range_filter", "leaders_top_n_filter", "leaders_sort_stat_filter", "leaders_year", "leaders_top_n", "leaders_sort"],
        "prefixes": ["leaders_"],
    },
    "Comparison Tool": {
        "exact": [
            "compare_players", "compare_players_saved", "compare_stat", "compare_x_axis_mode",
            "compare_year_range", "compare_age_range", "compare_trend_mode", "compare_smooth_window",
            "comparison_user_team",
            "compare_stat_saved", "compare_x_axis_mode_saved", "compare_year_range_saved",
            "compare_age_range_saved", "compare_trend_mode_saved", "compare_smooth_window_saved",
            "sig_player_a_clean", "sig_player_b_clean", "comparison_state",
        ],
        "prefixes": ["compare_", "sig_years_", "sig_player"],
    },
    "Trend Value": {
        "exact": [
            "trend_lag", "trend_min_g", "trend_position_filter",
            "trend_use_draft_room_sync", "trend_sync_team_for_draft",
            "trend_sort_col", "trend_players_multi", "single_trend_dashboard_player",
            "trend_plot_stat", "trend_chart_mode", "trend_smooth_window",
            "trend_anchor_fullname", "trend_multi_queue_fullnames",
            "trend_state",
            "single_trend_dashboard_stats", "single_trend_dashboard_mode",
            "single_trend_dashboard_smooth_window",
        ],
        "prefixes": ["trend_"],
    },
    "Valuation": {
        "exact": [
            "value_lag", "value_min_g", "value_position_filter",
            "value_use_draft_room_sync", "value_sync_team_for_draft",
            "value_w_current", "value_w_trend",
            "valuation_selected_player",
        ],
        "prefixes": ["value_"],
    },
    "ML Predictions": {
        "exact": [
            "ml_lookback", "ml_min_games", "ml_min_ab", "ml_max_players",
            "ml_projection_style", "ml_regression_strength", "ml_age_strength",
            "ml_comp_weight", "ml_k_neighbors", "ml_auto_apply_tuning",
            "ml_position_filter", "ml_sort_by", "ml_display_sort",
            "ml_projection_insight_player", "ml_predictions_selected_player",
            "ml_search_filter", "ml_table_row_count", "ml_confidence_filter",
            "ml_age_curve_stat", "ml_importance_stat",
            "ml_predictions_have_run",
        ],
        "prefixes": [],
    },
    "Fantasy Sleepers & Busts": {
        "exact": [
            "fantasy_market_window", "fantasy_market_format", "fantasy_market_min_g", "fantasy_market_min_ab",
            "fantasy_market_top_n", "fantasy_market_positions", "fantasy_market_age_range",
            "sleeper_max_market_rank", "sleeper_max_model_rank", "sleeper_min_proj_hr", "sleeper_min_expected_value",
            "sleeper_use_draft_room_needs", "sleeper_sync_team", "sleeper_focus_needed_positions",
            "fantasy_market_scatter_color", "fantasy_market_scatter_size", "fantasy_edge_scatter_view_mode",
            "fantasy_market_edge_trendline_type",
            "fantasy_pts_r", "fantasy_pts_rbi", "fantasy_pts_hr", "fantasy_pts_sb", "fantasy_pts_bb",
            "fantasy_pts_h", "fantasy_pts_xbh", "fantasy_pts_ab_penalty",
        ],
        "prefixes": ["fantasy_market_", "fantasy_pts_", "sleeper_"],
    },
    "Draft Assistant Simulator": {
        "exact": [
            "draft_window", "draft_format", "draft_top_n", "fantasy_draft_projection_style",
            "draft_use_ml_blend", "draft_ml_blend_weight", "draft_ml_min_games_signal",
            "draft_assistant_synced_team", "draft_pick_adjustment", "pending_draft_assistant_player",
        ],
        "prefixes": ["draft_need_positions_auto_", "draft_category_needs_auto_", "draft_assistant_"],
    },
    "Draft Room Simulator": {
        "exact": [
            "draft_room_roster_team_to_view", "draft_room_show_all_rosters",
            "room_your_team", "room_team_count", "room_rounds", "room_format", "room_window",
            "room_team_names", "fantasy_draft_projection_style",
        ],
        "prefixes": ["draft_room_", "room_"],
    },
    "Draft Simulation Test Mode": {
        "exact": [
            "draft_lab_window", "draft_lab_scoring_type", "draft_lab_format",
            "draft_lab_projection_style", "draft_lab_picks_per_team", "draft_lab_roster_team",
            "draft_lab_results",
        ],
        "prefixes": ["draft_lab_"],
    },
    "Live Draft Room": {
        "exact": [
            "live_draft_room", "live_draft_league_name", "live_draft_team_count", "live_draft_num_teams",
            "live_draft_picks_per_team", "live_draft_type", "live_draft_scoring", "live_draft_timer",
            "live_draft_auto_rule", "live_draft_proj_style", "live_draft_proj_window", "live_draft_setup_mode",
            "live_slot_c", "live_slot_1b", "live_slot_2b", "live_slot_3b", "live_slot_ss",
            "live_slot_of", "live_slot_dh", "live_slot_p", "live_slot_bench",
        ],
        "prefixes": ["live_draft_team_name_", "live_draft_", "live_slot_"],
    },
    "Fantasy Standings Tracker": {
        "exact": ["standings_scoring_format", "standings_stats_source", "standings_api_season"],
        "prefixes": ["standings_"],
    },
    "Fantasy Lineup Assistant": {
        "exact": [
            "lineup_team", "lineup_format", "lineup_bench_rows", "lineup_include_util", "lineup_custom_slots",
            "lineup_diagnosis_rate_col",
            "lineup_trade_my_team", "lineup_trade_other_team", "lineup_trade_give_players", "lineup_trade_get_players",
            "lineup_pts_r", "lineup_pts_rbi", "lineup_pts_hr", "lineup_pts_sb", "lineup_pts_h", "lineup_pts_bb", "lineup_pts_ops",
        ],
        "prefixes": ["lineup_"],
    },
}


_FILE_UPLOADER_WIDGET_KEYS = frozenset({
    "draft_room_import_uploader",
})


def _is_file_uploader_widget_key(key: str) -> bool:
    """file_uploader widget keys must never be restored into session_state."""
    k = str(key)
    if k in _FILE_UPLOADER_WIDGET_KEYS:
        return True
    if k.endswith("_uploader") or k.endswith("_file_uploader"):
        return True
    return False


def _is_ephemeral_widget_key(key: str) -> bool:
    """Button/action/file_uploader widget keys must not be snapshotted."""
    if _is_file_uploader_widget_key(key):
        return True
    k = str(key)
    if k.endswith("_button") or k.endswith("_btn"):
        if k in ("ml_predictions_refresh_button",):
            return False
        return True
    if k.startswith("live_draft_") and (
        k.endswith("_start")
        or k.endswith("_cancel")
        or "_confirm_" in k
        or "_convert_" in k
        or k.endswith("_save_btn")
        or k.endswith("_reset_btn")
        or k.endswith("_analyze_btn")
    ):
        return True
    if k.startswith("plr_act_") or k.startswith("ctx_go_"):
        return True
    if "compare_selected_action_" in k or k.startswith("sig_a_action_") or k.startswith("sig_b_action_"):
        return True
    if "_qa_" in k and any(
        tag in k
        for tag in ("_queue_", "_cmp_", "_tr_", "_da_", "_draft_", "_sim_", "_tacq_", "_taw_", "_proj_")
    ):
        return True
    return False


# Session keys that must never be snapshotted (action flags / large derived data).
_PAGE_STATE_SKIP_KEYS = frozenset({
    "ml_full_generation_requested",
    "ml_tuning_apply_requested",
    "ml_predictions_df",
    "draft_room_state",
    "draft_room_state_dirty",
    "draft_room_state_last_local_edit_ts",
    "draft_room_table",
    "draft_room_board_editor_cache",
    "draft_room_board_editor_seed",
    "draft_room_board_editor_version",
    "draft_room_import_uploader",
    "draft_room_import_uploaded_filename",
    "draft_room_import_last_processed_hash",
    "draft_room_import_pending_clear_token",
    "_simulator_to_live_show_confirm",
    "_start_live_draft_pending",
    "_start_live_draft_mode",
    "_live_draft_start_feedback",
    "_start_live_draft_trace",
})


def _global_snapshot_excluded_keys(session=None) -> frozenset[str]:
    try:
        from global_fantasy_settings_state import global_settings_snapshot_excluded_keys

        keys = set(global_settings_snapshot_excluded_keys())
    except ImportError:
        keys = set()
    if session is not None:
        try:
            from shared_draft_context import (
                has_active_draft_context,
                shared_draft_context_snapshot_excluded_keys,
            )

            if has_active_draft_context(session):
                keys.update(shared_draft_context_snapshot_excluded_keys())
        except ImportError:
            pass
    return frozenset(keys)


def _collect_keys_for_page(session, page_name: str) -> list:
    spec = PAGE_STATE_REGISTRY.get(page_name, {})
    keys = set(spec.get("exact", []))
    for prefix in spec.get("prefixes", []):
        for k in session:
            if isinstance(k, str) and k.startswith(prefix) and not _is_ephemeral_widget_key(k):
                if k not in _PAGE_STATE_SKIP_KEYS:
                    keys.add(k)
    keys -= _PAGE_STATE_SKIP_KEYS
    keys -= _global_snapshot_excluded_keys(session)
    return sorted(k for k in keys if not _is_ephemeral_widget_key(k))


def save_page_state(session, page_name: str, store: dict):
    """Snapshot widget keys for a page into ``store[page_name]``."""
    page_name = str(page_name)
    existing = store.get(page_name) if isinstance(store.get(page_name), dict) else {}
    snapshot = {}
    for key in _collect_keys_for_page(session, page_name):
        if key in session:
            try:
                snapshot[key] = copy.deepcopy(session[key])
            except Exception:
                snapshot[key] = session[key]
        elif key in existing:
            # on_change callbacks run before widgets render; keep prior snapshot
            # values for keys not yet repopulated in session this rerun.
            try:
                snapshot[key] = copy.deepcopy(existing[key])
            except Exception:
                snapshot[key] = existing[key]
    if snapshot:
        store[page_name] = snapshot


def restore_page_state(session, page_name: str, store: dict):
    """Restore a prior snapshot into session (sidebar return visits)."""
    if page_name == "Comparison Tool":
        try:
            from comparison_state import restore_comparison_page_filters

            return restore_comparison_page_filters(session, store)
        except ImportError:
            pass
    if page_name == "Trend Value":
        try:
            from trend_state import restore_trend_page_filters

            return restore_trend_page_filters(session, store)
        except ImportError:
            pass
    if page_name == "Live Draft Room":
        try:
            from live_draft_state import restore_live_draft_page_filters

            return restore_live_draft_page_filters(session, store)
        except ImportError:
            pass
    snapshot = store.get(page_name)
    if not snapshot:
        return False
    excluded = _global_snapshot_excluded_keys(session)
    for key, value in snapshot.items():
        if key in excluded:
            continue
        if _is_ephemeral_widget_key(key) or _is_file_uploader_widget_key(key):
            session.pop(key, None)
            continue
        try:
            session[key] = copy.deepcopy(value)
        except Exception:
            session[key] = value
    try:
        from global_fantasy_settings_state import mirror_canonical_to_all_aliases

        mirror_canonical_to_all_aliases(session)
    except ImportError:
        pass
    return True


def handle_sidebar_page_state(session, active_page: str, normalize_page_key, pending_transfer=None):
    """
    On sidebar page change: save leaving page, restore entering page.
    Skip restore when a contextual transfer targets the entering page.
    """
    session.setdefault("page_filter_state", {})
    store = session["page_filter_state"]
    curr = normalize_page_key(active_page)
    if session.pop("_suite_cloud_workspace_applied", None):
        cloud_page = str(session.get("_suite_cloud_target_page") or curr).strip()
        session["_page_state_last_active"] = cloud_page or curr
        return
    prev = session.get("_page_state_last_active")
    pending_target = None
    if pending_transfer and isinstance(pending_transfer, dict):
        pending_target = normalize_page_key(pending_transfer.get("target"))

    if prev and prev != curr:
        save_page_state(session, prev, store)
        session.pop("_transfer_just_applied_to", None)

    # Restore only when entering via sidebar — never when a contextual transfer or
    # player-action button navigates to this page (would overwrite freshly queued players).
    skip_restore = normalize_page_key(session.pop("_skip_page_restore_for", None) or "")
    ami_restore = normalize_page_key(session.get("_ami_return_restore_page") or "")
    if (
        prev != curr
        and pending_target != curr
        and skip_restore != curr
        and ami_restore != curr
    ):
        if curr == "Comparison Tool":
            try:
                from comparison_state import is_comparison_locally_dirty

                if is_comparison_locally_dirty(session):
                    session["_page_state_last_active"] = curr
                    return
            except ImportError:
                pass
        if curr == "Trend Value":
            try:
                from trend_state import is_trend_locally_dirty

                if is_trend_locally_dirty(session):
                    session["_page_state_last_active"] = curr
                    return
            except ImportError:
                pass
        restore_page_state(session, curr, store)

    session["_page_state_last_active"] = curr
