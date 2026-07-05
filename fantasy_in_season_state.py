"""Persist in-season fantasy stats and standings across refresh (cloud + disk)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

FANTASY_IN_SEASON_STATE_KEY = "fantasy_in_season_state"
SCHEMA_VERSION = 1

_SESSION_HITTER_KEY = "_fantasy_current_hitter_stats"
_SESSION_PITCHER_KEY = "_fantasy_current_pitcher_stats"
_SESSION_ROSTER_KEY = "fantasy_current_roster_stats"
_SESSION_STANDINGS_KEY = "fantasy_current_standings"
_LOADED_AT_KEY = "_fantasy_standings_stats_loaded_at"
_SOURCE_KEY = "_fantasy_standings_stats_source"
_API_SEASON_KEY = "standings_api_season"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _df_records(df: pd.DataFrame | None, *, limit: int = 2500) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    try:
        from dataframe_utils import sanitize_for_json

        rows = df.head(int(limit)).to_dict(orient="records")
        return sanitize_for_json(rows)  # type: ignore[return-value]
    except ImportError:
        return df.head(int(limit)).to_dict(orient="records")


def _records_to_df(records: Any) -> pd.DataFrame:
    if not isinstance(records, list) or not records:
        return pd.DataFrame()
    try:
        return pd.DataFrame(records)
    except Exception:
        return pd.DataFrame()


def has_restored_in_season_stats(session: dict[str, Any]) -> bool:
    hitters = session.get(_SESSION_HITTER_KEY)
    if isinstance(hitters, pd.DataFrame) and not hitters.empty:
        return True
    blob = session.get(FANTASY_IN_SEASON_STATE_KEY)
    return isinstance(blob, dict) and bool(blob.get("hitter_stats_records"))


def sync_fantasy_in_season_state(session: dict[str, Any], *, reason: str = "standings_updated") -> None:
    """Snapshot session dataframes into the canonical persisted blob."""
    hitters = session.get(_SESSION_HITTER_KEY)
    pitchers = session.get(_SESSION_PITCHER_KEY)
    roster = session.get(_SESSION_ROSTER_KEY)
    standings = session.get(_SESSION_STANDINGS_KEY)
    if not any(
        isinstance(df, pd.DataFrame) and not df.empty
        for df in (hitters, pitchers, roster, standings)
    ):
        return
    blob: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _utc_now_iso(),
        "reason": str(reason or ""),
        "stats_loaded_at": str(session.get(_LOADED_AT_KEY) or ""),
        "stats_source": str(session.get(_SOURCE_KEY) or ""),
        "api_season": session.get(_API_SEASON_KEY),
        "hitter_stats_records": _df_records(hitters if isinstance(hitters, pd.DataFrame) else None),
        "pitcher_stats_records": _df_records(pitchers if isinstance(pitchers, pd.DataFrame) else None),
        "roster_stats_records": _df_records(roster if isinstance(roster, pd.DataFrame) else None, limit=4000),
        "standings_records": _df_records(standings if isinstance(standings, pd.DataFrame) else None, limit=64),
        "stats_sig": str(session.get("_fantasy_current_hitter_stats_sig") or ""),
    }
    try:
        from fantasy_league_context import get_active_league_context

        ctx = get_active_league_context(session)
        if isinstance(ctx, dict):
            blob["active_league_context_id"] = str(ctx.get("league_context_id") or "")
            blob["my_team_name"] = str(ctx.get("my_team_name") or "")
    except ImportError:
        pass
    session[FANTASY_IN_SEASON_STATE_KEY] = blob


def hydrate_fantasy_in_season_to_session(session: dict[str, Any], state: dict[str, Any] | None = None) -> bool:
    """Restore hitter/pitcher/roster/standings dataframes from disk/cloud blob."""
    blob: dict[str, Any] | None = None
    if isinstance(state, dict):
        if isinstance(state.get(FANTASY_IN_SEASON_STATE_KEY), dict):
            blob = state.get(FANTASY_IN_SEASON_STATE_KEY)
        elif state.get("hitter_stats_records") is not None or state.get("roster_stats_records") is not None:
            blob = state
    if blob is None:
        raw = session.get(FANTASY_IN_SEASON_STATE_KEY)
        blob = raw if isinstance(raw, dict) else None
    if not isinstance(blob, dict):
        return False
    applied = False
    hitters = _records_to_df(blob.get("hitter_stats_records"))
    pitchers = _records_to_df(blob.get("pitcher_stats_records"))
    roster = _records_to_df(blob.get("roster_stats_records"))
    standings = _records_to_df(blob.get("standings_records"))
    if not hitters.empty:
        session[_SESSION_HITTER_KEY] = hitters
        applied = True
    if not pitchers.empty:
        session[_SESSION_PITCHER_KEY] = pitchers
        applied = True
    if not roster.empty:
        session[_SESSION_ROSTER_KEY] = roster
        applied = True
    if not standings.empty:
        session[_SESSION_STANDINGS_KEY] = standings
        applied = True
    if blob.get("stats_loaded_at"):
        session[_LOADED_AT_KEY] = blob["stats_loaded_at"]
    if blob.get("stats_source"):
        session[_SOURCE_KEY] = blob["stats_source"]
    if blob.get("api_season") is not None:
        session[_API_SEASON_KEY] = blob["api_season"]
    if blob.get("stats_sig"):
        session["_fantasy_current_hitter_stats_sig"] = blob["stats_sig"]
    if applied:
        session["_fantasy_in_season_restored"] = True
        session[FANTASY_IN_SEASON_STATE_KEY] = blob
    return applied


def prepare_fantasy_in_season_hydration(session: dict[str, Any]) -> bool:
    """Early page prep: hydrate from in-session blob if session dataframes are empty."""
    if has_restored_in_season_stats(session):
        return False
    return hydrate_fantasy_in_season_to_session(session)


def in_season_context_ready(session: dict[str, Any]) -> bool:
    roster = session.get(_SESSION_ROSTER_KEY)
    if isinstance(roster, pd.DataFrame) and not roster.empty:
        return True
    hitters = session.get(_SESSION_HITTER_KEY)
    return isinstance(hitters, pd.DataFrame) and not hitters.empty
