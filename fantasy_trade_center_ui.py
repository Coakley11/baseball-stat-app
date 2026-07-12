"""Unified Trade Center — build, analyze, offers, and history in one workspace."""

from __future__ import annotations

import html as html_lib
from typing import Any, Callable

import pandas as pd

from fantasy_trade_ideas import (
    LINEUP_TRADE_CENTER_STATE_KEY,
    LINEUP_TRADE_IDEAS_DIAG_KEY,
    LINEUP_TRADE_IDEAS_RESULTS_KEY,
    TRADE_CENTER_INTERNAL_TAB_KEY,
    TRADE_CENTER_INTERNAL_TABS,
    empty_trade_ideas_message,
    generate_trade_ideas,
    resolve_player_owner_team,
    resolve_receive_target_teams,
    resolve_trade_center_internal_tab,
)


def _persist_trade_plan(session: dict[str, Any], st: Any, *, reason: str) -> None:
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason=reason)
    except Exception:
        pass


def _trade_scope_state_key(scope_fingerprint: str) -> str:
    return f"trade_center_state|{scope_fingerprint}"


def _resolve_trade_scope(session: dict[str, Any], *, page_lineup_team: str) -> tuple[str, str, str]:
    try:
        from fantasy_league_context import get_active_league_context
        from fantasy_lineup_scope import resolve_canonical_lineup_team, resolve_lineup_scope

        context = get_active_league_context(session) or {}
        scope = resolve_lineup_scope(session, context, week=1, page_lineup_team=page_lineup_team)
        my_team = resolve_canonical_lineup_team(session, context, page_lineup_team=page_lineup_team)
        league_id = str(scope.league_id if scope else "") or str(context.get("league_context_id") or "")
        fingerprint = str(scope.fingerprint if scope else f"trade|{my_team}|{league_id}")
        return my_team, league_id, fingerprint
    except ImportError:
        return str(page_lineup_team or "").strip(), "", f"trade|{page_lineup_team}"


def _trade_workspace(
    session: dict[str, Any],
    *,
    my_team: str,
) -> dict[str, Any]:
    roster_stats = session.get("fantasy_current_roster_stats", pd.DataFrame())
    standings = session.get("fantasy_current_standings", pd.DataFrame())
    if roster_stats is None or roster_stats.empty:
        return {
            "roster_stats": roster_stats,
            "standings": standings,
            "my_team": my_team,
            "other_teams": [],
            "my_players": [],
            "all_other_players": [],
        }

    trade_teams = sorted(roster_stats["Team"].dropna().astype(str).unique().tolist())
    resolved_team = my_team if my_team in trade_teams else ""
    other_teams = [t for t in trade_teams if t != resolved_team]
    my_players = sorted(
        roster_stats[roster_stats["Team"].astype(str) == str(resolved_team)]["Player"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    ) if resolved_team else []
    all_other_players = sorted(
        roster_stats[roster_stats["Team"].astype(str) != str(resolved_team)]["Player"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    ) if resolved_team else []
    return {
        "roster_stats": roster_stats,
        "standings": standings,
        "my_team": resolved_team,
        "other_teams": other_teams,
        "my_players": my_players,
        "all_other_players": all_other_players,
    }


def _inject_trade_center_styles(st: Any) -> None:
    st.markdown(
        """
<style>
.tc-hero {
  display:flex; align-items:center; gap:14px;
  padding:14px 16px; margin:0 0 12px;
  border-radius:14px;
  background:linear-gradient(135deg,#0b3d6e 0%,#1d5f9a 55%,#2563eb 100%);
  color:#fff;
}
.tc-hero-icon { width:52px; height:52px; flex-shrink:0; }
.tc-hero h2 { margin:0; font-size:1.25rem; font-weight:800; color:#fff; }
.tc-hero p { margin:2px 0 0; font-size:0.82rem; opacity:0.92; }
.tc-meta { font-size:0.76rem; opacity:0.88; margin-top:4px; }
.tc-internal-tabs [data-testid="stHorizontalBlock"] { gap:0.35rem; }
.tc-builder {
  display:grid; grid-template-columns:1fr auto 1fr; gap:10px; align-items:start;
  margin:10px 0 14px;
}
@media (max-width: 768px) {
  .tc-builder { grid-template-columns:1fr; }
  .tc-exchange { transform:rotate(90deg); margin:4px auto; }
}
.tc-side {
  border:1px solid rgba(11,61,110,0.18); border-radius:12px; padding:10px 12px; background:#f8fbff;
}
.tc-side h4 { margin:0 0 8px; font-size:0.88rem; color:#0b3d6e; }
.tc-exchange {
  font-size:1.6rem; font-weight:800; color:#0b3d6e; align-self:center; padding-top:28px;
}
.tc-chip {
  display:inline-flex; align-items:center; gap:6px;
  border:1px solid rgba(11,61,110,0.2); border-radius:999px;
  padding:4px 10px; margin:3px 4px 3px 0; background:#fff; font-size:0.78rem;
}
.tc-idea-card {
  border:1px solid rgba(11,61,110,0.16); border-radius:12px; padding:10px 12px;
  margin-bottom:10px; background:#fff;
}
.tc-badge {
  display:inline-block; padding:2px 8px; border-radius:999px; font-size:0.72rem; font-weight:700;
  background:#dbeafe; color:#0b3d6e; margin-right:6px;
}
.tc-analysis {
  border:1px solid rgba(11,61,110,0.2); border-radius:12px; padding:12px; background:#f0f7ff;
  margin:8px 0 12px;
}
.tc-empty { text-align:center; padding:18px 12px; color:#64748b; border:1px dashed #cbd5e1; border-radius:12px; }
</style>
""",
        unsafe_allow_html=True,
    )


def _render_trade_center_hero(st: Any, *, league_name: str, my_team: str, pending_offers: int) -> None:
    pending = f" · {pending_offers} pending offer{'s' if pending_offers != 1 else ''}" if pending_offers else ""
    st.markdown(
        f"""
<div class="tc-hero">
  <svg class="tc-hero-icon" viewBox="0 0 64 64" aria-hidden="true">
    <circle cx="20" cy="32" r="14" fill="rgba(255,255,255,0.15)" stroke="#fff" stroke-width="2"/>
    <circle cx="44" cy="32" r="14" fill="rgba(255,255,255,0.15)" stroke="#fff" stroke-width="2"/>
    <path d="M26 28 L38 36 M38 28 L26 36" stroke="#fff" stroke-width="2.5" stroke-linecap="round"/>
    <path d="M10 18 L18 26 M54 18 L46 26" stroke="rgba(255,255,255,0.5)" stroke-width="2" stroke-linecap="round"/>
  </svg>
  <div>
    <h2>Trade Center</h2>
    <p>Build, analyze, propose, and manage trades</p>
    <div class="tc-meta">League: {html_lib.escape(league_name or '—')} · Your team: {html_lib.escape(my_team or '—')}{html_lib.escape(pending)}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _load_shared_trade_state(session: dict[str, Any], scope_key: str) -> dict[str, Any]:
    state = session.get(scope_key)
    if isinstance(state, dict):
        return dict(state)
    legacy = session.get(LINEUP_TRADE_CENTER_STATE_KEY)
    return dict(legacy) if isinstance(legacy, dict) else {}


def _save_shared_trade_state(session: dict[str, Any], scope_key: str, state: dict[str, Any]) -> None:
    session[scope_key] = dict(state)
    session[LINEUP_TRADE_CENTER_STATE_KEY] = dict(state)


def _player_chip(name: str) -> str:
    return f'<span class="tc-chip">{html_lib.escape(name)}</span>'


def _render_idea_card(st: Any, idea: dict[str, Any], idx: int, session: dict[str, Any], scope_key: str) -> None:
    give = str(idea.get("Give") or "")
    receive = str(idea.get("Receive") or "")
    other = str(idea.get("Other Team") or "")
    fairness = str(idea.get("Fairness Score") or idea.get("Fairness Gap") or "—")
    st.markdown(
        f"""<div class="tc-idea-card">
<span class="tc-badge">{html_lib.escape(str(idea.get('Recommendation') or 'Idea'))}</span>
<span class="tc-badge">Fit {html_lib.escape(str(idea.get('Trade Fit Score') or '—'))}</span>
<span class="tc-badge">Fair {html_lib.escape(fairness)}</span>
<p><b>{html_lib.escape(other)}</b> — give {_player_chip(give)} receive {_player_chip(receive)}</p>
<p style="font-size:0.82rem;margin:4px 0;">{html_lib.escape(str(idea.get('Why It Helps') or ''))}</p>
<p style="font-size:0.76rem;color:#64748b;">Risk: {html_lib.escape(str(idea.get('Main Risk') or '—'))}</p>
</div>""",
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    if c1.button("Use This Idea", key=f"tc_use_{idx}"):
        _save_shared_trade_state(
            session,
            scope_key,
            {
                "give_players": [give] if give else [],
                "get_players": [receive] if receive else [],
                "other_team": other,
                "source_idea_id": f"idea_{idx}",
            },
        )
        session["lineup_trade_give_players"] = [give] if give else []
        session["lineup_trade_get_players"] = [receive] if receive else []
        session["lineup_trade_other_team"] = other
        st.rerun()
    if c2.button("Analyze", key=f"tc_analyze_{idx}"):
        _save_shared_trade_state(
            session,
            scope_key,
            {
                "give_players": [give] if give else [],
                "get_players": [receive] if receive else [],
                "other_team": other,
                "source_idea_id": f"idea_{idx}",
                "auto_analyze": True,
            },
        )
        session["lineup_trade_give_players"] = [give] if give else []
        session["lineup_trade_get_players"] = [receive] if receive else []
        session["lineup_trade_other_team"] = other
        session[TRADE_CENTER_INTERNAL_TAB_KEY] = "Build & Analyze"
        st.rerun()


def _render_build_analyze(
    st: Any,
    session: dict[str, Any],
    *,
    ws: dict[str, Any],
    league_id: str,
    scope_key: str,
    ensure_select_in_options: Callable[..., Any],
    ensure_multiselect_state: Callable[..., Any],
    evaluate_trade_fn: Callable[..., Any],
    build_trade_verdict_text_fn: Callable[..., str],
    summarize_team_category_needs_fn: Callable[..., dict[str, bool]],
    developer_mode_enabled_fn: Callable[[], bool],
) -> None:
    roster_stats = ws["roster_stats"]
    standings = ws["standings"]
    my_team = ws["my_team"]
    other_teams = ws["other_teams"]
    my_players = ws["my_players"]
    all_other_players = ws["all_other_players"]
    shared = _load_shared_trade_state(session, scope_key)

    if not my_players:
        st.markdown('<div class="tc-empty">No players on your roster yet.</div>', unsafe_allow_html=True)
        return

    pending_give = list(shared.get("give_players") or session.get("lineup_trade_give_players") or [])
    pending_get = list(shared.get("get_players") or session.get("lineup_trade_get_players") or [])
    ensure_multiselect_state("lineup_trade_give_players", my_players, [p for p in pending_give if p in my_players])
    ensure_multiselect_state(
        "lineup_trade_get_players",
        all_other_players,
        [p for p in pending_get if p in all_other_players],
    )

    other_default = str(shared.get("other_team") or session.get("lineup_trade_other_team") or (other_teams[0] if other_teams else ""))

    st.markdown('<div class="tc-builder">', unsafe_allow_html=True)
    left, mid, right = st.columns([5, 1, 5])
    with left:
        st.markdown(f'<div class="tc-side"><h4>MY TEAM — {html_lib.escape(my_team)}</h4></div>', unsafe_allow_html=True)
        give_players = st.multiselect("Players I Give", my_players, key="lineup_trade_give_players", label_visibility="collapsed")
    with mid:
        st.markdown('<div class="tc-exchange">⇄</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="tc-side"><h4>OTHER TEAM</h4></div>', unsafe_allow_html=True)
        receive_players = st.multiselect("Players I Receive", all_other_players, key="lineup_trade_get_players", label_visibility="collapsed")
    st.markdown("</div>", unsafe_allow_html=True)

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
        elif len(owners) > 1:
            st.caption(f"Receive targets span: {', '.join(owners)}")
    elif other_teams:
        ensure_select_in_options("lineup_trade_other_team", other_teams, other_default)
        other_team = st.selectbox("Opposing team", other_teams, key="lineup_trade_other_team", label_visibility="collapsed")

    primary_label = "Analyze This Trade" if (give_players and receive_players) else "Find Trade Ideas"
    c1, c2, c3 = st.columns([2, 2, 1])
    primary = c1.button(primary_label, key="tc_primary_action", type="primary")
    send_offer = c2.button("Send Offer", key="tc_send_offer", disabled=not (give_players and receive_players and other_team))
    if c3.button("Clear", key="tc_clear_trade"):
        session.pop("lineup_trade_give_players", None)
        session.pop("lineup_trade_get_players", None)
        _save_shared_trade_state(session, scope_key, {})
        st.rerun()

    auto_analyze = bool(shared.pop("auto_analyze", False))
    analyze = primary and give_players and receive_players
    find_ideas = primary and not (give_players and receive_players)

    verdict = ""
    if analyze or auto_analyze:
        trade_eval, verdict, weighted_gain = evaluate_trade_fn(
            give_players,
            receive_players,
            roster_stats,
            roster_stats,
            standings,
            my_team,
        )
        st.markdown(
            f"""<div class="tc-analysis">
<b>Verdict:</b> {html_lib.escape(str(verdict or '—'))}<br/>
<span style="font-size:0.84rem;">{html_lib.escape(build_trade_verdict_text_fn(trade_eval, weighted_gain))}</span>
</div>""",
            unsafe_allow_html=True,
        )

    if find_ideas or (primary and give_players and not receive_players):
        owner_map = resolve_receive_target_teams(receive_players, roster_stats, my_team=my_team)
        suggestions, diag = generate_trade_ideas(
            my_team,
            roster_stats,
            standings,
            forced_give=give_players or None,
            forced_get=receive_players or None,
            target_team=other_team if receive_players and not owner_map else None,
            target_owner_teams=owner_map,
            summarize_team_category_needs_fn=summarize_team_category_needs_fn,
            league_context_id=league_id,
        )
        session[LINEUP_TRADE_IDEAS_RESULTS_KEY] = suggestions.to_dict(orient="records") if not suggestions.empty else []
        session[LINEUP_TRADE_IDEAS_DIAG_KEY] = diag
    elif analyze:
        session[LINEUP_TRADE_IDEAS_DIAG_KEY] = {"button_action": "analyze"}

    stored_rows = session.get(LINEUP_TRADE_IDEAS_RESULTS_KEY) or []
    diag = session.get(LINEUP_TRADE_IDEAS_DIAG_KEY) or {}
    if stored_rows:
        st.markdown("#### Top trade ideas")
        for idx, row in enumerate(stored_rows[:5]):
            _render_idea_card(st, row if isinstance(row, dict) else {}, idx, session, scope_key)
        if len(stored_rows) > 5 and st.button("Show more ideas", key="tc_show_more_ideas"):
            for idx, row in enumerate(stored_rows[5:10], start=5):
                _render_idea_card(st, row if isinstance(row, dict) else {}, idx, session, scope_key)
    elif find_ideas:
        st.markdown(
            f'<div class="tc-empty">{html_lib.escape(empty_trade_ideas_message(diag))}</div>',
            unsafe_allow_html=True,
        )

    _save_shared_trade_state(
        session,
        scope_key,
        {
            "league_id": league_id,
            "my_team": my_team,
            "other_team": other_team,
            "give_players": list(give_players or []),
            "get_players": list(receive_players or []),
            "source_offer_id": shared.get("source_offer_id"),
            "source_idea_id": shared.get("source_idea_id"),
            "mode": "analyze" if analyze else "ideas",
            "verdict": verdict,
        },
    )

    if send_offer and give_players and receive_players and other_team:
        try:
            from fantasy_trade_proposals_ui import submit_trade_proposal_from_analyzer

            submit_trade_proposal_from_analyzer(
                st,
                session,
                my_team=my_team,
                other_team=other_team,
                give_players=give_players,
                get_players=receive_players,
                persist_fn=_persist_trade_plan,
                key_prefix="tc_send",
            )
        except ImportError:
            st.info("Trade proposal submission is not available in this build.")

    if developer_mode_enabled_fn():
        with st.expander("Trade Center diagnostics (Developer Mode)", expanded=False):
            st.json(diag)


def _count_pending_offers(session: dict[str, Any], my_team: str) -> int:
    try:
        from fantasy_trade_proposals import get_trade_proposals

        proposals = get_trade_proposals(session) or []
        return sum(
            1
            for p in proposals
            if isinstance(p, dict)
            and str(p.get("status") or "").lower() == "pending"
            and (str(p.get("to_team") or "") == my_team or str(p.get("from_team") or "") == my_team)
        )
    except Exception:
        return 0


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
    del render_output_table_fn, format_trade_eval_table_fn, format_fantasy_table_fn, clean_ui_columns_fn

    _inject_trade_center_styles(st)
    my_team, league_id, scope_fingerprint = _resolve_trade_scope(session, page_lineup_team=lineup_team)
    scope_key = _trade_scope_state_key(scope_fingerprint)
    ws = _trade_workspace(session, my_team=my_team)

    if ws["roster_stats"] is None or ws["roster_stats"].empty:
        st.markdown('<div class="tc-empty">Load league rosters and stats to open Trade Center.</div>', unsafe_allow_html=True)
        return
    if not ws["my_team"]:
        st.markdown('<div class="tc-empty">Claim your team to use Trade Center.</div>', unsafe_allow_html=True)
        return

    try:
        from fantasy_lineup_scope import assert_lineup_write_identity, resolve_lineup_scope
        from fantasy_league_context import get_active_league_context

        context = get_active_league_context(session) or {}
        scope = resolve_lineup_scope(session, context, week=1, page_lineup_team=lineup_team)
        ok, err = assert_lineup_write_identity(scope)
        if not ok:
            st.warning(err)
    except ImportError:
        pass

    league_name = league_id
    try:
        from fantasy_league_context import get_active_league_context

        ctx = get_active_league_context(session) or {}
        league_name = str(ctx.get("display_name") or ctx.get("league_name") or league_id)
    except ImportError:
        pass

    pending = _count_pending_offers(session, ws["my_team"])
    _render_trade_center_hero(st, league_name=league_name, my_team=ws["my_team"], pending_offers=pending)

    internal_tab = resolve_trade_center_internal_tab(session)
    offers_badge = f" ({pending})" if pending else ""
    tab_labels = [
        TRADE_CENTER_INTERNAL_TABS[0],
        f"{TRADE_CENTER_INTERNAL_TABS[1]}{offers_badge}",
        TRADE_CENTER_INTERNAL_TABS[2],
    ]
    selected = st.radio(
        "Trade Center section",
        tab_labels,
        horizontal=True,
        key=TRADE_CENTER_INTERNAL_TAB_KEY,
        label_visibility="collapsed",
    )
    if selected.startswith("Offers"):
        internal_tab = "Offers"
    elif selected.startswith("History"):
        internal_tab = "History"
    else:
        internal_tab = "Build & Analyze"
    session[TRADE_CENTER_INTERNAL_TAB_KEY] = internal_tab

    if internal_tab == "Build & Analyze":
        _render_build_analyze(
            st,
            session,
            ws=ws,
            league_id=league_id,
            scope_key=scope_key,
            ensure_select_in_options=ensure_select_in_options,
            ensure_multiselect_state=ensure_multiselect_state,
            evaluate_trade_fn=evaluate_trade_fn,
            build_trade_verdict_text_fn=build_trade_verdict_text_fn,
            summarize_team_category_needs_fn=summarize_team_category_needs_fn,
            developer_mode_enabled_fn=developer_mode_enabled_fn,
        )
    elif internal_tab == "Offers":
        _render_offers_section(st, session, ws=ws, scope_key=scope_key)
    else:
        _render_history_section(st, session, ws=ws)


def _render_offers_section(st: Any, session: dict[str, Any], *, ws: dict[str, Any], scope_key: str) -> None:
    shared = _load_shared_trade_state(session, scope_key)
    try:
        from fantasy_trade_proposals_ui import render_trade_proposals_section, render_trade_response_ui_v2_marker

        render_trade_response_ui_v2_marker(st, session, my_team=ws["my_team"], caller="trade_center_offers")
        render_trade_proposals_section(
            st,
            session,
            my_team=ws["my_team"],
            other_team=str(shared.get("other_team") or ""),
            give_players=list(shared.get("give_players") or []),
            get_players=list(shared.get("get_players") or []),
            verdict=str(shared.get("verdict") or ""),
            persist_fn=_persist_trade_plan,
            key_prefix="tc_offers",
            on_analyze_offer=lambda offer: _load_offer_into_state(session, scope_key, offer, ws["my_team"]),
        )
    except TypeError:
        from fantasy_trade_proposals_ui import render_trade_proposals_section, render_trade_response_ui_v2_marker

        render_trade_response_ui_v2_marker(st, session, my_team=ws["my_team"], caller="trade_center_offers")
        render_trade_proposals_section(
            st,
            session,
            my_team=ws["my_team"],
            other_team=str(shared.get("other_team") or ""),
            give_players=list(shared.get("give_players") or []),
            get_players=list(shared.get("get_players") or []),
            verdict=str(shared.get("verdict") or ""),
            persist_fn=_persist_trade_plan,
            key_prefix="tc_offers",
        )
    except ImportError as exc:
        st.markdown(f'<div class="tc-empty">Offers unavailable: {html_lib.escape(str(exc))}</div>', unsafe_allow_html=True)


def _load_offer_into_state(session: dict[str, Any], scope_key: str, offer: dict[str, Any], my_team: str) -> None:
    from_team = str(offer.get("from_team") or "").strip()
    to_team = str(offer.get("to_team") or "").strip()
    if to_team == my_team:
        give = list(offer.get("requested_players") or offer.get("give_players") or [])
        receive = list(offer.get("offered_players") or offer.get("get_players") or [])
        other = from_team
    else:
        give = list(offer.get("offered_players") or offer.get("give_players") or [])
        receive = list(offer.get("requested_players") or offer.get("get_players") or [])
        other = to_team
    state = {
        "give_players": give,
        "get_players": receive,
        "other_team": other,
        "source_offer_id": str(offer.get("proposal_id") or offer.get("id") or ""),
        "auto_analyze": True,
    }
    _save_shared_trade_state(session, scope_key, state)
    session["lineup_trade_give_players"] = give
    session["lineup_trade_get_players"] = receive
    session["lineup_trade_other_team"] = other
    session[TRADE_CENTER_INTERNAL_TAB_KEY] = "Build & Analyze"


def _render_history_section(st: Any, session: dict[str, Any], *, ws: dict[str, Any]) -> None:
    try:
        from fantasy_trade_proposals import get_trade_proposals

        proposals = get_trade_proposals(session) or []
    except ImportError:
        proposals = []

    if not proposals:
        st.markdown('<div class="tc-empty">No trade history yet.</div>', unsafe_allow_html=True)
        return

    filter_status = st.selectbox(
        "Filter",
        ["All", "Accepted", "Declined", "Canceled", "Expired", "Countered", "Pending"],
        key="tc_history_filter",
    )
    shown = 0
    for idx, proposal in enumerate(reversed(proposals)):
        if not isinstance(proposal, dict):
            continue
        status = str(proposal.get("status") or "unknown").strip()
        if filter_status != "All" and status.lower() != filter_status.lower():
            continue
        shown += 1
        from_team = str(proposal.get("from_team") or "")
        to_team = str(proposal.get("to_team") or "")
        give = proposal.get("offered_players") or proposal.get("give_players") or []
        get = proposal.get("requested_players") or proposal.get("get_players") or []
        st.markdown(
            f"""<div class="tc-idea-card">
<span class="tc-badge">{html_lib.escape(status.title())}</span>
<b>{html_lib.escape(from_team)} → {html_lib.escape(to_team)}</b><br/>
<span style="font-size:0.82rem;">Give {html_lib.escape(', '.join(map(str, give)))} · Receive {html_lib.escape(', '.join(map(str, get)))}</span>
</div>""",
            unsafe_allow_html=True,
        )
        if shown >= 20:
            break
