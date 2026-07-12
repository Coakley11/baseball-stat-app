"""Unified Trade Center — build, analyze, offers, and history in one workspace."""

from __future__ import annotations

import html as html_lib
from typing import Any, Callable

import pandas as pd

from fantasy_trade_category_values import format_trade_category_value

from fantasy_trade_analysis import analysis_matches_selection, build_trade_analysis_package
from fantasy_trade_builder_state import (
    ANY_TRADE_PARTNER,
    apply_pending_to_logical_state,
    build_builder_diagnostics,
    build_search_summary,
    builder_diag_key,
    builder_widget_keys,
    maybe_migrate_builder_schema,
    migrate_legacy_builder_keys,
    prepare_builder_widget_state,
    proposal_confirm_key,
    prune_invalid_receive_for_partner,
    queue_pending_builder_update,
    receive_options_for_partner,
    reset_trade_builder,
    resolve_effective_partner,
    save_logical_state_from_widgets,
    scope_fingerprint_changed,
)
from fantasy_trade_player_index import (
    format_player_option_label,
    format_player_stat_line,
    format_position_label,
    stats_updated_caption,
)
from fantasy_trade_ideas import (
    LINEUP_TRADE_CENTER_STATE_KEY,
    LINEUP_TRADE_IDEAS_DIAG_KEY,
    LINEUP_TRADE_IDEAS_RESULTS_KEY,
    TRADE_CENTER_INTERNAL_TAB_KEY,
    TRADE_CENTER_INTERNAL_TABS,
    TRADE_CENTER_INTERNAL_WIDGET_KEY,
    apply_trade_center_internal_selection,
    empty_trade_ideas_message,
    generate_trade_ideas,
    resolve_player_owner_team,
    resolve_receive_target_teams,
    resolve_trade_center_internal_tab,
    sync_trade_center_internal_widget,
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
    load_error = ""
    if roster_stats is None or getattr(roster_stats, "empty", True):
        try:
            from fantasy_league_context import get_active_league_context
            from fantasy_lineup_stats_loader import ensure_lineup_page_hitter_stats

            context = get_active_league_context(session)
            loaded = ensure_lineup_page_hitter_stats(session, context)
            load_error = str(loaded.get("error") or "").strip()
            built = loaded.get("roster_stats")
            if isinstance(built, pd.DataFrame) and not built.empty:
                roster_stats = built
        except Exception as exc:
            load_error = f"{type(exc).__name__}: {exc}"

    if roster_stats is None or getattr(roster_stats, "empty", True):
        return {
            "roster_stats": roster_stats if isinstance(roster_stats, pd.DataFrame) else pd.DataFrame(),
            "standings": standings,
            "my_team": my_team,
            "other_teams": [],
            "my_players": [],
            "all_other_players": [],
            "load_error": load_error,
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
        "load_error": load_error,
    }


def _split_player_names(text: str) -> list[str]:
    return [part.strip() for part in str(text or "").split(",") if part.strip()]


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


OFFERS_ACTIVITY_TABS: tuple[str, ...] = ("Active Offers", "Trade History")
OFFERS_ACTIVITY_TAB_KEY_SUFFIX = "offers_activity_tab"
OFFERS_ACTIVITY_WIDGET_KEY_SUFFIX = "offers_activity_widget"


def _offers_activity_tab_key(scope_key: str) -> str:
    return f"{scope_key}|{OFFERS_ACTIVITY_TAB_KEY_SUFFIX}"


def _offers_activity_widget_key(scope_key: str) -> str:
    return f"{scope_key}|{OFFERS_ACTIVITY_WIDGET_KEY_SUFFIX}"


def _format_idea_badges(idea: dict[str, Any]) -> tuple[str, str, str, str]:
    recommendation = str(idea.get("Recommendation") or "Fair")
    fit_raw = pd.to_numeric(idea.get("Trade Fit Score"), errors="coerce")
    fair_raw = pd.to_numeric(idea.get("Fairness Score") or idea.get("Fairness Gap"), errors="coerce")
    fit = f"{int(round(float(fit_raw)))}/100" if pd.notna(fit_raw) else "—"
    value_match = f"{int(round(float(fair_raw)))}/100" if pd.notna(fair_raw) else "—"
    rec_lower = recommendation.lower()
    if "decline" in rec_lower or "avoid" in rec_lower or "weak" in rec_lower:
        tone = "red"
    elif "fair" in rec_lower or "slight" in rec_lower:
        tone = "amber"
    else:
        tone = "green"
    return recommendation, fit, value_match, tone


def _badge_style(tone: str) -> str:
    if tone == "red":
        return "background:#fee2e2;color:#991b1b;"
    if tone == "amber":
        return "background:#fef3c7;color:#92400e;"
    return "background:#dcfce7;color:#166534;"


def _render_player_lines(st: Any, roster_stats: pd.DataFrame, names: list[str], *, heading: str) -> None:
    st.markdown(f"**{heading}**")
    for name in names:
        pos = format_position_label(roster_stats, name)
        stats = format_player_stat_line(roster_stats, name)
        st.markdown(f"{name} · {pos}")
        st.caption(stats)


def _render_analysis_panel(st: Any, analysis: dict[str, Any], roster_stats: pd.DataFrame) -> None:
    title = str(analysis.get("title") or "Trade analysis")
    st.markdown(f"### {html_lib.escape(title)}")
    st.markdown(
        f"""<div class="tc-analysis">
<b>Verdict:</b> {html_lib.escape(str(analysis.get('verdict') or '—'))}<br/>
<span style="font-size:0.84rem;">{html_lib.escape(str(analysis.get('verdict_text') or ''))}</span>
</div>""",
        unsafe_allow_html=True,
    )
    player_rows = analysis.get("player_rows") or []
    if player_rows:
        st.markdown("**Players in the deal**")
        for row in player_rows:
            st.markdown(
                f"- {html_lib.escape(str(row.get('player') or ''))} · "
                f"{html_lib.escape(str(row.get('position') or '—'))} · "
                f"{html_lib.escape(str(row.get('owner') or ''))} — "
                f"{html_lib.escape(str(row.get('stats_line') or ''))}"
            )
    category_rows = analysis.get("category_rows") or []
    if category_rows:
        st.markdown("**Current-season statistical comparison**")
        lines = ["| Category | Give | Receive | Change |", "|---|---:|---:|---:|"]
        for row in category_rows:
            cat = str(row.get("category") or "")
            give_val = row.get("give")
            recv_val = row.get("receive")
            change = row.get("change")
            give_txt = format_trade_category_value(cat, give_val)
            recv_txt = format_trade_category_value(cat, recv_val)
            chg_txt = format_trade_category_value(cat, change, is_change=True)
            lines.append(f"| {cat} | {give_txt} | {recv_txt} | {chg_txt} |")
        st.markdown("\n".join(lines))
    helps = analysis.get("helps") or []
    hurts = analysis.get("hurts") or []
    if helps or hurts:
        st.markdown("**Projected category direction**")
        if helps:
            st.markdown("Helps: " + ", ".join(f"{c} +" for c in helps[:5]))
        if hurts:
            st.markdown("Hurts: " + ", ".join(f"{c} -" for c in hurts[:5]))
    lost = analysis.get("positions_lost") or []
    gained = analysis.get("positions_gained") or []
    if lost or gained:
        st.markdown("**Roster and position impact**")
        if lost:
            st.caption(f"Positions lost: {', '.join(lost)}")
        if gained:
            st.caption(f"Positions gained: {', '.join(gained)}")
    interpretation = str(analysis.get("interpretation") or "").strip()
    if interpretation:
        st.info(interpretation)


def _queue_idea_builder_update(
    session: dict[str, Any],
    scope_key: str,
    *,
    give_list: list[str],
    receive_list: list[str],
    other: str,
    idea_id: str,
    action: str,
) -> None:
    queue_pending_builder_update(
        session,
        scope_key,
        {
            "action": action,
            "give_players": give_list,
            "get_players": receive_list,
            "trade_partner": other,
            "other_team": other,
            "source_idea_id": idea_id,
            "auto_analyze": action in ("analyze", "analyze_offer"),
            "await_proposal_confirm": action == "propose",
        },
    )
    session[TRADE_CENTER_INTERNAL_TAB_KEY] = "Build & Analyze"


def _render_idea_card(
    st: Any,
    idea: dict[str, Any],
    idx: int,
    session: dict[str, Any],
    scope_key: str,
    *,
    roster_stats: pd.DataFrame,
) -> None:
    give_names = _split_player_names(str(idea.get("Give") or ""))
    receive_names = _split_player_names(str(idea.get("Receive") or ""))
    other = str(idea.get("Other Team") or "")
    recommendation, fit, value_match, tone = _format_idea_badges(idea)
    badge_style = _badge_style(tone)
    helps = str(idea.get("Category Gains") or idea.get("Why It Helps") or "—")
    hurts = str(idea.get("Category Losses") or idea.get("Hurts") or "—")
    risk = str(idea.get("Main Risk") or "—")

    with st.container(border=True):
        st.markdown(f"**TRADE WITH {other.upper()}**")
        st.markdown(
            f'<span class="tc-badge" style="{badge_style}">{html_lib.escape(recommendation)} value</span>'
            f' <span class="tc-badge" style="{_badge_style("amber")}">Team Fit {html_lib.escape(fit)}</span>'
            f' <span class="tc-badge">Value Match {html_lib.escape(value_match)}</span>',
            unsafe_allow_html=True,
        )
        left, right = st.columns(2)
        with left:
            _render_player_lines(st, roster_stats, give_names, heading="YOU GIVE")
        with right:
            _render_player_lines(st, roster_stats, receive_names, heading="YOU RECEIVE")
        st.caption(stats_updated_caption(session))
        st.markdown(f"Helps: {helps}")
        if hurts and hurts != "—":
            st.markdown(f"Hurts: {hurts}")
        st.markdown(f"Risk: {risk}")
        c1, c2, c3 = st.columns(3)
        if c1.button("Use This Idea", key=f"tc_use_{idx}"):
            _queue_idea_builder_update(
                session,
                scope_key,
                give_list=give_names,
                receive_list=receive_names,
                other=other,
                idea_id=f"idea_{idx}",
                action="use",
            )
            st.rerun()
        if c2.button("Analyze", key=f"tc_analyze_{idx}"):
            _queue_idea_builder_update(
                session,
                scope_key,
                give_list=give_names,
                receive_list=receive_names,
                other=other,
                idea_id=f"idea_{idx}",
                action="analyze",
            )
            st.rerun()
        if c3.button("Propose", key=f"tc_propose_{idx}", disabled=not (give_names and receive_names and other)):
            _queue_idea_builder_update(
                session,
                scope_key,
                give_list=give_names,
                receive_list=receive_names,
                other=other,
                idea_id=f"idea_{idx}",
                action="propose",
            )
            st.rerun()


def _render_build_analyze(
    st: Any,
    session: dict[str, Any],
    *,
    ws: dict[str, Any],
    league_id: str,
    scope_key: str,
    scope_fingerprint: str,
    ensure_select_in_options: Callable[..., Any],
    ensure_multiselect_state: Callable[..., Any],
    evaluate_trade_fn: Callable[..., Any],
    build_trade_verdict_text_fn: Callable[..., str],
    summarize_team_category_needs_fn: Callable[..., dict[str, bool]],
    developer_mode_enabled_fn: Callable[[], bool],
) -> None:
    del ensure_select_in_options, ensure_multiselect_state
    roster_stats = ws["roster_stats"]
    standings = ws["standings"]
    my_team = ws["my_team"]
    other_teams = ws["other_teams"]
    my_players = ws["my_players"]
    all_other_players = ws["all_other_players"]

    if not my_players:
        st.markdown('<div class="tc-empty">No players on your roster yet.</div>', unsafe_allow_html=True)
        return

    widget_keys = builder_widget_keys(scope_key)
    flash_key = f"{scope_key}|builder_flash"
    deployed_sha = ""
    try:
        from suite_deploy_marker import resolve_git_commit_short

        deployed_sha = str(resolve_git_commit_short() or "")
    except Exception:
        deployed_sha = "unknown"

    shared = migrate_legacy_builder_keys(session, scope_key, _load_shared_trade_state(session, scope_key))
    shared, schema_migrated = maybe_migrate_builder_schema(session, scope_key, shared)
    partner_options = [ANY_TRADE_PARTNER, *other_teams]
    receive_pool = receive_options_for_partner(
        roster_stats,
        my_team=my_team,
        partner=ANY_TRADE_PARTNER,
        all_other_players=all_other_players,
    )
    shared, pending_update = apply_pending_to_logical_state(
        session,
        scope_key,
        shared,
        my_players=my_players,
        receive_options=receive_pool,
        other_teams=other_teams,
    )
    scope_changed, previous_scope_stamp = scope_fingerprint_changed(session, scope_key, scope_fingerprint)
    force_widgets = bool(pending_update) or scope_changed or schema_migrated
    force_reason = "none"
    if pending_update:
        force_reason = "pending_update"
    elif scope_changed:
        force_reason = "scope_change"
    elif schema_migrated:
        force_reason = "scope_change"

    prepare_diag = prepare_builder_widget_state(
        session,
        scope_key,
        shared,
        my_players=my_players,
        receive_options=receive_pool,
        partner_options=partner_options,
        force=force_widgets,
        force_reason=force_reason,
    )
    builder_diag = build_builder_diagnostics(
        deployed_feature_sha=deployed_sha,
        scope_key=scope_key,
        scope_fingerprint=scope_fingerprint,
        previous_scope_stamp=previous_scope_stamp,
        scope_changed=scope_changed,
        pending_update=pending_update,
        prepare_diag=prepare_diag,
        handoff_present=bool((session.pop(f"{scope_key}|builder_handoff_meta", {}) or {}).get("present")),
        handoff_consumed=bool(pending_update),
        schema_migrated=schema_migrated,
    )
    session[builder_diag_key(scope_key)] = builder_diag

    flash = str(session.pop(flash_key, "") or "").strip()
    if flash:
        st.success(flash)

    trade_partner = str(session.get(widget_keys["partner"]) or ANY_TRADE_PARTNER)
    st.caption(build_search_summary(
        my_team=my_team,
        partner=trade_partner,
        give_players=list(session.get(widget_keys["give"]) or []),
        receive_players=list(session.get(widget_keys["receive"]) or []),
    ))

    st.selectbox(
        "Trade partner to search",
        partner_options,
        key=widget_keys["partner"],
        help="Choose a specific team to search only that roster, or choose Any team to search the entire league.",
    )
    trade_partner = str(session.get(widget_keys["partner"]) or ANY_TRADE_PARTNER)
    receive_options = receive_options_for_partner(
        roster_stats,
        my_team=my_team,
        partner=trade_partner,
        all_other_players=all_other_players,
    )
    for msg in prune_invalid_receive_for_partner(
        session,
        scope_key,
        receive_options=receive_options,
        roster_stats=roster_stats,
        my_team=my_team,
        partner=trade_partner,
    ):
        st.info(msg)
    if trade_partner != ANY_TRADE_PARTNER:
        st.caption(f"{len(receive_options)} players on {trade_partner}")

    def _give_label(player: str) -> str:
        return format_player_option_label(roster_stats, player)

    def _receive_label(player: str) -> str:
        if trade_partner == ANY_TRADE_PARTNER:
            owner = resolve_player_owner_team(player, roster_stats, my_team=my_team) or "Unknown"
            return format_player_option_label(roster_stats, player, owner=owner, include_owner=True)
        return format_player_option_label(roster_stats, player)

    st.markdown('<div class="tc-builder">', unsafe_allow_html=True)
    left, mid, right = st.columns([5, 1, 5])
    with left:
        st.markdown(f'<div class="tc-side"><h4>MY TEAM — {html_lib.escape(my_team)}</h4></div>', unsafe_allow_html=True)
        give_players = st.multiselect(
            "Players I Give",
            my_players,
            key=widget_keys["give"],
            format_func=_give_label,
            label_visibility="collapsed",
            max_selections=3,
        )
    with mid:
        st.markdown('<div class="tc-exchange">⇄</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="tc-side"><h4>PLAYERS I RECEIVE</h4></div>', unsafe_allow_html=True)
        receive_players = st.multiselect(
            "Players I Receive",
            receive_options,
            key=widget_keys["receive"],
            format_func=_receive_label,
            label_visibility="collapsed",
            max_selections=3,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    other_team = resolve_effective_partner(trade_partner, receive_players, roster_stats, my_team=my_team)
    if receive_players and other_team != ANY_TRADE_PARTNER:
        owners = {
            resolve_player_owner_team(player, roster_stats, my_team=my_team) for player in receive_players
        }
        owners.discard(None)
        if len(owners) > 1:
            st.warning("Receive players must belong to the same team in one trade.")
        elif trade_partner == ANY_TRADE_PARTNER and owners:
            owner = next(iter(owners))
            st.caption(f"{receive_players[0]} is owned by {owner}. Ideas will search {owner}.")

    auto_analyze = bool(shared.pop("auto_analyze", False))
    analyze_btn = False
    find_ideas_btn = False
    propose_btn = False
    persisted_analysis = shared.get("analysis") if isinstance(shared.get("analysis"), dict) else None
    verdict = str((persisted_analysis or {}).get("verdict") or "")
    analysis_rendered = False
    if auto_analyze and give_players and receive_players:
        package = build_trade_analysis_package(
            give_players=give_players,
            receive_players=receive_players,
            roster_stats=roster_stats,
            standings=standings,
            my_team=my_team,
            evaluate_trade_fn=evaluate_trade_fn,
            build_trade_verdict_text_fn=build_trade_verdict_text_fn,
            summarize_team_category_needs_fn=summarize_team_category_needs_fn,
            source_offer_id=str(shared.get("source_offer_id") or ""),
            source_idea_id=str(shared.get("source_idea_id") or ""),
        )
        _render_analysis_panel(st, package, roster_stats)
        st.success("Analysis complete.")
        shared["analysis"] = package
        verdict = str(package.get("verdict") or "")
        analysis_rendered = True
        session[LINEUP_TRADE_IDEAS_DIAG_KEY] = {
            "button_action": "analyze",
            "source_offer_id": shared.get("source_offer_id"),
        }
    elif analysis_matches_selection(persisted_analysis, give=give_players, receive=receive_players):
        _render_analysis_panel(st, persisted_analysis, roster_stats)
        verdict = str(persisted_analysis.get("verdict") or "")
        analysis_rendered = True

    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 1, 1])
    find_ideas_btn = c1.button("Find Trade Ideas", key="tc_find_ideas", type="primary")
    analyze_btn = c2.button(
        "Analyze Exact Trade",
        key="tc_analyze_trade",
        disabled=not (give_players and receive_players),
    )
    propose_btn = c3.button(
        "Propose Trade",
        key="tc_propose_trade",
        disabled=not (give_players and receive_players and other_team and other_team != ANY_TRADE_PARTNER),
    )
    if c4.button("Clear", key="tc_clear_trade"):
        queue_pending_builder_update(session, scope_key, {"action": "clear", "clear": True})
        st.rerun()
    if c5.button("Reset Trade Builder", key="tc_reset_builder"):
        shared = reset_trade_builder(session, scope_key, logical_state=shared)
        st.rerun()

    analyze = analyze_btn
    find_ideas = find_ideas_btn
    if analyze and give_players and receive_players:
        package = build_trade_analysis_package(
            give_players=give_players,
            receive_players=receive_players,
            roster_stats=roster_stats,
            standings=standings,
            my_team=my_team,
            evaluate_trade_fn=evaluate_trade_fn,
            build_trade_verdict_text_fn=build_trade_verdict_text_fn,
            summarize_team_category_needs_fn=summarize_team_category_needs_fn,
            source_offer_id=str(shared.get("source_offer_id") or ""),
            source_idea_id=str(shared.get("source_idea_id") or ""),
        )
        _render_analysis_panel(st, package, roster_stats)
        st.success("Analysis complete.")
        shared["analysis"] = package
        verdict = str(package.get("verdict") or "")
        analysis_rendered = True
        session[LINEUP_TRADE_IDEAS_DIAG_KEY] = {
            "button_action": "analyze",
            "source_offer_id": shared.get("source_offer_id"),
        }

    collapse_ideas = analysis_rendered and bool(persisted_analysis or shared.get("analysis"))
    if find_ideas:
        owner_map = resolve_receive_target_teams(receive_players, roster_stats, my_team=my_team)
        target = other_team if other_team and other_team != ANY_TRADE_PARTNER else None
        suggestions, diag = generate_trade_ideas(
            my_team,
            roster_stats,
            standings,
            forced_give=give_players or None,
            forced_get=receive_players or None,
            target_team=target if not owner_map else None,
            target_owner_teams=owner_map,
            summarize_team_category_needs_fn=summarize_team_category_needs_fn,
            league_context_id=league_id,
        )
        session[LINEUP_TRADE_IDEAS_RESULTS_KEY] = suggestions.to_dict(orient="records") if not suggestions.empty else []
        session[LINEUP_TRADE_IDEAS_DIAG_KEY] = diag

    stored_rows = session.get(LINEUP_TRADE_IDEAS_RESULTS_KEY) or []
    diag = session.get(LINEUP_TRADE_IDEAS_DIAG_KEY) or {}
    if stored_rows and not collapse_ideas:
        st.markdown("#### Top trade ideas")
        for idx, row in enumerate(stored_rows[:5]):
            _render_idea_card(
                st,
                row if isinstance(row, dict) else {},
                idx,
                session,
                scope_key,
                roster_stats=roster_stats,
            )
        if len(stored_rows) > 5 and st.button("Show more ideas", key="tc_show_more_ideas"):
            for idx, row in enumerate(stored_rows[5:10], start=5):
                _render_idea_card(
                    st,
                    row if isinstance(row, dict) else {},
                    idx,
                    session,
                    scope_key,
                    roster_stats=roster_stats,
                )
    elif find_ideas or session.get(LINEUP_TRADE_IDEAS_DIAG_KEY):
        if not collapse_ideas:
            st.markdown(
                f'<div class="tc-empty">{html_lib.escape(empty_trade_ideas_message(diag))}</div>',
                unsafe_allow_html=True,
            )

    saved = save_logical_state_from_widgets(
        shared,
        give_players=give_players,
        receive_players=receive_players,
        trade_partner=trade_partner,
        other_team=other_team,
    )
    if analysis_rendered:
        saved["analysis"] = shared.get("analysis")
    if auto_analyze and analysis_rendered:
        saved.pop("auto_analyze", None)
    saved["mode"] = "analyze" if analysis_rendered else "ideas"
    saved["verdict"] = verdict
    saved["league_id"] = league_id
    saved["my_team"] = my_team
    _save_shared_trade_state(session, scope_key, saved)

    confirm = session.get(proposal_confirm_key(scope_key))
    if isinstance(confirm, dict) and confirm:
        with st.container(border=True):
            st.markdown("**Confirm trade proposal**")
            st.markdown(
                f"Send to **{html_lib.escape(str(confirm.get('other_team') or other_team or ''))}** · "
                f"You give **{html_lib.escape(', '.join(confirm.get('give_players') or give_players))}** · "
                f"You receive **{html_lib.escape(', '.join(confirm.get('get_players') or receive_players))}**"
            )
            cc1, cc2 = st.columns(2)
            if cc1.button("Confirm and send proposal", key="tc_confirm_propose", type="primary"):
                try:
                    from fantasy_trade_proposals_ui import submit_trade_proposal_from_analyzer

                    submit_trade_proposal_from_analyzer(
                        st,
                        session,
                        my_team=my_team,
                        other_team=str(confirm.get("other_team") or other_team),
                        give_players=list(confirm.get("give_players") or give_players),
                        get_players=list(confirm.get("get_players") or receive_players),
                        verdict=verdict,
                        persist_fn=_persist_trade_plan,
                        key_prefix="tc_confirm_send",
                    )
                    session.pop(proposal_confirm_key(scope_key), None)
                    st.success("Proposal sent. Check Offers & Activity.")
                except ImportError:
                    st.info("Trade proposal submission is not available in this build.")
            if cc2.button("Cancel proposal", key="tc_cancel_propose"):
                session.pop(proposal_confirm_key(scope_key), None)
                st.rerun()

    if propose_btn and give_players and receive_players and other_team:
        session[proposal_confirm_key(scope_key)] = {
            "give_players": list(give_players),
            "get_players": list(receive_players),
            "trade_partner": trade_partner,
            "other_team": other_team,
            "source_idea_id": str(shared.get("source_idea_id") or ""),
            "source_offer_id": str(shared.get("source_offer_id") or ""),
        }
        st.rerun()

    if developer_mode_enabled_fn():
        with st.expander("Trade Center diagnostics (Developer Mode)", expanded=False):
            st.json(
                {
                    **diag,
                    **builder_diag,
                    "my_team": my_team,
                    "other_teams": ws.get("other_teams"),
                    "roster_counts_by_team": diag.get("roster_counts_by_team")
                    or {
                        team: int(len(roster_stats[roster_stats["Team"].astype(str) == team]))
                        for team in sorted(roster_stats["Team"].dropna().astype(str).unique().tolist())
                    },
                    "give_selections": give_players,
                    "receive_selections": receive_players,
                }
            )


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

    handoff = session.pop("_trade_center_handoff", None)
    if isinstance(handoff, dict):
        queue_pending_builder_update(
            session,
            scope_key,
            {
                "action": str(handoff.get("action") or "analyze_offer"),
                "give_players": list(handoff.get("give_players") or []),
                "get_players": list(handoff.get("receive_players") or handoff.get("get_players") or []),
                "trade_partner": str(handoff.get("other_team") or handoff.get("trade_partner") or ""),
                "other_team": str(handoff.get("other_team") or handoff.get("trade_partner") or ""),
                "source_offer_id": str(handoff.get("source_offer_id") or handoff.get("proposal_id") or ""),
                "auto_analyze": bool(handoff.get("auto_analyze", True)),
            },
        )
        session[f"{scope_key}|builder_handoff_meta"] = {"present": True, "consumed": True}
        session[TRADE_CENTER_INTERNAL_TAB_KEY] = "Build & Analyze"

    if ws["roster_stats"] is None or ws["roster_stats"].empty:
        missing_team = ""
        try:
            from fantasy_league_context import get_active_league_context

            ctx = get_active_league_context(session) or {}
            teams = sorted((ctx.get("league_rosters") or {}).keys())
            my = ws.get("my_team") or ""
            others = [t for t in teams if str(t) != str(my)]
            if others:
                missing_team = str(others[0])
        except ImportError:
            pass
        if missing_team:
            st.markdown(
                f'<div class="tc-empty">{html_lib.escape(missing_team)}\'s roster could not be loaded, so trade ideas cannot be generated yet.</div>',
                unsafe_allow_html=True,
            )
        else:
            err = str(ws.get("load_error") or "").strip()
            msg = err or "Load league rosters and stats to open Trade Center."
            st.markdown(f'<div class="tc-empty">{html_lib.escape(msg)}</div>', unsafe_allow_html=True)
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

    requested_tab = resolve_trade_center_internal_tab(session)
    valid_tabs = list(TRADE_CENTER_INTERNAL_TABS)
    sync_trade_center_internal_widget(session, requested_tab=requested_tab)

    nav_left, nav_right = st.columns([5, 2])
    with nav_left:
        selected = st.radio(
            "Trade Center section",
            valid_tabs,
            horizontal=True,
            key=TRADE_CENTER_INTERNAL_WIDGET_KEY,
            label_visibility="collapsed",
        )
    with nav_right:
        if pending:
            st.caption(f"Offers & Activity · {pending} pending")

    internal_tab = apply_trade_center_internal_selection(session, selected)

    if internal_tab == "Build & Analyze":
        _render_build_analyze(
            st,
            session,
            ws=ws,
            league_id=league_id,
            scope_key=scope_key,
            scope_fingerprint=scope_fingerprint,
            ensure_select_in_options=ensure_select_in_options,
            ensure_multiselect_state=ensure_multiselect_state,
            evaluate_trade_fn=evaluate_trade_fn,
            build_trade_verdict_text_fn=build_trade_verdict_text_fn,
            summarize_team_category_needs_fn=summarize_team_category_needs_fn,
            developer_mode_enabled_fn=developer_mode_enabled_fn,
        )
    elif internal_tab == "Offers & Activity":
        _render_offers_activity_section(st, session, ws=ws, scope_key=scope_key, league_id=league_id)


def _render_offers_activity_section(
    st: Any,
    session: dict[str, Any],
    *,
    ws: dict[str, Any],
    scope_key: str,
    league_id: str,
) -> None:
    tab_key = _offers_activity_tab_key(scope_key)
    widget_key = _offers_activity_widget_key(scope_key)
    requested = str(session.get(tab_key) or OFFERS_ACTIVITY_TABS[0])
    if requested not in OFFERS_ACTIVITY_TABS:
        requested = OFFERS_ACTIVITY_TABS[0]
    if session.get(widget_key) not in OFFERS_ACTIVITY_TABS:
        session[widget_key] = requested
    pending = _count_pending_offers(session, ws["my_team"])
    selected = st.radio(
        "Offers and activity section",
        list(OFFERS_ACTIVITY_TABS),
        horizontal=True,
        key=widget_key,
        label_visibility="collapsed",
    )
    if pending:
        st.caption(f"Active Offers · {pending} pending")
    session[tab_key] = selected
    if selected == "Active Offers":
        _render_offers_section(st, session, ws=ws, scope_key=scope_key, league_id=league_id)
    else:
        _render_history_section(st, session, ws=ws)


def _render_offers_section(st: Any, session: dict[str, Any], *, ws: dict[str, Any], scope_key: str, league_id: str) -> None:
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
            hide_propose_form=True,
            on_analyze_offer=lambda offer: _load_offer_into_state(session, scope_key, offer, ws["my_team"]),
            on_clear_offer=lambda offer: _clear_offer_from_inbox(session, offer, league_id=league_id),
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
            hide_propose_form=True,
        )
    except ImportError as exc:
        st.markdown(f'<div class="tc-empty">Offers unavailable: {html_lib.escape(str(exc))}</div>', unsafe_allow_html=True)


def _load_offer_into_state(session: dict[str, Any], scope_key: str, offer: dict[str, Any], my_team: str) -> None:
    try:
        from fantasy_trade_proposals import recipient_view, proposer_view

        pid = str(offer.get("proposal_id") or offer.get("id") or "").strip()
        recipient = str(offer.get("recipient_team") or offer.get("to_team") or "").strip()
        if recipient == my_team:
            view = recipient_view(offer)
        else:
            view = proposer_view(offer)
        give = list(view.get("give_players") or [])
        receive = list(view.get("receive_players") or [])
        other = str(view.get("other_team") or "").strip()
    except ImportError:
        from_team = str(offer.get("from_team") or offer.get("proposer_team") or "").strip()
        to_team = str(offer.get("to_team") or offer.get("recipient_team") or "").strip()
        pid = str(offer.get("proposal_id") or offer.get("id") or "").strip()
        if to_team == my_team:
            give = [str(p.get("player_name") or p) for p in (offer.get("proposer_receives") or offer.get("requested_players") or [])]
            receive = [str(p.get("player_name") or p) for p in (offer.get("proposer_gives") or offer.get("offered_players") or [])]
            other = from_team
        else:
            give = [str(p.get("player_name") or p) for p in (offer.get("proposer_gives") or offer.get("offered_players") or [])]
            receive = [str(p.get("player_name") or p) for p in (offer.get("proposer_receives") or offer.get("requested_players") or [])]
            other = to_team
    queue_pending_builder_update(
        session,
        scope_key,
        {
            "action": "analyze_offer",
            "give_players": [g for g in give if g],
            "get_players": [g for g in receive if g],
            "trade_partner": other,
            "other_team": other,
            "source_offer_id": pid,
            "auto_analyze": True,
        },
    )
    session[TRADE_CENTER_INTERNAL_TAB_KEY] = "Build & Analyze"


def _clear_offer_from_inbox(session: dict[str, Any], offer: dict[str, Any], *, league_id: str) -> None:
    try:
        from fantasy_trade_proposals import archive_offer_from_inbox

        archive_offer_from_inbox(
            session,
            str(offer.get("proposal_id") or offer.get("id") or ""),
            league_id=league_id,
        )
    except ImportError:
        pass


def _render_history_section(st: Any, session: dict[str, Any], *, ws: dict[str, Any]) -> None:
    try:
        from fantasy_league_context import get_active_league_context
        from fantasy_trade_proposals import get_trade_history

        context = get_active_league_context(session) or {}
        history = get_trade_history(context)
        proposals = (
            (history.get("accepted") or [])
            + (history.get("declined") or [])
            + (history.get("pending") or [])
        )
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
    seen_accepted: set[str] = set()
    for proposal in reversed(proposals):
        if not isinstance(proposal, dict):
            continue
        status = str(proposal.get("status") or "unknown").strip()
        pid = str(proposal.get("proposal_id") or proposal.get("trade_id") or "").strip()
        if filter_status != "All" and status.lower() != filter_status.lower():
            continue
        if status.lower() == "accepted":
            if pid and pid in seen_accepted:
                continue
            if pid:
                seen_accepted.add(pid)
        shown += 1
        from_team = str(proposal.get("proposer_team") or proposal.get("from_team") or "")
        to_team = str(proposal.get("recipient_team") or proposal.get("to_team") or "")
        give = proposal.get("proposer_gives") or proposal.get("offered_players") or proposal.get("give_players") or []
        get = proposal.get("proposer_receives") or proposal.get("requested_players") or proposal.get("get_players") or []
        give_names = ", ".join(
            f"{str(p.get('player_name') if isinstance(p, dict) else p)} · {format_position_label(ws['roster_stats'], str(p.get('player_name') if isinstance(p, dict) else p))}"
            for p in give
        )
        get_names = ", ".join(
            f"{str(p.get('player_name') if isinstance(p, dict) else p)} · {format_position_label(ws['roster_stats'], str(p.get('player_name') if isinstance(p, dict) else p))}"
            for p in get
        )
        st.markdown(
            f"""<div class="tc-idea-card">
<span class="tc-badge">{html_lib.escape(status.title())}</span>
<b>{html_lib.escape(from_team)} → {html_lib.escape(to_team)}</b><br/>
<span style="font-size:0.82rem;">Give {html_lib.escape(give_names)} · Receive {html_lib.escape(get_names)}</span>
</div>""",
            unsafe_allow_html=True,
        )
        if shown >= 20:
            break
