"""UI for locked weekly hitter scoring dashboard."""

from __future__ import annotations

import html as html_lib
from typing import Any

import pandas as pd

from fantasy_league_lineup_format import is_lineup_format_commissioner
from fantasy_weekly_hitter_scoring import (
    HitterScoringProfile,
    diagnose_weekly_scoring_record,
    finalize_week_for_league,
    get_weekly_scoring_record,
    is_legacy_locked_lineup,
    is_week_finalized_for_league,
    preview_finalize_week,
    refresh_weekly_scoring,
    resolve_hitter_scoring_profile,
    should_start_week_empty,
    start_weekly_tracking_from_now,
)
from fantasy_weekly_lineup import week_label


def _format_stat_value(cat: str, val: Any) -> str:
    if val is None:
        return "—"
    if cat in ("AVG", "OBP", "OPS"):
        try:
            return f"{float(val):.3f}"
        except (TypeError, ValueError):
            return "—"
    try:
        if float(val).is_integer():
            return str(int(float(val)))
        return f"{float(val):.1f}"
    except (TypeError, ValueError):
        return str(val)


def _stat_line_html(categories: tuple[str, ...], values: dict[str, Any], *, points: Any = None) -> str:
    parts: list[str] = []
    if points is not None:
        parts.append(f"<span class='fl-wk-pts'><b>{_format_stat_value('POINTS', points)}</b> pts</span>")
    for cat in categories:
        val = values.get(cat)
        parts.append(
            f"<span class='fl-wk-stat'><span class='fl-wk-cat'>{html_lib.escape(cat)}</span> "
            f"{html_lib.escape(_format_stat_value(cat, val))}</span>"
        )
    return " ".join(parts)


def render_weekly_scoring_styles(st: Any) -> None:
    st.markdown(
        """
<style>
.fl-weekly-scoring { margin: 8px 0 12px; }
.fl-weekly-scoring h4 { margin: 0 0 6px; font-size: 0.95rem; }
.fl-wk-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
.fl-wk-card {
  border: 1px solid rgba(11,61,110,0.15); border-radius: 10px; padding: 8px 10px; background: #fafcff;
}
.fl-wk-card.bench { opacity: 0.88; border-style: dashed; }
.fl-wk-name { font-weight: 700; font-size: 0.86rem; margin-bottom: 4px; }
.fl-wk-role { font-size: 0.72rem; color: #475569; margin-bottom: 4px; }
.fl-wk-stat { display: inline-block; margin-right: 8px; font-size: 0.74rem; }
.fl-wk-cat { color: #0b3d6e; font-weight: 700; margin-right: 2px; }
.fl-wk-pts { display: block; font-size: 0.82rem; margin-bottom: 4px; }
.fl-wk-team-totals { margin-top: 10px; padding: 8px 10px; background: #eef6ff; border-radius: 10px; }
.fl-wk-muted { color: #64748b; font-size: 0.8rem; }
</style>
""",
        unsafe_allow_html=True,
    )


def render_locked_weekly_dashboard(
    st: Any,
    *,
    context: dict[str, Any],
    week: int,
    team: str,
    scoring_record: dict[str, Any] | None,
    profile: HitterScoringProfile,
    roster_df: pd.DataFrame,
    saved_lineup: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
) -> None:
    """Render weekly stat cards, explicit status messages, and legacy commissioner actions."""
    st.subheader("Weekly statistics")

    if profile.blocked:
        st.warning(profile.block_message or "Weekly scoring is not configured for this league.")
        return

    if roster_df is None or roster_df.empty:
        st.warning(
            "Weekly statistics need current-season hitter stats for your roster. "
            "The app is loading stats automatically — refresh the page in a moment."
        )
        return

    has_baseline = isinstance(scoring_record, dict) and bool(scoring_record.get("baseline_created_at"))
    is_legacy = is_legacy_locked_lineup(saved_lineup or {"status": "locked"}, scoring_record)

    if is_legacy and not has_baseline:
        st.warning(
            "This lineup was locked before weekly scoring was enabled, so an original weekly baseline is unavailable."
        )
        if session is not None:
            try:
                from fantasy_league_lineup_format import is_lineup_format_commissioner

                if is_lineup_format_commissioner(session, context):
                    confirm_key = f"weekly_start_tracking_confirm_{int(week)}"
                    if st.checkbox(
                        "Start tracking statistics from now (uses current stats, not week start)",
                        key=confirm_key,
                    ):
                        assignments = dict((saved_lineup or {}).get("assignments") or {})
                        if st.button(
                            "Establish baseline from now",
                            key=f"weekly_start_tracking_btn_{int(week)}",
                            type="primary",
                        ):
                            result = start_weekly_tracking_from_now(
                                session,
                                context,
                                week=int(week),
                                team=team,
                                assignments=assignments,
                                roster_df=roster_df,
                                profile=profile,
                            )
                            if result.get("ok"):
                                st.rerun()
                            else:
                                st.error("; ".join(result.get("errors") or ["Could not start tracking."]))
            except ImportError:
                pass
        return

    if not has_baseline:
        st.info("Loading weekly statistics…")
        st.caption(
            "If this message persists, save may not have created a scoring baseline. "
            "Try Refresh weekly stats or contact the commissioner."
        )
        return

    starters = scoring_record.get("starters") or {}
    bench = scoring_record.get("bench") or {}
    if not starters and not bench:
        st.warning("Weekly scoring record exists but no players were captured. Try Refresh weekly stats.")
        return

    baseline_at = str(scoring_record.get("baseline_created_at") or "")
    if baseline_at:
        note = str(scoring_record.get("baseline_note") or "").strip()
        if note:
            st.caption(f"Baseline captured: {baseline_at} · {note}")
        else:
            st.caption(f"Baseline captured: {baseline_at}")

    updated = str(scoring_record.get("stats_updated_at") or "")
    if updated:
        st.caption(f"Weekly stats last updated: {updated}")

    render_weekly_scoring_styles(st)
    results = scoring_record.get("player_results") or {}
    cats = tuple(profile.display_categories)

    st.markdown('<div class="fl-weekly-scoring">', unsafe_allow_html=True)
    st.markdown("<h4>Starters — weekly scoring</h4>", unsafe_allow_html=True)
    cards: list[str] = []
    for pkey, meta in starters.items():
        if not isinstance(meta, dict):
            continue
        pres = results.get(pkey) or {}
        display = pres.get("display") or {}
        if not display and isinstance(scoring_record.get("baselines"), dict):
            display = {cat: 0 for cat in cats if cat not in ("AVG", "OBP", "OPS")}
            if "AVG" in cats:
                display["AVG"] = None
        cards.append(
            f"<div class='fl-wk-card'><div class='fl-wk-name'>{html_lib.escape(str(meta.get('player_name') or ''))}</div>"
            f"<div class='fl-wk-role'>{html_lib.escape(str(meta.get('slot') or 'Starter'))}</div>"
            f"{_stat_line_html(cats, display, points=pres.get('points_total'))}</div>"
        )
    if cards:
        st.markdown(f"<div class='fl-wk-grid'>{''.join(cards)}</div>", unsafe_allow_html=True)
    else:
        st.caption("No starters in weekly scoring record.")

    if bench:
        st.markdown("<h4>Bench — does not count toward team score</h4>", unsafe_allow_html=True)
        bench_cards: list[str] = []
        for pkey, meta in bench.items():
            if not isinstance(meta, dict):
                continue
            pres = results.get(pkey) or {}
            display = pres.get("display") or {}
            if not display:
                display = {cat: 0 for cat in cats if cat not in ("AVG", "OBP", "OPS")}
                if "AVG" in cats:
                    display["AVG"] = None
            bench_cards.append(
                f"<div class='fl-wk-card bench'><div class='fl-wk-name'>{html_lib.escape(str(meta.get('player_name') or ''))}</div>"
                f"<div class='fl-wk-role'>Bench (non-scoring)</div>"
                f"{_stat_line_html(cats, display, points=pres.get('points_total'))}</div>"
            )
        st.markdown(f"<div class='fl-wk-grid'>{''.join(bench_cards)}</div>", unsafe_allow_html=True)

    team_totals = (scoring_record.get("team_totals") or {}).get("totals")
    if not isinstance(team_totals, dict):
        team_totals = {cat: 0 for cat in cats if cat not in ("AVG", "OBP", "OPS")}
        if "AVG" in cats:
            team_totals["AVG"] = None
    st.markdown(
        f"<div class='fl-wk-team-totals'><b>Team weekly totals</b> "
        f"{_stat_line_html(cats, team_totals, points=team_totals.get('POINTS'))}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="fl-wk-muted">Bench statistics are shown for reference only and do not count toward your team score. '
        "Zero values mean no change since the baseline was captured.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    _render_player_details(st, scoring_record=scoring_record, profile=profile)

    try:
        from suite_workspace import can_show_developer_tools

        if session is not None and can_show_developer_tools(st=st):
            with st.expander("Weekly scoring diagnostics (Developer Mode)", expanded=False):
                st.json(
                    diagnose_weekly_scoring_record(
                        context,
                        week=week,
                        team=team,
                        saved_lineup=saved_lineup,
                        roster_df=roster_df,
                        profile=profile,
                    )
                )
    except ImportError:
        pass


def render_player_detail_panel(
    st: Any,
    *,
    player_name: str,
    scoring_record: dict[str, Any],
    profile: HitterScoringProfile,
) -> None:
    """Compact detail view for one tapped player face."""
    players = {**(scoring_record.get("starters") or {}), **(scoring_record.get("bench") or {})}
    pkey = ""
    meta: dict[str, Any] = {}
    for key, row in players.items():
        if isinstance(row, dict) and str(row.get("player_name") or "").strip() == player_name:
            pkey = str(key)
            meta = row
            break
    if not pkey:
        st.caption(f"No weekly scoring data for {player_name}.")
        return

    pres = (scoring_record.get("player_results") or {}).get(pkey) or {}
    display = pres.get("display") or {}
    baseline = (scoring_record.get("baselines") or {}).get(pkey) or {}
    role = "Starter" if meta.get("is_starter") else "Bench"
    slot = str(meta.get("slot") or ("Bench" if role == "Bench" else "Starter"))

    st.markdown(f"### {player_name}")
    st.caption(f"{role} · {slot}")
    cols = st.columns(min(5, max(1, len(profile.display_categories))))
    for idx, cat in enumerate(profile.display_categories):
        with cols[idx % len(cols)]:
            st.metric(f"Weekly {cat}", _format_stat_value(cat, display.get(cat)))
    if profile.scoring_mode == "points":
        st.metric("Weekly points", _format_stat_value("POINTS", pres.get("points_total")))
    unavailable = pres.get("unavailable") or {}
    if unavailable:
        st.caption(f"Unavailable: {unavailable}")
    with st.expander("Baseline & season context", expanded=False):
        st.caption(f"Baseline captured: {scoring_record.get('baseline_created_at') or '—'}")
        st.caption(f"Stats updated: {scoring_record.get('stats_updated_at') or '—'}")
        st.json({"baseline": baseline, "weekly": display, "unavailable": unavailable})


def _render_player_details(
    st: Any,
    *,
    scoring_record: dict[str, Any],
    profile: HitterScoringProfile,
) -> None:
    players = {**(scoring_record.get("starters") or {}), **(scoring_record.get("bench") or {})}
    baselines = scoring_record.get("baselines") or {}
    results = scoring_record.get("player_results") or {}
    if not players:
        return
    with st.expander("Player weekly details", expanded=False):
        for pkey, meta in players.items():
            if not isinstance(meta, dict):
                continue
            name = str(meta.get("player_name") or pkey)
            role = "Starter" if meta.get("is_starter") else "Bench"
            pres = results.get(pkey) or {}
            display = pres.get("display") or {}
            baseline = baselines.get(pkey) or {}
            st.markdown(f"**{name}** — {role}")
            cols = st.columns(min(4, max(1, len(profile.display_categories))))
            for idx, cat in enumerate(profile.display_categories):
                with cols[idx % len(cols)]:
                    st.caption(f"{cat}: {_format_stat_value(cat, display.get(cat))}")
            if profile.scoring_mode == "points":
                st.caption(f"Weekly points: {_format_stat_value('POINTS', pres.get('points_total'))}")
            with st.expander(f"Baseline & season context — {name}", expanded=False):
                st.caption(f"Baseline captured: {scoring_record.get('baseline_created_at') or '—'}")
                st.json({"baseline": baseline, "weekly": display, "unavailable": pres.get("unavailable") or {}})


def render_scoring_refresh_controls(
    st: Any,
    session: dict[str, Any],
    *,
    context: dict[str, Any],
    week: int,
    team: str,
    roster_df: pd.DataFrame,
    prefix: str,
) -> dict[str, Any] | None:
    """Controlled refresh — not on every rerun."""
    profile = resolve_hitter_scoring_profile(context, session=session)
    if profile.blocked:
        st.warning(profile.block_message)
        return None

    record = get_weekly_scoring_record(context, week=week, team=team)
    refresh_key = f"{prefix}_refresh_weekly_stats_{int(week)}"
    if st.button("Refresh weekly stats", key=refresh_key):
        result = refresh_weekly_scoring(context, week=week, team=team, roster_df=roster_df, profile=profile, session=session)
        if result.get("ok"):
            session[f"{prefix}_scoring_flash"] = "Weekly stats refreshed."
            st.rerun()
        else:
            st.error("; ".join(result.get("errors") or ["Could not refresh stats."]))

    flash = session.pop(f"{prefix}_scoring_flash", None)
    if flash:
        st.success(str(flash))

    if isinstance(record, dict) and record.get("baseline_created_at"):
        return record
    return record


def render_finalize_week_section(
    st: Any,
    session: dict[str, Any],
    *,
    context: dict[str, Any],
    week: int,
    roster_by_team: dict[str, pd.DataFrame],
    prefix: str,
) -> None:
    if not is_lineup_format_commissioner(session, context):
        return
    if is_week_finalized_for_league(context, week):
        st.success(f"{week_label(week)} finalized and added to standings.")
        return

    st.subheader("Finalize week")
    preview = preview_finalize_week(context, week=week, roster_by_team=roster_by_team)
    if preview.get("unlocked_teams"):
        st.warning(f"Teams without locked lineups: {', '.join(preview['unlocked_teams'])}")
    if preview.get("missing_data"):
        st.warning(f"Missing required data: {', '.join(preview['missing_data'])}")
    for row in preview.get("teams_preview") or []:
        st.caption(f"{row.get('team')}: {row.get('totals')}")

    confirm_key = f"{prefix}_finalize_confirm_{int(week)}"
    if st.checkbox(f"I confirm finalizing {week_label(week)}", key=confirm_key):
        if st.button(f"Finalize {week_label(week)}", key=f"{prefix}_finalize_btn_{int(week)}", type="primary"):
            result = finalize_week_for_league(session, context, week=week, roster_by_team=roster_by_team)
            if result.get("ok"):
                session[f"{prefix}_finalize_flash"] = f"{week_label(week)} finalized."
                st.rerun()
            else:
                st.error("; ".join(result.get("errors") or ["Finalize failed."]))

    flash = session.pop(f"{prefix}_finalize_flash", None)
    if flash:
        st.success(str(flash))


def render_week_transition_notice(
    st: Any,
    *,
    context: dict[str, Any],
    week: int,
) -> None:
    if should_start_week_empty(context, week):
        st.info(
            f"Week {int(week) - 1} is complete. Your results were added to Fantasy Standings. "
            f"Set your {week_label(week)} lineup."
        )
