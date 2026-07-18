"""Disk persistence for Baseball Stat App (global + per-page filter store)."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import page_state as pg_state
from suite_user_persistence import (
    DATA_DIR,
    autosave_if_changed,
    clear_workspace_autosave_block,
    finalize_suite_reset,
    force_autosave,
    sync_workspace_protocol,
)

APP_ID = "baseball"
WORKSPACE_SCHEMA_VERSION = 1

_DEFAULT_PAGE = "Historical Explorer"
_DEFAULT_SIDEBAR_PAGE = "Historical Explorer"

_DRAFT_ROOM_SETTINGS_GLOBALS = frozenset(
    {
        "room_format",
        "room_team_count",
        "room_rounds",
        "room_your_team",
        "room_window",
        "fantasy_draft_projection_style",
        "draft_shared_settings",
    }
)

_MULTIPLAYER_SCOPED_GLOBALS = frozenset(
    {
        "draft_room_participant_team",
        "draft_room_participant_id",
        "room_your_team",
        "draft_room_participant_membership",
    }
)


def _multiplayer_restore_active(ss: dict[str, Any], state: dict[str, Any]) -> bool:
    code = str(
        ss.get("active_shared_draft_room_code")
        or state.get("active_shared_draft_room_code")
        or ""
    ).strip()
    if code:
        return True
    if state.get("draft_room_participant_membership"):
        return True
    return False

_GLOBAL_KEYS = (
    "active_page",
    "main_sidebar_page",
    "career_hof_case_mode",
    "career_hof_case_target_player",
    "_hof_case_packet",
    "comparison_user_team",
    "draft_room_table",
    "room_your_team",
    "room_team_count",
    "room_rounds",
    "room_format",
    "room_window",
    "fantasy_draft_projection_style",
    "draft_shared_settings",
    "active_shared_draft_room_code",
    "draft_room_participant_state",
    "draft_room_participant_id",
    "draft_room_participant_team",
    "draft_room_participant_membership",
    "draft_room_shared_meta",
    "allow_free_pool_drafting",
)

_HOF_HANDOFF_KEYS = (
    "_hof_case_insight_staged_for_resume",
    "_hof_case_submit_pending_insight",
    "_ami_force_insight_render",
    "_ami_last_submit_source_page",
    "_ami_submit_render_insight_this_run",
    "_ami_hydrated_insight_id",
    "_ami_insight_return_preserve",
    # `_skip_page_restore_for` is session-ephemeral. Persisting it in full_session poisoned
    # long-lived workspaces (e.g. Daniel stuck on Historical Explorer after sidebar clicks).
    "_hof_case_last_submit_diag",
    "_hof_case_pipeline_status",
    "_hof_case_pipeline_errors",
    "_hof_case_last_blob_persist_trace",
)

_INSIGHT_KEYS = (
    "_ami_pending_insight",
    "_ami_return_context",
    "_ami_dismissed_insight_ids",
    "_ami_dismissed_insight_at",
    "_ami_dismissed_question_ids",
)

_WORKSPACE_KEYS = (
    "comparison_state",
    "trend_state",
    "career_state",
    "draft_state",
    "draft_room_state",
    "live_draft_state",
    "historical_state",
    "valuation_state",
    "projections_state",
    "leaderboards_state",
    "fantasy_state",
)

_WORKFLOW_KEYS = (
    "draft_queue",
    "watchlist_focus",
    "watchlist_favorites",
    "workflow_recently_viewed",
    "workflow_recent_compare_pairs",
    "workflow_transfer_batches",
    "_queue_player_meta",
    "draft_archive_teams",
    "active_draft_archive_id",
    "fantasy_league_context_state",
    "_deleted_draft_archive_ids",
    "fantasy_in_season_state",
    "draft_lab_persisted_state",
    "use_active_league_context_waiver_filter",
    "use_live_draft_as_fantasy_context",
    "use_simulator_board_as_fantasy_context",
    "live_draft_termination_tombstones",
    "last_draft_board_snapshot",
    "resumable_live_draft_slot",
    "_live_draft_resume_lobby",
    "_live_draft_resume_reserved_teams",
    "_live_draft_resumable_op_receipt",
    "_waiver_pending_move_pairs",
    "waiver_planner_add_pick",
    "waiver_planner_drop_pick",
    "_waiver_tx_ui_flash",
    "waiver_manual_add_select",
    "waiver_manual_drop_select",
    "_draft_library_save_diag",
    "_draft_library_load_diag",
    "_draft_library_restore_diag",
    "_draft_save_button_trace",
    "_draft_save_trace_expand",
    "_draft_save_ui_flash",
    "_suite_last_invite_submit_trace",
    "_last_commissioner_invite_sent",
    "_last_commissioner_invite_submit_error",
    "_last_invite_shared_push_ok",
    "_last_invite_shared_push_error",
    "_last_invite_shared_league_id",
    "_suite_last_trade_submit_trace",
    "_suite_last_trade_response_trace",
    "_last_trade_proposal_submit_error",
    "_last_trade_proposal_submit_ok",
    "_last_trade_response_submit_error",
    "_last_trade_response_submit_ok",
    "trade_offer_inbox_dismissals",
)

_DEVICE_ID_FILE = DATA_DIR / f"{APP_ID}_device_id.txt"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _get_device_id(st: Any) -> str:
    ss = st.session_state
    key = "_suite_device_id"
    existing = ss.get(key)
    if existing:
        return str(existing)
    try:
        if _DEVICE_ID_FILE.is_file():
            did = _DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
            if did:
                ss[key] = did
                return did
    except OSError:
        pass
    did = uuid.uuid4().hex[:12]
    ss[key] = did
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _DEVICE_ID_FILE.write_text(did, encoding="utf-8")
    except OSError:
        pass
    return did


def _clear_page_widget_keys(session: dict[str, Any], page_name: str) -> None:
    for key in pg_state._collect_keys_for_page(session, page_name):
        session.pop(key, None)


def _page_block(state: dict[str, Any], page_name: str) -> dict[str, Any]:
    pf = state.get("page_filter_state")
    if not isinstance(pf, dict):
        return {}
    block = pf.get(page_name)
    return block if isinstance(block, dict) else {}


def _historical_filter_summary(block: dict[str, Any]) -> dict[str, Any]:
    try:
        from historical_state import _filters_from_block

        return _filters_from_block(block)
    except ImportError:
        keys = (
            "historical_year_range_filter",
            "historical_sort_stat_filter",
            "historical_sort_order_filter",
            "historical_batting_hand_filter",
            "historical_position_filter_mode",
            "historical_position_filter",
            "historical_team_filter",
            "historical_combine_split_seasons_filter",
        )
        return {k: block[k] for k in keys if k in block}


def _career_filter_summary(block: dict[str, Any]) -> dict[str, Any]:
    try:
        from career_totals_state import _filters_from_block
    except ImportError:
        return {}
    return _filters_from_block(block)


def _valuation_filter_summary(block: dict[str, Any]) -> dict[str, Any]:
    try:
        from valuation_state import _filters_from_block

        return _filters_from_block(block)
    except ImportError:
        return {}


def _projections_filter_summary(block: dict[str, Any]) -> dict[str, Any]:
    try:
        from projections_state import _filters_from_block

        return _filters_from_block(block)
    except ImportError:
        return {}


def _leaderboards_filter_summary(block: dict[str, Any]) -> dict[str, Any]:
    try:
        from leaderboards_state import _filters_from_block

        return _filters_from_block(block)
    except ImportError:
        return {}


def _fantasy_section_filter_summary(session: dict[str, Any], section: str) -> dict[str, Any] | None:
    try:
        from fantasy_state import _flat_from_meta_for_envelope

        return _flat_from_meta_for_envelope(session, section)
    except ImportError:
        return None


def _build_workspace_envelope(st: Any, state: dict[str, Any], *, save_reason: str) -> dict[str, Any]:
    cmp_block = _page_block(state, "Comparison Tool")
    trend_block = _page_block(state, "Trend Value")
    hist_block = _page_block(state, "Historical Explorer")
    career_block = _page_block(state, "Career Totals")
    draft_block = _page_block(state, "Draft Room Simulator") or _page_block(state, "Draft Room")
    cmp_meta = state.get("comparison_state") if isinstance(state.get("comparison_state"), dict) else {}
    comparison_players = cmp_meta.get("players") or cmp_block.get("compare_players")
    trend_meta = state.get("trend_state") if isinstance(state.get("trend_state"), dict) else {}
    trend_players = trend_meta.get("players_multi") or trend_block.get("trend_players_multi")
    trend_chart_player = trend_meta.get("chart_player") or trend_block.get("single_trend_dashboard_player")
    career_meta = state.get("career_state") if isinstance(state.get("career_state"), dict) else {}
    career_filters = career_meta.get("filters") or _career_filter_summary(career_block) or None
    hist_meta = state.get("historical_state") if isinstance(state.get("historical_state"), dict) else {}
    historical_filters = hist_meta.get("filters") or _historical_filter_summary(hist_block) or None
    val_block = _page_block(state, "Valuation")
    val_meta = state.get("valuation_state") if isinstance(state.get("valuation_state"), dict) else {}
    valuation_filters = None
    if val_meta:
        vf = dict(val_meta.get("filters") or {})
        if val_meta.get("selected_player"):
            vf["valuation_selected_player"] = val_meta["selected_player"]
        valuation_filters = vf or None
    if not valuation_filters:
        valuation_filters = _valuation_filter_summary(val_block) or None
    ml_block = _page_block(state, "ML Predictions")
    ml_meta = state.get("projections_state") if isinstance(state.get("projections_state"), dict) else {}
    projections_filters = None
    if ml_meta:
        try:
            from projections_state import _flat_from_meta

            projections_filters = _flat_from_meta(ml_meta) or None
        except ImportError:
            projections_filters = None
    if not projections_filters:
        projections_filters = _projections_filter_summary(ml_block) or None
    lb_block = _page_block(state, "Leaderboards")
    lb_meta = state.get("leaderboards_state") if isinstance(state.get("leaderboards_state"), dict) else {}
    leaderboards_filters = lb_meta.get("filters") or _leaderboards_filter_summary(lb_block) or None
    fantasy_meta = state.get("fantasy_state") if isinstance(state.get("fantasy_state"), dict) else {}
    fantasy_sleepers_filters = None
    fantasy_standings_filters = None
    fantasy_lineup_filters = None
    if fantasy_meta:
        try:
            from fantasy_state import _flat_from_meta_for_envelope

            fantasy_sleepers_filters = _flat_from_meta_for_envelope(state, "sleepers")
            fantasy_standings_filters = _flat_from_meta_for_envelope(state, "standings")
            fantasy_lineup_filters = _flat_from_meta_for_envelope(state, "lineup")
        except ImportError:
            pass
    if not fantasy_sleepers_filters:
        fantasy_sleepers_filters = _fantasy_section_filter_summary(state, "sleepers")
    if not fantasy_standings_filters:
        fantasy_standings_filters = _fantasy_section_filter_summary(state, "standings")
    if not fantasy_lineup_filters:
        fantasy_lineup_filters = _fantasy_section_filter_summary(state, "lineup")
    draft_meta = state.get("draft_state") if isinstance(state.get("draft_state"), dict) else {}
    draft_workflow = None
    if draft_meta:
        draft_workflow = {
            "queue": draft_meta.get("queue"),
            "watchlist_focus": draft_meta.get("watchlist_focus"),
            "watchlist_favorites": draft_meta.get("watchlist_favorites"),
        }
    if not draft_workflow or not any(draft_workflow.values()):
        try:
            from draft_state import _draft_workflow_from_blob

            draft_workflow = _draft_workflow_from_blob(state)
        except ImportError:
            draft_workflow = None
    live_draft_summary = None
    try:
        from live_draft_state import live_draft_envelope_summary

        live_draft_summary = live_draft_envelope_summary(state)
    except ImportError:
        live_draft_summary = None
    out = {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "updated_at": _utc_now_iso(),
        "device_id": _get_device_id(st),
        "save_reason": save_reason or "autosave",
        "page": state.get("active_page"),
        "comparison_players": comparison_players,
        "comparison_player_a": cmp_meta.get("player_a") or cmp_block.get("sig_player_a_clean"),
        "comparison_player_b": cmp_meta.get("player_b") or cmp_block.get("sig_player_b_clean"),
        "trend_players": trend_players or trend_block.get("trend_players_multi"),
        "trend_chart_player": trend_chart_player,
        "career_filters": career_filters,
        "historical_filters": historical_filters,
        "valuation_filters": valuation_filters,
        "projections_filters": projections_filters,
        "leaderboards_filters": leaderboards_filters,
        "fantasy_sleepers_filters": fantasy_sleepers_filters,
        "fantasy_standings_filters": fantasy_standings_filters,
        "fantasy_lineup_filters": fantasy_lineup_filters,
        "draft_state": {
            k: draft_block[k]
            for k in ("room_your_team", "room_team_count", "room_rounds", "room_format")
            if k in draft_block
        }
        or None,
        "draft_workflow": draft_workflow if draft_workflow and any(draft_workflow.values()) else None,
        "live_draft": live_draft_summary,
    }
    try:
        from draft_room_state import draft_room_restore_stats

        dr = draft_room_restore_stats(state)
        if dr.get("pick_count", 0) > 0:
            out["draft_room"] = {
                "pick_count": dr["pick_count"],
                "board_rows": dr.get("pool_count"),
            }
    except ImportError:
        pass
    return out


def build_baseball_disk_state(st: Any) -> dict[str, Any]:
    ss = st.session_state
    try:
        from draft_room_state import sync_draft_room_session_before_save

        sync_draft_room_session_before_save(ss)
    except ImportError:
        pass
    try:
        from live_draft_state import sync_live_draft_session_before_save

        sync_live_draft_session_before_save(ss)
    except ImportError:
        pass
    try:
        from draft_lab_state import sync_draft_lab_session_before_save

        sync_draft_lab_session_before_save(ss)
    except ImportError:
        pass
    active = ss.get("active_page")
    if active:
        try:
            store = ss.setdefault("page_filter_state", {})
            if not isinstance(store, dict):
                store = {}
                ss["page_filter_state"] = store
            pg_state.save_page_state(ss, str(active), store)
        except Exception:
            pass
    state: dict[str, Any] = {}
    for key in _GLOBAL_KEYS:
        if key in ss:
            val = ss[key]
            try:
                state[key] = copy.deepcopy(val)
            except Exception:
                state[key] = val
    store = ss.get("page_filter_state")
    if isinstance(store, dict) and store:
        state["page_filter_state"] = copy.deepcopy(store)
    for key in _INSIGHT_KEYS + _HOF_HANDOFF_KEYS + _WORKSPACE_KEYS:
        if key in ss:
            try:
                state[key] = copy.deepcopy(ss[key])
            except Exception:
                state[key] = ss[key]
    for key in _WORKFLOW_KEYS:
        if key in ss:
            try:
                from account_fantasy_preferences import ACCOUNT_OWNED_SESSION_KEYS

                if key in ACCOUNT_OWNED_SESSION_KEYS:
                    continue
            except ImportError:
                if key in (
                    "use_active_league_context_waiver_filter",
                    "use_live_draft_as_fantasy_context",
                    "use_simulator_board_as_fantasy_context",
                    "sync_draft_assistant_position_needs",
                ):
                    continue
            try:
                state[key] = copy.deepcopy(ss[key])
            except Exception:
                state[key] = ss[key]
    save_reason = str(ss.get("_suite_pending_save_reason") or "autosave")
    try:
        from workflow_persist_guard import inject_session_draft_library_into_save_state, is_draft_library_mutation_save_reason

        if is_draft_library_mutation_save_reason(save_reason):
            state = inject_session_draft_library_into_save_state(state, ss)
    except ImportError:
        pass
    try:
        from fantasy_in_season_state import sync_fantasy_in_season_state

        sync_fantasy_in_season_state(ss, reason=save_reason)
    except ImportError:
        pass
    try:
        from draft_lab_state import sync_draft_lab_results_state

        sync_draft_lab_results_state(ss)
    except ImportError:
        pass
    try:
        from workflow_persist_guard import merge_protected_workflow_into_save

        state = merge_protected_workflow_into_save(
            state,
            ss,
            app_id=APP_ID,
            st=st,
            save_reason=save_reason,
        )
    except ImportError:
        pass
    ss.pop("_suite_pending_save_reason", None)
    state["baseball_workspace_state"] = _build_workspace_envelope(st, state, save_reason=save_reason)
    try:
        from draft_room_state import enrich_save_payload_with_draft_room, sanitize_state_dict_for_json as sanitize_draft_room
        from live_draft_state import enrich_save_payload_with_live_draft, sanitize_state_dict_for_json

        state, _ = enrich_save_payload_with_draft_room(ss, state)
        state, _ = enrich_save_payload_with_live_draft(ss, state)
        state = sanitize_state_dict_for_json(state)
        state = sanitize_draft_room(state)
    except ImportError:
        pass
    try:
        import json

        json.dumps(state)
    except (TypeError, ValueError):
        try:
            from dataframe_utils import sanitize_for_json

            state = sanitize_for_json(state)
        except ImportError:
            pass
    return state


def _comparison_players_from_workspace_blob(state: dict[str, Any]) -> list[str] | None:
    cs = state.get("comparison_state")
    if isinstance(cs, dict):
        players = cs.get("players")
        if isinstance(players, list):
            return [str(p) for p in players if p][:3]
    meta = state.get("baseball_workspace_state")
    if isinstance(meta, dict):
        cp = meta.get("comparison_players")
        if isinstance(cp, list):
            return [str(p) for p in cp if p][:3]
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get("Comparison Tool")
        if isinstance(block, dict):
            cp = block.get("compare_players")
            if isinstance(cp, list):
                return [str(p) for p in cp if p][:3]
            inner = block.get("comparison_state")
            if isinstance(inner, dict) and isinstance(inner.get("players"), list):
                return [str(p) for p in inner["players"] if p][:3]
    return None


def apply_baseball_disk_state(st: Any, state: dict[str, Any]) -> None:
    """Apply one authoritative workspace blob atomically (page + all page_filter_state)."""
    ss = st.session_state
    identity_snapshot: dict[str, Any] = {}
    try:
        from suite_identity_guard import snapshot_protected_browser_identity

        identity_snapshot = snapshot_protected_browser_identity(ss)
    except ImportError:
        try:
            from suite_auth import snapshot_auth_session

            identity_snapshot = {"auth": snapshot_auth_session(ss), "workspace": {}}
        except ImportError:
            pass
    pre_restore_session_page = str(ss.get("active_page") or "").strip()
    pre_restore_user_nav = bool(ss.get("_suite_page_user_nav"))
    skip_draft_room = False
    try:
        from draft_room_state import DRAFT_ROOM_STATE_KEY, DRAFT_ROOM_TABLE_KEY, is_draft_room_locally_dirty

        skip_draft_room = is_draft_room_locally_dirty(ss)
    except ImportError:
        DRAFT_ROOM_STATE_KEY = "draft_room_state"
        DRAFT_ROOM_TABLE_KEY = "draft_room_table"

    # Add-to-Queue mutates session in on_click before this restore runs. Stale disk/cloud
    # blobs with empty draft_queue were wiping the just-added player on every rerun.
    skip_draft_workflow = False
    try:
        from draft_state import is_draft_locally_dirty

        skip_draft_workflow = bool(is_draft_locally_dirty(ss) or ss.get("_draft_workflow_pending_sync"))
    except ImportError:
        skip_draft_workflow = bool(ss.get("draft_state_dirty") or ss.get("_draft_workflow_pending_sync"))
    if not skip_draft_workflow:
        try:
            from live_draft_queue_persist import is_draft_queue_persist_dirty

            skip_draft_workflow = is_draft_queue_persist_dirty(ss)
        except ImportError:
            skip_draft_workflow = bool(ss.get("_draft_queue_persist_dirty"))
    # Later-pass wipe: dirty may already be cleared after flush, but session still
    # has a populated queue while the blob carries []. Prefer live session.
    if not skip_draft_workflow:
        sess_q = [str(x).strip() for x in (ss.get("draft_queue") or []) if str(x).strip()]
        blob_q = [str(x).strip() for x in (state.get("draft_queue") or []) if str(x).strip()]
        ds = state.get("draft_state") if isinstance(state.get("draft_state"), dict) else {}
        blob_ds_q = [str(x).strip() for x in (ds.get("queue") or []) if str(x).strip()]
        if sess_q and not blob_q and not blob_ds_q:
            skip_draft_workflow = True
            ss["_live_draft_queue_blob_restore_skipped"] = "refuse_empty_blob_over_session"
            try:
                from live_draft_queue_survival import note_queue_survival, record_queue_write

                record_queue_write(
                    ss,
                    function="apply_baseball_disk_state",
                    reason="refuse_empty_blob_over_session",
                    old_session_queue=sess_q,
                    new_session_queue=sess_q,
                    blocked=True,
                    source="workspace_blob",
                )
                note_queue_survival(
                    ss,
                    "blob_restore_skip",
                    detail="refused empty blob overwrite of populated session queue",
                    st=st,
                )
            except ImportError:
                pass
    _DRAFT_WORKFLOW_RESTORE_KEYS = frozenset(
        {
            "draft_state",
            "draft_queue",
            "draft_assistant_focus_players",
            "watchlist_focus",
            "watchlist_favorites",
            "_queue_player_meta",
            "_suite_last_cloud_payload_draft_workflow",
        }
    )
    if skip_draft_workflow:
        if not ss.get("_live_draft_queue_blob_restore_skipped"):
            ss["_live_draft_queue_blob_restore_skipped"] = "local_dirty_or_pending"
        try:
            from live_draft_queue_survival import note_queue_survival

            note_queue_survival(
                ss,
                "blob_restore_skip",
                detail="apply_baseball_disk_state skipped draft_queue/draft_state overwrite",
                st=st,
            )
        except ImportError:
            pass
    else:
        ss.pop("_live_draft_queue_blob_restore_skipped", None)

    preserve_insight = bool(ss.get("_ami_insight_return_preserve"))
    multiplayer_restore = _multiplayer_restore_active(ss, state)
    foreign_blob = False
    foreign_reason = ""
    try:
        from live_draft_state import workspace_blob_owned_by_session

        owned, foreign_reason = workspace_blob_owned_by_session(ss, state)
        foreign_blob = not owned
        if foreign_blob:
            ss["_live_draft_restore_blocked_reason"] = foreign_reason
    except Exception as exc:
        ss["_live_draft_restore_blocked_reason"] = f"ownership_check_failed:{type(exc).__name__}"

    _FOREIGN_GLOBAL_KEYS = frozenset(
        {
            "room_your_team",
            "room_format",
            "room_team_count",
            "room_rounds",
            "room_window",
            "fantasy_draft_projection_style",
            "draft_shared_settings",
            "allow_free_pool_drafting",
            "live_draft_state",
            "live_draft_room",
        }
    )

    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        new_pf = copy.deepcopy(pf)
        existing_pf = ss.get("page_filter_state")
        if isinstance(existing_pf, dict):
            if skip_draft_room:
                dr_block = existing_pf.get("Draft Room Simulator")
                if isinstance(dr_block, dict):
                    new_pf["Draft Room Simulator"] = copy.deepcopy(dr_block)
            if skip_draft_workflow:
                # Preserve local Draft Workflow block (queue) over stale blob empty.
                try:
                    from draft_state import DRAFT_WORKFLOW_BLOCK

                    dw_block = existing_pf.get(DRAFT_WORKFLOW_BLOCK)
                except ImportError:
                    dw_block = existing_pf.get("Draft Workflow")
                if isinstance(dw_block, dict):
                    new_pf["Draft Workflow"] = copy.deepcopy(dw_block)
        ss["page_filter_state"] = new_pf
        if foreign_blob and isinstance(ss.get("page_filter_state"), dict):
            pf_live = ss["page_filter_state"].get("Live Draft Room")
            if isinstance(pf_live, dict):
                pf_live.pop("live_draft_room", None)
    else:
        ss.setdefault("page_filter_state", {})

    # Settings widgets (room_*) are part of _GLOBAL_KEYS but are also owned by the
    # draft-room blob. When the user edits settings, draft_room_state_dirty is set
    # (via mark_draft_room_local_edit on_change) and we must not let the cloud blob
    # overwrite their live edits on the very next rerun.
    auth_nav_lock = bool(
        str(ss.get("_suite_auth_preserve_page") or "").strip()
        or ss.get("active_page_source") == "auth_preserve"
    )
    for key in _GLOBAL_KEYS + _INSIGHT_KEYS + _HOF_HANDOFF_KEYS + _WORKSPACE_KEYS + _WORKFLOW_KEYS:
        if key not in state:
            continue
        # Account preference document owns these fields — never restore from full_session.
        try:
            from account_fantasy_preferences import ACCOUNT_OWNED_SESSION_KEYS

            if key in ACCOUNT_OWNED_SESSION_KEYS:
                continue
        except ImportError:
            if key in (
                "use_active_league_context_waiver_filter",
                "use_live_draft_as_fantasy_context",
                "use_simulator_board_as_fantasy_context",
                "sync_draft_assistant_position_needs",
            ):
                continue
        if foreign_blob and key in _FOREIGN_GLOBAL_KEYS:
            continue
        if multiplayer_restore and key in _MULTIPLAYER_SCOPED_GLOBALS:
            continue
        if skip_draft_room and key in (DRAFT_ROOM_TABLE_KEY, DRAFT_ROOM_STATE_KEY):
            continue
        if skip_draft_room and key in _DRAFT_ROOM_SETTINGS_GLOBALS:
            continue
        if skip_draft_workflow and key in _DRAFT_WORKFLOW_RESTORE_KEYS:
            continue
        if auth_nav_lock and key in (
            "active_page",
            "main_sidebar_page",
            "_skip_page_restore_for",
            "_navigate_to_page",
        ):
            continue
        # Never re-inject durable/stale skip targets over an explicit sidebar hop.
        if key == "_skip_page_restore_for" and (
            pre_restore_user_nav
            or str(ss.get("_suite_user_owned_page") or "").strip()
            or ss.get("active_page_source") in ("user_sidebar", "auth_preserve")
        ):
            continue
        if preserve_insight and key in _INSIGHT_KEYS + _HOF_HANDOFF_KEYS:
            if key == "_ami_pending_insight" and isinstance(val, dict):
                session_pending = ss.get("_ami_pending_insight")
                session_valid = isinstance(session_pending, dict) and bool(
                    str(session_pending.get("conclusion") or session_pending.get("short_answer") or "").strip()
                )
                blob_valid = bool(str(val.get("conclusion") or val.get("short_answer") or "").strip())
                if session_valid or not blob_valid:
                    continue
            else:
                continue
        val = state[key]
        if key == "_ami_pending_insight" and isinstance(val, dict):
            iid = str(val.get("insight_id") or "").strip()
            qid = str(val.get("question_id") or "").strip()
            session_dismissed = ss.get("_ami_dismissed_insight_ids")
            blob_dismissed = state.get("_ami_dismissed_insight_ids")
            dismissed_raw = session_dismissed if session_dismissed is not None else blob_dismissed
            if not isinstance(dismissed_raw, (list, tuple, set)):
                dismissed_raw = []
            dismissed_ids = {str(x).strip() for x in dismissed_raw if str(x).strip()}
            session_q_dismissed = ss.get("_ami_dismissed_question_ids")
            blob_q_dismissed = state.get("_ami_dismissed_question_ids")
            q_dismissed_raw = session_q_dismissed if session_q_dismissed is not None else blob_q_dismissed
            if not isinstance(q_dismissed_raw, (list, tuple, set)):
                q_dismissed_raw = []
            dismissed_qids = {str(x).strip() for x in q_dismissed_raw if str(x).strip()}
            if iid and iid in dismissed_ids:
                continue
            if qid and not iid and qid in dismissed_qids:
                continue
        if key == "_ami_dismissed_insight_ids":
            existing = ss.get("_ami_dismissed_insight_ids")
            blob_ids = val if isinstance(val, (list, tuple, set)) else []
            merged = {str(x).strip() for x in blob_ids if str(x).strip()}
            if isinstance(existing, (list, tuple, set)):
                merged.update(str(x).strip() for x in existing if str(x).strip())
            ss[key] = sorted(merged)
            continue
        if key == "_ami_dismissed_insight_at":
            existing = dict(ss.get("_ami_dismissed_insight_at") or {})
            if not isinstance(existing, dict):
                existing = {}
            blob_at = val if isinstance(val, dict) else {}
            merged_at = dict(blob_at)
            merged_at.update(existing)
            ss[key] = merged_at
            continue
        if key == "_ami_dismissed_question_ids":
            existing = ss.get("_ami_dismissed_question_ids")
            blob_ids = val if isinstance(val, (list, tuple, set)) else []
            merged = {str(x).strip() for x in blob_ids if str(x).strip()}
            if isinstance(existing, (list, tuple, set)):
                merged.update(str(x).strip() for x in existing if str(x).strip())
            ss[key] = sorted(merged)
            continue
        if key == "_hof_case_submit_pending_insight" and isinstance(val, dict):
            qid = str(val.get("question_id") or "").strip()
            iid = str(val.get("insight_id") or "").strip()
            dismissed_q = {str(x).strip() for x in (ss.get("_ami_dismissed_question_ids") or state.get("_ami_dismissed_question_ids") or []) if str(x).strip()}
            dismissed_i = {str(x).strip() for x in (ss.get("_ami_dismissed_insight_ids") or state.get("_ami_dismissed_insight_ids") or []) if str(x).strip()}
            if iid and iid in dismissed_i:
                continue
            if qid and not iid and qid in dismissed_q:
                continue
        if key == "page_filter_state" and isinstance(val, dict):
            continue
        if key in ("_draft_library_save_diag", "_draft_save_button_trace"):
            session_diag = ss.get(key)
            if isinstance(session_diag, dict) and (
                session_diag.get("save_request_received") or session_diag.get("save_requested")
            ):
                blob_diag = val if isinstance(val, dict) else {}
                session_at = str(
                    session_diag.get("save_request_at")
                    or session_diag.get("requested_at")
                    or session_diag.get("finalized_at")
                    or ""
                )
                blob_at = str(
                    blob_diag.get("save_request_at")
                    or blob_diag.get("requested_at")
                    or blob_diag.get("finalized_at")
                    or ""
                )
                if not blob_diag or (session_at and (not blob_at or session_at >= blob_at)):
                    continue
        try:
            from workflow_persist_guard import (
                PROTECTED_WORKFLOW_PERSIST_KEYS,
                should_keep_session_workflow_over_blob,
                should_skip_empty_blob_workflow_over_persisted,
            )

            if key in PROTECTED_WORKFLOW_PERSIST_KEYS and should_keep_session_workflow_over_blob(
                key, ss.get(key), val
            ):
                continue
            if key in PROTECTED_WORKFLOW_PERSIST_KEYS and should_skip_empty_blob_workflow_over_persisted(
                key, val, app_id=APP_ID, st=st
            ):
                continue
        except ImportError:
            pass
        try:
            new_val = copy.deepcopy(val)
        except Exception:
            new_val = val
        if key in (
            "active_page",
            "main_sidebar_page",
            "_skip_page_restore_for",
            "_navigate_to_page",
        ):
            try:
                from nav_page_trace import assign_nav_key

                assign_nav_key(
                    ss,
                    key,
                    new_val,
                    function="apply_baseball_disk_state.copy_blob_key",
                    reason=f"workspace blob restore key={key}",
                    st=st,
                )
            except ImportError:
                ss[key] = new_val
        else:
            ss[key] = new_val

    try:
        from workflow_persist_guard import merge_protected_workflow_on_restore

        merge_protected_workflow_on_restore(ss, state, st=st)
    except ImportError:
        pass

    blob_page = str(state.get("active_page") or "").strip()
    session_page_after_blob = str(ss.get("active_page") or "").strip()
    try:
        from nav_page_trace import note_nav_snapshot

        note_nav_snapshot(
            ss,
            function="apply_baseball_disk_state",
            reason="after_blob_key_copy",
            st=st,
            blob_page=blob_page,
            pre_restore_session_page=pre_restore_session_page,
            pre_restore_user_nav=pre_restore_user_nav,
        )
    except ImportError:
        pass
    last_persisted = str(ss.get("_suite_last_persisted_page") or "").strip()
    auth_preserve_page = ""
    owned_page = ""
    try:
        from suite_user_persistence import AUTH_PAGE_PRESERVE_KEY, SESSION_USER_OWNED_PAGE_KEY

        auth_preserve_page = str(ss.get(AUTH_PAGE_PRESERVE_KEY) or "").strip()
        owned_page = str(ss.get(SESSION_USER_OWNED_PAGE_KEY) or "").strip()
    except ImportError:
        auth_preserve_page = str(ss.get("_suite_auth_preserve_page") or "").strip()
        owned_page = str(ss.get("_suite_user_owned_page") or "").strip()
    preferred_page = ""
    if auth_preserve_page:
        preferred_page = auth_preserve_page
    elif owned_page and (
        owned_page == pre_restore_session_page
        or owned_page == last_persisted
        or pre_restore_user_nav
        or ss.get("active_page_source") in ("auth_preserve", "user_sidebar")
    ):
        preferred_page = owned_page
    user_owns_page = bool(
        pre_restore_user_nav
        or preferred_page
        or (
            pre_restore_session_page
            and last_persisted
            and pre_restore_session_page == last_persisted
        )
    )
    active = blob_page
    overwrite_source = "workspace_blob"
    if preferred_page:
        active = preferred_page
        overwrite_source = "auth_page_preserved" if auth_preserve_page else "user_page_preserved"
    elif (
        user_owns_page
        and pre_restore_session_page
        and blob_page
        and pre_restore_session_page != blob_page
    ):
        active = pre_restore_session_page
        overwrite_source = "user_page_preserved"
    elif blob_page:
        active = blob_page
    elif pre_restore_session_page:
        active = pre_restore_session_page
    elif session_page_after_blob:
        active = session_page_after_blob
    ss["_suite_page_overwrite_source"] = overwrite_source
    resume_page = str(ss.get("_navigate_to_page") or "").strip()
    skip_for = str(ss.get("_skip_page_restore_for") or "").strip()
    resume_from_skip_only = False
    if not resume_page and skip_for:
        resume_page = skip_for
        resume_from_skip_only = True
    if (
        ss.get("_suite_pending_draft_lab_resume")
        and resume_page
        and not ss.get("_draft_lab_resume_completed")
    ):
        active = resume_page
        overwrite_source = "draft_lab_resume_preserved"
        ss["_suite_page_overwrite_source"] = overwrite_source
    elif (
        ss.get("_suite_pending_hof_case_resume")
        and resume_page
        and not ss.get("_hof_case_resume_completed")
    ):
        active = resume_page
        overwrite_source = "hof_case_resume_preserved"
        ss["_suite_page_overwrite_source"] = overwrite_source
    elif (
        str(ss.get("_skip_page_restore_for") or "").strip() == "Career Totals"
        and resume_page == "Career Totals"
        and not ss.get("_hof_case_resume_completed")
    ):
        active = resume_page
        overwrite_source = "hof_case_skip_restore_preserved"
        ss["_suite_page_overwrite_source"] = overwrite_source
    elif resume_page and resume_page != active:
        # Explicit `_navigate_to_page` still wins. A skip-only resume from an old
        # workspace blob must not yank the user off a sidebar/owned page.
        user_intent = (
            preferred_page
            or owned_page
            or (pre_restore_session_page if pre_restore_user_nav else "")
        )
        if resume_from_skip_only and user_intent and resume_page != user_intent:
            ss.pop("_skip_page_restore_for", None)
            if active != user_intent:
                active = user_intent
                overwrite_source = "user_page_preserved"
                ss["_suite_page_overwrite_source"] = overwrite_source
        else:
            active = resume_page
            overwrite_source = "scheduled_navigation_preserved"
            ss["_suite_page_overwrite_source"] = overwrite_source
    consumed_target = str(ss.get("_suite_nav_consumed_target") or "").strip()
    if consumed_target:
        user_intent = (
            preferred_page
            or owned_page
            or (pre_restore_session_page if pre_restore_user_nav else "")
        )
        if user_intent and consumed_target != user_intent and consumed_target != active:
            # Stale consume marker from a prior blob/page — do not override sidebar intent.
            ss.pop("_suite_nav_consumed_target", None)
            ss.pop("_suite_nav_consumed_this_run", None)
        else:
            active = consumed_target
            overwrite_source = "nav_consumed_preserved"
            ss["_suite_page_overwrite_source"] = overwrite_source
    if active:
        # Only clear widget keys and restore from snapshot when navigating to a
        # different page (or on fresh-session startup where pre_restore_session_page
        # is empty).  When the user is already on `active` and merely interacted
        # with a widget, we must NOT clear their new input: the snapshot still has
        # the previous-rerun values and would overwrite whatever the user just typed.
        page_actually_changed = active != pre_restore_session_page
        if page_actually_changed:
            _clear_page_widget_keys(ss, active)
        try:
            from nav_page_trace import assign_nav_key, log_nav_event

            assign_nav_key(
                ss,
                "active_page",
                active,
                function="apply_baseball_disk_state.finalize",
                reason=f"overwrite_source={overwrite_source}",
                st=st,
            )
            assign_nav_key(
                ss,
                "main_sidebar_page",
                active,
                function="apply_baseball_disk_state.finalize",
                reason=f"overwrite_source={overwrite_source}",
                st=st,
            )
            log_nav_event(
                ss,
                function="apply_baseball_disk_state.finalize",
                reason="page_decision",
                key="resume_page",
                previous=pre_restore_session_page,
                new=active,
                extra={
                    "overwrite_source": overwrite_source,
                    "blob_page": blob_page,
                    "preferred_page": preferred_page,
                    "owned_page": owned_page,
                    "skip_for": skip_for,
                    "resume_from_skip_only": resume_from_skip_only,
                    "consumed_target": consumed_target,
                },
                st=st,
            )
        except ImportError:
            ss["active_page"] = active
            ss["main_sidebar_page"] = active
        pending_nav = str(ss.get("_navigate_to_page") or "").strip()
        # Keep a real redirect schedule (even after we mirror it into active). Do not leave a
        # sticky same-page schedule from ordinary restore — that re-forces the old page on
        # the next consume and fights the sidebar (Historical Explorer stuck).
        _keep_scheduled = overwrite_source in {
            "scheduled_navigation_preserved",
            "draft_lab_resume_preserved",
            "hof_case_resume_preserved",
            "hof_case_skip_restore_preserved",
        }
        if pending_nav and (pending_nav != active or _keep_scheduled):
            pass
        else:
            try:
                from nav_page_trace import assign_nav_key

                assign_nav_key(
                    ss,
                    "_navigate_to_page",
                    None,
                    function="apply_baseball_disk_state.finalize",
                    reason="clear sticky same-page navigate",
                    st=st,
                )
            except ImportError:
                ss.pop("_navigate_to_page", None)
        try:
            from nav_page_trace import assign_nav_key

            assign_nav_key(
                ss,
                "_suite_last_persisted_page",
                active,
                function="apply_baseball_disk_state.finalize",
                reason=f"overwrite_source={overwrite_source}",
                st=st,
            )
        except ImportError:
            ss["_suite_last_persisted_page"] = active
        ss.pop("_suite_cloud_target_page", None)
        if page_actually_changed:
            try:
                from comparison_state import clear_comparison_local_edit, restore_comparison_page_filters

                clear_comparison_local_edit(ss)
                try:
                    from career_totals_state import clear_career_local_edit

                    clear_career_local_edit(ss)
                except ImportError:
                    pass
                try:
                    from draft_state import clear_draft_local_edit

                    clear_draft_local_edit(ss)
                except ImportError:
                    pass
                try:
                    from historical_state import clear_historical_local_edit

                    clear_historical_local_edit(ss)
                except ImportError:
                    pass
                try:
                    from valuation_state import clear_valuation_local_edit

                    clear_valuation_local_edit(ss)
                except ImportError:
                    pass
                try:
                    from projections_state import clear_projections_local_edit

                    clear_projections_local_edit(ss)
                except ImportError:
                    pass
                try:
                    from leaderboards_state import clear_leaderboards_local_edit

                    clear_leaderboards_local_edit(ss)
                except ImportError:
                    pass
                try:
                    from fantasy_state import clear_fantasy_local_edit

                    clear_fantasy_local_edit(ss)
                except ImportError:
                    pass
                if active == "Comparison Tool":
                    restore_comparison_page_filters(ss, ss["page_filter_state"])
                elif active == "Trend Value":
                    from trend_state import restore_trend_page_filters

                    restore_trend_page_filters(ss, ss["page_filter_state"])
                elif active == "Valuation":
                    from valuation_state import restore_valuation_page_filters

                    restore_valuation_page_filters(ss, ss["page_filter_state"])
                elif active == "ML Predictions":
                    from projections_state import restore_projections_page_filters

                    restore_projections_page_filters(ss, ss["page_filter_state"])
                elif active == "Leaderboards":
                    from leaderboards_state import restore_leaderboards_page_filters

                    restore_leaderboards_page_filters(ss, ss["page_filter_state"])
                elif active in ("Fantasy Sleepers & Busts", "Fantasy Standings Tracker", "Fantasy Lineup Assistant"):
                    from fantasy_state import restore_fantasy_page_filters

                    restore_fantasy_page_filters(ss, ss["page_filter_state"], active)
                elif active == "Live Draft Room":
                    from live_draft_state import restore_live_draft_page_filters

                    restore_live_draft_page_filters(ss, ss["page_filter_state"])
                else:
                    pg_state.restore_page_state(ss, active, ss["page_filter_state"])
            except ImportError:
                pg_state.restore_page_state(ss, active, ss["page_filter_state"])
        ss["_page_state_last_active"] = active
        # After any page navigation or fresh load, push the canonical team/format into all
        # per-page alias keys.  This ensures that a team/format change made on one page
        # propagates to every page rather than being overwritten by a stale snapshot.
        try:
            from global_fantasy_settings_state import mirror_canonical_to_all_aliases

            mirror_canonical_to_all_aliases(ss)
        except ImportError:
            pass
        try:
            from shared_draft_context import (
                apply_draft_shared_settings_to_widgets,
                hydrate_canonical_draft_settings_from_session,
                record_cloud_draft_settings_snapshot,
            )

            record_cloud_draft_settings_snapshot(ss, state)
            hydrate_canonical_draft_settings_from_session(ss)
            apply_draft_shared_settings_to_widgets(ss)
        except ImportError:
            pass
        try:
            from settings_persistence_trace import record_restore_event

            record_restore_event(ss, cloud_state=state, page=active)
        except Exception:
            pass
        try:
            from comparison_state import record_comparison_field_write

            record_comparison_field_write(ss, "active_page", "workspace_restore", new=active)
        except ImportError:
            pass

    try:
        from comparison_state import clear_comparison_local_edit, is_comparison_locally_dirty, write_canonical_comparison_state

        if not is_comparison_locally_dirty(ss):
            restored_players = _comparison_players_from_workspace_blob(state)
            if restored_players is not None:
                write_canonical_comparison_state(ss, restored_players, reason="workspace_restore")
                clear_comparison_local_edit(ss)
                ss["_comparison_restored_players"] = list(restored_players)
                ss["_comparison_restore_source"] = ss.get("_suite_persist_last_restore_source", "workspace")
    except ImportError:
        pass

    try:
        from trend_state import clear_trend_local_edit, is_trend_locally_dirty, write_canonical_trend_state

        if not is_trend_locally_dirty(ss):
            ts = state.get("trend_state")
            chart_player = None
            players_multi = None
            if isinstance(ts, dict):
                if "chart_player" in ts:
                    chart_player = ts.get("chart_player") or ""
                if isinstance(ts.get("players_multi"), list):
                    players_multi = [str(p) for p in ts["players_multi"] if p]
            if players_multi is None:
                pf = state.get("page_filter_state")
                if isinstance(pf, dict):
                    block = pf.get("Trend Value")
                    if isinstance(block, dict):
                        if chart_player is None and block.get("single_trend_dashboard_player"):
                            chart_player = str(block.get("single_trend_dashboard_player"))
                        tm = block.get("trend_players_multi")
                        if isinstance(tm, list):
                            players_multi = [str(p) for p in tm if p]
            meta_ws = state.get("baseball_workspace_state")
            if isinstance(meta_ws, dict):
                if players_multi is None and isinstance(meta_ws.get("trend_players"), list):
                    players_multi = [str(p) for p in meta_ws["trend_players"] if p]
                if chart_player is None and meta_ws.get("trend_chart_player"):
                    chart_player = str(meta_ws.get("trend_chart_player"))
            if chart_player is not None or players_multi is not None:
                write_canonical_trend_state(
                    ss,
                    chart_player=chart_player if chart_player is not None else "",
                    players_multi=players_multi if players_multi is not None else [],
                    reason="workspace_restore",
                )
                clear_trend_local_edit(ss)
                ss["_trend_restored_players_multi"] = list(players_multi or [])
                ss["_trend_restore_source"] = ss.get("_suite_persist_last_restore_source", "workspace")
    except ImportError:
        pass

    try:
        from career_totals_state import apply_cloud_career_state_if_allowed

        apply_cloud_career_state_if_allowed(ss, state)
    except ImportError:
        pass

    try:
        from draft_state import apply_cloud_draft_state_if_allowed, prepare_draft_workflow

        apply_cloud_draft_state_if_allowed(ss, state)
        prepare_draft_workflow(ss)
    except ImportError:
        pass

    try:
        from draft_room_state import apply_cloud_draft_room_state_if_allowed, prepare_draft_room_state

        apply_cloud_draft_room_state_if_allowed(ss, state)
        prepare_draft_room_state(ss)
        try:
            from draft_room_state import draft_room_restore_stats

            dr = draft_room_restore_stats(ss)
            ss["restored_draft_room_pick_count"] = dr.get("pick_count")
            ss["restore_source"] = ss.get("_draft_room_restore_source") or ss.get("_suite_restore_pick_source")
            ss["restore_reason"] = ss.get("_suite_restore_pick_reason") or ss.get("restore_winner_reason_detail")
            ss["local_has_draft_room_board"] = dr.get("has_draft_board")
            ss["session_pick_count"] = dr.get("pick_count")
            cloud_dr = draft_room_restore_stats(state)
            ss["cloud_has_draft_room_board"] = cloud_dr.get("has_draft_board")
            ss["cloud_draft_room_pick_count"] = cloud_dr.get("pick_count")
            ss["local_draft_room_pick_count"] = dr.get("pick_count")
            ss["cloud_fetch_updated_at"] = ss.get("_suite_cloud_fetch_updated_at") or ss.get(
                "cloud_updated_at_at_restore"
            )
        except ImportError:
            pass
    except ImportError:
        pass

    try:
        from live_draft_state import apply_cloud_live_draft_state_if_allowed, prepare_live_draft_state

        apply_cloud_live_draft_state_if_allowed(ss, state)
        prepare_live_draft_state(ss)
    except ImportError:
        pass

    try:
        from historical_state import apply_cloud_historical_state_if_allowed

        apply_cloud_historical_state_if_allowed(ss, state)
    except ImportError:
        pass

    try:
        from valuation_state import apply_cloud_valuation_state_if_allowed

        apply_cloud_valuation_state_if_allowed(ss, state)
    except ImportError:
        pass

    try:
        from projections_state import apply_cloud_projections_state_if_allowed

        apply_cloud_projections_state_if_allowed(ss, state)
    except ImportError:
        pass

    try:
        from leaderboards_state import apply_cloud_leaderboards_state_if_allowed

        apply_cloud_leaderboards_state_if_allowed(ss, state)
    except ImportError:
        pass

    try:
        from fantasy_state import apply_cloud_fantasy_state_if_allowed

        apply_cloud_fantasy_state_if_allowed(ss, state)
    except ImportError:
        pass

    try:
        from fantasy_league_context import apply_fantasy_league_context_disk_state

        apply_fantasy_league_context_disk_state(ss, state)
    except ImportError:
        pass

    try:
        from fantasy_in_season_state import hydrate_fantasy_in_season_to_session

        hydrate_fantasy_in_season_to_session(ss, state)
    except ImportError:
        pass

    try:
        from draft_lab_state import hydrate_draft_lab_results_state

        hydrate_draft_lab_results_state(ss, state)
    except ImportError:
        pass

    try:
        from suite_identity_guard import enforce_identity_after_state_apply

        enforce_identity_after_state_apply(
            ss,
            snapshot=identity_snapshot if identity_snapshot else None,
            reason="apply_baseball_disk_state",
            last_mutator="apply_baseball_disk_state",
            st=st,
        )
    except ImportError:
        auth_snap = identity_snapshot.get("auth") if isinstance(identity_snapshot, dict) else None
        if isinstance(auth_snap, dict) and auth_snap:
            try:
                from suite_auth import restore_auth_session_snapshot

                restore_auth_session_snapshot(ss, auth_snap)
            except ImportError:
                pass
        try:
            from suite_auth import enforce_workspace_ownership

            enforce_workspace_ownership(ss)
        except ImportError:
            pass

    ss["_suite_cloud_workspace_applied"] = True


def apply_baseball_session_defaults(st: Any) -> None:
    ss = st.session_state
    for key in list(ss.keys()):
        if str(key).startswith("_suite_"):
            ss.pop(key, None)
    ss.pop("page_filter_state", None)
    ss.pop("_page_state_last_active", None)
    ss["active_page"] = _DEFAULT_PAGE
    ss["main_sidebar_page"] = _DEFAULT_SIDEBAR_PAGE


def _workspace_restore_cloud_first(session: dict[str, Any]) -> bool:
    """Prefer durable cloud restore whenever cloud storage is configured.

    Streamlit Cloud disk is ephemeral (wiped on reboot), so cloud is the only
    durable source. We restore cloud-first whenever it is enabled — including
    local/demo mode — so a reboot rehydrates the workspace instead of falling
    back to a blank default. Only fall back to disk-first when cloud storage is
    not configured at all.
    """
    try:
        from suite_storage_config import cloud_storage_enabled

        if not cloud_storage_enabled():
            return False
    except ImportError:
        return False
    return True


def warm_startup_fingerprint(session: dict[str, Any]) -> str:
    """Identity/cloud revision fingerprint used to skip expensive warm hydration.

    Intentionally omits library_manifest_revision / archive list size so Visiting
    Saved Draft Library cannot invalidate warm_skip for subsequent page hops.
    """
    return "|".join(
        [
            str(session.get("_suite_auth_user_id") or ""),
            str(session.get("_suite_active_workspace_id") or ""),
            str(
                session.get("_suite_cloud_session_revision")
                or session.get("_suite_workspace_cloud_meta_fp")
                or ""
            ),
            str(WORKSPACE_SCHEMA_VERSION),
        ]
    )


def prepare_baseball_workspace(st: Any) -> bool:
    """Single authoritative cloud/disk workspace sync before sidebar widgets."""
    ss = st.session_state
    # Final ownership clamp BEFORE any workspace-scoped cloud/disk load.
    try:
        from suite_auth import hard_clamp_owned_workspace_before_scoped_load

        before_ws = str(ss.get("_suite_active_workspace_id") or "")
        hard_clamp_owned_workspace_before_scoped_load(ss)
        after_ws = str(ss.get("_suite_active_workspace_id") or "")
        if before_ws and after_ws and before_ws != after_ws:
            ss["_suite_workspace_force_sync"] = True
            ss.pop("_baseball_warm_startup_fp", None)
    except Exception as exc:
        ss["_suite_workspace_hard_clamp_error"] = f"{type(exc).__name__}: {exc}"

    warm_skip = False
    try:
        from suite_user_persistence import _workspace_synced_key

        synced = bool(ss.get(_workspace_synced_key(APP_ID)))
        force = bool(
            ss.get("_suite_workspace_force_sync")
            or ss.get("_suite_workspace_refresh_needed")
            or ss.get("_suite_auth_just_signed_in")
            or ss.get("_suite_auth_just_logged_in")
        )
        fp = warm_startup_fingerprint(ss)
        prev_fp = str(ss.get("_baseball_warm_startup_fp") or "")
        if synced and not force and prev_fp == fp and prev_fp:
            warm_skip = True
            ss["_baseball_warm_startup_skipped"] = True
        else:
            ss["_baseball_warm_startup_fp"] = fp
            ss["_baseball_warm_startup_skipped"] = False
    except Exception:
        warm_skip = False

    result = False
    if warm_skip:
        result = True
    else:
        try:
            from page_perf_phases import session_perf_phase

            with session_perf_phase(ss, "cloud_hydration"):
                result = sync_workspace_protocol(
                    st,
                    APP_ID,
                    apply_state=lambda st_obj, s: apply_baseball_disk_state(st_obj, s),
                    cloud_first=_workspace_restore_cloud_first(ss),
                )
        except ImportError:
            try:
                from page_perf import perf_end, perf_timer

                t0 = perf_timer(ss, "workspace_sync")
            except ImportError:
                t0 = 0.0
            result = sync_workspace_protocol(
                st,
                APP_ID,
                apply_state=lambda st_obj, s: apply_baseball_disk_state(st_obj, s),
                cloud_first=_workspace_restore_cloud_first(ss),
            )
            try:
                from page_perf import perf_end

                perf_end(ss, "workspace_sync", t0)
            except ImportError:
                pass
        try:
            from workflow_persist_guard import ensure_session_workflow_hydrated

            ensure_session_workflow_hydrated(st, APP_ID)
        except ImportError:
            pass
    # Warm navigation: skip global settings prep. Mirror only on cold hydrate or
    # an explicit force flag — not on every sidebar hop (_suite_page_user_nav).
    if (not warm_skip) or bool(
        ss.get("_suite_workspace_refresh_needed")
        or ss.get("_global_settings_force_mirror")
    ):
        try:
            from global_fantasy_settings_state import prepare_global_fantasy_settings

            force_mirror = bool(
                ss.get("_suite_workspace_refresh_needed")
                or ss.pop("_global_settings_force_mirror", None)
                or (not warm_skip)
            )
            prepare_global_fantasy_settings(ss, force_mirror=force_mirror)
        except Exception:
            pass
    if not warm_skip:
        try:
            from suite_auth import is_auth_enabled, restore_auth_session

            if is_auth_enabled():
                before_auth_workspace = str(ss.get("_suite_active_workspace_id") or "")
                restore_auth_session(ss, st=st)
                try:
                    from suite_auth import enforce_workspace_ownership

                    enforce_workspace_ownership(ss)
                except ImportError:
                    pass
                after_auth_workspace = str(ss.get("_suite_active_workspace_id") or "")
                try:
                    from workflow_persist_guard import ensure_session_workflow_hydrated

                    post_auth_hydrate = ensure_session_workflow_hydrated(st, APP_ID)
                    ss["_suite_post_auth_workflow_hydrate"] = dict(post_auth_hydrate)
                    if (
                        post_auth_hydrate.get("hydrated")
                        and not ss.get("_suite_post_auth_workflow_hydration_rerun_done")
                    ):
                        ss["_suite_post_auth_workflow_hydration_rerun_done"] = True
                        ss["_suite_post_auth_workflow_hydration_rerun_reason"] = (
                            "workspace_changed_after_auth"
                            if before_auth_workspace != after_auth_workspace
                            else "post_auth_workflow_hydrated"
                        )
                        try:
                            from fantasy_workflow_trace import note_rerun

                            note_rerun(
                                ss,
                                function="prepare_baseball_workspace.post_auth_hydrate",
                                reason=str(ss.get("_suite_post_auth_workflow_hydration_rerun_reason") or ""),
                                page=str(ss.get("active_page") or ""),
                                st=st,
                            )
                        except ImportError:
                            pass
                        rerun = getattr(st, "rerun", None)
                        if callable(rerun):
                            rerun()
                except ImportError:
                    pass
        except ImportError:
            pass
        try:
            from workflow_persist_guard import AUTH_RESTORE_CYCLE_COMPLETE_KEY

            ss[AUTH_RESTORE_CYCLE_COMPLETE_KEY] = True
        except ImportError:
            pass
        try:
            from workflow_persist_guard import run_consolidated_startup_workflow

            ss["_suite_consolidated_startup_trace"] = run_consolidated_startup_workflow(st, APP_ID)
        except ImportError:
            pass
        except Exception:
            pass
        try:
            from fantasy_league_invites import reconcile_stranded_foreign_disk_drafts

            if not ss.get("_suite_shared_league_startup_sync_trace", {}).get("rebuilt"):
                reconcile_stranded_foreign_disk_drafts(st, APP_ID)
        except ImportError:
            pass
        except Exception:
            pass
        try:
            from workflow_persist_guard import maybe_authenticated_workflow_cloud_writeback

            if not ss.get("_suite_shared_league_startup_sync_trace", {}).get("rebuilt"):
                maybe_authenticated_workflow_cloud_writeback(st, APP_ID)
        except ImportError:
            pass
        except Exception:
            pass
        try:
            from live_draft_lineup_config import repair_known_live_draft_lineup_configs

            repair_known_live_draft_lineup_configs(ss)
        except ImportError:
            pass
        except Exception:
            pass
    # Account preferences are the final authority after actual hydration only.
    try:
        from account_fantasy_preferences import (
            reassert_account_preferences_after_hydration,
            sync_account_fantasy_preferences,
        )

        if not warm_skip:
            sync_account_fantasy_preferences(ss, force=bool(ss.get("_suite_workspace_refresh_needed")))
            reassert_account_preferences_after_hydration(ss)
        else:
            # Warm navigation: compact header compare only — no full preference fetch.
            sync_account_fantasy_preferences(ss, poll=True)
    except ImportError:
        pass
    except Exception:
        pass
    # First-render (and every prepare): reject foreign/unowned private simulator boards
    # already present in a signed-in session — sign-out transitions alone are not enough.
    try:
        from live_draft_navigation import scrub_simulator_runtime_for_current_account

        ss["_simulator_ownership_scrub_trace"] = scrub_simulator_runtime_for_current_account(
            ss,
            reason="prepare_baseball_workspace",
        )
    except ImportError:
        pass
    except Exception as exc:
        ss["_simulator_ownership_scrub_trace"] = {"error": str(exc)}
    # One post-auth cold hydrate is enough — do not defeat warm_skip forever.
    if not warm_skip:
        ss.pop("_suite_workspace_refresh_needed", None)
        ss.pop("_suite_workspace_force_sync", None)
        ss.pop("_suite_auth_just_logged_in", None)
        ss.pop("_suite_auth_just_signed_in", None)
    return result


def record_post_restore_workspace_diagnostics(st: Any) -> dict[str, Any]:
    """Capture post-restore counts after resume hooks (authoritative session view)."""
    ss = st.session_state
    cloud_state: dict[str, Any] | None = None
    disk_state: dict[str, Any] | None = None
    try:
        from suite_cloud_state import load_cloud_full_session

        loaded, _ = load_cloud_full_session(APP_ID)
        if isinstance(loaded, dict):
            cloud_state = loaded
    except ImportError:
        pass
    try:
        from suite_user_persistence import _load_raw

        disk_state, _, _ = _load_raw(APP_ID)
    except ImportError:
        pass
    try:
        from workflow_persist_guard import record_startup_restore_snapshot

        snapshot = record_startup_restore_snapshot(
            st,
            cloud_state=cloud_state,
            disk_state=disk_state if isinstance(disk_state, dict) else None,
            phase="post_resume",
        )
    except ImportError:
        snapshot = {}
    ss["_suite_post_restore_active_page"] = ss.get("active_page")
    return snapshot if isinstance(snapshot, dict) else {}


def restore_baseball_disk_state_once(st: Any) -> bool:
    """Deprecated — use prepare_baseball_workspace() before sidebar instead."""
    return False


def sync_baseball_cloud_workspace(st: Any) -> bool:
    """Backward-compatible alias for prepare_baseball_workspace."""
    return prepare_baseball_workspace(st)


def autosave_baseball_state(st: Any) -> None:
    before_save_at = st.session_state.get("_suite_persist_last_save_at")
    autosave_if_changed(st, APP_ID, build_state=build_baseball_disk_state)
    try:
        from comparison_state import clear_comparison_local_edit

        after_save_at = st.session_state.get("_suite_persist_last_save_at")
        if (
            after_save_at
            and after_save_at != before_save_at
            and st.session_state.get("_suite_persist_last_save_cloud")
        ):
            clear_comparison_local_edit(st.session_state)
            try:
                from career_totals_state import clear_career_local_edit

                clear_career_local_edit(st.session_state)
            except ImportError:
                pass
            try:
                from draft_state import clear_draft_local_edit

                clear_draft_local_edit(st.session_state)
            except ImportError:
                pass
            try:
                from live_draft_state import clear_live_draft_local_edit

                clear_live_draft_local_edit(st.session_state)
            except ImportError:
                pass
            try:
                from draft_room_state import clear_draft_room_local_edit

                clear_draft_room_local_edit(st.session_state)
            except ImportError:
                pass
            try:
                from historical_state import clear_historical_local_edit

                clear_historical_local_edit(st.session_state)
            except ImportError:
                pass
            try:
                from valuation_state import clear_valuation_local_edit

                clear_valuation_local_edit(st.session_state)
            except ImportError:
                pass
            try:
                from projections_state import clear_projections_local_edit

                clear_projections_local_edit(st.session_state)
            except ImportError:
                pass
            try:
                from leaderboards_state import clear_leaderboards_local_edit

                clear_leaderboards_local_edit(st.session_state)
            except ImportError:
                pass
            try:
                from fantasy_state import clear_fantasy_local_edit

                clear_fantasy_local_edit(st.session_state)
            except ImportError:
                pass
    except ImportError:
        pass


def force_save_baseball_state(st: Any, *, reason: str = "") -> bool:
    defer = str(st.session_state.get("_suite_defer_baseball_save_reason") or "").strip()
    bypass_defer = reason in (
        "hof_case_submit",
        "insight_hydrate",
        "insight_persist",
    ) or bool(st.session_state.get("_suite_persist_insight_dirty"))
    try:
        from suite_user_persistence import _FORCE_SAVE_CLOUD_REASONS

        bypass_defer = bypass_defer or reason in _FORCE_SAVE_CLOUD_REASONS
    except ImportError:
        pass
    if defer.startswith("ami_send") and not bypass_defer:
        st.session_state.pop("_suite_defer_baseball_save_reason", None)
        st.session_state["_suite_last_deferred_save_reason"] = defer
        return False
    if bypass_defer:
        st.session_state.pop("_suite_defer_baseball_save_reason", None)
    if reason:
        st.session_state["_suite_pending_save_reason"] = reason
    _trace_live_draft_save = "live_draft" in str(reason or "")
    if _trace_live_draft_save:
        try:
            from live_draft_perf import PHASE_SETUP_BUILD_DISK_STATE, PHASE_SETUP_CLOUD_AUTOSAVE, live_draft_perf_action

            with live_draft_perf_action(st.session_state, "build_disk_state", phase=PHASE_SETUP_BUILD_DISK_STATE):
                _built = build_baseball_disk_state(st)
            st.session_state["_suite_pending_save_reason"] = reason
            with live_draft_perf_action(st.session_state, "cloud_autosave", phase=PHASE_SETUP_CLOUD_AUTOSAVE):
                saved = force_autosave(st, APP_ID, build_state=lambda _st: _built, reason=reason)
        except ImportError:
            saved = force_autosave(st, APP_ID, build_state=build_baseball_disk_state, reason=reason)
    else:
        saved = force_autosave(st, APP_ID, build_state=build_baseball_disk_state, reason=reason)
    if reason == "career_edit":
        try:
            from career_totals_state import record_career_force_save_result

            record_career_force_save_result(
                st.session_state,
                attempted=True,
                success=bool(saved and st.session_state.get("_suite_persist_last_save_cloud")),
                reason=reason,
            )
        except ImportError:
            pass
    if saved and st.session_state.get("_suite_persist_last_save_cloud"):
        try:
            from comparison_state import clear_comparison_local_edit

            clear_comparison_local_edit(st.session_state)
        except ImportError:
            pass
        try:
            from career_totals_state import clear_career_local_edit

            clear_career_local_edit(st.session_state)
        except ImportError:
            pass
        try:
            from draft_state import clear_draft_local_edit

            clear_draft_local_edit(st.session_state)
        except ImportError:
            pass
        try:
            from live_draft_state import clear_live_draft_local_edit

            clear_live_draft_local_edit(st.session_state)
        except ImportError:
            pass
        try:
            from draft_room_state import clear_draft_room_local_edit

            clear_draft_room_local_edit(st.session_state)
        except ImportError:
            pass
        try:
            from historical_state import clear_historical_local_edit

            clear_historical_local_edit(st.session_state)
        except ImportError:
            pass
        try:
            from valuation_state import clear_valuation_local_edit

            clear_valuation_local_edit(st.session_state)
        except ImportError:
            pass
        try:
            from projections_state import clear_projections_local_edit

            clear_projections_local_edit(st.session_state)
        except ImportError:
            pass
        try:
            from leaderboards_state import clear_leaderboards_local_edit

            clear_leaderboards_local_edit(st.session_state)
        except ImportError:
            pass
        try:
            from fantasy_state import clear_fantasy_local_edit

            clear_fantasy_local_edit(st.session_state)
        except ImportError:
            pass
    return saved


def default_reset_baseball_session(st: Any) -> None:
    """Full baseball reset: session, disk, and cloud ``full_session``."""
    apply_baseball_session_defaults(st)
    fresh = build_baseball_disk_state(st)
    finalize_suite_reset(
        st,
        APP_ID,
        fresh,
        page=_DEFAULT_PAGE,
        summary="Reset to defaults",
    )


def _load_cloud_workspace_snapshot() -> tuple[dict[str, Any], str | None]:
    try:
        from suite_cloud_state import load_cloud_full_session

        cloud_state, cloud_ts = load_cloud_full_session(APP_ID)
        if isinstance(cloud_state, dict):
            return cloud_state, cloud_ts
    except ImportError:
        pass
    return {}, None


def _workspace_meta(state: dict[str, Any]) -> dict[str, Any]:
    meta = state.get("baseball_workspace_state")
    return meta if isinstance(meta, dict) else {}


def render_cross_device_sync_debug(st: Any) -> None:
    """Developer Mode panel — authoritative workspace sync trace."""
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        if not developer_mode_checkbox_enabled(st=st):
            return
    except ImportError:
        return
    try:
        from suite_cloud_state import FULL_SESSION_KEY, parse_persist_timestamp, probe_cloud_restore_diagnostics
        from suite_user_persistence import _applied_cloud_ts_key, _local_dirty_key, state_file_path
    except ImportError:
        return

    ss = st.session_state
    diag = probe_cloud_restore_diagnostics(st, APP_ID)
    cloud_state, _cloud_ts_direct = _load_cloud_workspace_snapshot()
    if not cloud_state and diag.get("cloud_has_full_session"):
        cloud_state, _ = _load_cloud_workspace_snapshot()

    cloud_meta = _workspace_meta(cloud_state)
    cloud_pf = cloud_state.get("page_filter_state") if isinstance(cloud_state.get("page_filter_state"), dict) else {}
    cloud_cmp = cloud_pf.get("Comparison Tool") if isinstance(cloud_pf.get("Comparison Tool"), dict) else {}
    cloud_trend = cloud_pf.get("Trend Value") if isinstance(cloud_pf.get("Trend Value"), dict) else {}
    cloud_hist = cloud_pf.get("Historical Explorer") if isinstance(cloud_pf.get("Historical Explorer"), dict) else {}

    local_pf = ss.get("page_filter_state")
    local_cmp: dict[str, Any] = {}
    local_trend: dict[str, Any] = {}
    local_pf_pages: list[str] = []
    if isinstance(local_pf, dict):
        local_pf_pages = sorted(str(k) for k in local_pf.keys())
        local_cmp = local_pf.get("Comparison Tool") or {}
        local_trend = local_pf.get("Trend Value") or {}

    disk_ts = None
    disk_state: dict[str, Any] = {}
    try:
        import json

        path = state_file_path(APP_ID)
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                disk_ts = raw.get("saved_at")
                inner = raw.get("state")
                if isinstance(inner, dict):
                    disk_state = inner
    except Exception:
        disk_ts = None

    local_meta = _workspace_meta(disk_state)
    cloud_ts = diag.get("cloud_updated_at") or ss.get("_suite_persist_debug_cloud_ts")
    applied_ts = ss.get(_applied_cloud_ts_key(APP_ID))
    cloud_epoch = parse_persist_timestamp(str(cloud_ts) if cloud_ts else None)
    disk_epoch = parse_persist_timestamp(str(disk_ts) if disk_ts else None)
    applied_epoch = parse_persist_timestamp(str(applied_ts) if applied_ts else None)
    local_epoch = max(disk_epoch, applied_epoch)

    cloud_rows = {
        "updated_at": cloud_ts or cloud_meta.get("updated_at"),
        "page": cloud_meta.get("page") or cloud_state.get("active_page") or ss.get("_suite_page_sync_cloud_page"),
        "comparison_players": cloud_meta.get("comparison_players") or cloud_cmp.get("compare_players"),
        "trend_players": cloud_meta.get("trend_players") or cloud_trend.get("trend_players_multi"),
        "save_reason": cloud_meta.get("save_reason") or ss.get("_suite_persist_last_save_reason"),
        "device_id": cloud_meta.get("device_id"),
        "schema_version": cloud_meta.get("schema_version"),
        "historical_filters": cloud_meta.get("historical_filters") or _historical_filter_summary(cloud_hist) or None,
        "room_format": cloud_state.get("room_format"),
        "room_team_count": cloud_state.get("room_team_count"),
        "room_your_team": cloud_state.get("room_your_team"),
        "live_draft_scoring": cloud_state.get("live_draft_scoring"),
    }
    local_rows = {
        "updated_at": disk_ts or applied_ts or local_meta.get("updated_at"),
        "page": ss.get("active_page"),
        "comparison_players": local_cmp.get("compare_players") or ss.get("compare_players"),
        "trend_players": local_trend.get("trend_players_multi") or ss.get("trend_players_multi"),
        "dirty_flag": ss.get(_local_dirty_key(APP_ID)),
        "page_filter_pages": local_pf_pages or None,
        "device_id": local_meta.get("device_id") or ss.get("_suite_device_id"),
        "room_format": ss.get("room_format"),
        "room_team_count": ss.get("room_team_count"),
        "room_your_team": ss.get("room_your_team"),
        "live_draft_scoring": ss.get("live_draft_scoring"),
        "draft_lab_scoring_type": ss.get("draft_lab_scoring_type"),
        "draft_format": ss.get("draft_format"),
        "fantasy_market_format": ss.get("fantasy_market_format"),
    }
    cloud_top_cs = cloud_state.get("comparison_state") if isinstance(cloud_state.get("comparison_state"), dict) else {}
    startup_rows = {
        "cloud_fetch_attempted": ss.get("_suite_cloud_fetch_attempted"),
        "cloud_fetch_success": ss.get("_suite_cloud_fetch_success"),
        "cloud_fetch_user_id": ss.get("_suite_cloud_fetch_user_id"),
        "cloud_fetch_updated_at": ss.get("_suite_cloud_fetch_updated_at"),
        "cloud_fetch_active_page": ss.get("_suite_cloud_fetch_active_page"),
        "cloud_fetch_comparison_players": ss.get("_suite_cloud_fetch_comparison_players"),
        "restore_decision": ss.get("_suite_restore_decision"),
        "restore_should_apply": ss.get("_suite_restore_should_apply"),
        "restore_apply_reason": ss.get("_suite_restore_apply_reason"),
        "restore_skip_reason": ss.get("_suite_restore_skip_reason") or ss.get("_suite_persist_restore_skip_reason"),
        "restore_pick_source": ss.get("_suite_restore_pick_source"),
        "already_synced_before_restore": ss.get("_suite_already_synced_before_restore"),
        "comparison_mismatch_detected": ss.get("_suite_workspace_comparison_mismatch"),
        "disk_restore_after_cloud": ss.get("_suite_disk_restore_after_cloud"),
        "post_restore_active_page": ss.get("_suite_post_restore_active_page"),
        "post_restore_comparison_players": ss.get("_suite_post_restore_comparison_players"),
        "resume_insight_hydration_only": ss.get("_suite_resume_insight_hydration_only"),
        "workspace_sync_skipped_no_apply": ss.get("_suite_workspace_sync_skipped_no_apply"),
        "autosave_cloud_blocked_reason": ss.get("_suite_autosave_cloud_blocked_reason"),
        "local_has_live_draft_state": ss.get("local_has_live_draft_state"),
        "local_live_draft_pick_count": ss.get("local_live_draft_pick_count"),
        "cloud_has_live_draft_state": ss.get("cloud_has_live_draft_state"),
        "cloud_live_draft_pick_count": ss.get("cloud_live_draft_pick_count"),
        "local_has_draft_room_board": ss.get("local_has_draft_room_board"),
        "local_draft_room_pick_count": ss.get("local_draft_room_pick_count"),
        "cloud_has_draft_room_board": ss.get("cloud_has_draft_room_board"),
        "cloud_draft_room_pick_count": ss.get("cloud_draft_room_pick_count"),
        "active_draft_page": ss.get("active_draft_page"),
        "draft_board_source_key": ss.get("draft_board_source_key"),
        "session_has_draft_board": ss.get("session_has_draft_board"),
        "session_pick_count": ss.get("session_pick_count"),
        "payload_has_draft_board": ss.get("payload_has_draft_board"),
        "cloud_payload_pick_count": ss.get("cloud_payload_pick_count"),
        "restore_winner_reason_detail": ss.get("restore_winner_reason_detail"),
        "already_synced_why": ss.get("already_synced_why"),
        "local_disk_updated_at": ss.get("local_disk_updated_at"),
        "cloud_updated_at_at_restore": ss.get("cloud_updated_at_at_restore"),
    }
    startup_snap = ss.get("_suite_startup_restore_snapshot")
    if isinstance(startup_snap, dict):
        startup_rows.update(startup_snap)
    try:
        from suite_deploy_marker import GIT_COMMIT_SHORT, SUITE_BUILD_LABEL

        startup_rows["deploy_build"] = SUITE_BUILD_LABEL
        startup_rows["deploy_commit"] = GIT_COMMIT_SHORT
    except ImportError:
        pass
    try:
        from suite_workspace import DEVELOPER_MODE_DIAG_KEY

        dev_diag = ss.get(DEVELOPER_MODE_DIAG_KEY)
        if isinstance(dev_diag, dict):
            startup_rows.update(dev_diag)
    except ImportError:
        pass
    try:
        from live_draft_state import live_draft_envelope_summary, live_draft_restore_diagnostics

        live_draft_rows = dict(live_draft_restore_diagnostics(ss))
        live_draft_rows["last_live_draft_save_reason"] = ss.get("last_live_draft_save_reason")
        live_draft_rows["last_live_draft_save_success"] = ss.get("last_live_draft_save_success")
        live_draft_rows["last_live_draft_save_error"] = ss.get("last_live_draft_save_error")
        live_draft_rows["saved_live_draft_state_present"] = ss.get("saved_live_draft_state_present")
        live_draft_rows["saved_pick_count"] = ss.get("saved_pick_count")
        live_draft_rows["saved_current_pick_index"] = ss.get("saved_current_pick_index")
        live_draft_rows["saved_pool_count"] = ss.get("saved_pool_count")
        live_draft_rows["cloud_payload_has_live_draft_state"] = ss.get("cloud_payload_has_live_draft_state")
        live_draft_rows["cloud_payload_pick_count"] = ss.get("cloud_payload_pick_count")
        live_draft_rows["cloud_payload_pool_count"] = ss.get("cloud_payload_pool_count")
        live_draft_rows["cloud_existing_has_live_draft_state_before_save"] = ss.get(
            "cloud_existing_has_live_draft_state_before_save"
        )
        live_draft_rows["cloud_live_draft_preserved_on_page_change"] = ss.get(
            "cloud_live_draft_preserved_on_page_change"
        )
        cloud_ld = live_draft_envelope_summary(cloud_state)
        if cloud_ld:
            live_draft_rows["cloud_live_draft"] = cloud_ld
    except ImportError:
        live_draft_rows = {}
    try:
        from draft_room_state import draft_board_diagnostics, draft_room_restore_stats

        board_diag = draft_board_diagnostics(ss)
        dr_stats = draft_room_restore_stats(ss)
        draft_board_rows = {
            **board_diag,
            "restored_draft_room_pick_count": dr_stats.get("pick_count"),
            "restored_draft_room_rows": dr_stats.get("pool_count"),
            "cloud_payload_has_draft_board": ss.get("cloud_payload_has_draft_board"),
            "last_draft_room_save_trace": ss.get("_draft_room_last_save_trace"),
        }
        editor_diag = ss.get("_draft_room_editor_diagnostics")
        if isinstance(editor_diag, dict):
            draft_board_rows.update(editor_diag)
    except ImportError:
        draft_board_rows = {}
    decision_rows = {
        "cloud_loaded": ss.get("_suite_workspace_cloud_loaded"),
        "local_loaded": ss.get("_suite_workspace_local_loaded"),
        "winner": ss.get("_suite_workspace_winner") or ss.get("_suite_persist_debug_pick_source"),
        "reason": ss.get("_suite_workspace_winner_reason") or ss.get("_suite_persist_debug_pick_reason"),
        "cloud_first_enabled": ss.get("_suite_page_sync_cloud_first", True),
        "cloud_newer_than_local": ss.get(
            "_suite_page_sync_cloud_newer_than_local",
            cloud_epoch > local_epoch if cloud_ts else False,
        ),
        "cloud_record_timestamp": cloud_ts,
        "applied_cloud_timestamp": applied_ts,
        "cloud_comparison_players": ss.get("_suite_workspace_cloud_comparison_players")
        or cloud_top_cs.get("players")
        or cloud_rows.get("comparison_players"),
        "local_comparison_players": ss.get("_suite_workspace_local_comparison_players")
        or ss.get("compare_players"),
        "comparison_mismatch": ss.get("_suite_workspace_comparison_mismatch"),
        "comparison_state_dirty": ss.get("comparison_state_dirty"),
        "comparison_last_local_edit_ts": ss.get("comparison_state_last_local_edit_ts"),
        "restore_skipped_reason": ss.get("_suite_persist_restore_skip_reason"),
        "cloud_workspace_restored": ss.get("_cloud_workspace_restored"),
        "restore_source": ss.get("_comparison_restore_source")
        or ss.get("_suite_persist_last_restore_source"),
        "restored_comparison_players": ss.get("_comparison_restored_players"),
        "page_state_source": "page_filter_state + full_session",
    }
    apply_rows = {
        "applied_page": ss.get("_suite_workspace_applied_page"),
        "applied_comparison_players": ss.get("_suite_workspace_applied_comparison_players"),
        "applied_trend_players": ss.get("_suite_workspace_applied_trend_players"),
        "applied_success": ss.get("_suite_workspace_apply_success"),
    }
    autosave_rows = {
        "autosave_blocked_after_restore": ss.get("_suite_autosave_blocked_after_restore"),
        "autosave_reason": ss.get("_suite_autosave_reason") or ss.get("_suite_persist_last_save_reason"),
        "autosave_wrote_cloud": ss.get("_suite_autosave_wrote_cloud"),
        "autosave_payload_page": ss.get("_suite_autosave_payload_page"),
        "autosave_payload_comparison_players": ss.get("_suite_autosave_payload_comparison_players"),
        "last_autosave_at": ss.get("_suite_last_autosave_at"),
        "last_force_save_at": ss.get("_suite_last_force_save_at"),
        "last_cloud_payload_players": ss.get("_suite_last_cloud_payload_comparison_players"),
        "last_save_cloud": ss.get("_suite_persist_last_save_cloud"),
    }
    final_rows = {
        "final_page": ss.get("active_page"),
        "final_comparison_players": ss.get("compare_players"),
        "final_trend_players": ss.get("trend_players_multi"),
        "final_room_format": ss.get("room_format"),
        "final_room_team_count": ss.get("room_team_count"),
        "final_room_your_team": ss.get("room_your_team"),
        "final_live_draft_scoring": ss.get("live_draft_scoring"),
        "final_draft_lab_scoring_type": ss.get("draft_lab_scoring_type"),
    }
    nav_rows = {
        "nav_phase": ss.get("_suite_sidebar_nav_phase"),
        "nav_rerun_source": ss.get("_suite_sidebar_nav_rerun_source"),
        "nav_main_sidebar_page": ss.get("_suite_sidebar_nav_main_sidebar_page"),
        "nav_active_page": ss.get("_suite_sidebar_nav_active_page"),
        "nav_user_nav": ss.get("_suite_sidebar_nav_user_nav"),
        "nav_cloud_target_page": ss.get("_suite_sidebar_nav_cloud_target"),
        "nav_last_persisted_page": ss.get("_suite_sidebar_nav_last_persisted_page"),
        "nav_cloud_restored_this_run": ss.get("_suite_sidebar_nav_cloud_restored_this_run"),
        "user_nav_sync_skipped": ss.get("_suite_user_nav_sync_skipped"),
    }
    infra_rows = {
        "cloud_enabled": diag.get("cloud_enabled"),
        "suite_user_id": (diag.get("suite_user_id") or "")[:24],
        "storage_module": diag.get("storage_module"),
        "cloud_load_error": diag.get("cloud_load_error"),
        "last_save_cloud": ss.get("_suite_persist_last_save_cloud"),
        "last_save_disk": ss.get("_suite_persist_last_save_disk"),
        "last_cloud_error": ss.get("_suite_persist_last_cloud_error"),
        "cloud_target_page": ss.get("_suite_cloud_target_page"),
        "main_sidebar_page": ss.get("main_sidebar_page"),
    }

    with st.sidebar.expander("Workspace sync trace", expanded=True):
        st.caption(f"Authoritative blob: baseball_workspace_state ({FULL_SESSION_KEY}).")
        st.markdown("**Startup restore (Dell read path)**")
        for k, v in startup_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        st.markdown("**Cloud workspace**")
        for k, v in cloud_rows.items():
            if v is not None and v != "" and v != {}:
                st.text(f"{k}: {v}")
        st.markdown("**Local workspace**")
        for k, v in local_rows.items():
            if v is not None and v != "" and v != []:
                st.text(f"{k}: {v}")
        st.markdown("**Startup decision**")
        for k, v in decision_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        st.markdown("**Apply**")
        for k, v in apply_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        st.markdown("**Autosave**")
        for k, v in autosave_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        st.markdown("**Live draft**")
        for k, v in live_draft_rows.items():
            if v is not None and v != "" and v != {}:
                st.text(f"{k}: {v}")
        st.markdown("**Draft board (Simulator + Live)**")
        for k, v in draft_board_rows.items():
            if v is not None and v != "" and v != {}:
                st.text(f"{k}: {v}")
        st.markdown("**Final**")
        for k, v in final_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        st.markdown("**Page Navigation Trace**")
        for k, v in nav_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        with st.expander("Infra", expanded=False):
            for k, v in infra_rows.items():
                if v is not None and v != "":
                    st.text(f"{k}: {v}")
        perf_trace = ss.get("_page_perf_trace")
        if isinstance(perf_trace, list) and perf_trace:
            st.markdown("**Page perf (dev)**")
            for row in perf_trace:
                if isinstance(row, dict):
                    st.text(f"{row.get('label')}: {row.get('ms')} ms")


__all__ = [
    "APP_ID",
    "WORKSPACE_SCHEMA_VERSION",
    "apply_baseball_disk_state",
    "apply_baseball_session_defaults",
    "autosave_baseball_state",
    "build_baseball_disk_state",
    "clear_workspace_autosave_block",
    "default_reset_baseball_session",
    "force_save_baseball_state",
    "prepare_baseball_workspace",
    "warm_startup_fingerprint",
    "render_cross_device_sync_debug",
    "restore_baseball_disk_state_once",
    "sync_baseball_cloud_workspace",
]
