"""Fantasy Lineup Assistant — Lineup Management tab rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd


@dataclass
class LineupManagementDeps:
    """Callables and constants supplied by streamlit_app (avoids circular imports)."""

    build_lineup_assistant_scores: Callable[..., Any]
    enrich_lineup_roster_positions: Callable[..., pd.DataFrame]
    parse_custom_lineup_slots: Callable[..., list[str] | None]
    build_position_aware_lineup: Callable[..., dict[str, Any]]
    roster_position_slot_list: Callable[..., list[str]]
    lineup_diagnosis_report: Callable[..., dict[str, Any]]
    open_waiver_wire_from_lineup_slot: Callable[..., None]
    fantasy_filter_changed: Callable[..., None]
    ensure_select_in_options: Callable[..., Any]
    ensure_widget_state: Callable[..., Any]
    render_output_table: Callable[..., Any]
    format_lineup_assistant_table: Callable[..., pd.DataFrame]
    clean_ui_columns: Callable[..., pd.DataFrame]
    render_contextual_page_nav: Callable[..., None]
    developer_mode_enabled: Callable[[], bool]
    navigate_to_page: Callable[..., None]
    page_option_label: Callable[..., str]
    safe_collection_len: Callable[..., int]
    lineup_default_hitting_slots: tuple[str, ...]
    resolve_lineup_scoring_format: Callable[..., str]


def render_lineup_management_page(
    st: Any,
    session: dict[str, Any],
    *,
    roster_stats: pd.DataFrame,
    lineup_team: str,
    lineup_teams: list[str],
    deps: LineupManagementDeps,
) -> None:
    _weekly_team_roster = (
        roster_stats[roster_stats["Team"].astype(str) == str(lineup_team)].copy()
        if lineup_team
        else pd.DataFrame()
    )
    if not _weekly_team_roster.empty:
        _weekly_team_roster = deps.enrich_lineup_roster_positions(_weekly_team_roster)
        _lineup_fmt_resolved = deps.resolve_lineup_scoring_format(session)
        session["lineup_format"] = _lineup_fmt_resolved
        _lineup_scored_for_weekly = None
        try:
            _lineup_scored_for_weekly = deps.build_lineup_assistant_scores(
                _weekly_team_roster, _lineup_fmt_resolved, None
            )
        except Exception:
            _lineup_scored_for_weekly = None
        try:
            from fantasy_weekly_lineup_ui import render_weekly_lineup_section

            render_weekly_lineup_section(
                st,
                session,
                team_roster=_weekly_team_roster,
                lineup_team=str(lineup_team or ""),
                on_open_waiver_wire=deps.open_waiver_wire_from_lineup_slot,
                scored_roster=_lineup_scored_for_weekly,
            )
        except ImportError:
            pass

    _lineup_format_options = ["5x5 Roto", "Points League", "Head-to-Head Categories"]
    with st.expander("Start-Sit recommendations", expanded=False):
        l2, l3 = st.columns(2)
        with l2:
            _lineup_fmt_resolved = deps.resolve_lineup_scoring_format(session)
            session["lineup_format"] = _lineup_fmt_resolved
            deps.ensure_select_in_options("lineup_format", _lineup_format_options, _lineup_fmt_resolved)
            lineup_format = st.selectbox(
                "Lineup Scoring Mode",
                _lineup_format_options,
                key="lineup_format",
                on_change=deps.fantasy_filter_changed,
                help="Roto and Points League follow your global fantasy format (Draft Room / Standings). Head-to-Head is lineup-only.",
            )
        with l3:
            _context_bench_default = 12
            try:
                from fantasy_league_context import get_active_league_context, resolve_context_bench_slot_count

                _lineup_bench_ctx = get_active_league_context(session)
                _ctx_bench = resolve_context_bench_slot_count(_lineup_bench_ctx)
                if _ctx_bench is not None:
                    _context_bench_default = max(3, min(25, int(_ctx_bench) or 3))
            except ImportError:
                pass
            deps.ensure_widget_state("lineup_bench_rows", _context_bench_default)
            bench_rows_to_show = st.slider(
                "Bench rows to show",
                min_value=3,
                max_value=25,
                value=int(session["lineup_bench_rows"]),
                key="lineup_bench_rows",
                on_change=deps.fantasy_filter_changed,
            )
    if deps.developer_mode_enabled():
        with st.sidebar.expander("Lineup data trace", expanded=False):
            _lu_diag = {
                "roster_rows": len(roster_stats),
                "stats_loaded_at": session.get("_fantasy_standings_stats_loaded_at"),
                "stats_source": session.get("_fantasy_standings_stats_source"),
                "lineup_team": lineup_team,
                "lineup_team_in_options": lineup_team in lineup_teams,
                "all_teams": lineup_teams,
                "lineup_format": session.get("lineup_format"),
                "room_format": session.get("room_format"),
                "standings_scoring_format": session.get("standings_scoring_format"),
                "room_your_team": session.get("room_your_team"),
                "draft_room_pick_count": deps.safe_collection_len(session.get("draft_room_table")),
                "cloud_restore_source": session.get("_fantasy_restore_source"),
            }
            for _k, _v in _lu_diag.items():
                st.text(f"{_k}: {_v}")

    _context_lineup_slots = None
    _lineup_active_context = None
    _context_has_slots = False
    use_util = True
    custom_slots_text = ""
    try:
        from fantasy_league_context import (
            context_has_roster_slots,
            get_active_league_context,
            resolve_context_lineup_slots,
        )

        _lineup_active_context = get_active_league_context(session)
        _context_has_slots = context_has_roster_slots(_lineup_active_context)
        if _context_has_slots:
            _context_lineup_slots = resolve_context_lineup_slots(_lineup_active_context)
    except ImportError:
        pass

    # A saved context with no roster-slot rules (e.g. a mock-draft simulation)
    # must not be filled with a default 15-player lineup. Suppress positional
    # completion checks and analyze category/value/balance only.
    _context_no_slot_config = bool(_lineup_active_context) and not _context_has_slots

    if _context_lineup_slots:
        st.caption(
            f"**Active league context slots ({len(_context_lineup_slots)}):** "
            f"{', '.join(_context_lineup_slots)}. "
            "Lineup needs and recommendations use this format — not the default 15-player template."
        )
    elif _context_no_slot_config:
        st.info(
            "This mock draft was saved without roster-slot settings, so analysis focuses "
            "on player value, category balance, and team strengths rather than missing "
            "lineup positions."
        )
    else:
        with st.expander("Starting lineup slots (optional)"):
            deps.ensure_widget_state("lineup_include_util", True)
            use_util = st.checkbox(
                "Include UTIL slot",
                key="lineup_include_util",
                help="Uncheck if your league has no UTIL. A custom slot list below replaces defaults when provided.",
                on_change=deps.fantasy_filter_changed,
            )
            custom_slots_text = st.text_input(
                "Custom slot order (comma-separated)",
                placeholder="e.g. C, 1B, 2B, 3B, SS, OF, OF, OF, UTIL",
                key="lineup_custom_slots",
                help="Valid tokens: C, 1B, 2B, 3B, SS, OF, LF, CF, RF, UTIL. Leave blank for default order.",
                on_change=deps.fantasy_filter_changed,
            )

    custom_weights = None
    if lineup_format == "Points League":
        with st.expander("Custom Points Scoring"):
            pw1, pw2, pw3, pw4 = st.columns(4)
            with pw1:
                w_r = st.number_input("Run Pts", value=1.0, step=0.5, key="lineup_pts_r")
                w_rbi = st.number_input("RBI Pts", value=1.0, step=0.5, key="lineup_pts_rbi")
            with pw2:
                w_hr = st.number_input("HR Pts", value=4.0, step=0.5, key="lineup_pts_hr")
                w_sb = st.number_input("SB Pts", value=2.0, step=0.5, key="lineup_pts_sb")
            with pw3:
                w_h = st.number_input("Hit Pts", value=1.0, step=0.5, key="lineup_pts_h")
                w_bb = st.number_input("Walk Pts", value=1.0, step=0.5, key="lineup_pts_bb")
            with pw4:
                w_ops = st.number_input("OPS Weight", value=10.0, step=1.0, key="lineup_pts_ops")
            custom_weights = {"R": w_r, "RBI": w_rbi, "HR": w_hr, "SB": w_sb, "H": w_h, "BB": w_bb, "OPS": w_ops}

    team_roster = roster_stats[roster_stats["Team"].astype(str) == str(lineup_team)].copy()
    if team_roster.empty:
        st.warning("No players found for the selected team.")
    else:
        team_roster = deps.enrich_lineup_roster_positions(team_roster)
        lineup_scored_for_weekly = None
        try:
            lineup_scored_for_weekly = deps.build_lineup_assistant_scores(
                team_roster, lineup_format, custom_weights
            )
        except Exception:
            lineup_scored_for_weekly = None
        try:
            from fantasy_perf_cache import (
                _df_sig,
                get_cached_lineup_scores,
                lineup_scores_cache_key,
                store_lineup_scores,
            )
            from page_perf_phases import session_perf_phase

            if _context_lineup_slots:
                _slot_list_preview = list(_context_lineup_slots)
            elif _context_no_slot_config:
                _slot_list_preview = deps.roster_position_slot_list(team_roster)
            else:
                _slot_list_preview = deps.parse_custom_lineup_slots(custom_slots_text)
                if _slot_list_preview is None:
                    _slot_list_preview = list(deps.lineup_default_hitting_slots)
                    if not use_util:
                        _slot_list_preview = [s for s in _slot_list_preview if s != "UTIL"]
            _lineup_cache_key = lineup_scores_cache_key(
                team=str(lineup_team),
                lineup_format=str(lineup_format),
                roster_sig=_df_sig(team_roster, extra="lineup"),
                custom_weights=custom_weights,
                slot_sig=",".join(_slot_list_preview),
            )
            scored = get_cached_lineup_scores(session, _lineup_cache_key)
            if scored is None:
                with session_perf_phase(session, "lineup_assistant_scores"):
                    scored = deps.build_lineup_assistant_scores(team_roster, lineup_format, custom_weights)
                store_lineup_scores(session, _lineup_cache_key, scored)
        except ImportError:
            scored = deps.build_lineup_assistant_scores(team_roster, lineup_format, custom_weights)
        scored = scored.sort_values("Lineup Confidence", ascending=False)

        if _context_lineup_slots:
            slot_list = list(_context_lineup_slots)
        elif _context_no_slot_config:
            # No saved roster-slot rules: derive slots from the players actually
            # on the roster so no fake missing positions are generated.
            slot_list = deps.roster_position_slot_list(team_roster)
        else:
            slot_list = deps.parse_custom_lineup_slots(custom_slots_text)
            if slot_list is None:
                slot_list = list(deps.lineup_default_hitting_slots)
                if not use_util:
                    slot_list = [s for s in slot_list if s != "UTIL"]
            elif not use_util:
                slot_list = [s for s in slot_list if s != "UTIL"]

        lineup_pkg = deps.build_position_aware_lineup(scored, slots=slot_list)
        starters = lineup_pkg["lineup_df"]

        # Mock drafts without slot rules must not surface positional-completion
        # warnings or invented roster needs.
        if _context_no_slot_config:
            lineup_pkg["slot_warnings"] = []
            lineup_pkg["missing_slots"] = []

        for w in lineup_pkg["slot_warnings"]:
            st.warning(w)

        st.subheader("Recommended Starters")
        st.caption(
            "Position-aware starters for your active team. **Start/Sit Recommendation** shows the call; "
            "**Lineup Reason** explains confidence and why."
        )
        if not starters.empty:
            try:
                from player_photos import get_player_photo_info, inject_player_photo_styles, render_rec_card_photo_html

                inject_player_photo_styles(st)
                photo_cells: list[str] = []
                for _, srow in starters.head(9).iterrows():
                    pname = str(srow.get("Player") or srow.get("fullName") or "")
                    slot_lbl = str(srow.get("Fantasy slot") or "")
                    photo_info = get_player_photo_info(full_name=pname, row=srow, use_api=True)
                    photo_html = render_rec_card_photo_html(photo_info, alt=pname)
                    photo_cells.append(
                        f'<div style="text-align:center;min-width:64px;">{photo_html}'
                        f'<div style="font-size:0.7rem;font-weight:600;">{slot_lbl}</div>'
                        f'<div style="font-size:0.68rem;color:#64748b;">{pname.split()[-1] if pname else ""}</div></div>'
                    )
                if photo_cells:
                    st.markdown(
                        f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 12px;">{"".join(photo_cells)}</div>',
                        unsafe_allow_html=True,
                    )
            except ImportError:
                pass
        starter_cols = [
            "Fantasy slot",
            "Player",
            "Primary Position",
            "MLB Team",
            "Start/Sit Recommendation",
            "Lineup Confidence",
            "Momentum Score",
            "Consistency Score",
            "Volatility Meter",
            "HR",
            "RBI",
            "R",
            "SB",
            "BA",
            "OPS",
            "Lineup Reason",
        ]
        if starters.empty:
            st.info("No eligible players matched every required hitting slot — check warnings above and your roster’s Primary Position values.")
        starter_disp_rows = max(1, min(15, len(starters))) if not starters.empty else 1
        deps.render_output_table(
            deps.format_lineup_assistant_table(deps.clean_ui_columns(starters[[c for c in starter_cols if c in starters.columns]])),
            key="lineup_recommended_starters",
            file_name="lineup_recommended_starters.csv",
            display_rows=starter_disp_rows,
        )
        deps.render_contextual_page_nav(
            "Fantasy Lineup Assistant",
            "after_lineup",
            label="Analyze this roster in…",
            extra_context={"team": lineup_team},
        )

        st.subheader("Lineup Diagnosis / How to Improve This Team")
        st.caption(
            "Uses **Standings Tracker current-season stats** merged with your Draft Room roster. "
            "**Lineup** = the **position-aware recommended starters** above; **team** = full drafted team on this page. "
            "Shares and ranks compare starter totals to the whole team — not projected rest-of-season."
        )
        if lineup_format == "5x5 Roto":
            deps.ensure_select_in_options("lineup_diagnosis_rate_col", ["BA", "OBP"], "BA")
            diag_rate_choice = st.radio(
                "Roto rate category",
                ["BA", "OBP"],
                horizontal=True,
                key="lineup_diagnosis_rate_col",
                help="OBP requires an OBP column in your loaded stats.",
            )
        else:
            diag_rate_choice = "BA"
            st.caption("For non-roto modes, the table still uses raw HR/R/RBI/SB/BA from loaded stats.")

        rate_for_diag = str(diag_rate_choice).upper() if lineup_format == "5x5 Roto" else "BA"
        if rate_for_diag == "OBP" and "OBP" not in starters.columns:
            rate_for_diag = "BA"
            st.caption("OBP not found in roster stats — using **BA** for the rate row.")

        diag = deps.lineup_diagnosis_report(
            starters,
            scored,
            lineup_format,
            rate_col=rate_for_diag,
            missing_slots=lineup_pkg["missing_slots"],
            slot_warnings=lineup_pkg["slot_warnings"],
            league_roster_df=roster_stats,
        )

        _outlook_line = ""
        _strength_cats: list[str] = []
        _weakness_cats: list[str] = []
        _cat_ranks: dict[str, int] = {}
        _cat_values: dict[str, float] = {}
        _n_teams = 0
        _needs: dict = {}
        _waiver_pool = pd.DataFrame()
        _ctx = None
        try:
            from fantasy_league_context import get_active_league_context

            _ctx = get_active_league_context(session)
            _ctx_id = str((_ctx or {}).get("league_context_id") or "")
            _roster_sig = ""
            try:
                from fantasy_perf_cache import _df_sig

                _roster_sig = _df_sig(roster_stats, extra=str(lineup_team or ""))
            except ImportError:
                _roster_sig = str(len(roster_stats))
            _stats_sig = str(session.get("_fantasy_current_hitter_stats_sig") or "")
            _diag_cache_key = None
            try:
                from fantasy_perf_cache import (
                    get_cached_lineup_diagnosis,
                    lineup_diagnosis_cache_key,
                    store_lineup_diagnosis,
                )

                _diag_cache_key = lineup_diagnosis_cache_key(
                    context_id=_ctx_id,
                    team=str(lineup_team or ""),
                    roster_sig=_roster_sig,
                    stats_sig=_stats_sig,
                    lineup_format=str(lineup_format or ""),
                    rate_col=str(rate_for_diag or ""),
                    missing_slots=tuple(str(s) for s in (lineup_pkg.get("missing_slots") or [])),
                )
                _cached_diag = get_cached_lineup_diagnosis(session, _diag_cache_key)
            except ImportError:
                _cached_diag = None
                _diag_cache_key = None

            if isinstance(_cached_diag, dict):
                _needs = dict(_cached_diag.get("needs") or {})
                _cat_ranks = dict(_cached_diag.get("category_ranks") or {})
                _cat_values = dict(_cached_diag.get("category_values") or {})
                _n_teams = int(_cached_diag.get("n_teams") or 0)
                _strength_cats = list(_cached_diag.get("strength_cats") or [])
                _weakness_cats = list(_cached_diag.get("weakness_cats") or [])
                _outlook_line = str(_cached_diag.get("outlook_line") or "")
                _pool_df = _cached_diag.get("waiver_pool")
                if isinstance(_pool_df, pd.DataFrame):
                    _waiver_pool = _pool_df.copy()
            else:
                try:
                    from page_perf_phases import session_perf_phase

                    _diag_phase = session_perf_phase(session, "lineup_diagnosis_bundle")
                except ImportError:
                    from contextlib import nullcontext

                    _diag_phase = nullcontext()
                with _diag_phase:
                    from fantasy_waiver_wire import analyze_current_team_needs, build_waiver_pool, merge_current_season_stats

                    _my_team_df = (
                        roster_stats[roster_stats["Team"].astype(str) == str(lineup_team)]
                        if "Team" in roster_stats.columns
                        else roster_stats
                    )
                    if not _my_team_df.empty:
                        _needs = analyze_current_team_needs(_my_team_df, roster_stats)
                        _cat_ranks = dict(_needs.get("category_ranks") or {})
                        _cat_values = dict(_needs.get("category_values") or {})
                        _n_teams = int(_needs.get("n_teams") or 0)
                    _hit = session.get("_fantasy_current_hitter_stats", pd.DataFrame())
                    _pit = session.get("_fantasy_current_pitcher_stats", pd.DataFrame())
                    _pool = merge_current_season_stats(_hit, _pit)
                    _waiver_pool = build_waiver_pool(_pool, _ctx) if not _pool.empty else pd.DataFrame()
                    from fantasy_actionable_recommendations import (
                        league_strength_categories,
                        league_weakness_categories,
                        team_outlook_summary,
                    )

                    _strength_cats = league_strength_categories(_cat_ranks, n_teams=_n_teams) if _cat_ranks else []
                    _weakness_cats = league_weakness_categories(_cat_ranks, n_teams=_n_teams) if _cat_ranks else []
                    if _needs.get("strengths"):
                        _strength_cats = list(_needs.get("strengths") or _strength_cats)[:2]
                    if _needs.get("weaknesses"):
                        _weakness_cats = list(_needs.get("weaknesses") or _weakness_cats)[:2]
                    _outlook, _confidence, _stars = team_outlook_summary(
                        strong_cats=_strength_cats,
                        weak_cats=_weakness_cats,
                        category_ranks=_cat_ranks,
                        n_teams=_n_teams,
                    )
                    _outlook_line = f"**Team Outlook:** {_outlook} · **Confidence:** {_confidence} · {_stars}"
                if _diag_cache_key is not None:
                    try:
                        from fantasy_perf_cache import store_lineup_diagnosis

                        store_lineup_diagnosis(
                            session,
                            _diag_cache_key,
                            {
                                "needs": _needs,
                                "category_ranks": _cat_ranks,
                                "category_values": _cat_values,
                                "n_teams": _n_teams,
                                "strength_cats": _strength_cats,
                                "weakness_cats": _weakness_cats,
                                "outlook_line": _outlook_line,
                                "waiver_pool": _waiver_pool.copy() if not _waiver_pool.empty else pd.DataFrame(),
                            },
                        )
                    except ImportError:
                        pass
        except Exception:
            pass

        if diag.get("slot_gaps"):
            st.warning(str(diag["slot_gaps"]))
            if lineup_pkg.get("missing_slots"):
                if st.button(
                    "View Waiver Options For Open Positions",
                    key="lineup_open_waiver_for_open_slots_btn",
                    use_container_width=False,
                ):
                    deps.navigate_to_page("Waiver Wire / Add-Drop Center")
        elif diag.get("weakest_pos"):
            with st.container(border=True):
                try:
                    from fantasy_actionable_recommendations import build_actionable_position_weakness_note

                    grp_col = (
                        "Fantasy slot"
                        if "Fantasy slot" in starters.columns
                        else "Primary Position"
                        if "Primary Position" in starters.columns
                        else None
                    )
                    worst_starters = (
                        starters[starters[grp_col].astype(str) == str(diag["weakest_pos"])]
                        if grp_col
                        else pd.DataFrame()
                    )
                    st.markdown(
                        build_actionable_position_weakness_note(
                            worst_pos=str(diag["weakest_pos"]),
                            worst_val=float(diag.get("weakest_pos_val") or 0),
                            starter_df=worst_starters,
                            waiver_pool=_waiver_pool,
                            needs=_needs,
                            benchmark=diag.get("weakest_pos_benchmark"),
                        )
                    )
                except ImportError:
                    if diag.get("position_note"):
                        st.markdown(str(diag["position_note"]))
        if _outlook_line:
            st.caption(_outlook_line.replace("**Team Outlook:**", "Team Outlook:"))

        _team_summary: dict = {}
        try:
            from fantasy_actionable_recommendations import (
                build_condensed_team_summary,
                render_condensed_team_summary,
            )

            _team_summary = build_condensed_team_summary(
                strong_cats=_strength_cats,
                weak_cats=_weakness_cats,
                needs=_needs,
                waiver_pool=_waiver_pool,
                league_context=_ctx if isinstance(_ctx, dict) else None,
            )
            with st.container(border=True):
                render_condensed_team_summary(st, _team_summary)
        except ImportError:
            _team_summary = {}

        if _needs:
            try:
                from fantasy_waiver_wire import build_category_action_table, style_category_action_table

                _cat_action = build_category_action_table(_needs)
                if not _cat_action.empty:
                    st.markdown("##### Category standings vs league")
                    st.dataframe(
                        style_category_action_table(_cat_action),
                        width="stretch",
                        hide_index=True,
                    )
            except ImportError:
                pass
        elif not diag["hitting_table"].empty:
            ht_disp = diag["hitting_table"].copy()
            if "Rel. strength (0–100)" in ht_disp.columns:
                rel_vals = pd.to_numeric(ht_disp["Rel. strength (0–100)"], errors="coerce")
                if rel_vals.isna().all() or rel_vals.nunique(dropna=True) <= 1:
                    ht_disp = ht_disp.drop(columns=["Rel. strength (0–100)"])
            mask_rate = ht_disp["Category"].isin(["AVG", "OBP"])
            ht_disp.loc[mask_rate, "Lineup total"] = pd.to_numeric(ht_disp.loc[mask_rate, "Lineup total"], errors="coerce").round(3)
            ht_disp.loc[~mask_rate, "Lineup total"] = pd.to_numeric(ht_disp.loc[~mask_rate, "Lineup total"], errors="coerce").round(0).astype("Int64")
            ht_disp["% of team"] = pd.to_numeric(ht_disp["% of team"], errors="coerce").round(1)
            st.markdown("##### Category strength (starters)")
            st.dataframe(ht_disp, width="stretch", hide_index=True)

        if diag.get("pitching_table") is not None and not diag["pitching_table"].empty:
            st.markdown("##### Pitching snapshot (full roster — if columns exist)")
            st.dataframe(diag["pitching_table"], width="stretch", hide_index=True)


        try:
            from fantasy_actionable_recommendations import build_team_actionable_summary, render_waiver_strategy_cards

            _action_lines = build_team_actionable_summary(
                strong_cats=_strength_cats,
                weak_cats=_weakness_cats,
                position_note=str(diag.get("position_note") or ""),
                needs=_needs,
                waiver_pool=_waiver_pool,
                league_rosters=roster_stats,
                my_team=str(lineup_team or ""),
                league_context=_ctx if isinstance(_ctx, dict) else None,
            )
            _waiver_cards = list((_team_summary or {}).get("waiver_targets") or [])
            if _waiver_cards:
                render_waiver_strategy_cards(st, _waiver_cards)
            for _action_line in _action_lines:
                if _action_line == "__WAIVER_CARDS__":
                    continue
                st.markdown(_action_line)
            if _action_lines or _waiver_cards:
                act_w, act_s = st.columns(2)
                with act_w:
                    if st.button(
                        deps.page_option_label("Waiver Wire / Add-Drop Center"),
                        key="lineup_open_waiver_wire_btn",
                        use_container_width=True,
                    ):
                        deps.navigate_to_page("Waiver Wire / Add-Drop Center")
                with act_s:
                    if st.button(
                        deps.page_option_label("Fantasy Standings Tracker"),
                        key="lineup_open_standings_btn",
                        use_container_width=True,
                    ):
                        deps.navigate_to_page("Fantasy Standings Tracker")
        except Exception as exc:
            if deps.developer_mode_enabled():
                st.caption(f"Action summary unavailable: {type(exc).__name__}: {exc}")
        if diag.get("balance_label"):
            st.caption(diag["balance_label"])

        rec_df = pd.DataFrame(diag.get("recommendations") or [])
        if not rec_df.empty and not _waiver_pool.empty and _needs:
            try:
                from fantasy_actionable_recommendations import enrich_recommendations_with_waiver_targets

                enriched = enrich_recommendations_with_waiver_targets(
                    rec_df.to_dict(orient="records"),
                    _waiver_pool,
                    needs=_needs,
                )
                rec_df = pd.DataFrame(enriched)
            except ImportError:
                pass
        elif not rec_df.empty:
            try:
                from fantasy_waiver_wire import analyze_current_team_needs, build_waiver_pool, merge_current_season_stats
                from fantasy_actionable_recommendations import enrich_recommendations_with_waiver_targets

                _hit = session.get("_fantasy_current_hitter_stats", pd.DataFrame())
                _pit = session.get("_fantasy_current_pitcher_stats", pd.DataFrame())
                _pool = merge_current_season_stats(_hit, _pit)
                from fantasy_league_context import get_active_league_context

                _ctx = get_active_league_context(session)
                _waiver_pool = build_waiver_pool(_pool, _ctx) if not _pool.empty else pd.DataFrame()
                _my_roster = scored[scored["Team"].astype(str) == str(lineup_team)] if "Team" in scored.columns else scored
                _needs = analyze_current_team_needs(_my_roster, roster_stats) if not _my_roster.empty else {}
                enriched = enrich_recommendations_with_waiver_targets(
                    rec_df.to_dict(orient="records"),
                    _waiver_pool,
                    needs=_needs,
                )
                rec_df = pd.DataFrame(enriched)
            except ImportError:
                pass
            st.subheader("Actionable Recommendations")
            st.caption("Concrete next steps — trades, adds, and category repairs for your weakest areas.")
            st.dataframe(rec_df, width="stretch", hide_index=True)

        st.subheader("Bench / Sit / Watch List")
        st.caption("Borderline options not in the recommended lineup — compare **Lineup Reason** vs your starters.")
        assigned_ix = set(starters.index) if not starters.empty else set()
        bench_pool = scored.drop(index=list(assigned_ix), errors="ignore") if assigned_ix else scored
        bench = bench_pool.sort_values("Lineup Confidence", ascending=False).head(bench_rows_to_show).copy()
        deps.render_output_table(
            deps.format_lineup_assistant_table(deps.clean_ui_columns(bench[[c for c in starter_cols if c in bench.columns]])),
            key="lineup_bench_watch",
            file_name="lineup_bench_watch.csv",
            display_rows=bench_rows_to_show,
        )

        st.divider()

