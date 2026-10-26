"""OpenAPI 3.1 document for the read-only API, generated from the pydantic models in
``baseball_api.schemas`` (the single source of truth: TypeScript types are generated from this
document, never written by hand). Contract-only resources (career, comparison, trends, valuation,
leagues, standings, lineup, trade evaluation) are included as component schemas so a client can
be generated ahead of the endpoints."""

from __future__ import annotations

import inspect
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from baseball_api import schemas as s

REF = "#/components/schemas/{model}"


def _q(name: str, kind: str, desc: str, *, required: bool = False, enum: list[str] | None = None,
       default: Any = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": kind}
    if enum:
        schema["enum"] = enum
    if default is not None:
        schema["default"] = default
    return {"name": name, "in": "query", "required": required, "description": desc, "schema": schema}


_RETRY_AFTER = {"Retry-After": {"description": "Seconds to wait. Sent while the data is still loading "
                                               "(error.details.retry_after); absent when the data is missing.",
                                "schema": {"type": "integer"}}}


def _ok(model: type[BaseModel], summary: str, params: list[dict[str, Any]], errors: tuple[int, ...] = (422, 503),
        *, csv: str | None = None) -> dict[str, Any]:
    content: dict[str, Any] = {"application/json": {"schema": {"$ref": REF.format(model=model.__name__)}}}
    if csv:
        content["text/csv"] = {"schema": {"type": "string", "description": csv}}
    responses: dict[str, Any] = {"200": {"description": "OK", "content": content}}
    for code in errors + (500,):
        responses[str(code)] = {"description": "Error", "content": {"application/json": {"schema": {"$ref": REF.format(model="ErrorResponse")}}}}
        if code == 503:
            responses[str(code)]["headers"] = _RETRY_AFTER
    return {"get": {"summary": summary, "parameters": params, "responses": responses}}


_YEARS = [_q("start", "integer", "First season (inclusive)."), _q("end", "integer", "Last season (inclusive).")]
_QUAL = [_q("min_ab", "integer", "Minimum AB. Setting it switches qualification to manual."),
         _q("qualified", "boolean", "Apply the qualified AB to rate-stat rankings (the app's default).", default=True),
         {"name": "min_{STAT}", "in": "query", "required": False,
          "description": "Stat minimums, e.g. min_HR=20, min_OPS=0.8 (R H 2B 3B HR RBI SB BB BA OBP SLG OPS; "
                         "catalog minimum_columns). The AB minimum is min_ab.",
          "schema": {"type": "number"}}]
_PAGE = [_q("limit", "integer", "JSON: 1-200, default 25. CSV: optional, every row when omitted."),
         _q("offset", "integer", "0-based position of the first row (paging). Ranks stay absolute.", default=0),
         _q("format", "string", "csv: the page's CSV export (same columns and rounding) for the same query.",
            enum=["json", "csv"], default="json")]


def build_openapi() -> dict[str, Any]:
    models = [m for _n, m in inspect.getmembers(s, inspect.isclass) if issubclass(m, BaseModel) and m.__module__ == s.__name__
              and not m.__name__.startswith("_")]
    _keys, defs = models_json_schema([(m, "serialization") for m in models], ref_template=REF)
    paths = {
        "/api/v1/health": _ok(s.HealthInfo, "Service health and version", [], errors=()),
        "/api/v1/catalog": _ok(s.Catalog, "Control options, labels and defaults for the Historical Explorer and Leaderboards",
                               [], errors=(503,)),
        "/api/v1/players/{player_id}": _ok(s.PlayerSummary, "One player's summary", [
            {"name": "player_id", "in": "path", "required": True, "schema": {"type": "string"}, "description": "Lahman playerID."}],
            errors=(404, 503)),
        "/api/v1/players/search": _ok(s.PlayerSearchResult, "Find players by name (the app's player-picker matching)", [
            _q("q", "string", "At least 2 characters.", required=True), _q("limit", "integer", "1–200, default 10.")]),
        "/api/v1/players/resolve": _ok(s.PlayerSummary, "One player by exact name; 409 ambiguous_player lists candidates", [
            _q("name", "string", "Exact name or disambiguated label.", required=True)], errors=(404, 409, 503)),
        "/api/v1/players/{player_id}/seasons": _ok(s.PlayerSeasonsResult, "A player's seasons (Historical Explorer rows)", [
            {"name": "player_id", "in": "path", "required": True, "schema": {"type": "string"}, "description": "Lahman playerID."},
            *_YEARS, _q("split", "string", "team: split seasons stay separate; combined: one row per season.", enum=["team", "combined"], default="team")],
            errors=(404, 422, 503)),
        "/api/v1/seasons": _ok(s.SeasonLeadersResult, "Historical Explorer: best single seasons (or one player's, ranked)", [
            *_YEARS, _q("metric", "string", "Sort stat (catalog historical.metrics, or yearID).", default="HR"),
            _q("order", "string", "", enum=["desc", "asc"], default="desc"), *_PAGE, _q("bats", "string", "Comma list: L,R,B."),
            _q("positions", "string", "Comma list, e.g. SS,2B."), _q("position_source", "string", "", enum=["season", "career"], default="season"),
            _q("teams", "string", "Comma list of catalog historical.filters.teams values."),
            _q("combine", "boolean", "Combine split-team seasons into one row.", default=False), *_QUAL,
            _q("player_id", "string", "Only this player's seasons: the same query, rows limited to the player. "
                                      "Without start/end the range is the player's career."),
            _q("include_below_minimum", "boolean", "With player_id: also return the player's seasons below the minimums "
                                                   "(meets_minimum false, rank null), after the ranked ones. Never in CSV.",
               default=False)],
            csv="historical_explorer.csv: Year, Player, Bats, Primary Position, Team, R ... OPS"),
        "/api/v1/leaderboards": _ok(s.LeaderboardResult, "Leaderboards: totals over a span, ranked", [
            *_YEARS, _q("metric", "string", "Sort stat or 'score'.", default="score"), *_PAGE,
            _q("weights", "string", "Score weights, e.g. HR:1,RBI:1,SB:1 (the default)."), *_QUAL],
            csv="leaderboards.csv: Player, Bats, R ... OPS, Score (the page exports its Top N: pass limit)"),
    }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Baseball Explorer API", "version": s.API_VERSION,
                 "description": "Read-only historical analytics. Python is authoritative for every number; "
                                "see docs/NEXTJS_API_CONTRACTS.md."},
        "paths": paths,
        "components": {"schemas": defs.get("$defs", {})},
    }
