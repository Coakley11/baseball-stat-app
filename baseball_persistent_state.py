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

_GLOBAL_KEYS = (
    "active_page",
    "main_sidebar_page",
    "comparison_user_team",
    "draft_room_table",
    "room_your_team",
    "room_team_count",
    "room_rounds",
    "room_format",
)

_INSIGHT_KEYS = (
    "_ami_pending_insight",
    "_ami_return_context",
    "_ami_dismissed_insight_ids",
    "_ami_dismissed_insight_at",
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
    for key in _INSIGHT_KEYS + _WORKSPACE_KEYS:
        if key in ss:
            try:
                state[key] = copy.deepcopy(ss[key])
            except Exception:
                state[key] = ss[key]
    save_reason = str(ss.pop("_suite_pending_save_reason", None) or "autosave")
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
    pre_restore_session_page = str(ss.get("active_page") or "").strip()
    pre_restore_user_nav = bool(ss.get("_suite_page_user_nav"))
    skip_draft_room = False
    try:
        from draft_room_state import DRAFT_ROOM_STATE_KEY, DRAFT_ROOM_TABLE_KEY, is_draft_room_locally_dirty

        skip_draft_room = is_draft_room_locally_dirty(ss)
    except ImportError:
        DRAFT_ROOM_STATE_KEY = "draft_room_state"
        DRAFT_ROOM_TABLE_KEY = "draft_room_table"

    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        if skip_draft_room:
            new_pf = copy.deepcopy(pf)
            existing_pf = ss.get("page_filter_state")
            if isinstance(existing_pf, dict):
                dr_block = existing_pf.get("Draft Room Simulator")
                if isinstance(dr_block, dict):
                    new_pf["Draft Room Simulator"] = copy.deepcopy(dr_block)
            ss["page_filter_state"] = new_pf
        else:
            ss["page_filter_state"] = copy.deepcopy(pf)
    else:
        ss.setdefault("page_filter_state", {})

    # Settings widgets (room_*) are part of _GLOBAL_KEYS but are also owned by the
    # draft-room blob. When the user edits settings, draft_room_state_dirty is set
    # (via mark_draft_room_local_edit on_change) and we must not let the cloud blob
    # overwrite their live edits on the very next rerun.
    _DRAFT_ROOM_SETTINGS_GLOBALS = frozenset(
        {"room_format", "room_team_count", "room_rounds", "room_your_team", "room_window"}
    )

    preserve_insight = bool(ss.get("_ami_insight_return_preserve"))
    for key in _GLOBAL_KEYS + _INSIGHT_KEYS + _WORKSPACE_KEYS:
        if key not in state:
            continue
        if skip_draft_room and key in (DRAFT_ROOM_TABLE_KEY, DRAFT_ROOM_STATE_KEY):
            continue
        if skip_draft_room and key in _DRAFT_ROOM_SETTINGS_GLOBALS:
            continue
        if preserve_insight and key in _INSIGHT_KEYS:
            continue
        val = state[key]
        if key == "_ami_pending_insight" and isinstance(val, dict):
            iid = str(val.get("insight_id") or "").strip()
            session_dismissed = ss.get("_ami_dismissed_insight_ids")
            blob_dismissed = state.get("_ami_dismissed_insight_ids")
            dismissed_raw = session_dismissed if session_dismissed is not None else blob_dismissed
            if not isinstance(dismissed_raw, (list, tuple, set)):
                dismissed_raw = []
            dismissed_ids = {str(x).strip() for x in dismissed_raw if str(x).strip()}
            if iid and iid in dismissed_ids:
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
        if key == "page_filter_state" and isinstance(val, dict):
            continue
        try:
            ss[key] = copy.deepcopy(val)
        except Exception:
            ss[key] = val

    blob_page = str(state.get("active_page") or "").strip()
    session_page_after_blob = str(ss.get("active_page") or "").strip()
    last_persisted = str(ss.get("_suite_last_persisted_page") or "").strip()
    user_owns_page = bool(
        pre_restore_user_nav
        or (
            pre_restore_session_page
            and last_persisted
            and pre_restore_session_page == last_persisted
        )
    )
    active = blob_page
    overwrite_source = "workspace_blob"
    if (
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
    if active:
        # Only clear widget keys and restore from snapshot when navigating to a
        # different page (or on fresh-session startup where pre_restore_session_page
        # is empty).  When the user is already on `active` and merely interacted
        # with a widget, we must NOT clear their new input: the snapshot still has
        # the previous-rerun values and would overwrite whatever the user just typed.
        page_actually_changed = active != pre_restore_session_page
        if page_actually_changed:
            _clear_page_widget_keys(ss, active)
        ss["active_page"] = active
        ss["main_sidebar_page"] = active
        ss["_navigate_to_page"] = active
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
        from draft_state import apply_cloud_draft_state_if_allowed

        apply_cloud_draft_state_if_allowed(ss, state)
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


def prepare_baseball_workspace(st: Any) -> bool:
    """Single authoritative cloud/disk workspace sync before sidebar widgets."""
    result = sync_workspace_protocol(
        st,
        APP_ID,
        apply_state=lambda st_obj, s: apply_baseball_disk_state(st_obj, s),
        cloud_first=True,
    )
    try:
        from global_fantasy_settings_state import prepare_global_fantasy_settings
        prepare_global_fantasy_settings(st.session_state)
    except Exception:
        pass
    return result


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
    defer = str(st.session_state.pop("_suite_defer_baseball_save_reason", "") or "").strip()
    if defer.startswith("ami_send"):
        st.session_state["_suite_last_deferred_save_reason"] = defer
        return False
    if reason:
        st.session_state["_suite_pending_save_reason"] = reason
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
    """Developer / ?dev=1 panel — authoritative workspace sync trace."""
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
    }
    local_rows = {
        "updated_at": disk_ts or applied_ts or local_meta.get("updated_at"),
        "page": ss.get("active_page"),
        "comparison_players": local_cmp.get("compare_players") or ss.get("compare_players"),
        "trend_players": local_trend.get("trend_players_multi") or ss.get("trend_players_multi"),
        "dirty_flag": ss.get(_local_dirty_key(APP_ID)),
        "page_filter_pages": local_pf_pages or None,
        "device_id": local_meta.get("device_id") or ss.get("_suite_device_id"),
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
    try:
        from suite_deploy_marker import GIT_COMMIT_SHORT, SUITE_BUILD_LABEL

        startup_rows["deploy_build"] = SUITE_BUILD_LABEL
        startup_rows["deploy_commit"] = GIT_COMMIT_SHORT
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
    "render_cross_device_sync_debug",
    "restore_baseball_disk_state_once",
    "sync_baseball_cloud_workspace",
]
