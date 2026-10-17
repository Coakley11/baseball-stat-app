"""Typed API resources (pydantic v2). The OpenAPI document is generated from these models, so a
TypeScript client can be generated from it; there is no hand-written TypeScript copy.

Identity rules (docs/NEXTJS_API_CONTRACTS.md, "Identity"):
* players: Lahman ``playerID`` (e.g. ``judgeaa01``), never a display name;
* MLB teams: the franchise ``teamID`` the app normalizes to (``NYY``), with the season's historical
  display name alongside;
* leagues: ``league_context_id``; fantasy teams: the league's team key; scoring periods: the
  period number inside a league.

Business data only: numbers, identifiers, short plain-language copy the Python side already
writes (qualification captions, answer headlines). No HTML, no Streamlit markup, no session state.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

API_VERSION = "v1"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- shared

class ErrorBody(_Model):
    code: Literal[
        "player_not_found", "ambiguous_player", "invalid_metric", "invalid_date_range", "invalid_parameter",
        "no_active_league", "unauthorized_team", "missing_finalized_weeks", "data_unavailable",
        "not_found", "internal_error",
    ]
    message: str = Field(description="Plain-language, safe to show. Never a traceback or Streamlit text.")
    details: dict[str, object] | None = Field(default=None, description="Structured extras, e.g. candidates.")


class ErrorResponse(_Model):
    error: ErrorBody


class TeamRef(_Model):
    team_id: str = Field(description="Franchise teamID the app normalizes to, e.g. NYY.")
    name: str = Field(description="Franchise display name.")
    season_name: str | None = Field(default=None, description="Historical name for that season, e.g. Indians.")
    league: str | None = Field(default=None, description="AL / NL / Unknown for that season.")


class PlayerRef(_Model):
    player_id: str = Field(description="Canonical Lahman playerID. Stable across name changes.")
    name: str
    label: str = Field(description="Unique display label; adds the career span when names collide.")


class MetricInfo(_Model):
    key: str
    label: str
    kind: Literal["count", "rate", "score", "year"]
    higher_is_better: bool = True
    decimals: int = Field(description="Display precision the app uses (rates 3, counts 0, score 1).")


class Qualification(_Model):
    applies: bool = Field(description="True when a rate stat is ranked and a minimum AB is in force.")
    min_ab: int
    qualified_ab: int = Field(description="The qualifying AB for the range under the app's rule.")
    mode: Literal["auto", "manual"]
    text: str = Field(description="The same caption the app shows next to the ranking.")


class StatLine(_Model):
    G: float | None = None
    AB: float | None = None
    R: float | None = None
    H: float | None = None
    doubles: float | None = Field(default=None, alias="2B")
    triples: float | None = Field(default=None, alias="3B")
    HR: float | None = None
    RBI: float | None = None
    SB: float | None = None
    BB: float | None = None
    BA: float | None = None
    OBP: float | None = None
    SLG: float | None = None
    OPS: float | None = None
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, serialize_by_alias=True)


# ---------------------------------------------------------------- health

class HealthInfo(_Model):
    status: Literal["ok", "degraded"]
    api_version: str = API_VERSION
    build: str = Field(description="Short git commit of the running code, or 'unknown'.")
    data_loaded: bool
    seasons: list[int] | None = Field(default=None, description="[first, last] season in the loaded data.")


# ---------------------------------------------------------------- players

class PlayerSummary(_Model):
    player: PlayerRef
    first_season: int
    last_season: int
    career_primary_position: str | None = None
    bats: str | None = None
    throws: str | None = None
    last_team: TeamRef | None = None
    hall_of_fame: bool | None = None


class PlayerSearchResult(_Model):
    query: str
    results: list[PlayerSummary]
    truncated: bool


class PlayerSeason(_Model):
    year: int
    team: TeamRef | None
    position: str | None
    stats: StatLine


class PlayerSeasonsResult(_Model):
    player: PlayerSummary
    start: int
    end: int
    split_mode: Literal["team", "combined"] = Field(
        description="team: one row per season and team (split seasons stay separate); combined: one row per season.")
    seasons: list[PlayerSeason]


# ---------------------------------------------------------------- historical explorer / leaderboards

class SeasonRow(_Model):
    rank: int
    player: PlayerRef
    year: int
    team: TeamRef | None
    position: str | None
    bats: str | None = None
    stats: StatLine


class SeasonLeadersResult(_Model):
    """Historical Explorer: best single seasons for a range and stat."""
    start: int
    end: int
    metric: MetricInfo
    order: Literal["desc", "asc"]
    split_mode: Literal["team", "combined"]
    qualification: Qualification
    total_rows: int = Field(description="Seasons that pass the filters (before the limit).")
    rows: list[SeasonRow]
    headline: str | None = Field(default=None, description="The page's own answer headline for these rows.")


class LeaderboardRow(_Model):
    rank: int
    player: PlayerRef
    bats: str | None = None
    stats: StatLine
    score: float


class LeaderboardResult(_Model):
    """Leaderboards: totals over a span of seasons, ranked by one stat or the weighted score."""
    start: int
    end: int
    metric: MetricInfo
    weights: dict[str, float] = Field(description="Weights behind 'score' (rate stats count ×100).")
    qualification: Qualification
    total_rows: int
    rows: list[LeaderboardRow]


# ---------------------------------------------------------------- documented, not yet served (contracts only)

class CareerSummary(_Model):
    player: PlayerSummary
    seasons: int
    games: int
    stats: StatLine
    best_season: dict[str, object] | None = Field(default=None, description="Counting-stat best season, as the page names it.")


class ComparisonMetric(_Model):
    metric: MetricInfo
    values: dict[str, float | None] = Field(description="player_id -> value over the shared range.")
    leaders: list[str] = Field(description="player_id(s) leading at displayed precision (ties allowed).")


class ComparisonResult(_Model):
    players: list[PlayerRef]
    start: int
    end: int
    metrics: list[ComparisonMetric]
    headline: str = Field(description="Who leads where. Never an overall winner without a user-chosen weighting.")


class TrendPoint(_Model):
    year: int
    value: float | None
    at_bats: float | None = None


class TrendResult(_Model):
    player: PlayerRef
    metric: MetricInfo
    slope_per_season: float | None
    direction: Literal["up", "down", "flat"]
    points: list[TrendPoint]
    weighting: str = Field(description="How seasons are weighted (rate stats by playing time).")


class ValuationRow(_Model):
    rank: int
    player: PlayerRef
    valuation_score: float = Field(description="0-100 within the ranked list.")
    production_rank: int | None
    trend_rank: int | None
    production_points: float | None = Field(description="w_current·Perf_Pct/(w_current+w_trend)·100")
    trend_points: float | None = Field(description="w_trend·Trend_Pct/(w_current+w_trend)·100")


class ValuationResult(_Model):
    start: int
    end: int
    weights: dict[str, float]
    pool_size: int
    rows: list[ValuationRow]


class LeagueSummary(_Model):
    league_id: str = Field(description="league_context_id")
    name: str
    my_team: str | None
    teams: list[str]
    scoring_format: str
    lineup_slots: list[str]
    has_season_calendar: bool
    finalized_periods: list[int]


class StandingsRow(_Model):
    rank: int
    team: str
    points: float
    categories: dict[str, float | None]


class StandingsResult(_Model):
    league_id: str
    kind: Literal["official", "snapshot"]
    label: str
    basis: str
    periods_counted: list[int]
    rows: list[StandingsRow]


class LineupSlot(_Model):
    slot_key: str
    slot: str
    player: str | None
    eligible: bool | None


class LineupReport(_Model):
    league_id: str
    team: str
    period: int
    status: Literal["not_saved", "draft", "locked"]
    slots: list[LineupSlot]
    open_from_bench: list[str]
    open_needs_waiver: list[str]
    ineligible: list[str]


class TradeEvaluation(_Model):
    league_id: str
    team: str
    partner: str
    give: list[str]
    receive: list[str]
    verdict: Literal["Favors your team", "Balanced", "Favors the other team", "Creates roster issue"]
    value_difference: float = Field(description="Need-weighted category score difference (evaluate_trade).")
    category_changes: dict[str, float]
    roster_issues: list[str]
