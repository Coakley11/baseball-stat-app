"""Tabbed trade sections for Fantasy Lineup Assistant."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from fantasy_trade_ideas import (
    LINEUP_TRADE_IDEAS_DIAG_KEY,
    LINEUP_TRADE_IDEAS_RESULTS_KEY,
    empty_trade_ideas_message,
    generate_trade_ideas,
)


def _persist_trade_plan(session: dict[str, Any], st: Any, *, reason: str) -> None:
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason=reason)
    except Exception:
        pass


def _trade_context(
    session: dict[str, Any],
    *,
    lineup_team: str,
) -> tuple[pd.DataFrame, pd.DataFrame, str, list[str], str, list[str], list[str]]:
    roster_stats = session.get("fantasy_current_roster_stats", pd.DataFrame())
    standings = session.get("fantasy_current_standings", pd.DataFrame())
    if roster_stats is None or roster_stats.empty:
        return roster_stats, standings, "", [], "", [], []

    trade_teams = sorted(roster_stats["Team"].dropna().astype(str).unique().tolist())
    my_team = lineup_team if lineup_team in trade_teams else (trade_teams[0] if trade_teams else "")
    other_teams = [t for t in trade_teams if t != my_team]
    other_team = str(session.get("lineup_trade_other_team") or (other_teams[0] if other_teams else "")).strip()
    if other_team and other_team not in other_teams:
        other_team = other_teams[0] if other_teams else ""

    my_players = sorted(
        roster_stats[roster_stats["Team"].astype(str) == str(my_team)]["Player"].dropna().astype(str).unique().tolist()
    )
    other_players = sorted(
        roster_stats[roster_stats["Team"].astype(str) == str(other_team)]["Player"].dropna().astype(str).unique().tolist()
    ) if other_team else []
    return roster_stats, standings, my_team, other_teams, other_team, my_players, other_players


def render_trade_analyzer_tab(
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
    clean_ui_columns_fn: Callable[..., pd.DataFrame],
    developer_mode_enabled_fn: Callable[[], bool],
) -> None:
    st.subheader("Trade Analyzer")
    st.caption(
        "Evaluate proposed trades using current stats, standings, and category needs from the active league."
    )
    try:
        from fantasy_trade_proposals_ui import render_trade_response_ui_v2_marker

        render_trade_response_ui_v2_marker(
            st,
            session,
            my_team=str(session.get("lineup_team") or "").strip(),
            caller="lineup_trade_analyzer_tab",
        )
    except Exception:
        pass

    roster_stats, standings, my_team, other_teams, other_team, my_players, other_players = _trade_context(
        session,
        lineup_team=lineup_team,
    )
    if roster_stats.empty:
        st.info(
            "Load current-season stats on Fantasy Standings Tracker first so trade analysis can use live rosters."
        )
        return

    st.caption(f"**Your team:** {my_team or '—'} (from active fantasy team)")
    if not other_teams:
        st.info("Need at least two fantasy teams in the active league to analyze trades.")
        return

    ensure_select_in_options("lineup_trade_other_team", other_teams, other_team or other_teams[0])
    other_team = st.selectbox("Other Team", other_teams, key="lineup_trade_other_team")
    other_players = sorted(
        roster_stats[roster_stats["Team"].astype(str) == str(other_team)]["Player"].dropna().astype(str).unique().tolist()
    )

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

    st.markdown("##### Analyze a Proposed Trade")
    pending_give = [p for p in workflow_give if p in my_players]
    pending_get = [p for p in workflow_get if p in other_players]
    if pending_give and "lineup_trade_give_players" not in session:
        session["lineup_trade_give_players"] = pending_give
    if pending_get and "lineup_trade_get_players" not in session:
        session["lineup_trade_get_players"] = pending_get
    ensure_multiselect_state("lineup_trade_give_players", my_players, pending_give or [])
    ensure_multiselect_state("lineup_trade_get_players", other_players, pending_get or [])
    st.caption(
        "Build 1-for-1, 2-for-1, 2-for-2, or 3-for-2 proposals. "
        "Roster changes happen only when a pending proposal is accepted."
    )
    give_players = st.multiselect("Players You Give Up (up to 3)", my_players, key="lineup_trade_give_players")
    get_players = st.multiselect("Players You Receive (up to 3)", other_players, key="lineup_trade_get_players")
    verdict = ""

    if give_players and get_players:
        trade_eval, verdict, weighted_gain = evaluate_trade_fn(
            give_players,
            get_players,
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

            trade_sig = (my_team, other_team, tuple(sorted(give_players)), tuple(sorted(get_players)))
            if session.get("_cc_trade_activity_sig") != trade_sig:
                session["_cc_trade_activity_sig"] = trade_sig
                log_trade_analysis(give=give_players, get=get_players, verdict=str(verdict or ""))
        except Exception:
            pass

    session["_lineup_trade_analyzer_state"] = {
        "my_team": my_team,
        "other_team": other_team,
        "give_players": list(give_players or []),
        "get_players": list(get_players or []),
        "verdict": str(verdict or "") if give_players and get_players else "",
    }


def render_trade_ideas_tab(
    st: Any,
    session: dict[str, Any],
    *,
    lineup_team: str,
    ensure_multiselect_state: Callable[..., Any],
    render_output_table_fn: Callable[..., Any],
    format_fantasy_table_fn: Callable[..., pd.DataFrame],
    clean_ui_columns_fn: Callable[..., pd.DataFrame],
    summarize_team_category_needs_fn: Callable[..., dict[str, bool]],
    developer_mode_enabled_fn: Callable[[], bool],
) -> None:
    st.subheader("Trade Ideas")
    st.caption(
        "Search every opposing team in the active league for fair trades that improve your weak categories."
    )

    roster_stats, standings, my_team, other_teams, other_team, my_players, other_players = _trade_context(
        session,
        lineup_team=lineup_team,
    )
    if roster_stats.empty:
        st.info(
            "Load current-season stats on Fantasy Standings Tracker first so trade ideas can use live rosters."
        )
        return
    if not other_teams:
        st.info("Need at least two fantasy teams in the active league to generate trade ideas.")
        return

    st.caption(f"**Your team:** {my_team or '—'} · searching {len(other_teams)} opposing team(s)")

    trade_mode = st.radio(
        "Trade Idea Mode",
        [
            "General fair-but-helpful ideas",
            "I want to trade away specific player(s)",
            "I want to acquire specific player(s)",
            "I want to choose both trade-away and acquire targets",
        ],
        horizontal=False,
        key="lineup_trade_idea_mode",
    )

    forced_give: list[str] = []
    forced_get: list[str] = []
    target_team = None
    if trade_mode in {
        "I want to trade away specific player(s)",
        "I want to choose both trade-away and acquire targets",
    }:
        ensure_multiselect_state("lineup_trade_ideas_forced_give", my_players, [])
        forced_give = st.multiselect(
            "Player(s) on my team I am willing to trade away",
            my_players,
            key="lineup_trade_ideas_forced_give",
        )
    if trade_mode in {
        "I want to acquire specific player(s)",
        "I want to choose both trade-away and acquire targets",
    }:
        if other_team:
            ensure_multiselect_state("lineup_trade_ideas_forced_get", other_players, [])
            forced_get = st.multiselect(
                "Player(s) I want to acquire (from selected other team)",
                other_players,
                key="lineup_trade_ideas_forced_get",
            )
            target_team = other_team

    generate_clicked = st.button("Generate Trade Ideas", key="lineup_suggest_trades_button", type="primary")
    if generate_clicked:
        try:
            from fantasy_league_context import get_active_league_context

            ctx = get_active_league_context(session) or {}
            league_id = str(ctx.get("league_context_id") or "")
        except ImportError:
            league_id = ""

        suggestions, diag = generate_trade_ideas(
            my_team,
            roster_stats,
            standings,
            forced_give=forced_give,
            forced_get=forced_get,
            target_team=target_team if trade_mode != "General fair-but-helpful ideas" else None,
            summarize_team_category_needs_fn=summarize_team_category_needs_fn,
            league_context_id=league_id,
        )
        session[LINEUP_TRADE_IDEAS_RESULTS_KEY] = (
            suggestions.to_dict(orient="records") if not suggestions.empty else []
        )
        session[LINEUP_TRADE_IDEAS_DIAG_KEY] = diag

    stored_rows = session.get(LINEUP_TRADE_IDEAS_RESULTS_KEY) or []
    diag = session.get(LINEUP_TRADE_IDEAS_DIAG_KEY) or {}
    suggestions = pd.DataFrame(stored_rows) if stored_rows else pd.DataFrame()

    if suggestions.empty:
        if diag.get("button_clicked") or generate_clicked:
            st.info(empty_trade_ideas_message())
    else:
        render_output_table_fn(
            format_fantasy_table_fn(clean_ui_columns_fn(suggestions)),
            key="lineup_trade_suggestions",
            file_name="lineup_trade_suggestions.csv",
            display_rows=20,
            style_cols=["Trade Fit Score", "Fairness Gap"],
        )

    if developer_mode_enabled_fn():
        with st.expander("Trade idea diagnostics (Developer Mode)", expanded=bool(generate_clicked)):
            st.json(
                {
                    "button_clicked": bool(generate_clicked or diag.get("button_clicked")),
                    "selected_give_players": list(forced_give or diag.get("selected_give_players") or []),
                    "selected_get_players": list(forced_get or diag.get("selected_get_players") or []),
                    "active_league_id": diag.get("active_league_id"),
                    "user_team": diag.get("user_team") or my_team,
                    "opposing_teams_searched": diag.get("opposing_teams_searched") or other_teams,
                    "candidate_count_before_filters": diag.get("candidate_count_before_filters", 0),
                    "candidate_count_after_filters": diag.get("candidate_count_after_filters", 0),
                    "final_idea_count": diag.get("final_idea_count", len(suggestions)),
                    "failure_reason": diag.get("failure_reason"),
                    "category_needs": diag.get("category_needs"),
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
    roster_stats, _standings, my_team, other_teams, other_team, _my_players, _other_players = _trade_context(
        session,
        lineup_team=lineup_team,
    )
    if roster_stats.empty:
        st.info("Load league rosters and stats before reviewing trade offers.")
        return

    analyzer_state = session.get("_lineup_trade_analyzer_state") or {}
    give_players = list(analyzer_state.get("give_players") or [])
    get_players = list(analyzer_state.get("get_players") or [])
    verdict = str(analyzer_state.get("verdict") or "")
    other_team = str(analyzer_state.get("other_team") or other_team or (other_teams[0] if other_teams else ""))

    try:
        from fantasy_trade_proposals_ui import (
            render_trade_proposals_section,
            render_trade_response_ui_v2_marker,
        )

        render_trade_response_ui_v2_marker(
            st,
            session,
            my_team=my_team,
            caller="lineup_offers_activity_tab",
        )
        render_trade_proposals_section(
            st,
            session,
            my_team=my_team,
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
