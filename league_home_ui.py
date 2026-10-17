"""League Standings answer block (U1): where your team stands, before the full tables.

Order: your place and gap → strengths / closest gaps → the official standings at a glance →
this week's status → next steps. All numbers come from the season ledger's official standings
(``fantasy_season_results.official_standings``) and ``home_page.league_summary``; the current
roster snapshot is never used here.
"""

from __future__ import annotations

from typing import Any, Callable

LINEUP_PAGE = "Fantasy Lineup Assistant"


def _team_for_viewer(session: Any, context: dict[str, Any]) -> tuple[str, bool]:
    """(team to describe, viewer manages it)."""
    from home_page import _my_team

    team = _my_team(session, context)
    try:
        from fantasy_team_control import resolve_team_control

        return team, bool(resolve_team_control(session, context, team).can_manage) if team else False
    except Exception:
        return team, bool(team)


def _commissioner(session: Any, context: dict[str, Any], team: str) -> bool:
    try:
        from fantasy_team_control import resolve_team_control

        return bool(resolve_team_control(session, context, team).is_commissioner)
    except Exception:
        return False


def render_league_answer(st: Any, session: Any, context: dict[str, Any] | None,
                         navigate: Callable[..., Any]) -> bool:
    """Render the answer block. Returns False when there is no league to describe."""
    import ui_hierarchy as ui
    from home_page import _ordinal, league_summary

    def go(page: str, **state: Any) -> Callable[[], None]:
        def _cb() -> None:
            for key, value in state.items():
                session[key] = value
            navigate(page, from_callback=True)
        return _cb

    if not isinstance(context, dict) or not (context.get("league_rosters") or {}):
        ui.answer_card(st, "No active league", "Pick a league in My Leagues & Drafts, or draft one first.",
                       kicker="League standings", tone="warn")
        ui.action_row(st, [("Open my leagues", go("Saved Draft Library")),
                           ("Start or import a draft", go("Draft Room Simulator"))], key="league_none")
        return False
    team, manages = _team_for_viewer(session, context)
    is_comm = _commissioner(session, context, team)
    summary = league_summary(context, team, is_commissioner=is_comm)
    if summary is None:
        return False

    if summary.place is not None:
        who = "You're" if manages else f"{team} is"
        tie = "tied " if summary.tied else ""
        headline = f"{who} {tie}{_ordinal(summary.place)} of {summary.team_count} · {summary.gap_text}"
        body = (f"{team} · official standings after {summary.weeks_final} completed week"
                f"{'s' if summary.weeks_final != 1 else ''}. Each completed week counts the lineup used that week.")
        ui.answer_card(st, headline, body, kicker=summary.league_name)
        from fantasy_season_results import official_standings, scoring_categories
        import u1_answers as u1a

        table, _weeks = official_standings(context)
        notes = u1a.category_strengths_and_gaps(table, team, scoring_categories(context))
        chips = [(f"Strength · {s}", "good") for s in notes["strengths"]]
        chips += [(f"Closest gain · {g}", "warn") for g in notes["opportunities"]]
        ui.chips(st, chips)
        ui.section_label(st, "Official standings")
        ui.ranked_list(st, [
            {"rank": rank, "name": name, "value": f"{pts:g} pts", "me": name == team}
            for rank, name, pts in summary.leaderboard
        ])
    else:
        headline = (f"{summary.league_name}: no completed weeks yet" if summary.week_text != "No season calendar yet"
                    else f"{summary.league_name}: official standings haven't started")
        body = ("Official standings are the sum of completed weeks. They start when the commissioner sets the "
                "season calendar and finalizes the first week.")
        ui.answer_card(st, headline, body, kicker="League standings")
    ui.chips(st, [(summary.week_text, ""),
                  (summary.next_action, "warn" if summary.next_action.startswith(("Set", "Finalize")) else "")])
    ui.action_row(st, [
        ("Set Lineup", go(LINEUP_PAGE, lineup_assistant_tab="Lineup Management",
                          lineup_assistant_tab_widget="Lineup Management")),
        ("Check Waivers", go("Waiver Wire / Add-Drop Center")),
        ("Explore Trades", go(LINEUP_PAGE, _lineup_focus_trade_center=True)),
    ], key="league_next", primary=0)
    return True
