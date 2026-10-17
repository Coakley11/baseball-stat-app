"""Read-only historical analytics service: request parameters → the app's own functions → typed
results. No HTTP, no Streamlit, no session state, no persistence.

Every number comes from the same functions the Streamlit pages call:
* data: ``baseball_history.load_history_frames`` (the app's ``load_data``);
* Historical Explorer rows: ``baseball_history.historical_rows`` + ``apply_stat_minimums``;
* Leaderboards: ``leaderboard_aggregation`` + ``baseball_history.add_leaderboard_score``;
* qualification: ``rate_stat_qualification`` (same auto/manual rule and caption);
* player labels and search: ``baseball_history.build_clean_player_label_map`` and
  ``draft_player_names.search_draft_pool_names`` (the app's player pickers);
* answer headlines: ``u1_answers.season_answer``.
"""

from __future__ import annotations

import functools
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

import baseball_history as bh
import rate_stat_qualification as rsq
from baseball_api import schemas as s
from baseball_api.errors import ApiError

ROOT = Path(__file__).resolve().parents[1]
STAT_KEYS = ("G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS")
COUNTING = ("G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "BB")
SEASON_METRICS = ("R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS", "yearID")  # Historical Explorer "Sort by"
LEADERBOARD_METRICS = ("score", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS")  # Leaderboards "Sort by"
WEIGHT_STATS = ("R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS")
DEFAULT_WEIGHTS = {"HR": 1.0, "RBI": 1.0, "SB": 1.0}  # the page's defaults
MAX_LIMIT = 200
MIN_QUERY = 2
_LABELS = {"BA": "AVG", "yearID": "Year", "score": "Score"}


@dataclass(frozen=True)
class HistoryData:
    batting: pd.DataFrame
    yearly: pd.DataFrame
    people: pd.DataFrame
    season_lengths: dict[int, int]
    labels: dict[str, str]  # label -> playerID
    label_by_id: dict[str, str]
    label_tuple: tuple[str, ...]
    years: tuple[int, int]
    load_seconds: float


class HistoryStore:
    """Loads the Lahman frames once per process (the API's equivalent of the app's cache)."""

    def __init__(self, base_dir: Path = ROOT):
        self._base_dir = Path(base_dir)
        self._lock = threading.Lock()
        self._data: HistoryData | None = None

    @property
    def loaded(self) -> bool:
        return self._data is not None

    def get(self) -> HistoryData:
        if self._data is None:
            with self._lock:
                if self._data is None:
                    t0 = time.perf_counter()
                    try:
                        batting, yearly, people = bh.load_history_frames(self._base_dir)
                    except bh.HistoryDataMissing as exc:
                        raise ApiError("data_unavailable", "Historical data is not available on this server.") from exc
                    labels = bh.build_clean_player_label_map(yearly)
                    years = pd.to_numeric(yearly["yearID"], errors="coerce").dropna().astype(int)
                    self._data = HistoryData(
                        batting=batting, yearly=yearly, people=people,
                        season_lengths=rsq.season_lengths(yearly),
                        labels=labels, label_by_id={pid: label for label, pid in labels.items()}, label_tuple=tuple(labels),
                        years=(int(years.min()), int(years.max())), load_seconds=round(time.perf_counter() - t0, 3),
                    )
        return self._data


STORE = HistoryStore()


# ---------------------------------------------------------------- helpers

def _num(v: Any) -> float | None:
    x = pd.to_numeric(v, errors="coerce")
    return None if pd.isna(x) else float(x)


def _metric(key: str) -> s.MetricInfo:
    if key == "score":
        return s.MetricInfo(key="score", label="Score", kind="score", decimals=1)
    if key == "yearID":
        return s.MetricInfo(key="yearID", label="Year", kind="year", decimals=0)
    rate = key in bh.RATE_STATS
    return s.MetricInfo(key=key, label=_LABELS.get(key, key), kind="rate" if rate else "count", decimals=3 if rate else 0)


def _stats(row: Mapping[str, Any]) -> s.StatLine:
    vals = {}
    for k in STAT_KEYS:
        v = _num(row.get(k))
        if v is not None and k in bh.RATE_STATS:
            v = round(v, 3)
        vals[k] = v
    return s.StatLine.model_validate(vals)


def _team(team_id: Any, season_name: Any = None, league: Any = None) -> s.TeamRef | None:
    tid = str(team_id or "").strip()
    if not tid or tid.lower() == "nan":
        return None
    name = bh.team_id_to_name.get(tid, tid)
    sn = str(season_name or "").strip()
    return s.TeamRef(team_id=tid, name=name, season_name=sn if sn and sn.lower() != "nan" else None,
                     league=str(league) if league is not None and str(league) != "nan" else None)


def _player_ref(data: HistoryData, player_id: str, name: str = "") -> s.PlayerRef:
    label = data.label_by_id.get(player_id) or name or player_id
    return s.PlayerRef(player_id=player_id, name=name or label.split(" (")[0], label=label)


def _years(data: HistoryData, start: int | None, end: int | None, default: tuple[int, int]) -> tuple[int, int]:
    lo, hi = data.years
    a = default[0] if start is None else int(start)
    b = default[1] if end is None else int(end)
    if a > b:
        raise ApiError("invalid_date_range", f"start ({a}) is after end ({b}).")
    if b < lo or a > hi:
        raise ApiError("invalid_date_range", f"Seasons {a}–{b} are outside the data ({lo}–{hi}).",
                       details={"available": [lo, hi]})
    return max(a, lo), min(b, hi)


def _limit(limit: int | None, default: int = 25) -> int:
    n = default if limit is None else int(limit)
    if not 1 <= n <= MAX_LIMIT:
        raise ApiError("invalid_parameter", f"limit must be between 1 and {MAX_LIMIT}.")
    return n


def _qualification(data: HistoryData, metric: str, years: tuple[int, int], *, span: bool,
                   min_ab: int | None, qualified: bool) -> tuple[s.Qualification, int]:
    """The page's rule: automatic mode puts the qualified AB on rate-stat rankings (0 otherwise);
    a Min AB the user set (manual) is kept as is."""
    info = rsq.qualified_ab(data.season_lengths, years, span=span)
    prefix = "api"
    session: dict[str, Any] = {}
    if min_ab is not None or not qualified:
        rsq.mark_manual(session, prefix)
        session[rsq.ab_min_key(prefix)] = int(min_ab or 0)
    state = rsq.resolve_ab_minimum(session, prefix, metric, info["value"])
    text = rsq.qualification_caption(state, info, metric) if state["rate"] else ""
    q = s.Qualification(applies=bool(state["rate"] and state["value"] > 0), min_ab=int(state["value"]),
                        qualified_ab=int(state["qualified"]), mode=state["mode"], text=text)
    return q, int(state["value"])


def _mins(min_ab: int, extra: Mapping[str, float] | None) -> dict[str, float]:
    mins = {k: 0 for k in bh.STAT_MINIMUM_COLUMNS}
    mins["AB"] = min_ab
    for k, v in (extra or {}).items():
        if k not in bh.STAT_MINIMUM_COLUMNS:
            raise ApiError("invalid_parameter", f"Unknown minimum '{k}'.", details={"allowed": list(bh.STAT_MINIMUM_COLUMNS)})
        mins[k] = float(v)
    return mins


def _prepare_minimum_columns(df: pd.DataFrame) -> pd.DataFrame:
    """The column coercion apply_stat_min_filters does before masking."""
    df = df.copy()
    for col in bh.STAT_MINIMUM_COLUMNS:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ---------------------------------------------------------------- endpoints' business calls

def health(store: HistoryStore = STORE) -> s.HealthInfo:
    build = "unknown"
    try:
        from suite_deploy_marker import resolve_git_commit_short

        build = str(resolve_git_commit_short() or "unknown")[:12]
    except Exception:
        pass
    if not store.loaded:
        return s.HealthInfo(status="ok", build=build, data_loaded=False)
    return s.HealthInfo(status="ok", build=build, data_loaded=True, seasons=list(store.get().years))


def _summary(data: HistoryData, player_id: str) -> s.PlayerSummary:
    rows = data.yearly[data.yearly["playerID"] == player_id]
    if rows.empty:
        raise ApiError("player_not_found", f"No player with id '{player_id}'.")
    years = pd.to_numeric(rows["yearID"], errors="coerce").dropna().astype(int)
    last = rows.loc[pd.to_numeric(rows["yearID"], errors="coerce").idxmax()]
    first = rows.iloc[0]
    hof = None
    if "isHallOfFamer" in rows.columns:
        hof = bool(rows["isHallOfFamer"].fillna(False).astype(bool).any())
    return s.PlayerSummary(
        player=_player_ref(data, player_id, str(first.get("fullName") or "")),
        first_season=int(years.min()), last_season=int(years.max()),
        career_primary_position=str(first.get("careerPrimaryPos") or "") or None,
        bats=str(first.get("bats")) if pd.notna(first.get("bats")) else None,
        throws=str(first.get("throws")) if pd.notna(first.get("throws")) else None,
        last_team=_team(last.get("primaryTeamID"), last.get("primaryHistoricalTeamName"), last.get("primaryLeague")),
        hall_of_fame=hof,
    )


@functools.lru_cache(maxsize=512)
def _search_labels(data_id: int, labels: tuple[str, ...], query: str, n: int) -> tuple[str, ...]:
    """The app's picker matching (draft_player_names.search_draft_pool_names). Its fuzzy word
    match is the slow part (~1.5 s over 24k labels), so repeated queries are memoized."""
    from draft_player_names import search_draft_pool_names

    return tuple(search_draft_pool_names(query, list(labels), limit=n))


def search_players(q: str, *, limit: int | None = None, store: HistoryStore = STORE) -> s.PlayerSearchResult:
    query = str(q or "").strip()
    if len(query) < MIN_QUERY:
        raise ApiError("invalid_parameter", f"Search needs at least {MIN_QUERY} characters.")
    n = _limit(limit, 10)
    data = store.get()
    labels = _search_labels(id(data), data.label_tuple, query, n + 1)
    results = [_summary(data, data.labels[label]) for label in labels[:n]]
    return s.PlayerSearchResult(query=query, results=results, truncated=len(labels) > n)


def resolve_player(name: str, *, store: HistoryStore = STORE) -> s.PlayerSummary:
    """Exact name (or label) → one player; several players share it → ambiguous_player."""
    data = store.get()
    text = str(name or "").strip()
    if text in data.labels:
        return _summary(data, data.labels[text])
    ids = sorted(set(data.yearly.loc[data.yearly["fullName"].astype(str).str.strip().str.casefold() == text.casefold(), "playerID"]))
    if not ids:
        raise ApiError("player_not_found", f"No player named '{text}'.")
    if len(ids) > 1:
        raise ApiError("ambiguous_player", f"{len(ids)} players are named '{text}'.",
                       details={"candidates": [{"player_id": pid, "label": data.label_by_id.get(pid, pid)} for pid in ids]})
    return _summary(data, ids[0])


def player_seasons(player_id: str, *, start: int | None = None, end: int | None = None, split: str = "team",
                   store: HistoryStore = STORE) -> s.PlayerSeasonsResult:
    if split not in ("team", "combined"):
        raise ApiError("invalid_parameter", "split must be 'team' or 'combined'.")
    data = store.get()
    summary = _summary(data, player_id)
    years = _years(data, start, end, (summary.first_season, summary.last_season))
    own = data.batting[data.batting["playerID"] == player_id]
    rows, team_col, _sort_col, _note = bh.historical_rows(own, year_range=years, combine_split_seasons=split == "combined")
    rows = bh.safe_round_rate_stats(rows).sort_values(["yearID"], kind="stable")
    team_id_col = "primaryTeamID" if split == "combined" else "teamID"
    league_col = "primaryLeague" if split == "combined" else "teamLeague"
    seasons = [s.PlayerSeason(year=int(r["yearID"]), team=_team(r.get(team_id_col), r.get(team_col), r.get(league_col)),
                              position=str(r.get("displayPosition") or "") or None, stats=_stats(r))
               for _, r in rows.iterrows()]
    return s.PlayerSeasonsResult(player=summary, start=years[0], end=years[1], split_mode=split, seasons=seasons)


def season_leaders(*, start: int | None = None, end: int | None = None, metric: str = "HR", order: str = "desc",
                   limit: int | None = None, bats: Iterable[str] = (), positions: Iterable[str] = (),
                   position_source: str = "season", teams: Iterable[str] = (), combine: bool = False,
                   min_ab: int | None = None, qualified: bool = True, minimums: Mapping[str, float] | None = None,
                   store: HistoryStore = STORE) -> s.SeasonLeadersResult:
    """Historical Explorer: the page's filters, minimums and sort, as one query."""
    if metric not in SEASON_METRICS:
        raise ApiError("invalid_metric", f"'{metric}' is not a Historical Explorer stat.", details={"allowed": list(SEASON_METRICS)})
    if order not in ("desc", "asc"):
        raise ApiError("invalid_parameter", "order must be 'desc' or 'asc'.")
    if position_source not in ("season", "career"):
        raise ApiError("invalid_parameter", "position_source must be 'season' or 'career'.")
    data = store.get()
    years = _years(data, start, end, (max(data.years[0], 2010), data.years[1]))  # the page's default range
    n = _limit(limit)
    src_col = "careerPrimaryPos" if position_source == "career" else "primaryPos"
    rows, team_col, _sort_col, _note = bh.historical_rows(
        data.batting, year_range=years, bats=list(bats), positions=list(positions), position_source_col=src_col,
        teams=list(teams) or ["All Teams"], combine_split_seasons=bool(combine))
    qual, ab = _qualification(data, metric, years, span=False, min_ab=min_ab, qualified=qualified)
    rows = bh.apply_stat_minimums(_prepare_minimum_columns(rows), _mins(ab, minimums))
    rows = bh.safe_round_rate_stats(rows)
    if metric in rows.columns:
        rows = rows.sort_values(by=metric, ascending=(order == "asc"), na_position="last")
    headline = None
    try:
        import u1_answers as u1a

        display = rows[[c for c in ["yearID", "fullName", "bats", "displayPosition", team_col, *STAT_KEYS] if c in rows.columns]]
        ans = u1a.season_answer(display, metric, years, ascending=order == "asc", team_col=team_col, qualification=qual.text)
        headline = (ans or {}).get("headline")
    except Exception:
        headline = None
    team_id_col = "primaryTeamID" if combine else "teamID"
    league_col = "primaryLeague" if combine else "teamLeague"
    out = [s.SeasonRow(rank=i, player=_player_ref(data, str(r["playerID"]), str(r.get("fullName") or "")), year=int(r["yearID"]),
                       team=_team(r.get(team_id_col), r.get(team_col), r.get(league_col)),
                       position=str(r.get("displayPosition") or "") or None,
                       bats=str(r.get("bats")) if pd.notna(r.get("bats")) else None, stats=_stats(r))
           for i, (_, r) in enumerate(rows.head(n).iterrows(), start=1)]
    return s.SeasonLeadersResult(start=years[0], end=years[1], metric=_metric(metric), order=order,
                                 split_mode="combined" if combine else "team", qualification=qual,
                                 total_rows=len(rows), rows=out, headline=headline)


def leaderboard(*, start: int | None = None, end: int | None = None, metric: str = "score", limit: int | None = None,
                weights: Mapping[str, float] | None = None, min_ab: int | None = None, qualified: bool = True,
                minimums: Mapping[str, float] | None = None, store: HistoryStore = STORE) -> s.LeaderboardResult:
    """Leaderboards: the page's aggregation, minimums, weighted score and sort."""
    from leaderboard_aggregation import aggregate_leaderboard_career_totals, filter_yearly_for_leaderboards

    if metric not in LEADERBOARD_METRICS:
        raise ApiError("invalid_metric", f"'{metric}' is not a Leaderboards stat.", details={"allowed": list(LEADERBOARD_METRICS)})
    w = dict(DEFAULT_WEIGHTS if weights is None else weights)
    bad = [k for k in w if k not in WEIGHT_STATS]
    if bad:
        raise ApiError("invalid_parameter", f"Unknown weight stat(s): {', '.join(bad)}.", details={"allowed": list(WEIGHT_STATS)})
    if any(not (0 <= float(v) <= 10) for v in w.values()):
        raise ApiError("invalid_parameter", "Weights must be between 0 and 10.")
    weight_values = {k: float(w.get(k, 0.0)) for k in WEIGHT_STATS}  # the page passes every stat
    data = store.get()
    years = _years(data, start, end, (max(data.years[0], 2020), data.years[1]))
    n = _limit(limit)
    board = aggregate_leaderboard_career_totals(filter_yearly_for_leaderboards(data.yearly, years))
    board = bh.add_rate_stats(board)
    qual, ab = _qualification(data, metric, years, span=True, min_ab=min_ab, qualified=qualified)
    board = bh.apply_stat_minimums(_prepare_minimum_columns(board), _mins(ab, minimums))
    board = bh.safe_round_rate_stats(board)
    board = bh.add_leaderboard_score(board, weight_values)
    board = board.sort_values(metric, ascending=False, na_position="last")
    out = [s.LeaderboardRow(rank=i, player=_player_ref(data, str(r["playerID"]), str(r.get("fullName") or "")),
                            bats=str(r.get("bats")) if pd.notna(r.get("bats")) else None, stats=_stats(r),
                            score=float(np.round(float(r["score"]), 4)))
           for i, (_, r) in enumerate(board.head(n).iterrows(), start=1)]
    return s.LeaderboardResult(start=years[0], end=years[1], metric=_metric(metric),
                               weights={k: v for k, v in weight_values.items() if v}, qualification=qual,
                               total_rows=len(board), rows=out)
