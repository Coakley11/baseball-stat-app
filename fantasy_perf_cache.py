"""Session caches for fantasy standings and lineup assistant calculations."""

from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd

STANDINGS_ROSTER_CACHE_KEY = "_fantasy_standings_roster_cache"
LINEUP_SCORES_CACHE_KEY = "_fantasy_lineup_scores_cache"


def _df_sig(df: pd.DataFrame | None, *, extra: str = "") -> str:
    if df is None or getattr(df, "empty", True):
        return f"empty:{extra}"
    cols = sorted(str(c) for c in df.columns)
    sample = df.head(40).to_csv(index=False)
    raw = f"{extra}|{cols}|{len(df)}|{sample}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def standings_roster_cache_key(
    session: dict[str, Any],
    *,
    stats_source: str,
    api_season: int | None,
    scoring_format: str,
    draft_table: pd.DataFrame | None,
    active_archive_id: str = "",
    league_context_id: str = "",
    league_rosters_sig: str = "",
) -> tuple[Any, ...]:
    return (
        str(league_context_id or ""),
        str(league_rosters_sig or ""),
        str(active_archive_id or ""),
        _df_sig(draft_table, extra="draft"),
        str(stats_source or ""),
        int(api_season or 0),
        str(scoring_format or ""),
        str(session.get("_fantasy_current_hitter_stats_sig") or ""),
    )


def get_cached_standings_results(
    session: dict[str, Any],
    cache_key: tuple[Any, ...],
) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    entry = session.get(STANDINGS_ROSTER_CACHE_KEY)
    if isinstance(entry, dict) and entry.get("key") == cache_key:
        roster = entry.get("roster_stats")
        standings = entry.get("standings")
        if isinstance(roster, pd.DataFrame) and isinstance(standings, pd.DataFrame):
            try:
                from page_perf_phases import record_cache_event

                record_cache_event(session, "standings_calculations", hit=True)
            except ImportError:
                pass
            return roster.copy(), standings.copy()
    return None, None


def store_standings_results(
    session: dict[str, Any],
    cache_key: tuple[Any, ...],
    roster_stats: pd.DataFrame,
    standings: pd.DataFrame,
) -> None:
    try:
        from page_perf_phases import record_cache_event

        record_cache_event(session, "standings_calculations", hit=False)
    except ImportError:
        pass
    session[STANDINGS_ROSTER_CACHE_KEY] = {
        "key": cache_key,
        "roster_stats": roster_stats.copy(),
        "standings": standings.copy(),
    }
    session["_fantasy_current_hitter_stats_sig"] = cache_key[-1]


def get_cached_standings_roster_stats(
    session: dict[str, Any],
    cache_key: tuple[Any, ...],
) -> pd.DataFrame | None:
    roster, _ = get_cached_standings_results(session, cache_key)
    return roster


def store_standings_roster_stats(
    session: dict[str, Any],
    cache_key: tuple[Any, ...],
    roster_stats: pd.DataFrame,
) -> None:
    store_standings_results(session, cache_key, roster_stats, pd.DataFrame())


def lineup_scores_cache_key(
    *,
    team: str,
    lineup_format: str,
    roster_sig: str,
    custom_weights: dict[str, float] | None,
    slot_sig: str,
) -> tuple[Any, ...]:
    weights = tuple(sorted((str(k), float(v)) for k, v in (custom_weights or {}).items()))
    return (str(team or ""), str(lineup_format or ""), str(roster_sig or ""), weights, str(slot_sig or ""))


def get_cached_lineup_scores(session: dict[str, Any], cache_key: tuple[Any, ...]) -> pd.DataFrame | None:
    entry = session.get(LINEUP_SCORES_CACHE_KEY)
    if isinstance(entry, dict) and entry.get("key") == cache_key:
        df = entry.get("df")
        if isinstance(df, pd.DataFrame):
            try:
                from page_perf_phases import record_cache_event

                record_cache_event(session, "lineup_assistant_scores", hit=True)
            except ImportError:
                pass
            return df.copy()
    return None


def store_lineup_scores(session: dict[str, Any], cache_key: tuple[Any, ...], scored: pd.DataFrame) -> None:
    try:
        from page_perf_phases import record_cache_event

        record_cache_event(session, "lineup_assistant_scores", hit=False)
    except ImportError:
        pass
    session[LINEUP_SCORES_CACHE_KEY] = {"key": cache_key, "df": scored.copy()}
