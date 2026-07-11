"""Unified Trade Center — discovery, analysis, and proposal prep in one workspace."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from fantasy_trade_ideas import (
    LINEUP_TRADE_CENTER_STATE_KEY,
    LINEUP_TRADE_IDEAS_DIAG_KEY,
    LINEUP_TRADE_IDEAS_RESULTS_KEY,
    empty_trade_ideas_message,
    generate_trade_ideas,
    resolve_player_owner_team,
    resolve_receive_target_teams,
)


def _persist_trade_plan(session: dict[str, Any], st: Any, *, reason: str) -> None:
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason=reason)
    except Exception:
        pass


def _trade_workspace(
    session: dict[str, Any],
    *,
    lineup_team: str,
) -> dict[str, Any]:
    roster_stats = session.get("fantasy_current_roster_stats", pd.DataFrame())
    standings = session.get("fantasy_current_standings", pd.DataFrame())
    if roster_stats is None or roster_stats.empty:
        return {
            "roster_stats": roster_stats,
            "standings": standings,
            "my_team": "",
            "other_teams": [],
            "my_players": [],
            "all_other_players": [],
        }

    trade_teams = sorted(roster_stats["Team"].dropna().astype(str).unique().tolist())
    my_team = lineup_team if lineup_team in trade_teams else (trade_teams[0] if trade_teams else "")
    other_teams = [t for t in trade_teams if t != my_team]
    my_players = sorted(
        roster_stats[roster_stats["Team"].astype(str) == str(my_team)]["Player"].dropna().astype(str).unique().tolist()
    )
    all_other_players = sorted(
        roster_stats[roster_stats["Team"].astype(str) != str(my_team)]["Player"].dropna().astype(str).unique().tolist()
    )
    return {
        "roster_stats": roster_stats,
        "standings": standings,
        "my_team": my_team,
        "other_teams": other_teams,
        "my_players": my_players,
        "all_other_players": all_other_players,
    }


def _apply_trade_idea(session: dict[str, Any], idea: dict[str, Any]) -> None:
    give = str(idea.get("Give") or "").strip()
    receive = str(idea.get("Receive") or "").strip()
    other = str(idea.get("Other Team") or "").strip()
    if give:
        session["lineup_trade_give_players"] = [give]
    if receive:
        session["lineup_trade_get_players"] = [receive]
    if other:
        session["lineup_trade_other_team"] = other
    session[LINEUP_TRADE_CENTER_STATE_KEY] = {
        "give_players": [give] if give else [],
        "get_players": [receive] if receive else [],
        "other_team": other,
        "from_idea": True,
    }


def render_trade_center_tab(
    st: Any,
    session: dict[str, Any],
    *,
    lineup_team: str,
    ensure_select_in_options: Callable[..., Any],
    ensure_multiselect_state: Callable[..., Any],
    evaluate_trade_fn: Callable[..., Any],
    build_trade_verdict_text_fn: Callable[..., str],
    render_output_table_fn: Callable[..., Any],
    format_trade_eval_table_fn: Callable[..., pd.DataFrame],
    format_fantasy_table_fn: Callable[..., pd.DataFrame],
    clean_ui_columns_fn: Callable[..., pd.DataFrame],
    summarize_team_category_needs_fn: Callable[..., dict[str, bool]],
    developer_mode_enabled_fn: Callable[[], bool],
) -> None:
    st.subheader("Trade Center")
    st.caption(
        "Select players you would give and receive, then analyze an exact trade or find helpful ideas. "
        "All Player Actions open here with shared selections."
    )

    ws = _trade_workspace(session, lineup_team=lineup_team)
    roster_stats = ws["roster_stats"]
    standings = ws["standings"]
    my_team = ws["my_team"]
    other_teams = ws["other_teams"]
    my_players = ws["my_players"]
    all_other_players = ws["all_other_players"]

    if roster_stats is None or roster_stats.empty:
        st.info("Load league rosters and current-season stats to use Trade Center.")
        return
    if not my_team:
        st.info("Select your active fantasy team to use Trade Center.")
        return

    try:
        from fantasy_league_context import get_active_league_context

        ctx = get_active_league_context(session) or {}
        league_id = str(ctx.get("league_context_id") or "")
    except ImportError:
        league_id = ""

    st.caption(f"**Your team:** {my_team} · **Active league:** {league_id or '—'}")

    try:
        from fantasy_trade_plan_ui import render_trade_plan_section

        workflow_give, workflow_get = render_trade_plan_section(
            st,
            session,
            persist_fn=_persist_trade_plan,
            key_prefix="lineup_trade_plan",
        )
    except ImportError:
        workflow_give, workflow_get = [], []

    pending_give = [p for p in workflow_give if p in my_players]
    pending_get = [p for p in workflow_get if p in all_other_players]
    if pending_give and "lineup_trade_give_players" not in session:
        session["lineup_trade_give_players"] = pending_give
    if pending_get and "lineup_trade_get_players" not in session:
        session["lineup_trade_get_players"] = pending_get

    ensure_multiselect_state("lineup_trade_give_players", my_players, pending_give or [])
    ensure_multiselect_state("lineup_trade_get_players", all_other_players, pending_get or [])

    give_players = st.multiselect("Players I Give", my_players, key="lineup_trade_give_players")
    receive_players = st.multiselect("Players I Receive", all_other_players, key="lineup_trade_get_players")

    other_team = ""
    if receive_players:
        owners = sorted(
            {
                owner
                for player in receive_players
                if (owner := resolve_player_owner_team(player, roster_stats, my_team=my_team))
            }
        )
        if len(owners) == 1:
            other_team = owners[0]
            session["lineup_trade_other_team"] = other_team
            st.caption(f"**Opposing team for selected receive player(s):** {other_team}")
        elif len(owners) > 1:
            st.caption(f"**Receive targets span teams:** {', '.join(owners)}")
    elif other_teams:
        default_other = str(session.get("lineup_trade_other_team") or other_teams[0])
        ensure_select_in_options("lineup_trade_other_team", other_teams, default_other)
        other_team = st.selectbox(
            "Opposing team (optional — used when evaluating a specific proposal)",
            other_teams,
            key="lineup_trade_other_team",
        )

    action_col1, action_col2 = st.columns(2)
    find_clicked = action_col1.button("Find Trade Ideas", key="lineup_find_trade_ideas_btn", type="primary")
    analyze_clicked = action_col2.button(
        "Analyze This Trade",
        key="lineup_analyze_trade_btn",
        disabled=not (give_players and receive_players),
    )
    similar_clicked = False
    if give_players and receive_players:
        similar_clicked = st.button("Find Similar Ideas", key="lineup_find_similar_ideas_btn")

    verdict = ""
    if analyze_clicked and give_players and receive_players:
        trade_eval, verdict, weighted_gain = evaluate_trade_fn(
            give_players,
            receive_players,
            roster_stats,
            roster_stats,
            standings,
            my_team,
        )
        st.metric("Trade Verdict", verdict)
        st.caption(build_trade_verdict_text_fn(trade_eval, weighted_gain))
        render_output_table_fn(
            format_trade_eval_table_fn(clean_ui_columns_fn(trade_eval)),
            key="lineup_trade_eval_table",
            file_name="lineup_trade_evaluation.csv",
            display_rows=20,
            style_cols=["Net Gain"],
        )
        try:
            from baseball_activity import log_trade_analysis

            trade_sig = (my_team, other_team, tuple(sorted(give_players)), tuple(sorted(receive_players)))
            if session.get("_cc_trade_activity_sig") != trade_sig:
                session["_cc_trade_activity_sig"] = trade_sig
                log_trade_analysis(give=give_players, get=receive_players, verdict=str(verdict or ""))
        except Exception:
            pass

    if find_clicked or similar_clicked:
        owner_map = resolve_receive_target_teams(receive_players, roster_stats, my_team=my_team)
        target_team = other_team if receive_players and not owner_map else None
        suggestions, diag = generate_trade_ideas(
            my_team,
            roster_stats,
            standings,
            forced_give=give_players if (give_players or similar_clicked) else None,
            forced_get=receive_players if (receive_players or similar_clicked) else None,
            target_team=target_team,
            target_owner_teams=owner_map,
            summarize_team_category_needs_fn=summarize_team_category_needs_fn,
            league_context_id=league_id,
        )
        diag["button_action"] = "find_similar" if similar_clicked else "find_trade_ideas"
        session[LINEUP_TRADE_IDEAS_RESULTS_KEY] = (
            suggestions.to_dict(orient="records") if not suggestions.empty else []
        )
        session[LINEUP_TRADE_IDEAS_DIAG_KEY] = diag

    stored_rows = session.get(LINEUP_TRADE_IDEAS_RESULTS_KEY) or []
    diag = session.get(LINEUP_TRADE_IDEAS_DIAG_KEY) or {}
    suggestions = pd.DataFrame(stored_rows) if stored_rows else pd.DataFrame()

    if not suggestions.empty:
        st.markdown("##### Suggested trades")
        render_output_table_fn(
            format_fantasy_table_fn(clean_ui_columns_fn(suggestions)),
            key="lineup_trade_suggestions",
            file_name="lineup_trade_suggestions.csv",
            display_rows=20,
            style_cols=["Trade Fit Score", "Fairness Gap"],
        )
        for idx, row in suggestions.head(8).iterrows():
            label = (
                f"Use: give {row.get('Give')} · receive {row.get('Receive')} "
                f"({row.get('Other Team')})"
            )
            if st.button(label, key=f"lineup_use_trade_idea_{idx}"):
                _apply_trade_idea(session, row.to_dict())
                st.rerun()
    elif find_clicked or similar_clicked or diag.get("button_clicked"):
        st.info(empty_trade_ideas_message())

    session[LINEUP_TRADE_CENTER_STATE_KEY] = {
        "my_team": my_team,
        "other_team": other_team,
        "give_players": list(give_players or []),
        "get_players": list(receive_players or []),
        "verdict": str(verdict or ""),
        "league_id": league_id,
    }
    session["_lineup_trade_analyzer_state"] = session[LINEUP_TRADE_CENTER_STATE_KEY]

    if developer_mode_enabled_fn():
        with st.expander("Trade Center diagnostics (Developer Mode)", expanded=bool(find_clicked or analyze_clicked)):
            st.json(
                {
                    "button_action": diag.get("button_action") or ("analyze" if analyze_clicked else None),
                    "give_players": list(give_players or []),
                    "receive_players": list(receive_players or []),
                    "active_league_id": league_id or diag.get("active_league_id"),
                    "my_team": my_team,
                    "other_team": other_team,
                    "target_owner_teams": diag.get("target_owner_teams") or resolve_receive_target_teams(
                        receive_players, roster_stats, my_team=my_team
                    ),
                    "opposing_teams_searched": diag.get("opposing_teams_searched") or other_teams,
                    "candidate_count_before_filters": diag.get("candidate_count_before_filters", 0),
                    "candidate_count_after_filters": diag.get("candidate_count_after_filters", 0),
                    "final_idea_count": diag.get("final_idea_count", len(suggestions)),
                    "failure_reason": diag.get("failure_reason"),
                }
            )


def render_offers_activity_tab(
    st: Any,
    session: dict[str, Any],
    *,
    lineup_team: str,
    developer_mode_enabled_fn: Callable[[], bool],
) -> None:
    st.subheader("Offers & Activity")
    ws = _trade_workspace(session, lineup_team=lineup_team)
    if ws["roster_stats"] is None or ws["roster_stats"].empty:
        st.info("Load league rosters and stats before reviewing trade offers.")
        return

    center_state = session.get(LINEUP_TRADE_CENTER_STATE_KEY) or session.get("_lineup_trade_analyzer_state") or {}
    give_players = list(center_state.get("give_players") or [])
    get_players = list(center_state.get("get_players") or [])
    verdict = str(center_state.get("verdict") or "")
    other_team = str(
        center_state.get("other_team")
        or session.get("lineup_trade_other_team")
        or (ws["other_teams"][0] if ws["other_teams"] else "")
    )

    try:
        from fantasy_trade_proposals_ui import (
            render_trade_proposals_section,
            render_trade_response_ui_v2_marker,
        )

        render_trade_response_ui_v2_marker(
            st,
            session,
            my_team=ws["my_team"],
            caller="lineup_offers_activity_tab",
        )
        render_trade_proposals_section(
            st,
            session,
            my_team=ws["my_team"],
            other_team=other_team,
            give_players=give_players,
            get_players=get_players,
            verdict=verdict,
            persist_fn=_persist_trade_plan,
            key_prefix="lineup_trade_proposals",
        )
    except ImportError as exc:
        st.warning(f"Trade proposals UI import failed: {exc}")
    except Exception as exc:
        st.error(f"Trade proposals UI render failed: {type(exc).__name__}: {exc}")
