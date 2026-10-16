"""Fantasy team intelligence — contracts declared, not wired until Phase C lands.

The fantasy roster / lineup / waiver / trade / standings model is being stabilized on the
``quality/rest-of-app`` branch (Phase C, see docs/FANTASY_LEAGUE_DATA_MODEL.md there). These
tools return ``not_wired`` so AMI can say so plainly instead of guessing from session
leftovers. When Phase C is accepted, each one wraps the canonical read function named in
``PHASE_C_DEPENDENCIES`` and enforces the same team/league visibility as the UI.
"""

from __future__ import annotations

from typing import Any, Mapping

from ami_assistant.tools.registry import NOT_WIRED, ToolResult, fail, tool

PHASE_C_DEPENDENCIES: dict[str, dict[str, Any]] = {
    "get_active_league": {
        "page": "Saved Draft Library",
        "returns": "league id/name, my team, team count, scoring format, lineup format",
        "needs": "the accepted active-league resolver (resolved_fantasy_context / fantasy_league_context)",
    },
    "get_team_roster": {
        "page": "Fantasy Lineup Assistant",
        "returns": "my roster with positions and eligibility",
        "needs": "the canonical league roster store and position eligibility (fantasy_position_sync)",
    },
    "get_lineup": {
        "page": "Fantasy Lineup Assistant",
        "returns": "starters by slot, bench, empty slots",
        "needs": "the weekly lineup model (fantasy_weekly_lineup / fantasy_lineup_fill)",
    },
    "get_standings": {
        "page": "Fantasy Standings Tracker",
        "returns": "category ranks/points per team, my weakest categories",
        "needs": "the roto scoring with tie splitting and team rates (Phase C4)",
    },
    "get_available_free_agents": {
        "page": "Waiver Wire / Add-Drop Center",
        "returns": "waiver pool by position with roster-aware recommendations",
        "needs": "the roster-aware waiver recommendations (Phase C2)",
    },
    "evaluate_trade": {
        "page": "Fantasy Lineup Assistant → Trade Center",
        "returns": "category impact for both teams plus roster/lineup legality",
        "needs": "trade evaluation plus fantasy_trade_legality (Phase C3)",
    },
}


def _not_wired(name: str) -> ToolResult:
    dep = PHASE_C_DEPENDENCIES[name]
    return fail(
        name,
        NOT_WIRED,
        f"AMI can't read your {dep['returns']} yet — that connection is waiting on the fantasy league "
        f"model now being finished. You can see it on {dep['page']}.",
        page=dep["page"],
    )


@tool("get_active_league", capability="fantasy_team", description="Active league summary (Phase C).", needs_session=True, wired=False)
def get_active_league(*, session: Mapping[str, Any]) -> ToolResult:
    return _not_wired("get_active_league")


@tool("get_team_roster", capability="fantasy_team", description="My fantasy roster (Phase C).", needs_session=True, wired=False)
def get_team_roster(*, session: Mapping[str, Any]) -> ToolResult:
    return _not_wired("get_team_roster")


@tool("get_lineup", capability="fantasy_team", description="My starters and bench (Phase C).", needs_session=True, wired=False)
def get_lineup(*, session: Mapping[str, Any]) -> ToolResult:
    return _not_wired("get_lineup")


@tool("get_standings", capability="fantasy_team", description="League standings by category (Phase C).", needs_session=True, wired=False)
def get_standings(*, session: Mapping[str, Any]) -> ToolResult:
    return _not_wired("get_standings")


@tool(
    "get_available_free_agents",
    capability="fantasy_team",
    description="Waiver pool for a position (Phase C).",
    parameters={"properties": {"position": {"type": "string"}}},
    needs_session=True,
    wired=False,
)
def get_available_free_agents(*, session: Mapping[str, Any], position: str | None = None) -> ToolResult:
    return _not_wired("get_available_free_agents")


@tool(
    "evaluate_trade",
    capability="fantasy_team",
    description="Evaluate a proposed trade read-only (Phase C).",
    parameters={"properties": {"give": {"type": "array"}, "receive": {"type": "array"}}},
    needs_session=True,
    wired=False,
)
def evaluate_trade(*, session: Mapping[str, Any], give: Any = None, receive: Any = None) -> ToolResult:
    return _not_wired("evaluate_trade")
