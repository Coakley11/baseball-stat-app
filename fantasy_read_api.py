"""Read-only fantasy interface for AMI and other consumers.

One import surface over the authoritative modules. Nothing here computes a statistic of its
own: every number comes from the module named in each function's docstring. Nothing here
writes the session, fetches data, or changes a league.

Contracts in brief (details per function; see docs/FANTASY_SHARED_INTERFACES.md):

* ``active_league(session)`` — which league/team the fantasy pages show.
* ``official_standings_view(session)`` — THE standings: sum of finalized weeks.
* ``current_roster_standings_view(roster_stats, fmt)`` — today's rosters on season-to-date
  stats. Analysis only; always labeled "not official standings".
* ``loaded_roster_stats(session)`` — the roster stats a page already loaded (never fetches).
* ``team_access(session, team)`` — may this user act for / see private data of a team.
* ``evaluate_trade_for_team(...)`` — trade value + legality, only for a team the user manages.
* ``lineup_report(...)``, ``explain_slot_eligibility(...)``, ``check_lineup(...)`` — lineup
  scoring, recommended starters, diagnosis and eligibility explanations.

Every result says which kind of data it is (``kind`` / ``label``) so an assistant can never
present a snapshot as the official standings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from fantasy_league_peek import isolated_session_view, peek_active_league_context, peek_resolved_fantasy_context
from fantasy_standings_snapshot import SNAPSHOT_KIND, SNAPSHOT_LABEL

OFFICIAL_KIND = "official"
OFFICIAL_LABEL = "League Standings (official)"
OFFICIAL_BASIS = (
    "Sum of finalized weeks. Each week counts the lineup used that week; later drops and trades never change "
    "a completed week. Tied teams split category points."
)
SNAPSHOT_BASIS = (
    "Season-to-date stats of the players on each roster today. A player counts for whoever owns him now, "
    "whenever he played. Not the league standings."
)
ELIGIBILITY_RULE = (
    "Eligible at his primary position and at any position with at least 10 games this season or last season "
    "(LF/CF/RF count as OF; UTIL takes any hitter)."
)


@dataclass(frozen=True)
class LeagueSummary:
    league_context_id: str
    league_name: str
    my_team: str
    team_names: tuple[str, ...]
    scoring_format: str
    lineup_slots: tuple[str, ...]
    has_season_calendar: bool
    finalized_weeks: tuple[int, ...]
    source_kind: str
    context_fingerprint: str
    coherent: bool
    coherence_error: str = ""


@dataclass(frozen=True)
class StandingsView:
    kind: str  # OFFICIAL_KIND or SNAPSHOT_KIND
    label: str
    basis: str
    table: pd.DataFrame
    finalized_weeks: tuple[int, ...] = ()
    note: str = ""

    @property
    def is_official(self) -> bool:
        return self.kind == OFFICIAL_KIND


@dataclass(frozen=True)
class TradeEvaluation:
    allowed: bool
    reason: str = ""
    my_team: str = ""
    partner_team: str = ""
    give: tuple[str, ...] = ()
    receive: tuple[str, ...] = ()
    category_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    verdict: str = ""
    weighted_gain: float = 0.0
    verdict_text: str = ""
    proposal_ok: bool = False
    proposal_message: str = ""
    legality_warnings: tuple[str, ...] = ()
    acting_as: str = ""
    basis: str = (
        "Current-season stats of the players involved (BA/OPS are the plain average of each side's players). "
        "Team needs come from the Current Roster Snapshot, not the official standings."
    )


# --- League -----------------------------------------------------------------------------------


def active_league(session: Any) -> LeagueSummary | None:
    """The league the fantasy pages show, resolved without side effects.

    Source: ``fantasy_league_peek`` (= ``resolve_fantasy_context_for_page`` /
    ``get_active_league_context`` on an isolated view). None when there is no league.
    """
    resolved = peek_resolved_fantasy_context(session)
    context = peek_active_league_context(session)
    if context is None and not resolved.active_league_context_id:
        return None
    context = context or {}
    from fantasy_season_ledger import ledger_initialized, list_periods

    from fantasy_league_lineup_format import lineup_format_block

    slots = tuple((lineup_format_block(context) or {}).get("lineup_slots") or ())
    finalized = tuple(int(p["number"]) for p in list_periods(context) if str(p.get("finalized_at") or "").strip())
    return LeagueSummary(
        league_context_id=str(context.get("league_context_id") or resolved.active_league_context_id or ""),
        league_name=str(context.get("league_name") or context.get("display_name") or context.get("draft_name") or ""),
        my_team=str(resolved.active_team_name or context.get("my_team_name") or ""),
        team_names=tuple(resolved.team_names),
        scoring_format=str(context.get("fantasy_format") or ""),
        lineup_slots=slots,
        has_season_calendar=bool(ledger_initialized(context)),
        finalized_weeks=finalized,
        source_kind=resolved.source_kind,
        context_fingerprint=resolved.context_fingerprint,
        coherent=resolved.coherent,
        coherence_error=resolved.coherence_error,
    )


def team_access(session: Any, team: str):
    """``fantasy_team_control.resolve_team_control`` for ``team`` in the active league (read-only).

    ``.can_manage`` is True for the team's owner, or for the commissioner acting for a team
    nobody has claimed (``.is_proxy``). Use it before showing team-private data (pending
    trades, unsaved lineups, lineups for weeks that haven't started) or any team-perspective
    advice.
    """
    from fantasy_team_control import resolve_team_control

    view = isolated_session_view(session)
    return resolve_team_control(view, peek_active_league_context(session), team)


# --- Standings --------------------------------------------------------------------------------


def official_standings_view(session: Any) -> StandingsView:
    """THE league standings: ``fantasy_season_results.official_standings`` on the active league.

    Empty table (with a note) when the league has no season calendar or no finalized week.
    """
    from fantasy_season_ledger import ledger_initialized
    from fantasy_season_results import official_standings

    context = peek_active_league_context(session)
    if not context or not ledger_initialized(context):
        return StandingsView(OFFICIAL_KIND, OFFICIAL_LABEL, OFFICIAL_BASIS, pd.DataFrame(),
                             note="This league has no season calendar yet, so there are no official standings.")
    table, weeks = official_standings(context)
    note = "" if weeks else "No week is final yet."
    return StandingsView(OFFICIAL_KIND, OFFICIAL_LABEL, OFFICIAL_BASIS, table.copy(), tuple(weeks), note)


def current_roster_standings_view(roster_stats: pd.DataFrame, scoring_format: str = "5x5 Roto") -> StandingsView:
    """Today's rosters on season-to-date stats (``fantasy_standings_snapshot``). NOT official."""
    from fantasy_standings_snapshot import score_current_roster_standings

    if roster_stats is None or getattr(roster_stats, "empty", True):
        return StandingsView(SNAPSHOT_KIND, SNAPSHOT_LABEL, SNAPSHOT_BASIS, pd.DataFrame(), note="No roster stats loaded.")
    table = score_current_roster_standings(roster_stats, scoring_format)
    return StandingsView(SNAPSHOT_KIND, SNAPSHOT_LABEL, SNAPSHOT_BASIS, table)


def loaded_roster_stats(session: Any) -> tuple[pd.DataFrame, str]:
    """(roster stats the Standings/Lineup pages last loaded, loaded-at timestamp). Never fetches.

    Empty frame when no page has loaded current stats in this session — tell the user to open
    Fantasy Standings Tracker rather than fetching.
    """
    view = isolated_session_view(session)
    frame = view.get("fantasy_current_roster_stats")
    loaded_at = str(view.get("_fantasy_standings_stats_loaded_at") or "")
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        return frame, loaded_at
    return pd.DataFrame(), loaded_at


# --- Trades -----------------------------------------------------------------------------------


def evaluate_trade_for_team(
    session: Any,
    *,
    my_team: str,
    partner_team: str,
    give: list[str],
    receive: list[str],
    roster_stats: pd.DataFrame,
    scoring_format: str = "5x5 Roto",
) -> TradeEvaluation:
    """Trade value and legality from ``my_team``'s point of view.

    Authorization: ``my_team`` must be a team this user may manage (``team_access``); otherwise
    ``allowed`` is False and nothing is computed.

    Sources: value — ``fantasy_trade_evaluation.evaluate_trade`` / ``build_trade_verdict_text``
    with needs from ``fantasy_standings_snapshot``; proposal rules —
    ``fantasy_trade_proposals.validate_proposal_players``; roster/lineup consequences —
    ``fantasy_trade_legality.trade_roster_warnings``. Evaluating never proposes or executes.
    """
    give_t, receive_t = tuple(str(p) for p in give or ()), tuple(str(p) for p in receive or ())
    base = dict(my_team=str(my_team or ""), partner_team=str(partner_team or ""), give=give_t, receive=receive_t)
    context = peek_active_league_context(session)
    if not context:
        return TradeEvaluation(False, "There is no active league.", **base)
    control = team_access(session, my_team)
    if not control.can_manage:
        return TradeEvaluation(False, control.reason or f"You can't manage {my_team}.", **base)
    if roster_stats is None or getattr(roster_stats, "empty", True):
        return TradeEvaluation(False, "Current roster stats aren't loaded. Open Fantasy Standings Tracker first.", **base)

    from fantasy_standings_snapshot import score_current_roster_standings
    from fantasy_trade_evaluation import build_trade_verdict_text, evaluate_trade
    from fantasy_trade_legality import trade_roster_warnings
    from fantasy_trade_proposals import validate_proposal_players

    standings = score_current_roster_standings(roster_stats, scoring_format)
    my_roster = roster_stats[roster_stats["Team"].astype(str) == str(my_team)]
    table, verdict, gain = evaluate_trade(list(give_t), list(receive_t), my_roster, roster_stats, standings, my_team)
    ok, message = validate_proposal_players(context, proposer_team=my_team, recipient_team=partner_team,
                                            proposer_gives=list(give_t), proposer_receives=list(receive_t))
    warnings = trade_roster_warnings(context, proposer_team=my_team, recipient_team=partner_team,
                                     proposer_gives=list(give_t), proposer_receives=list(receive_t), stats_pool=roster_stats)
    return TradeEvaluation(
        True, "", category_table=table, verdict=verdict, weighted_gain=float(gain),
        verdict_text=build_trade_verdict_text(table, gain), proposal_ok=bool(ok), proposal_message=message,
        legality_warnings=tuple(warnings or ()), acting_as=control.mode, **base,
    )


# --- Lineups ----------------------------------------------------------------------------------


def lineup_report(
    team_roster_stats: pd.DataFrame,
    *,
    slots: list[str] | None = None,
    scoring_format: str = "5x5 Roto",
    custom_weights: dict[str, float] | None = None,
    rate_col: str = "BA",
    league_roster_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Start/sit scores, recommended starters and lineup diagnosis for one team's roster frame.

    Sources: ``fantasy_lineup_scoring`` (the Lineup Assistant's own functions). Returns
    ``{"scored", "recommended", "missing_slots", "slot_warnings", "diagnosis", "basis"}``.
    Recommended starters use the same slot rule Save Lineup enforces
    (``fantasy_slot_eligibility.player_eligible_for_slot_strict``); ``check_lineup`` validates
    any lineup, including one the user built by hand.
    """
    from fantasy_lineup_scoring import build_lineup_assistant_scores, build_position_aware_lineup, lineup_diagnosis_report
    from fantasy_slot_eligibility import enrich_lineup_roster_positions

    scored = enrich_lineup_roster_positions(build_lineup_assistant_scores(team_roster_stats, scoring_format, custom_weights))
    package = build_position_aware_lineup(scored, slots=slots)
    diagnosis = lineup_diagnosis_report(package["lineup_df"], scored, scoring_format, rate_col,
                                        missing_slots=package["missing_slots"], slot_warnings=package["slot_warnings"],
                                        league_roster_df=league_roster_df)
    return {
        "scored": scored,
        "recommended": package["lineup_df"],
        "missing_slots": list(package["missing_slots"]),
        "slot_warnings": list(package["slot_warnings"]),
        "diagnosis": diagnosis,
        "basis": "Season-to-date stats of this roster, scored relative to each other (0-1).",
    }


def explain_slot_eligibility(player_row: Any, slot: str) -> dict[str, Any]:
    """Why a player can or cannot fill a lineup slot, by the rule lineup saves enforce.

    Sources: ``fantasy_weekly_lineup.position_tokens_from_row`` / ``player_eligible_for_slot``
    (``fantasy_lineup_fill`` with ``fantasy_position_eligibility``).
    """
    from fantasy_weekly_lineup import player_eligible_for_slot, position_tokens_from_row

    row = player_row if isinstance(player_row, (pd.Series, dict)) else {}
    tokens = position_tokens_from_row(row)
    name = str((row.get("Player") if hasattr(row, "get") else "") or "")
    eligible = bool(player_eligible_for_slot(tokens, slot))
    positions = ", ".join(tokens) or "none on record"
    reason = (
        f"{name or 'This player'} can play {slot}: eligible at {positions}."
        if eligible
        else f"{name or 'This player'} can't play {slot}: eligible only at {positions}."
    )
    return {"player": name, "slot": str(slot), "eligible": eligible, "eligible_positions": tokens,
            "rule": ELIGIBILITY_RULE, "reason": reason}


def check_lineup(slots: list[str], assignments: dict[str, str], roster_df: pd.DataFrame) -> dict[str, Any]:
    """Would this lineup pass Save Lineup's checks? ``fantasy_weekly_lineup.validate_weekly_lineup``.

    Returns its dict: ok, missing_slots, ineligible_slots, duplicate_players, unfillable_slots,
    messages. (Week lock rules are separate: ``fantasy_season_ledger.save_period_lineup``.)
    """
    from fantasy_weekly_lineup import validate_weekly_lineup

    return validate_weekly_lineup(list(slots), dict(assignments), roster_df)
