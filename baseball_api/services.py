"""Read-only historical analytics service: request parameters → the app's own functions → typed
results. No HTTP, no Streamlit, no session state, no persistence.

Every number comes from the same functions the Streamlit pages call:
* data: ``baseball_history.load_history_frames`` (the app's ``load_data``);
* Historical Explorer rows: ``baseball_history.historical_rows`` + ``apply_stat_minimums``;
* Leaderboards: ``leaderboard_aggregation`` + ``baseball_history.add_leaderboard_score``;
* qualification: ``rate_stat_qualification`` (same auto/manual rule and caption);
* player labels and search: ``baseball_history.build_clean_player_label_map`` and
  ``draft_player_names.search_draft_pool_names`` (the app's player pickers);
* answers and qualification lines: ``u1_answers`` (the pages' answer cards and chips).
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
import u1_answers as u1a
from baseball_api import schemas as s
from baseball_api.errors import ApiError

ROOT = Path(__file__).resolve().parents[1]
STAT_KEYS = ("G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS")
COUNTING = ("G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "BB")
HISTORICAL_SORT_OPTIONS = ("R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS")  # Historical Explorer "Sort by"
SEASON_METRICS = HISTORICAL_SORT_OPTIONS + ("yearID",)  # the API can also order seasons by year
LEADERBOARD_METRICS = ("score", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS")  # Leaderboards "Sort by"
WEIGHT_STATS = ("R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS")
DEFAULT_WEIGHTS = {"HR": 1.0, "RBI": 1.0, "SB": 1.0}  # the page's defaults
WEIGHT_BOUNDS = (0.0, 10.0)  # the page's weight inputs
WEIGHT_STEP = 0.5
LEADERBOARD_LIMIT_BOUNDS = (5, 100)  # the page's "Show Top N Players" slider
HISTORICAL_DEFAULT_START = 2010  # the pages' default ranges end at the last season
LEADERBOARD_DEFAULT_START = 2020
DEFAULT_LIMIT = 25
MAX_LIMIT = 200
MIN_QUERY = 2
TEAM_GROUPS = ("All Teams", "American League", "National League")
_LABELS = {"BA": "AVG", "yearID": "Year", "score": "Score"}
_NAMES = {**u1a.STAT_NAMES, "G": "games", "yearID": "season"}
_BATS_LABELS = {"L": "Left", "R": "Right", "B": "Both"}
MINIMUM_PARAMS = tuple(c for c in bh.STAT_MINIMUM_COLUMNS if c != "AB")  # AB has its own parameter, min_ab
RETRY_AFTER_SECONDS = 5

# The pages' CSV export columns (render_output_table after clean_ui_columns / format_display_table).
_HIST_CSV_RENAME = {"yearID": "Year", "fullName": "Player", "bats": "Bats", "displayPosition": "Primary Position"}
_CSV_COUNTS = ("Year", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB")
_CSV_RATES = ("BA", "OBP", "SLG", "OPS")
_BOARD_CSV_COLUMNS = ["fullName", "bats", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS", "score"]


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
    bats_options: tuple[str, ...] = ()
    position_options: Mapping[str, tuple[str, ...]] | None = None  # source column -> options
    franchise_names: tuple[str, ...] = ()


def _page_options(batting: pd.DataFrame) -> dict[str, Any]:
    """The Historical Explorer's filter options, built the way the page builds them."""
    bats = sorted([x for x in batting["bats"].dropna().unique() if str(x).strip() != ""])
    positions = {
        col: tuple(sorted(x for x in batting[col].dropna().unique() if str(x).strip() != "" and x not in ("PH", "PR")))
        for col in ("primaryPos", "careerPrimaryPos")
    }
    franchises = sorted(set(batting["teamName"].dropna().astype(str)).intersection(set(bh.team_id_to_name.values())))
    return {"bats_options": tuple(bats), "position_options": positions, "franchise_names": tuple(franchises)}


class HistoryStore:
    """Loads the Lahman frames once per process (the API's equivalent of the app's cache)."""

    def __init__(self, base_dir: Path = ROOT):
        self._base_dir = Path(base_dir)
        self._lock = threading.Lock()
        self._data: HistoryData | None = None

    @property
    def loaded(self) -> bool:
        return self._data is not None

    def get(self, *, wait: bool = True) -> HistoryData:
        """``wait=False``: while another request (or the startup preload) is loading, raise
        ``data_unavailable`` with a retry hint instead of blocking on the load."""
        if self._data is None:
            if not self._lock.acquire(blocking=wait):
                raise ApiError("data_unavailable", "Historical data is still loading. Try again in a few seconds.",
                               details={"retry_after": RETRY_AFTER_SECONDS})
            try:
                if self._data is None:
                    self._data = self._load()
            finally:
                self._lock.release()
        return self._data

    def _load(self) -> HistoryData:
        t0 = time.perf_counter()
        try:
            batting, yearly, people = bh.load_history_frames(self._base_dir)
        except bh.HistoryDataMissing as exc:
            raise ApiError("data_unavailable", "Historical data is not available on this server.") from exc
        labels = bh.build_clean_player_label_map(yearly)
        try:  # warm the search's name normalization so the first search is as fast as the rest
            from draft_player_names import _normalize_lookup_key

            for label in labels:
                _normalize_lookup_key(label)
        except ImportError:
            pass
        years = pd.to_numeric(yearly["yearID"], errors="coerce").dropna().astype(int)
        return HistoryData(
            batting=batting, yearly=yearly, people=people,
            season_lengths=rsq.season_lengths(yearly),
            labels=labels, label_by_id={pid: label for label, pid in labels.items()}, label_tuple=tuple(labels),
            years=(int(years.min()), int(years.max())), load_seconds=round(time.perf_counter() - t0, 3),
            **_page_options(batting),
        )


STORE = HistoryStore()


# ---------------------------------------------------------------- helpers

def _num(v: Any) -> float | None:
    x = pd.to_numeric(v, errors="coerce")
    return None if pd.isna(x) else float(x)


def _metric(key: str) -> s.MetricInfo:
    name = _NAMES.get(key, key)
    if key == "score":
        return s.MetricInfo(key="score", label="Score", name=name, kind="score", decimals=1)
    if key == "yearID":
        return s.MetricInfo(key="yearID", label="Year", name=name, kind="year", decimals=0)
    rate = key in bh.RATE_STATS
    return s.MetricInfo(key=key, label=_LABELS.get(key, key), name=name, kind="rate" if rate else "count",
                        decimals=3 if rate else 0)


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


def _limit(limit: int | None, default: int = DEFAULT_LIMIT) -> int:
    n = default if limit is None else int(limit)
    if not 1 <= n <= MAX_LIMIT:
        raise ApiError("invalid_parameter", f"limit must be between 1 and {MAX_LIMIT}.")
    return n


def _offset(offset: int | None) -> int:
    n = 0 if offset is None else int(offset)
    if n < 0:
        raise ApiError("invalid_parameter", "offset must be 0 or more.")
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
    rate = bool(state["rate"])
    q = s.Qualification(
        applies=bool(rate and state["value"] > 0), min_ab=int(state["value"]), qualified_ab=int(state["qualified"]),
        mode=state["mode"], text=rsq.qualification_caption(state, info, metric) if rate else "",
        # the chip line the page shows (u1_answers.qualification_text, from the resolved state)
        summary=u1a.qualification_summary(state["value"], manual=state["mode"] == rsq.MODE_MANUAL, sort_stat=metric,
                                          year_range=years, per_season=not span),
        explanation=rsq.qualification_explanation(state, info, u1a.stat_name(metric)) if rate else None,
    )
    return q, int(state["value"])


def _mins(min_ab: int, extra: Mapping[str, float] | None) -> dict[str, float]:
    mins = {k: 0 for k in bh.STAT_MINIMUM_COLUMNS}
    mins["AB"] = min_ab
    for k, v in (extra or {}).items():
        if k == "AB":
            raise ApiError("invalid_parameter", "Set the at-bat minimum with min_ab.")
        if k not in bh.STAT_MINIMUM_COLUMNS:
            raise ApiError("invalid_parameter", f"Unknown minimum '{k}'.", details={"allowed": list(MINIMUM_PARAMS)})
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


def _csv(df: pd.DataFrame, *, score: bool = False) -> str:
    """format_display_table's rounding, then the page's ``to_csv(index=False)``."""
    df = df.copy()
    for col in df.columns:
        if col in _CSV_COUNTS:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(0)
        elif col in _CSV_RATES:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(3)
        elif score and col == "Score":
            df[col] = pd.to_numeric(df[col], errors="coerce").round(1)
    return df.to_csv(index=False)


def _page(frame: pd.DataFrame, offset: int, limit: int | None) -> pd.DataFrame:
    return frame.iloc[offset:] if limit is None else frame.iloc[offset:offset + limit]


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


def catalog(store: HistoryStore = STORE) -> s.Catalog:
    """What the pages' controls offer and start with. Defaults are the ones the endpoints use
    when a parameter is omitted."""
    data = store.get()
    lo, hi = data.years
    positions = data.position_options or {}
    hist = s.HistoricalCatalog(
        metrics=list(HISTORICAL_SORT_OPTIONS),
        defaults=s.HistoricalDefaults(
            start=max(lo, HISTORICAL_DEFAULT_START), end=hi, metric="HR", order="desc", split="team",
            bats=list(data.bats_options), positions=list(positions.get("primaryPos", ())), position_source="season",
            teams=["All Teams"]),
        filters=s.HistoricalFilters(
            bats=[s.Option(value=b, label=_BATS_LABELS.get(b, b)) for b in data.bats_options],
            positions=list(positions.get("primaryPos", ())),
            positions_by_source={"season": list(positions.get("primaryPos", ())),
                                 "career": list(positions.get("careerPrimaryPos", ()))},
            position_sources=[s.Option(value="season", label="Season Primary Position"),
                              s.Option(value="career", label="Career Primary Position")],
            teams=[s.Option(value=t, label=t) for t in (*TEAM_GROUPS, *data.franchise_names)],
            minimum_columns=list(MINIMUM_PARAMS)),
    )
    boards = s.LeaderboardCatalog(
        metrics=list(LEADERBOARD_METRICS),
        defaults=s.LeaderboardDefaults(start=max(lo, LEADERBOARD_DEFAULT_START), end=hi, metric="score",
                                       weights=dict(DEFAULT_WEIGHTS), limit=DEFAULT_LIMIT),
        weight_stats=list(WEIGHT_STATS), weight_bounds=list(WEIGHT_BOUNDS), weight_step=WEIGHT_STEP,
        limit_bounds=list(LEADERBOARD_LIMIT_BOUNDS), minimum_columns=list(MINIMUM_PARAMS),
    )
    keys = list(dict.fromkeys([*LEADERBOARD_METRICS, *STAT_KEYS, *SEASON_METRICS]))
    return s.Catalog(seasons=s.SeasonSpan(first=lo, last=hi), metrics=[_metric(k) for k in keys],
                     historical=hist, leaderboards=boards)


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


def player(player_id: str, *, store: HistoryStore = STORE) -> s.PlayerSummary:
    return _summary(store.get(), player_id)


@functools.lru_cache(maxsize=512)
def _search_labels(data_id: int, labels: tuple[str, ...], query: str, n: int) -> tuple[str, ...]:
    """The app's picker matching (draft_player_names.search_draft_pool_names); repeated queries
    are memoized."""
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


@dataclass(frozen=True)
class _SeasonQuery:
    data: HistoryData
    years: tuple[int, int]
    metric: str
    order: str
    combine: bool
    team_col: str
    qualification: s.Qualification
    ranked: pd.DataFrame  # the page's rows after minimums, rounded and sorted (one player's, with player_id)
    below: pd.DataFrame  # that player's seasons below the minimums (include_below_minimum only)
    player_id: str | None


def _season_query(*, start: int | None = None, end: int | None = None, metric: str = "HR", order: str = "desc",
                  bats: Iterable[str] = (), positions: Iterable[str] = (), position_source: str = "season",
                  teams: Iterable[str] = (), combine: bool = False, min_ab: int | None = None, qualified: bool = True,
                  minimums: Mapping[str, float] | None = None, player_id: str | None = None,
                  include_below_minimum: bool = False, store: HistoryStore = STORE) -> _SeasonQuery:
    """Historical Explorer: the page's filters, minimums and sort, as one query. With
    ``player_id`` the whole page pipeline still runs and its rows are then limited to that player,
    so the result is exactly the page's table filtered to them."""
    if metric not in SEASON_METRICS:
        raise ApiError("invalid_metric", f"'{metric}' is not a Historical Explorer stat.", details={"allowed": list(SEASON_METRICS)})
    if order not in ("desc", "asc"):
        raise ApiError("invalid_parameter", "order must be 'desc' or 'asc'.")
    if position_source not in ("season", "career"):
        raise ApiError("invalid_parameter", "position_source must be 'season' or 'career'.")
    if include_below_minimum and not player_id:
        raise ApiError("invalid_parameter", "include_below_minimum needs player_id.")
    data = store.get()
    default = (max(data.years[0], HISTORICAL_DEFAULT_START), data.years[1])  # the page's default range
    if player_id:
        summary = _summary(data, player_id)
        default = (summary.first_season, summary.last_season)  # one player: their career
    years = _years(data, start, end, default)
    src_col = "careerPrimaryPos" if position_source == "career" else "primaryPos"
    rows, team_col, _sort_col, _note = bh.historical_rows(
        data.batting, year_range=years, bats=list(bats), positions=list(positions), position_source_col=src_col,
        teams=list(teams) or ["All Teams"], combine_split_seasons=bool(combine))
    qual, ab = _qualification(data, metric, years, span=False, min_ab=min_ab, qualified=qualified)
    prepared = _prepare_minimum_columns(rows)
    kept = bh.apply_stat_minimums(prepared, _mins(ab, minimums))
    kept = bh.safe_round_rate_stats(kept)
    if metric in kept.columns:
        kept = kept.sort_values(by=metric, ascending=(order == "asc"), na_position="last")
    below = kept.iloc[0:0]
    if player_id:
        if include_below_minimum:
            mine = prepared[prepared["playerID"] == player_id]
            below = bh.safe_round_rate_stats(mine[~mine.index.isin(kept.index)])
            if metric in below.columns:
                below = below.sort_values(by=metric, ascending=(order == "asc"), na_position="last", kind="stable")
        kept = kept[kept["playerID"] == player_id]
    return _SeasonQuery(data=data, years=years, metric=metric, order=order, combine=bool(combine), team_col=team_col,
                        qualification=qual, ranked=kept, below=below, player_id=player_id or None)


def _season_row(q: _SeasonQuery, r: pd.Series, rank: int | None) -> s.SeasonRow:
    team_id_col = "primaryTeamID" if q.combine else "teamID"
    league_col = "primaryLeague" if q.combine else "teamLeague"
    return s.SeasonRow(rank=rank, player=_player_ref(q.data, str(r["playerID"]), str(r.get("fullName") or "")),
                       year=int(r["yearID"]), team=_team(r.get(team_id_col), r.get(q.team_col), r.get(league_col)),
                       position=str(r.get("displayPosition") or "") or None,
                       bats=str(r.get("bats")) if pd.notna(r.get("bats")) else None, stats=_stats(r),
                       meets_minimum=rank is not None)


def _hist_display(q: _SeasonQuery) -> pd.DataFrame:
    """The page's ``hist_display_raw`` columns."""
    cols = ["yearID", "fullName", "bats", "displayPosition", q.team_col, *HISTORICAL_SORT_OPTIONS]  # R, AB, H … OPS
    return q.ranked[[c for c in cols if c in q.ranked.columns]]


def season_leaders(*, start: int | None = None, end: int | None = None, metric: str = "HR", order: str = "desc",
                   limit: int | None = None, offset: int | None = None, bats: Iterable[str] = (),
                   positions: Iterable[str] = (), position_source: str = "season", teams: Iterable[str] = (),
                   combine: bool = False, min_ab: int | None = None, qualified: bool = True,
                   minimums: Mapping[str, float] | None = None, player_id: str | None = None,
                   include_below_minimum: bool = False, store: HistoryStore = STORE) -> s.SeasonLeadersResult:
    """Historical Explorer: best single seasons (or one player's seasons, ranked)."""
    n, start_at = _limit(limit), _offset(offset)
    q = _season_query(start=start, end=end, metric=metric, order=order, bats=bats, positions=positions,
                      position_source=position_source, teams=teams, combine=combine, min_ab=min_ab, qualified=qualified,
                      minimums=minimums, player_id=player_id, include_below_minimum=include_below_minimum, store=store)
    answer = None
    ans = u1a.season_answer(_hist_display(q), metric, q.years, ascending=q.order == "asc", team_col=q.team_col,
                            qualification=q.qualification.summary)
    if ans:
        answer = s.SeasonAnswer(headline=ans["headline"], body=ans["body"], context=ans["context"],
                                tile_metrics=list(ans["tile_stats"]))
    ranked_n = len(q.ranked)
    full = pd.concat([q.ranked, q.below]) if len(q.below) else q.ranked
    out = [_season_row(q, r, i + 1 if i < ranked_n else None)
           for i, (_, r) in enumerate(full.iloc[start_at:start_at + n].iterrows(), start=start_at)]
    return s.SeasonLeadersResult(start=q.years[0], end=q.years[1], metric=_metric(q.metric), order=q.order,
                                 split_mode="combined" if q.combine else "team", qualification=q.qualification,
                                 total_rows=len(full), ranked_rows=ranked_n, offset=start_at, player_id=q.player_id,
                                 rows=out, headline=answer.headline if answer else None, answer=answer)


def season_leaders_csv(*, limit: int | None = None, offset: int | None = None, **params: Any) -> str:
    """The page's "Export CSV" for the same query: every ranked row (or ``offset``/``limit`` of
    them), the page's columns and rounding. Below-minimum seasons are never exported."""
    params.pop("include_below_minimum", None)
    start_at = _offset(offset)
    if limit is not None and int(limit) < 1:
        raise ApiError("invalid_parameter", "limit must be 1 or more.")
    q = _season_query(**params)
    table = _page(_hist_display(q), start_at, None if limit is None else int(limit))
    return _csv(table.rename(columns={**_HIST_CSV_RENAME, q.team_col: "Team"}))


def _board(*, start: int | None = None, end: int | None = None, metric: str = "score",
           weights: Mapping[str, float] | None = None, min_ab: int | None = None, qualified: bool = True,
           minimums: Mapping[str, float] | None = None, store: HistoryStore = STORE):
    from leaderboard_aggregation import aggregate_leaderboard_career_totals, filter_yearly_for_leaderboards

    if metric not in LEADERBOARD_METRICS:
        raise ApiError("invalid_metric", f"'{metric}' is not a Leaderboards stat.", details={"allowed": list(LEADERBOARD_METRICS)})
    w = dict(DEFAULT_WEIGHTS if weights is None else weights)
    bad = [k for k in w if k not in WEIGHT_STATS]
    if bad:
        raise ApiError("invalid_parameter", f"Unknown weight stat(s): {', '.join(bad)}.", details={"allowed": list(WEIGHT_STATS)})
    if any(not (WEIGHT_BOUNDS[0] <= float(v) <= WEIGHT_BOUNDS[1]) for v in w.values()):
        raise ApiError("invalid_parameter", "Weights must be between 0 and 10.")
    weight_values = {k: float(w.get(k, 0.0)) for k in WEIGHT_STATS}  # the page passes every stat
    data = store.get()
    years = _years(data, start, end, (max(data.years[0], LEADERBOARD_DEFAULT_START), data.years[1]))
    board = aggregate_leaderboard_career_totals(filter_yearly_for_leaderboards(data.yearly, years))
    board = bh.add_rate_stats(board)
    qual, ab = _qualification(data, metric, years, span=True, min_ab=min_ab, qualified=qualified)
    board = bh.apply_stat_minimums(_prepare_minimum_columns(board), _mins(ab, minimums))
    board = bh.safe_round_rate_stats(board)
    board = bh.add_leaderboard_score(board, weight_values)
    board = board.sort_values(metric, ascending=False, na_position="last")
    return data, years, weight_values, qual, board


def leaderboard(*, start: int | None = None, end: int | None = None, metric: str = "score", limit: int | None = None,
                offset: int | None = None, weights: Mapping[str, float] | None = None, min_ab: int | None = None,
                qualified: bool = True, minimums: Mapping[str, float] | None = None,
                store: HistoryStore = STORE) -> s.LeaderboardResult:
    """Leaderboards: the page's aggregation, minimums, weighted score and sort."""
    n, start_at = _limit(limit), _offset(offset)
    data, years, weight_values, qual, board = _board(start=start, end=end, metric=metric, weights=weights, min_ab=min_ab,
                                                     qualified=qualified, minimums=minimums, store=store)
    answer = None
    ans = u1a.leaderboard_answer(board, metric, years, weights=weight_values, qualification=qual.summary,
                                 control_hint=False)
    if ans:
        answer = s.LeaderboardAnswer(headline=ans["headline"], body=ans["body"], context=f"Ranked by {u1a.stat_name(metric)}")
    out = [s.LeaderboardRow(rank=i, player=_player_ref(data, str(r["playerID"]), str(r.get("fullName") or "")),
                            bats=str(r.get("bats")) if pd.notna(r.get("bats")) else None, stats=_stats(r),
                            score=float(np.round(float(r["score"]), 4)))
           for i, (_, r) in enumerate(board.iloc[start_at:start_at + n].iterrows(), start=start_at + 1)]
    return s.LeaderboardResult(start=years[0], end=years[1], metric=_metric(metric),
                               weights={k: v for k, v in weight_values.items() if v}, qualification=qual,
                               total_rows=len(board), offset=start_at, rows=out, answer=answer)


def leaderboard_csv(*, limit: int | None = None, offset: int | None = None, **params: Any) -> str:
    """The page's "Export CSV": the page exports its Top N rows, so pass ``limit`` for the same
    file; without it every ranked player is exported."""
    start_at = _offset(offset)
    if limit is not None and int(limit) < 1:
        raise ApiError("invalid_parameter", "limit must be 1 or more.")
    _data, _years_, _w, _qual, board = _board(**params)
    table = _page(board, start_at, None if limit is None else int(limit))[_BOARD_CSV_COLUMNS]
    return _csv(table.rename(columns={"fullName": "Player", "bats": "Bats", "score": "Score"}), score=True)
