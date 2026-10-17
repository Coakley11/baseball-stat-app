"""Read-only fantasy league tools over the shared interfaces (Phase C/D).

Every number comes from ``fantasy_read_api`` / ``fantasy_league_peek`` or the public season-ledger
read functions they are built on. Nothing here computes a fantasy statistic, writes the session,
fetches data or changes a league:

* league resolution runs on an isolated copy of the session (``fantasy_league_peek``);
* standings keep the API's ``kind`` / ``label`` — official (sum of finalized weeks) and the
  current-roster what-if are never mixed;
* team-perspective data (lineups, trades, a team's weaknesses as advice) requires
  ``team_access(...).can_manage`` — the owner, or the commissioner acting for an unclaimed team —
  and the team must actually be in the league;
* roster stats are only the ones a page already loaded (``loaded_roster_stats``).

There are deliberately no tools for Save Lineup, Use Suggested Lineup, waiver moves, trades or
finalizing a week. See docs/AMI_PHASE_D_RECONCILIATION.md for the interfaces still missing.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from ami_assistant.safety import clean_text
from ami_assistant.tools.registry import (
    BAD_ARGUMENT,
    MISSING_ACTIVE_LEAGUE,
    NOT_WIRED,
    UNKNOWN_PLAYER,
    ToolResult,
    fail,
    tool,
)
from player_name_normalization import normalize_player_name_for_merge

NO_ROSTER_STATS = "no_roster_stats"
NO_SEASON_CALENDAR = "no_season_calendar"
NOT_YOUR_TEAM = "not_your_team"
UNKNOWN_TEAM = "unknown_team"
LOAD_STATS_HINT = (
    "Current roster stats aren't loaded in this session. Open League Standings and load stats under "
    "“How current rosters would rank”, then ask again."
)
SLOT_NAMES = {"C": "catcher", "1B": "first base", "2B": "second base", "3B": "third base", "SS": "shortstop",
              "OF": "outfield", "DH": "utility (DH)", "UTIL": "utility", "P": "pitcher"}

# What a shared waiver reader would have to provide before AMI can answer waiver questions.
WAIVER_INTERFACE_NEEDED = (
    "fantasy_read_api.waiver_recommendations_view(session, team, position=None) returning the Waiver Wire's own "
    "ranked adds/drops (fantasy_waiver_wire.recommend_adds_personalized / recommend_drops_current on the page's "
    "waiver pool) with each card's reason, and loaded_player_pool(session) for the unrostered players the page loaded."
)


# --- helpers ----------------------------------------------------------------------------------


def _api():
    import fantasy_read_api

    return fantasy_read_api


def _context(session: Any) -> dict[str, Any] | None:
    from fantasy_league_peek import peek_active_league_context

    return peek_active_league_context(session)


def _no_league(tool_name: str) -> ToolResult:
    return fail(
        tool_name,
        MISSING_ACTIVE_LEAGUE,
        "You don't have an active league in this session. Pick one in Saved Draft Library (under My League), "
        "or draft one first.",
    )


def _num(value: Any) -> Any:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return clean_text(value, 80)
    if pd.isna(v):
        return None
    return int(v) if v.is_integer() else round(v, 4)


def _records(frame: pd.DataFrame, columns: list[str] | None = None, limit: int = 30) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    cols = [c for c in (columns or list(frame.columns)) if c in frame.columns]
    return [{c: _num(r[c]) if c not in ("Team", "Player", "Fantasy Team") else clean_text(r[c], 80) for c in cols}
            for _, r in frame.head(limit).iterrows()]


def access_payload(control: Any, team: str) -> dict[str, Any]:
    """How the user relates to ``team``, in words the answer can use verbatim."""
    mode = str(getattr(control, "mode", "none") or "none")
    if mode == "owner":
        text = f"{team} is your team."
    elif mode == "commissioner_proxy":
        text = f"You're viewing {team} as commissioner; the team is currently unclaimed."
    else:
        text = clean_text(getattr(control, "reason", ""), 160) or f"{team} is managed by someone else."
    return {"team": team, "mode": mode, "can_manage": bool(getattr(control, "can_manage", False)),
            "is_commissioner": bool(getattr(control, "is_commissioner", False)), "text": text}


def _resolve_team(session: Any, league: Any, team: str | None, tool_name: str) -> tuple[str, dict[str, Any], ToolResult | None]:
    """The league team a question is about (default: my team) and the user's access to it."""
    names = list(league.team_names)
    wanted = str(team or league.my_team or "").strip()
    if not wanted:
        return "", {}, fail(tool_name, UNKNOWN_TEAM, "This league doesn't say which team is yours yet. Claim your team "
                                                  "in Saved Draft Library or the league invite.")
    match = next((n for n in names if n.lower() == wanted.lower()), "")
    if not match:
        return "", {}, fail(tool_name, UNKNOWN_TEAM, f"There's no team called “{wanted}” in {league.league_name or 'this league'}.",
                            teams=names)
    access = access_payload(_api().team_access(session, match), match)
    return match, access, None


def _require_manage(access: dict[str, Any], tool_name: str) -> ToolResult | None:
    if access.get("can_manage"):
        return None
    return fail(tool_name, NOT_YOUR_TEAM, access["text"] + " AMI only shows lineups and team advice for a team you "
                "manage.", access=access)


def _team_frame(session: Any, team: str) -> tuple[pd.DataFrame, str]:
    frame, loaded_at = _api().loaded_roster_stats(session)
    if frame.empty or "Team" not in frame.columns:
        return pd.DataFrame(), loaded_at
    return frame[frame["Team"].astype(str) == team].copy(), loaded_at


def _scoring_format(league: Any) -> str:
    return str(getattr(league, "scoring_format", "") or "5x5 Roto")


def _find_row(frame: pd.DataFrame, player: str) -> pd.Series | None:
    """A roster row by full name, else by an unambiguous surname."""
    if frame is None or frame.empty or "Player" not in frame.columns:
        return None
    want = normalize_player_name_for_merge(player)
    norm = frame["Player"].map(normalize_player_name_for_merge)
    hit = frame[norm == want]
    if hit.empty and " " not in want:
        hit = frame[norm.str.split(" ").str[-1] == want]
    return hit.iloc[0] if len(hit) == 1 else None


def normalize_slot(slot: str) -> str:
    s = str(slot or "").strip().upper()
    return {"DH/UTIL": "UTIL", "SHORTSTOP": "SS", "CATCHER": "C"}.get(s, s)


def _period_info(context: dict[str, Any], number: int | None) -> dict[str, Any] | None:
    from fantasy_season_ledger import get_period, period_date_label, period_status

    period = get_period(context, int(number)) if number else None
    if not period:
        return None
    return {"number": int(period.get("number") or number), "label": clean_text(period.get("label") or f"Week {number}", 40),
            "dates": clean_text(period_date_label(period), 60), "status": period_status(period),
            "finalized": bool(str(period.get("finalized_at") or "").strip())}


def league_brief(session: Any) -> dict[str, Any] | None:
    """Small league context for AMI (also used by the page context line). Never writes."""
    league = _api().active_league(session)
    if league is None:
        return None
    from fantasy_season_ledger import current_period_number, ledger_initialized

    context = _context(session) or {}
    brief: dict[str, Any] = {
        "league_name": clean_text(league.league_name, 80),
        "my_team": clean_text(league.my_team, 80),
        "teams": [clean_text(t, 80) for t in league.team_names],
        "scoring_format": _scoring_format(league),
        "lineup_slots": list(league.lineup_slots),
        "has_season_calendar": bool(league.has_season_calendar),
        "finalized_weeks": list(league.finalized_weeks),
        "coherent": bool(league.coherent),
    }
    if league.my_team:
        brief["access"] = access_payload(_api().team_access(session, league.my_team), league.my_team)
    if ledger_initialized(context):
        brief["current_week"] = _period_info(context, current_period_number(context))
    return brief


# --- league -----------------------------------------------------------------------------------


@tool(
    "get_active_league",
    capability="fantasy_team",
    description="The league the fantasy pages show: name, your team and your access to it, teams, lineup slots, "
                "the current week and which weeks are final.",
    reuses=("fantasy_read_api.active_league", "fantasy_read_api.team_access", "fantasy_season_ledger"),
    needs_session=True,
)
def get_active_league(*, session: Mapping[str, Any]) -> ToolResult:
    brief = league_brief(session)
    if brief is None:
        return _no_league("get_active_league")
    return ToolResult(tool="get_active_league", ok=True, data=brief)


# --- standings --------------------------------------------------------------------------------


@tool(
    "get_official_standings",
    capability="fantasy_team",
    description="League Standings (official) — the sum of finalized weeks — with a team's place, gap to first, "
                "strongest categories and closest category gains (the same chips League Standings shows).",
    parameters={"properties": {"team": {"type": "string"}}},
    reuses=("fantasy_read_api.official_standings_view", "u1_answers.category_strengths_and_gaps",
            "fantasy_season_results.scoring_categories"),
    needs_session=True,
)
def get_official_standings(*, session: Mapping[str, Any], team: str | None = None) -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("get_official_standings")
    name, access, err = _resolve_team(session, league, team, "get_official_standings")
    if err:
        return err
    view = api.official_standings_view(session)
    data: dict[str, Any] = {"kind": view.kind, "label": view.label, "basis": view.basis, "note": view.note,
                            "finalized_weeks": list(view.finalized_weeks), "team": name, "access": access,
                            "league_name": clean_text(league.league_name, 80), "team_count": len(league.team_names)}
    table = view.table
    if table is None or table.empty:
        data["rows"] = []
        return ToolResult(tool="get_official_standings", ok=True, data=data)
    from fantasy_season_results import scoring_categories
    import u1_answers

    context = _context(session)
    categories = tuple(scoring_categories(context))
    data["categories"] = list(categories)
    data["rows"] = _records(table, ["Rank", "Team", "Total Points"])
    mine = table[table["Team"].astype(str) == name]
    if not mine.empty:
        me = mine.iloc[0]
        rank, points = int(me["Rank"]), float(me["Total Points"])
        leader_points = float(pd.to_numeric(table["Total Points"]).max())
        ahead = table[pd.to_numeric(table["Total Points"]) > points]
        data["position"] = {
            "rank": rank,
            "tied": int((table["Rank"] == rank).sum()) > 1,
            "points": _num(points),
            "behind_first": _num(leader_points - points),
            "next_team_up": (clean_text(ahead.sort_values("Total Points").iloc[0]["Team"], 80) if not ahead.empty else ""),
            "behind_next": (_num(float(ahead["Total Points"].min()) - points) if not ahead.empty else 0),
        }
        data["by_category"] = [
            {"category": c, "value": _num(me.get(c)), "points": _num(me.get(f"{c} Points"))} for c in categories
        ]
        # The exact phrases League Standings shows as chips; all opportunities, not just two.
        notes = u1_answers.category_strengths_and_gaps(table, name, categories, max_gaps=len(categories))
        data["strengths"] = list(notes["strengths"])
        data["opportunities"] = list(notes["opportunities"])
    return ToolResult(tool="get_official_standings", ok=True, data=data)


@tool(
    "get_current_roster_standings",
    capability="fantasy_team",
    description="How current rosters would rank (not official standings): today's rosters on season-to-date stats. "
                "Analysis only — never the league standings.",
    parameters={"properties": {"team": {"type": "string"}}},
    reuses=("fantasy_read_api.loaded_roster_stats", "fantasy_read_api.current_roster_standings_view"),
    needs_session=True,
)
def get_current_roster_standings(*, session: Mapping[str, Any], team: str | None = None) -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("get_current_roster_standings")
    name, access, err = _resolve_team(session, league, team, "get_current_roster_standings")
    if err:
        return err
    frame, loaded_at = api.loaded_roster_stats(session)
    if frame.empty:
        return fail("get_current_roster_standings", NO_ROSTER_STATS, LOAD_STATS_HINT)
    view = api.current_roster_standings_view(frame, _scoring_format(league))
    table = view.table
    data: dict[str, Any] = {"kind": view.kind, "label": view.label, "basis": view.basis, "note": view.note,
                            "loaded_at": clean_text(loaded_at, 40), "team": name, "access": access,
                            "rows": _records(table, ["League Rank", "Fantasy Team", "Total Roto Points"])}
    mine = table[table["Fantasy Team"].astype(str) == name] if "Fantasy Team" in table.columns else pd.DataFrame()
    if not mine.empty:
        rank = mine.iloc[0].get("League Rank")
        data["position"] = {"rank": _num(rank), "tied": int((table["League Rank"] == rank).sum()) > 1,
                            "points": _num(mine.iloc[0].get("Total Roto Points"))}
    return ToolResult(tool="get_current_roster_standings", ok=True, data=data)


# --- weeks ------------------------------------------------------------------------------------


def _week_number(context: dict[str, Any], week: Any, *, default: str) -> int | None:
    from fantasy_season_ledger import current_period_number, list_periods

    if week not in (None, ""):
        try:
            return int(week)
        except (TypeError, ValueError):
            return None
    if default == "current":
        return current_period_number(context)
    finals = [int(p["number"]) for p in list_periods(context) if str(p.get("finalized_at") or "").strip()]
    return max(finals) if finals else None


@tool(
    "get_week",
    capability="fantasy_team",
    description="One scoring week: dates and status (upcoming/active/locked/finalized), and once final, the week's "
                "category table and your team's totals. Default: the last finalized week.",
    parameters={"properties": {"week": {"type": "integer"}, "team": {"type": "string"},
                               "which": {"type": "string", "enum": ["last_final", "current"]}}},
    reuses=("fantasy_season_ledger.get_period/period_status", "fantasy_season_results.period_result",
            "fantasy_season_results.period_category_table"),
    needs_session=True,
)
def get_week(*, session: Mapping[str, Any], week: Any = None, team: str | None = None, which: str = "last_final") -> ToolResult:
    from fantasy_season_ledger import ledger_initialized, list_periods
    from fantasy_season_results import period_category_table, period_result

    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("get_week")
    context = _context(session) or {}
    if not ledger_initialized(context):
        return fail("get_week", NO_SEASON_CALENDAR, "This league has no season calendar yet, so there are no weeks. "
                    "The commissioner sets it on the Lineup page (“Set the season calendar”).")
    name, access, err = _resolve_team(session, league, team, "get_week")
    if err:
        return err
    number = _week_number(context, week, default=which)
    info = _period_info(context, number) if number else None
    if info is None:
        weeks = [int(p["number"]) for p in list_periods(context)]
        message = ("No week is final yet." if which == "last_final" and week in (None, "")
                   else f"There's no Week {week} in this league's calendar (weeks {min(weeks)}–{max(weeks)}).")
        return fail("get_week", BAD_ARGUMENT, message, weeks=weeks)
    data: dict[str, Any] = {"week": info, "team": name, "access": access}
    if info["finalized"]:
        table = period_category_table(context, info["number"])
        data["table"] = _records(table, ["Rank", "Team", "Total Points"])
        result = period_result(context, info["number"]) or {}
        team_result = (result.get("teams") or {}).get(name) or {}
        data["totals"] = {k: _num(v) for k, v in (team_result.get("totals") or {}).items() if k in ("AB", "H", "HR", "R", "RBI", "SB")}
        data["rates"] = {k: _num(v) for k, v in (team_result.get("rates") or {}).items()}
        data["lineup_missing"] = bool(team_result.get("lineup_missing"))
        mine = table[table["Team"].astype(str) == name] if not table.empty else pd.DataFrame()
        if not mine.empty:
            data["rank"] = int(mine.iloc[0]["Rank"])
            data["points"] = _num(mine.iloc[0]["Total Points"])
    return ToolResult(tool="get_week", ok=True, data=data)


@tool(
    "get_week_lineup",
    capability="fantasy_team",
    description="The lineup saved for a week (starters by slot, bench, empty slots) — the snapshot that week is scored from.",
    parameters={"properties": {"week": {"type": "integer"}, "team": {"type": "string"},
                               "which": {"type": "string", "enum": ["current", "last_final"]}}},
    reuses=("fantasy_season_ledger.get_period_lineup",),
    needs_session=True,
)
def get_week_lineup(*, session: Mapping[str, Any], week: Any = None, team: str | None = None,
                    which: str = "current") -> ToolResult:
    from fantasy_season_ledger import get_period_lineup, ledger_initialized

    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("get_week_lineup")
    context = _context(session) or {}
    if not ledger_initialized(context):
        return fail("get_week_lineup", NO_SEASON_CALENDAR, "This league has no season calendar yet, so weekly lineups "
                    "aren't stored by week.")
    name, access, err = _resolve_team(session, league, team, "get_week_lineup")
    if err:
        return err
    number = _week_number(context, week, default=which)
    info = _period_info(context, number) if number else None
    if info is None:
        message = ("No week is final yet." if which == "last_final" and week in (None, "")
                   else f"There's no Week {week} in this league's calendar.")
        return fail("get_week_lineup", BAD_ARGUMENT, message)
    # Another team's lineup is private until its week has started.
    if not access["can_manage"] and info["status"] == "upcoming":
        return fail("get_week_lineup", NOT_YOUR_TEAM, f"{name}'s {info['label']} lineup stays private until the week starts.")
    snap = get_period_lineup(context, info["number"], name)
    data: dict[str, Any] = {"week": info, "team": name, "access": access, "saved": bool(snap)}
    if snap:
        data["starters"] = [{"slot": clean_text(s.get("slot"), 10), "player": clean_text(s.get("player_name"), 80),
                             "eligible_positions": [clean_text(p, 6) for p in s.get("eligible_positions") or []]}
                            for s in snap.get("starters") or []]
        data["bench"] = [clean_text(b.get("player_name") if isinstance(b, Mapping) else b, 80) for b in snap.get("bench") or []]
        data["empty_slots"] = [clean_text(e if not isinstance(e, Mapping) else e.get("slot"), 10) for e in snap.get("empty_slots") or []]
        data["set_after_lock"] = bool(snap.get("set_after_lock"))
    return ToolResult(tool="get_week_lineup", ok=True, data=data)


@tool(
    "explain_player_week",
    capability="fantasy_team",
    description="Why a player did or didn't count for your team in a finalized week, from that week's lineup "
                "snapshot and scored result.",
    parameters={"properties": {"player": {"type": "string"}, "week": {"type": "integer"}, "team": {"type": "string"}},
                "required": ["player"]},
    reuses=("fantasy_season_ledger.get_period_lineup", "fantasy_season_results.period_result"),
    needs_session=True,
)
def explain_player_week(*, session: Mapping[str, Any], player: str, week: Any = None, team: str | None = None) -> ToolResult:
    from fantasy_season_ledger import get_period_lineup, ledger_initialized
    from fantasy_season_results import period_result

    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("explain_player_week")
    context = _context(session) or {}
    if not ledger_initialized(context):
        return fail("explain_player_week", NO_SEASON_CALENDAR, "This league has no season calendar yet, so no week is scored.")
    name, access, err = _resolve_team(session, league, team, "explain_player_week")
    if err:
        return err
    denied = _require_manage(access, "explain_player_week")
    if denied:
        return denied
    number = _week_number(context, week, default="last_final")
    info = _period_info(context, number) if number else None
    if info is None:
        return fail("explain_player_week", BAD_ARGUMENT, "No week is final yet." if week in (None, "") else f"There's no Week {week}.")
    want = normalize_player_name_for_merge(player)

    def same(n: Any) -> bool:
        cand = normalize_player_name_for_merge(n)
        return cand == want or (" " not in want and cand.split(" ")[-1:] == [want])

    # The roster's spelling of the name, and who owns the player today (league_rosters is the source of truth;
    # same name keys as fantasy_league_context.build_ownership_map — a shared player_owner reader is still missing).
    owners = {str(p.get("player_name") or p.get("Player") or p.get("fullName") or p.get("name") or ""): str(t)
              for t, entry in (context.get("league_rosters") or {}).items()
              for p in (entry or {}).get("players") or [] if isinstance(p, Mapping)}
    canonical = next((n for n in owners if n and same(n)), "")
    data: dict[str, Any] = {"week": info, "team": name, "player": clean_text(canonical or player, 80),
                            "owner_now": clean_text(owners.get(canonical, ""), 80), "on_a_roster": bool(canonical)}
    if not info["finalized"]:
        data["reason"] = "not_final"
        return ToolResult(tool="explain_player_week", ok=True, data=data)
    snap = get_period_lineup(context, info["number"], name) or {}
    result = ((period_result(context, info["number"]) or {}).get("teams") or {}).get(name) or {}
    starter = next((s for s in result.get("starters") or [] if same(s.get("player_name"))), None)
    if starter is not None:
        matched = str(starter.get("matched_by") or "").strip()
        data.update(reason="counted" if matched else "no_stats", slot=clean_text(starter.get("slot"), 10),
                    stats={k: _num(starter.get(k)) for k in ("AB", "H", "HR", "R", "RBI", "SB")})
    elif any(same(b.get("player_name") if isinstance(b, Mapping) else b) for b in snap.get("bench") or []):
        data["reason"] = "bench"
    elif result.get("lineup_missing") or not snap:
        data["reason"] = "no_lineup"
    else:
        data["reason"] = "not_in_lineup"
    return ToolResult(tool="explain_player_week", ok=True, data=data)


# --- lineups and eligibility ------------------------------------------------------------------


def _bench(frame: Any, rec: Any) -> list[str]:
    """Rostered players the recommendation leaves out (not the saved lineup's bench)."""
    if "Player" not in getattr(frame, "columns", ()):
        return []
    starters = set(rec["Player"].astype(str)) if "Player" in getattr(rec, "columns", ()) else set()
    return [clean_text(p, 80) for p in frame["Player"].astype(str) if p not in starters]


@tool(
    "get_lineup_report",
    capability="fantasy_team",
    description="The lineup report (Lineup & Trades page) for a team you manage: recommended starters by slot (Save Lineup's slot "
                "rule), slots the roster can't fill, warnings, and the diagnosis (strongest/weakest areas).",
    parameters={"properties": {"team": {"type": "string"}}},
    reuses=("fantasy_read_api.lineup_report", "fantasy_read_api.loaded_roster_stats"),
    needs_session=True,
)
def get_lineup_report(*, session: Mapping[str, Any], team: str | None = None) -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("get_lineup_report")
    name, access, err = _resolve_team(session, league, team, "get_lineup_report")
    if err:
        return err
    denied = _require_manage(access, "get_lineup_report")
    if denied:
        return denied
    frame, loaded_at = _team_frame(session, name)
    if frame.empty:
        return fail("get_lineup_report", NO_ROSTER_STATS, LOAD_STATS_HINT)
    slots = list(league.lineup_slots) or None
    report = api.lineup_report(frame, slots=slots, scoring_format=_scoring_format(league))
    rec = report["recommended"]
    diag = report.get("diagnosis") or {}
    data = {
        "team": name, "access": access, "slots": slots or [], "loaded_at": clean_text(loaded_at, 40),
        "recommended": [{"slot": clean_text(r.get("Fantasy slot"), 10), "player": clean_text(r.get("Player"), 80),
                         "call": clean_text(r.get("Start/Sit Recommendation"), 20)} for _, r in rec.iterrows()],
        "bench": _bench(frame, rec),
        "missing_slots": [clean_text(s, 10) for s in report["missing_slots"]],
        "slot_warnings": [clean_text(w, 200) for w in report["slot_warnings"]],
        "strongest": clean_text(diag.get("strongest"), 120) if not isinstance(diag.get("strongest"), list)
        else [clean_text(x, 40) for x in diag.get("strongest")],
        "weakest": clean_text(diag.get("weakest"), 120) if not isinstance(diag.get("weakest"), list)
        else [clean_text(x, 40) for x in diag.get("weakest")],
        "basis": report.get("basis", ""),
    }
    return ToolResult(tool="get_lineup_report", ok=True, data=data)


@tool(
    "check_slot_eligibility",
    capability="fantasy_team",
    description="Can a rostered player fill a lineup slot? Uses the exact rule Save Lineup enforces (his eligible "
                "positions; no assumed 1B/3B or 2B/SS swaps).",
    parameters={"properties": {"player": {"type": "string"}, "slot": {"type": "string"}}, "required": ["player", "slot"]},
    reuses=("fantasy_read_api.explain_slot_eligibility", "fantasy_read_api.loaded_roster_stats"),
    needs_session=True,
)
def check_slot_eligibility(*, session: Mapping[str, Any], player: str, slot: str) -> ToolResult:
    api = _api()
    if api.active_league(session) is None:
        return _no_league("check_slot_eligibility")
    frame, _loaded = api.loaded_roster_stats(session)
    if frame.empty:
        return fail("check_slot_eligibility", NO_ROSTER_STATS, LOAD_STATS_HINT)
    row = _find_row(frame, player)
    if row is None:
        return fail("check_slot_eligibility", UNKNOWN_PLAYER,
                    f"“{player}” isn't on a roster in this league (or the name matches more than one player).")
    result = api.explain_slot_eligibility(row, normalize_slot(slot))
    result = {k: (clean_text(v, 240) if isinstance(v, str) else v) for k, v in result.items()}
    result["team"] = clean_text(row.get("Team"), 80)
    return ToolResult(tool="check_slot_eligibility", ok=True, data=result)


@tool(
    "find_eligible_players",
    capability="fantasy_team",
    description="Which players on your roster can fill a slot (Save Lineup's rule), split into this week's starters "
                "and bench when a lineup is saved.",
    parameters={"properties": {"slot": {"type": "string"}, "team": {"type": "string"}, "bench_only": {"type": "boolean"}},
                "required": ["slot"]},
    reuses=("fantasy_read_api.explain_slot_eligibility", "fantasy_season_ledger.get_period_lineup"),
    needs_session=True,
)
def find_eligible_players(*, session: Mapping[str, Any], slot: str, team: str | None = None, bench_only: bool = False) -> ToolResult:
    from fantasy_season_ledger import current_period_number, get_period_lineup, ledger_initialized

    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("find_eligible_players")
    name, access, err = _resolve_team(session, league, team, "find_eligible_players")
    if err:
        return err
    denied = _require_manage(access, "find_eligible_players")
    if denied:
        return denied
    frame, _loaded = _team_frame(session, name)
    if frame.empty:
        return fail("find_eligible_players", NO_ROSTER_STATS, LOAD_STATS_HINT)
    slot = normalize_slot(slot)
    context = _context(session) or {}
    starters: set[str] = set()
    week = None
    if ledger_initialized(context):
        number = current_period_number(context)
        snap = get_period_lineup(context, number, name) if number else None
        if snap:
            week = _period_info(context, number)
            starters = {normalize_player_name_for_merge(s.get("player_name")) for s in snap.get("starters") or []}
    eligible, ineligible = [], []
    for _, row in frame.iterrows():
        res = api.explain_slot_eligibility(row, slot)
        entry = {"player": clean_text(row.get("Player"), 80), "eligible_positions": res["eligible_positions"],
                 "starting": normalize_player_name_for_merge(row.get("Player")) in starters}
        (eligible if res["eligible"] else ineligible).append(entry)
    if bench_only and week is not None:
        eligible = [e for e in eligible if not e["starting"]]
    return ToolResult(tool="find_eligible_players", ok=True, data={
        "team": name, "access": access, "slot": slot, "slot_name": SLOT_NAMES.get(slot, slot), "week": week,
        "bench_only": bool(bench_only), "lineup_saved": week is not None, "eligible": eligible,
        "rule": api.ELIGIBILITY_RULE})


# --- trades -----------------------------------------------------------------------------------


@tool(
    "evaluate_trade",
    capability="fantasy_team",
    description="What a trade would do for a team you manage: category value, verdict, proposal rule checks and "
                "roster/lineup warnings (e.g. no catcher left). Read-only — it never proposes or executes.",
    parameters={"properties": {"give": {"type": "array", "items": {"type": "string"}},
                               "receive": {"type": "array", "items": {"type": "string"}},
                               "partner": {"type": "string"}, "team": {"type": "string"}, "slot": {"type": "string"}},
                "required": ["give", "receive"]},
    reuses=("fantasy_read_api.evaluate_trade_for_team", "fantasy_read_api.explain_slot_eligibility"),
    needs_session=True,
)
def evaluate_trade(*, session: Mapping[str, Any], give: list[str], receive: list[str], partner: str | None = None,
                   team: str | None = None, slot: str | None = None) -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("evaluate_trade")
    name, access, err = _resolve_team(session, league, team, "evaluate_trade")
    if err:
        return err
    frame, _loaded = api.loaded_roster_stats(session)
    if frame.empty:
        return fail("evaluate_trade", NO_ROSTER_STATS, LOAD_STATS_HINT)
    give_rows = [_find_row(frame, p) for p in give or []]
    recv_rows = [_find_row(frame, p) for p in receive or []]
    missing = [p for p, r in zip(list(give or []) + list(receive or []), give_rows + recv_rows) if r is None]
    if missing or not give_rows or not recv_rows:
        return fail("evaluate_trade", UNKNOWN_PLAYER, "I couldn't match "
                    + (", ".join(f"“{m}”" for m in missing) if missing else "the players")
                    + " to a roster in this league. Name the players on each side.")
    give_names = [str(r["Player"]) for r in give_rows]
    recv_names = [str(r["Player"]) for r in recv_rows]
    owners = {str(r["Team"]) for r in recv_rows}
    partner_team = str(partner or (owners.pop() if len(owners) == 1 else "")).strip()
    if not partner_team:
        return fail("evaluate_trade", BAD_ARGUMENT, "The players you'd receive are on different teams; which team is the trade with?")
    ev = api.evaluate_trade_for_team(session, my_team=name, partner_team=partner_team, give=give_names,
                                     receive=recv_names, roster_stats=frame, scoring_format=_scoring_format(league))
    if not ev.allowed:
        return fail("evaluate_trade", NOT_YOUR_TEAM, ev.reason or access["text"], access=access)
    data: dict[str, Any] = {
        "team": name, "partner": partner_team, "give": give_names, "receive": recv_names, "access": access,
        "acting_as": ev.acting_as, "verdict": clean_text(ev.verdict, 40), "verdict_text": clean_text(ev.verdict_text, 400),
        "weighted_gain": _num(ev.weighted_gain), "category_table": _records(ev.category_table),
        "proposal_ok": bool(ev.proposal_ok), "proposal_message": clean_text(ev.proposal_message, 200),
        "legality_warnings": [clean_text(w, 240) for w in ev.legality_warnings], "basis": ev.basis,
    }
    if slot:
        # Who could still fill the slot afterwards, by Save Lineup's rule.
        slot = normalize_slot(slot)
        mine = frame[frame["Team"].astype(str) == name]
        after = pd.concat([mine[~mine["Player"].isin(give_names)], frame[frame["Player"].isin(recv_names)]])
        data["slot_check"] = {"slot": slot, "slot_name": SLOT_NAMES.get(slot, slot), "eligible_after": [
            clean_text(r["Player"], 80) for _, r in after.iterrows() if api.explain_slot_eligibility(r, slot)["eligible"]]}
    return ToolResult(tool="evaluate_trade", ok=True, data=data)


# --- waivers (not wired: no shared reader yet) ------------------------------------------------


@tool(
    "get_waiver_recommendations",
    capability="fantasy_team",
    description="Waiver Wire recommendations (needs a shared waiver reader; not wired yet).",
    parameters={"properties": {"position": {"type": "string"}}},
    needs_session=True,
    wired=False,
)
def get_waiver_recommendations(*, session: Mapping[str, Any], position: str | None = None) -> ToolResult:
    return fail(
        "get_waiver_recommendations",
        NOT_WIRED,
        "AMI can't read the Waiver Wire's recommendations yet — there's no shared read-only waiver interface. "
        "Open Waiver Wire: it leads with your biggest need and the top adds, each with its reason.",
        needs=WAIVER_INTERFACE_NEEDED,
        page="Waiver Wire / Add-Drop Center",
    )
