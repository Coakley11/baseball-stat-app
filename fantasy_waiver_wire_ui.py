"""Streamlit UI for Waiver Wire / Add-Drop Center — current-season stats driven."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from fantasy_league_context import (
    build_roster_stats_from_league_context,
    context_has_roster_slots,
    filter_roster_stats_to_league_teams,
    get_active_league_context,
    has_full_league_rosters,
    league_context_coverage_badge,
    league_context_type_badge,
    resolve_context_open_position_needs,
)
from fantasy_waiver_wire import (
    WAIVER_PLANNER_ADD_KEY,
    WAIVER_PLANNER_DROP_KEY,
    MAX_WAIVER_MOVE_PAIRS,
    add_pending_move_pair,
    analyze_current_team_needs,
    apply_waiver_move_pairs,
    build_category_standings_table,
    build_waiver_pool,
    build_weakness_narrative,
    compute_add_drop_category_impact,
    compute_waiver_transaction_impact,
    filter_waiver_names_by_search,
    format_current_stat_line,
    format_projected_stat_line,
    format_league_rank_lines,
    get_pending_move_pairs,
    my_team_roster_dataframe,
    pop_waiver_tx_flash,
    recommend_adds_current,
    recommend_adds_personalized,
    recommend_drops_current,
    remove_pending_move_pair,
    set_waiver_tx_flash,
    sync_waiver_roster_views,
    waiver_categories_for_context,
    waiver_display_stat_columns,
)

WAIVER_POSITION_FILTER_KEY = "waiver_position_filter"
WAIVER_POSITION_FILTER_OPTIONS: tuple[str, ...] = (
    "All positions",
    "C",
    "1B",
    "2B",
    "3B",
    "SS",
    "OF",
    "DH/UTIL",
)


def _import_streamlit_main_attr(attr_name: str):
    """Prefer helpers from the running Streamlit __main__ app to avoid re-importing streamlit_app."""
    import sys

    main_mod = sys.modules.get("__main__")
    if main_mod is not None and hasattr(main_mod, attr_name):
        return getattr(main_mod, attr_name)
    from streamlit_app import __dict__ as _app_exports  # noqa: WPS433

    return _app_exports[attr_name]


def _apply_waiver_position_filter(pool_df: pd.DataFrame, position_filter: str) -> pd.DataFrame:
    choice = str(position_filter or "").strip()
    if not choice or choice == "All positions":
        return pool_df
    try:
        from streamlit_app import enrich_lineup_roster_positions, filter_players_by_fantasy_position
    except ImportError:
        return pool_df
    if pool_df is None or pool_df.empty:
        return pool_df
    work = enrich_lineup_roster_positions(pool_df.copy())
    return filter_players_by_fantasy_position(work, choice)


def _player_names(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty:
        return []
    for col in ("Player", "fullName", "player_name"):
        if col in df.columns:
            return sorted(df[col].dropna().astype(str).unique().tolist())
    return []


def _row_for_player(df: pd.DataFrame, name: str) -> pd.Series | None:
    if df is None or df.empty or not name:
        return None
    for col in ("Player", "fullName", "player_name"):
        if col not in df.columns:
            continue
        match = df[df[col].astype(str).str.strip() == str(name).strip()]
        if not match.empty:
            return match.iloc[0]
    return None


def _photo_helpers(st: Any) -> tuple[bool, Any, Any]:
    try:
        from player_photos import get_player_photo_info, inject_player_photo_styles, render_rec_card_photo_html

        inject_player_photo_styles(st)
        return True, get_player_photo_info, render_rec_card_photo_html
    except ImportError:
        return False, None, None


def _render_player_card(
    st: Any,
    row: pd.Series,
    *,
    key_prefix: str,
    button_label: str,
    on_click,
    subtitle: str = "",
) -> None:
    use_photos, get_photo, render_photo = _photo_helpers(st)
    name = str(row.get("Player") or row.get("fullName") or "")
    team = str(row.get("MLB Team") or row.get("Team") or "—")
    pos = str(row.get("Primary Position") or row.get("Position") or "—")

    with st.container(border=True):
        c_photo, c_body, c_action = st.columns([1, 3, 1])
        with c_photo:
            if use_photos and get_photo and render_photo:
                photo_info = get_photo(full_name=name, row=row, use_api=True)
                st.markdown(render_photo(photo_info, alt=name), unsafe_allow_html=True)
        with c_body:
            st.markdown(f"**{name}**")
            st.caption(f"{team} · {pos}")
            current_line = format_current_stat_line(row)
            if current_line:
                st.caption(f"Current: {current_line}")
            projected_line = format_projected_stat_line(row)
            if projected_line:
                st.caption(f"Projected: {projected_line}")
            if subtitle:
                st.caption(subtitle)
        with c_action:
            safe_key = "".join(ch if ch.isalnum() else "_" for ch in name)[:40]
            st.button(
                button_label,
                key=f"{key_prefix}_{safe_key}",
                use_container_width=True,
                on_click=on_click,
            )


def _render_add_player_card(
    st: Any,
    row: pd.Series,
    *,
    key_prefix: str,
) -> None:
    why = str(row.get("Why Add") or "").strip()
    use_photos, get_photo, render_photo = _photo_helpers(st)
    name = str(row.get("Player") or row.get("fullName") or "")
    team = str(row.get("MLB Team") or row.get("Team") or "—")
    pos = str(row.get("Primary Position") or row.get("Position") or "—")

    with st.container(border=True):
        c_photo, c_body, c_action = st.columns([1, 3, 1])
        with c_photo:
            if use_photos and get_photo and render_photo:
                photo_info = get_photo(full_name=name, row=row, use_api=True)
                st.markdown(render_photo(photo_info, alt=name), unsafe_allow_html=True)
        with c_body:
            st.markdown(f"**{name}**")
            st.caption(f"{team} · {pos}")
            if why:
                st.markdown(f"**Why Recommended:** {why}")
            current_line = format_current_stat_line(row)
            if current_line:
                st.caption(f"Current: {current_line}")
        with c_action:
            safe_key = "".join(ch if ch.isalnum() else "_" for ch in name)[:40]
            st.button(
                "Plan Add",
                key=f"{key_prefix}_{safe_key}",
                use_container_width=True,
                on_click=_on_plan_add_click,
                args=(name,),
            )


def _render_drop_player_card(
    st: Any,
    row: pd.Series,
    *,
    key_prefix: str,
    button_label: str,
) -> None:
    why = str(row.get("Why Drop") or "").strip()
    use_photos, get_photo, render_photo = _photo_helpers(st)
    name = str(row.get("Player") or row.get("fullName") or "")
    team = str(row.get("MLB Team") or row.get("Team") or "—")
    pos = str(row.get("Primary Position") or row.get("Position") or "—")

    with st.container(border=True):
        c_photo, c_body, c_action = st.columns([1, 3, 1])
        with c_photo:
            if use_photos and get_photo and render_photo:
                photo_info = get_photo(full_name=name, row=row, use_api=True)
                st.markdown(render_photo(photo_info, alt=name), unsafe_allow_html=True)
        with c_body:
            st.markdown(f"**{name}**")
            st.caption(f"{team} · {pos}")
            if why:
                st.markdown(f"**Why Drop:** {why}")
            current_line = format_current_stat_line(row)
            if current_line:
                st.caption(f"Current: {current_line}")
        with c_action:
            safe_key = "".join(ch if ch.isalnum() else "_" for ch in name)[:40]
            st.button(
                button_label,
                key=f"{key_prefix}_{safe_key}",
                use_container_width=True,
                on_click=_on_plan_drop_click,
                args=(name,),
            )


def _on_waiver_filter_changed(*_args, **_kwargs) -> None:
    """Persist waiver global filter toggle to baseball workspace state."""
    try:
        import streamlit as st
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="waiver_filter_changed")
    except Exception:
        pass


def _on_planner_pick_changed(*_args, **_kwargs) -> None:
    try:
        import streamlit as st
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="waiver_planner_pick")
    except Exception:
        pass


def _resolve_normalize_name_fn():
    try:
        from player_name_normalization import normalize_player_name_for_merge

        return normalize_player_name_for_merge
    except ImportError:
        from fantasy_league_context import normalize_player_key

        return normalize_player_key


def _resolve_waiver_stats_pool(session: dict[str, Any]) -> pd.DataFrame:
    hitters = session.get("_fantasy_current_hitter_stats", pd.DataFrame())
    if not isinstance(hitters, pd.DataFrame):
        hitters = pd.DataFrame()
    try:
        from fantasy_league_context import get_active_league_context
        from fantasy_waiver_wire import fantasy_format_includes_pitching, merge_current_season_stats

        ctx = get_active_league_context(session)
        fmt = str((ctx or {}).get("fantasy_format") or "5x5 Roto")
        if fantasy_format_includes_pitching(fmt, ctx):
            pitchers = session.get("_fantasy_current_pitcher_stats", pd.DataFrame())
            if not isinstance(pitchers, pd.DataFrame):
                pitchers = pd.DataFrame()
            return merge_current_season_stats(hitters, pitchers)
    except ImportError:
        pass
    return hitters


def _planner_add_pick(session: dict[str, Any]) -> str:
    manual = str(session.get("waiver_manual_add_select") or "").strip()
    return str(session.get(WAIVER_PLANNER_ADD_KEY) or manual or "").strip()


def _planner_drop_pick(session: dict[str, Any]) -> str:
    manual = str(session.get("waiver_manual_drop_select") or "").strip()
    return str(session.get(WAIVER_PLANNER_DROP_KEY) or manual or "").strip()


def purge_waiver_action_widget_keys(session: dict[str, Any]) -> None:
    """Drop stale waiver button widget keys so Streamlit can bind callbacks safely."""
    for key in list(session.keys()):
        if not isinstance(key, str):
            continue
        if key in (
            "waiver_confirm_tx_btn",
            "waiver_save_pair_btn",
            "waiver_confirm_pending_btn",
        ):
            session.pop(key, None)
            continue
        if key.startswith("waiver_rm_pair_") and key.endswith("_btn"):
            session.pop(key, None)
            continue
        if key.startswith(("waiver_rec_", "waiver_drop_", "waiver_planner_add_", "waiver_planner_drop_")):
            if key.endswith("_btn") or "_btn_" in key:
                session.pop(key, None)


WAIVER_TX_CLEAR_WIDGETS_KEY = "_waiver_tx_clear_widgets"


def _request_waiver_widget_clear(session: dict[str, Any]) -> None:
    """Defer clearing widget-backed keys until the next render (before widgets exist)."""
    session[WAIVER_TX_CLEAR_WIDGETS_KEY] = True


def _apply_deferred_waiver_widget_clears(session: dict[str, Any]) -> None:
    """Clear waiver widget session keys before multiselect/selectbox widgets are created."""
    if not session.pop(WAIVER_TX_CLEAR_WIDGETS_KEY, False):
        return
    for key in (
        "waiver_tx_add_players",
        "waiver_tx_drop_players",
        "waiver_manual_add_select",
        "waiver_manual_drop_select",
    ):
        session.pop(key, None)


def _clear_waiver_tx_multiselects(session: dict[str, Any]) -> None:
    _request_waiver_widget_clear(session)


def _clear_manual_planner_widgets(session: dict[str, Any]) -> None:
    session.pop(WAIVER_PLANNER_ADD_KEY, None)
    session.pop(WAIVER_PLANNER_DROP_KEY, None)
    _request_waiver_widget_clear(session)


def _on_plan_add_click(player_name: str, *_args, **_kwargs) -> None:
    import streamlit as st

    session = st.session_state
    session[WAIVER_PLANNER_ADD_KEY] = str(player_name or "").strip()
    _on_planner_pick_changed()


def _on_plan_drop_click(player_name: str, *_args, **_kwargs) -> None:
    import streamlit as st

    session = st.session_state
    session[WAIVER_PLANNER_DROP_KEY] = str(player_name or "").strip()
    _on_planner_pick_changed()


def _on_clear_planner_add_click(*_args, **_kwargs) -> None:
    import streamlit as st

    session = st.session_state
    session.pop(WAIVER_PLANNER_ADD_KEY, None)
    _on_planner_pick_changed()


def _on_clear_planner_drop_click(*_args, **_kwargs) -> None:
    import streamlit as st

    session = st.session_state
    session.pop(WAIVER_PLANNER_DROP_KEY, None)
    _on_planner_pick_changed()


def _on_confirm_waiver_move_click(*_args, **_kwargs) -> None:
    import streamlit as st

    session = st.session_state
    tx_adds = list(session.get("waiver_tx_add_players") or [])
    tx_drops = list(session.get("waiver_tx_drop_players") or [])
    if not tx_adds:
        set_waiver_tx_flash(session, level="warning", message="Select at least one player to add.")
        return
    try:
        from fantasy_league_context import get_active_league_context
        from fantasy_waiver_wire import waiver_roster_transaction_mode

        context = get_active_league_context(session)
        my_roster = my_team_roster_dataframe(context) if context else pd.DataFrame()
        tx_mode = waiver_roster_transaction_mode(context, len(_player_names(my_roster)))
    except ImportError:
        tx_mode = "add_drop"
    if tx_mode == "add_drop":
        if not tx_drops:
            set_waiver_tx_flash(
                session,
                level="warning",
                message="Roster is full. Select a matching drop for each add.",
            )
            return
        if len(tx_adds) != len(tx_drops):
            set_waiver_tx_flash(
                session,
                level="warning",
                message="Adds and drops must match (Add 1/Drop 1 or Add 2/Drop 2).",
            )
            return
    elif tx_drops and len(tx_adds) != len(tx_drops):
        set_waiver_tx_flash(
            session,
            level="warning",
            message="When dropping players, match the number of adds and drops.",
        )
        return
    if len(tx_adds) > MAX_WAIVER_MOVE_PAIRS:
        set_waiver_tx_flash(
            session,
            level="warning",
            message=(
                f"At most {MAX_WAIVER_MOVE_PAIRS} add/drop pairs per transaction "
                "(Add 1/Drop 1 or Add 2/Drop 2)."
            ),
        )
        return
    if tx_drops:
        pairs = [
            {"add_player": add_name, "drop_player": drop_name}
            for add_name, drop_name in zip(tx_adds, tx_drops)
        ]
    else:
        pairs = [{"add_player": add_name, "drop_player": ""} for add_name in tx_adds]
    stats_pool = _resolve_waiver_stats_pool(session)
    tx_result = apply_waiver_move_pairs(session, pairs, stats_pool=stats_pool)
    _apply_waiver_tx_result(session, tx_result, stats_pool=stats_pool)


def _on_add_pending_pair_click(*_args, **_kwargs) -> None:
    import streamlit as st

    session = st.session_state
    planner_add = _planner_add_pick(session)
    planner_drop = _planner_drop_pick(session)
    if not planner_add or not planner_drop:
        set_waiver_tx_flash(
            session,
            level="warning",
            message="Select both an add target and a drop player before saving a pending move.",
        )
        return
    if add_pending_move_pair(
        session,
        add_player=planner_add,
        drop_player=planner_drop,
        category_impact=[],
    ):
        _clear_manual_planner_widgets(session)
        set_waiver_tx_flash(
            session,
            level="success",
            message=f"Pending move saved: **Add {planner_add}** · **Drop {planner_drop}**",
        )
    else:
        set_waiver_tx_flash(
            session,
            level="error",
            message="Could not save pending move — check your active league context.",
        )


def _on_remove_pending_pair_click(pair_index: int, *_args, **_kwargs) -> None:
    import streamlit as st

    remove_pending_move_pair(st.session_state, int(pair_index))


def _on_confirm_pending_waiver_moves_click(*_args, **_kwargs) -> None:
    import streamlit as st

    session = st.session_state
    pairs = get_pending_move_pairs(session)
    if not pairs:
        set_waiver_tx_flash(session, level="warning", message="No pending add/drop moves to confirm.")
        return
    stats_pool = _resolve_waiver_stats_pool(session)
    tx_result = apply_waiver_move_pairs(session, pairs, stats_pool=stats_pool)
    _apply_waiver_tx_result(session, tx_result, stats_pool=stats_pool)


def _apply_waiver_tx_result(
    session: dict[str, Any],
    tx_result: dict,
    *,
    stats_pool: pd.DataFrame,
) -> None:
    normalize_name_fn = _resolve_normalize_name_fn()
    if tx_result.get("ok"):
        added = ", ".join(tx_result.get("added_players") or [])
        dropped = ", ".join(tx_result.get("dropped_players") or [])
        message = f"**Added:** {added or '—'}\n\n**Dropped:** {dropped or '—'}"
        warns = [str(w) for w in (tx_result.get("position_warnings") or []) if str(w).strip()]
        if warns:
            message = f"{message}\n\n" + "\n".join(warns)
        set_waiver_tx_flash(session, level="success", message=message)
        try:
            sync_waiver_roster_views(session, stats_pool=stats_pool, normalize_name_fn=normalize_name_fn)
        except Exception:
            pass
        _clear_waiver_tx_multiselects(session)
        return
    errors = [str(err) for err in (tx_result.get("errors") or []) if str(err).strip()]
    if errors:
        set_waiver_tx_flash(session, level="error", message="\n".join(errors))
        return
    set_waiver_tx_flash(
        session,
        level="error",
        message="Waiver move could not be applied. Check your add/drop selections and try again.",
    )


def _handle_waiver_tx_result(
    st: Any,
    session: dict[str, Any],
    tx_result: dict,
    *,
    stats_pool: pd.DataFrame,
    normalize_name_fn=None,
) -> None:
    if tx_result.get("ok"):
        added = ", ".join(tx_result.get("added_players") or [])
        dropped = ", ".join(tx_result.get("dropped_players") or [])
        message = f"**Added:** {added or '—'}\n\n**Dropped:** {dropped or '—'}"
        warns = [str(w) for w in (tx_result.get("position_warnings") or []) if str(w).strip()]
        if warns:
            message = f"{message}\n\n" + "\n".join(warns)
        set_waiver_tx_flash(session, level="success", message=message)
        try:
            sync_waiver_roster_views(session, stats_pool=stats_pool, normalize_name_fn=normalize_name_fn)
        except Exception:
            pass
        _request_waiver_widget_clear(session)
        st.rerun()
        return
    errors = [str(err) for err in (tx_result.get("errors") or []) if str(err).strip()]
    if errors:
        set_waiver_tx_flash(session, level="error", message="\n".join(errors))
        st.rerun()
        return
    set_waiver_tx_flash(
        session,
        level="error",
        message="Waiver move could not be applied. Check your add/drop selections and try again.",
    )
    st.rerun()


def render_waiver_wire_page(
    st: Any,
    session: dict[str, Any],
    *,
    current_stats_pool: pd.DataFrame,
    league_roster_stats: pd.DataFrame | None = None,
    normalize_name_fn=None,
    page_label_fn=None,
) -> None:
    context = get_active_league_context(session)
    if not context:
        st.warning(
            "No fantasy context available. Set a **Saved Active Draft** in Saved Draft Library, "
            "or enable a **temporary / unsaved** simulator or live board override there."
        )
        return

    try:
        from fantasy_league_identity import resolve_canonical_league_id
        from player_waiver_handoff import consume_waiver_wire_handoff_into_planner

        active_context_id = str(context.get("league_context_id") or "").strip()
        active_canonical_league_id = str(resolve_canonical_league_id(context) or "").strip()
        consume_waiver_wire_handoff_into_planner(
            session,
            active_context_id=active_context_id,
            active_canonical_league_id=active_canonical_league_id,
        )
    except ImportError:
        pass

    purge_waiver_action_widget_keys(session)

    flash = pop_waiver_tx_flash(session)
    if flash:
        level = str(flash.get("level") or "info")
        message = str(flash.get("message") or "")
        if message:
            if level == "success":
                st.success(message)
            elif level == "error":
                st.error(message)
            elif level == "warning":
                st.warning(message)
            else:
                st.info(message)

    my_team = str(context.get("my_team_name") or "").strip()
    if my_team:
        st.caption(f"My team: **{my_team}**")

    stats_pool = current_stats_pool.copy() if current_stats_pool is not None else pd.DataFrame()
    if stats_pool.empty:
        st.warning(
            "**Current 2026 stats not loaded yet.** Open **Fantasy Standings Tracker**, "
            "load MLB API or CSV current-season stats, then return here."
        )
        return

    st.caption(
        "Waiver analysis uses **current-season MLB stats** and your **Fantasy Source** — "
        "not projections, ADP, Fantasy Edge, or draft-risk metrics."
    )

    try:
        from fantasy_in_season_state import prepare_fantasy_in_season_hydration

        prepare_fantasy_in_season_hydration(session)
    except ImportError:
        pass

    league_df = league_roster_stats.copy() if league_roster_stats is not None and not league_roster_stats.empty else pd.DataFrame()
    session_roster = session.get("fantasy_current_roster_stats")
    if isinstance(session_roster, pd.DataFrame) and not session_roster.empty:
        league_df = session_roster.copy()
    elif league_df.empty and normalize_name_fn is not None:
        cached = stats_pool
        if isinstance(cached, pd.DataFrame) and not cached.empty and has_full_league_rosters(context):
            league_df = build_roster_stats_from_league_context(
                context,
                cached,
                normalize_name_fn=normalize_name_fn,
            )

    my_team = str(context.get("my_team_name") or "").strip()
    league_df = filter_roster_stats_to_league_teams(league_df, context)
    if not league_df.empty and my_team and "Team" in league_df.columns:
        my_roster = league_df[league_df["Team"].astype(str) == my_team].copy()
    else:
        my_roster = my_team_roster_dataframe(context)
        if not my_roster.empty and not league_df.empty:
            name_col = "Player" if "Player" in league_df.columns else None
            if name_col:
                names = set(my_roster.get("Player", my_roster.get("fullName", pd.Series())).astype(str))
                my_roster = league_df[league_df[name_col].astype(str).isin(names)].copy()

    waiver_cats = waiver_categories_for_context(context)
    ctx_id = str(context.get("context_id") or context.get("draft_id") or context.get("display_name") or "")
    stats_sig = str(len(stats_pool)) + ":" + str(tuple(stats_pool.columns[:8].tolist()))
    try:
        from fantasy_league_context import league_rosters_cache_sig

        league_sig = league_rosters_cache_sig(context)
    except ImportError:
        league_sig = str(len(league_df)) + ":" + str(my_team)
    cache_key = None
    cached_payload = None
    try:
        from fantasy_perf_cache import (
            get_cached_waiver_analysis,
            store_waiver_analysis,
            waiver_analysis_cache_key,
        )

        cache_key = waiver_analysis_cache_key(
            context_id=ctx_id,
            my_team=my_team,
            stats_sig=stats_sig,
            league_sig=league_sig,
            categories=tuple(waiver_cats),
        )
        cached_payload = get_cached_waiver_analysis(session, cache_key)
    except ImportError:
        pass

    if cached_payload:
        needs = dict(cached_payload.get("needs") or {})
        waiver_pool = cached_payload.get("waiver_pool")
        if not isinstance(waiver_pool, pd.DataFrame):
            waiver_pool = pd.DataFrame()
        adds_cached = cached_payload.get("adds")
        adds = adds_cached.copy() if isinstance(adds_cached, pd.DataFrame) else pd.DataFrame()
        drops_cached = cached_payload.get("drops")
        drops = drops_cached.copy() if isinstance(drops_cached, pd.DataFrame) else pd.DataFrame()
    else:
        needs = analyze_current_team_needs(my_roster, league_df, categories=waiver_cats)
        waiver_pool = build_waiver_pool(stats_pool, context)
        adds = recommend_adds_personalized(
            waiver_pool,
            needs,
            context=context,
            my_roster=my_roster,
            limit=15,
        )
        if adds is None or adds.empty:
            adds = recommend_adds_current(waiver_pool, needs, limit=15)
        drops = recommend_drops_current(my_roster, limit=15, categories=waiver_cats)
        if cache_key is not None:
            try:
                from fantasy_perf_cache import store_waiver_analysis

                store_waiver_analysis(
                    session,
                    cache_key,
                    {
                        "needs": needs,
                        "waiver_pool": waiver_pool.copy() if not waiver_pool.empty else waiver_pool,
                        "adds": adds.copy() if not adds.empty else adds,
                        "drops": drops.copy() if not drops.empty else drops,
                    },
                )
            except ImportError:
                pass
    try:
        _has_slots = context_has_roster_slots(context)
        open_slots = resolve_context_open_position_needs(context, my_roster) if _has_slots else []
    except Exception:
        _has_slots = False
        open_slots = []

    st.markdown("##### Position filter")
    position_filter = st.selectbox(
        "Filter available players by position",
        list(WAIVER_POSITION_FILTER_OPTIONS),
        key=WAIVER_POSITION_FILTER_KEY,
        help="Applies to recommendations, search, tables, and add/drop selectors. "
        "Lineup Assistant pre-sets this when you open Waiver Wire for an empty slot.",
    )
    filtered_pool = _apply_waiver_position_filter(waiver_pool, position_filter)
    adds = _apply_waiver_position_filter(adds, position_filter) if not adds.empty else adds

    st.markdown("##### League snapshot")
    rank_lines = format_league_rank_lines(needs, categories=waiver_cats)
    if rank_lines:
        st.caption(" · ".join(rank_lines))
    cat_table = build_category_standings_table(needs, categories=waiver_cats)
    if not cat_table.empty:
        with st.expander("Category ranks", expanded=False):
            st.dataframe(cat_table, use_container_width=True, hide_index=True)
    for line in build_weakness_narrative(needs)[:2]:
        st.caption(line)

    _apply_deferred_waiver_widget_clears(session)

    try:
        from fantasy_waiver_wire import waiver_roster_transaction_mode

        tx_mode = waiver_roster_transaction_mode(context, len(_player_names(my_roster)))
    except ImportError:
        tx_mode = "add_drop"

    st.markdown("##### Waiver Transaction")
    if tx_mode == "add_only":
        st.caption(
            "**Roster has open spots.** Select waiver players to add without a drop. "
            "You can still drop players separately if you want to swap."
        )
    elif tx_mode == "cleanup_required":
        st.warning("Roster is over capacity. Drop players before adding more.")
    else:
        st.caption(
            "**Step 1:** Select waiver players to add (1–2). **Step 2:** Select roster players to drop "
            "(same count). **Step 3:** Confirm the move. Allowed: Add 1/Drop 1 or Add 2/Drop 2."
        )
    add_options = _player_names(filtered_pool)
    drop_options = _player_names(my_roster)
    tx_adds = st.multiselect(
        "Players to ADD (waiver pool)",
        add_options,
        key="waiver_tx_add_players",
        placeholder="Choose 1–2 free agents…",
        max_selections=MAX_WAIVER_MOVE_PAIRS,
    )
    tx_drops = st.multiselect(
        "Players to DROP (your roster)",
        drop_options,
        key="waiver_tx_drop_players",
        placeholder="Choose 1–2 matching roster drops…",
        max_selections=MAX_WAIVER_MOVE_PAIRS,
    )
    if tx_adds or tx_drops:
        if tx_mode == "add_drop" and len(tx_adds) != len(tx_drops):
            st.warning(
                f"Select the same number of adds and drops "
                f"({len(tx_adds)} add(s) · {len(tx_drops)} drop(s)) — up to {MAX_WAIVER_MOVE_PAIRS} pairs."
            )
        elif len(tx_adds) > MAX_WAIVER_MOVE_PAIRS:
            st.warning(
                f"At most {MAX_WAIVER_MOVE_PAIRS} add/drop pairs per transaction (Add 1/Drop 1 or Add 2/Drop 2)."
            )
    if (
        tx_adds
        and len(tx_adds) <= MAX_WAIVER_MOVE_PAIRS
        and (tx_mode == "add_only" or (tx_drops and len(tx_adds) == len(tx_drops)))
    ):
        impact = compute_waiver_transaction_impact(
            my_roster,
            list(tx_adds),
            list(tx_drops),
            stats_pool=stats_pool,
            needs=needs,
            categories=tuple(waiver_cats),
        )
        impact_rows = impact.get("rows") or []
        if impact_rows:
            st.markdown("**Projected impact**")
            st.dataframe(pd.DataFrame(impact_rows), use_container_width=True, hide_index=True)
            gain = str(impact.get("biggest_gain") or "").strip()
            loss = str(impact.get("biggest_loss") or "").strip()
            bits: list[str] = []
            if gain:
                bits.append(f"Biggest gain: **{gain}**")
            if loss:
                bits.append(f"Biggest loss: **{loss}**")
            if bits:
                st.caption(" · ".join(bits))
    st.button(
        "Confirm Waiver Move",
        key="waiver_confirm_tx_btn",
        type="primary",
        on_click=_on_confirm_waiver_move_click,
    )

    try:
        from fantasy_waiver_wire import rostered_player_names
        from recommendation_player_diagnostics import (
            diagnose_recommendation_players,
            format_recommendation_diagnostic_line,
        )

        _waiver_rostered = rostered_player_names(context)
        _waiver_diag_rows = diagnose_recommendation_players(
            source_pool=stats_pool,
            available_pool=waiver_pool,
            recs=adds,
            drafted_or_rostered=_waiver_rostered,
            needed_positions=None,
            rec_limit=15,
            context=context,
            value_col="Expected Fantasy Value" if "Expected Fantasy Value" in stats_pool.columns else "HR",
            rank_col="Expected Fantasy Value" if "Expected Fantasy Value" in (waiver_pool.columns if not waiver_pool.empty else []) else "HR",
        )
        with st.expander("Top player recommendation diagnostics", expanded=False):
            st.caption(
                "Why top raw-value players (including Ohtani) are available, ranked, or excluded from waiver adds."
            )
            for _diag_row in _waiver_diag_rows:
                st.markdown(format_recommendation_diagnostic_line(_diag_row))
    except ImportError:
        pass

    st.markdown("##### 1. Top Recommended Adds")
    if adds.empty:
        st.info("No waiver recommendations yet — load current-season stats and check your league context.")
    else:
        for i, (_, row) in enumerate(adds.head(15).iterrows()):
            _render_add_player_card(st, row, key_prefix=f"waiver_rec_{i}")

    st.markdown("##### 2. Recommended Drops")
    if drops.empty:
        st.info("No drop candidates on your roster yet.")
    else:
        selected_drop = str(session.get(WAIVER_PLANNER_DROP_KEY) or "").strip()

        for i, (_, row) in enumerate(drops.head(15).iterrows()):
            name = str(row.get("Player") or row.get("fullName") or "")
            label = "Selected To Drop" if name == selected_drop else "Plan Drop"
            _render_drop_player_card(
                st,
                row,
                key_prefix=f"waiver_drop_{i}",
                button_label=label,
            )

    st.markdown("##### 3. Available Player Pool")
    st.caption(
        f"{len(filtered_pool)} waiver-eligible players for **{position_filter}**. "
        "Search and sort in the table — use **Plan Add** cards above or the planner below."
    )
    search_query = st.text_input(
        "Search available players",
        key="waiver_pool_search",
        placeholder="Type a player name…",
    )
    if filtered_pool.empty:
        st.info("No waiver players match this position filter.")
    else:
        pool_view = filtered_pool.copy()
        if search_query:
            names = _player_names(pool_view)
            keep = set(filter_waiver_names_by_search(names, search_query))
            name_col = "Player" if "Player" in pool_view.columns else "fullName"
            if name_col in pool_view.columns:
                pool_view = pool_view[pool_view[name_col].astype(str).isin(keep)]
        disp_cols = [c for c in waiver_display_stat_columns(pool_view) if c in pool_view.columns]
        extra_cols = [c for c in ("Team", "Primary Position", "Position", "MLB Team") if c in pool_view.columns]
        for c in extra_cols:
            if c not in disp_cols:
                disp_cols.insert(0, c)
        st.dataframe(pool_view[disp_cols].head(150), use_container_width=True, hide_index=True)

    st.markdown("##### 4. Manual Add / Drop Actions")
    st.caption("Pick an add and a drop below, or use **Plan Add** / **Plan Drop** cards above.")
    manual_add_options = [""] + add_options
    manual_drop_options = [""] + drop_options
    manual_add_pick = st.selectbox(
        "Add player (waiver pool)",
        manual_add_options,
        key="waiver_manual_add_select",
        format_func=lambda name: "Select a waiver add…" if not name else name,
    )
    manual_drop_pick = st.selectbox(
        "Drop player (your roster)",
        manual_drop_options,
        key="waiver_manual_drop_select",
        format_func=lambda name: "Select a roster drop…" if not name else name,
    )
    planner_add = str(session.get(WAIVER_PLANNER_ADD_KEY) or manual_add_pick or "").strip()
    planner_drop = str(session.get(WAIVER_PLANNER_DROP_KEY) or manual_drop_pick or "").strip()
    if planner_add:
        add_row = _row_for_player(filtered_pool, planner_add)
        if add_row is not None:
            st.markdown("**Add target**")
            _render_player_card(
                st,
                add_row,
                key_prefix="waiver_planner_add",
                button_label="Clear Add",
                on_click=_on_clear_planner_add_click,
            )
    if planner_drop:
        drop_row = _row_for_player(my_roster, planner_drop)
        if drop_row is not None:
            st.markdown("**Drop candidate**")
            _render_player_card(
                st,
                drop_row,
                key_prefix="waiver_planner_drop",
                button_label="Clear Drop",
                on_click=_on_clear_planner_drop_click,
            )
    add_row = _row_for_player(filtered_pool, planner_add) if planner_add else None
    drop_row = _row_for_player(my_roster, planner_drop) if planner_drop else None
    impact = compute_add_drop_category_impact(
        add_row,
        drop_row,
        categories=list(needs.get("available_categories") or waiver_cats),
    )
    if impact:
        st.caption(f"**Category impact:** {', '.join(impact)}")
    st.button(
        "Add to Pending Moves",
        key="waiver_save_pair_btn",
        type="primary",
        on_click=_on_add_pending_pair_click,
    )

    st.markdown("##### Pending Add/Drop Moves")
    pairs = get_pending_move_pairs(session)
    if not pairs:
        st.caption("No pending add/drop pairs yet.")
    else:
        for i, pair in enumerate(pairs):
            add_name = str(pair.get("add_player") or "")
            drop_name = str(pair.get("drop_player") or "")
            impact_txt = ", ".join(pair.get("category_impact") or []) or "—"
            st.markdown(f"**Add:** {add_name}  ·  **Drop:** {drop_name}")
            st.caption(f"Category impact: {impact_txt}")
            st.button(
                "Remove pair",
                key=f"waiver_rm_pair_{i}_btn",
                on_click=_on_remove_pending_pair_click,
                args=(i,),
            )
        st.button(
            "Confirm Pending Waiver Moves",
            key="waiver_confirm_pending_btn",
            type="primary",
            on_click=_on_confirm_pending_waiver_moves_click,
        )
