"""Auto-load current-season hitter stats for Fantasy Lineup Assistant."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_lineup_page_hitter_stats(
    session: dict[str, Any],
    context: dict[str, Any] | None,
    *,
    normalize_name_fn=None,
) -> dict[str, Any]:
    """
    Resolve hitter stats and merged league roster stats without visiting Standings first.

    Returns {ok, source, error, hitter_stats, roster_stats}.
    """
    result: dict[str, Any] = {
        "ok": False,
        "source": "",
        "error": "",
        "hitter_stats": pd.DataFrame(),
        "roster_stats": pd.DataFrame(),
    }
    try:
        from fantasy_in_season_state import (
            has_restored_in_season_stats,
            hydrate_fantasy_in_season_to_session,
        )
    except ImportError:
        has_restored_in_season_stats = lambda _s: False  # type: ignore
        hydrate_fantasy_in_season_to_session = lambda _s: False  # type: ignore

    hitters = session.get("_fantasy_current_hitter_stats", pd.DataFrame())
    if not isinstance(hitters, pd.DataFrame) or hitters.empty:
        if not has_restored_in_season_stats(session):
            hydrate_fantasy_in_season_to_session(session)
        hitters = session.get("_fantasy_current_hitter_stats", pd.DataFrame())

    if isinstance(hitters, pd.DataFrame) and not hitters.empty:
        result["source"] = str(session.get("_fantasy_standings_stats_source") or "restored")
        result["hitter_stats"] = hitters.copy()
    else:
        season = int(session.get("standings_api_season") or datetime.now().year)
        try:
            from streamlit_app import fetch_mlb_api_hitter_stats

            fetched = fetch_mlb_api_hitter_stats(season)
            if isinstance(fetched, pd.DataFrame) and not fetched.empty:
                session["_fantasy_current_hitter_stats"] = fetched.copy()
                session["_fantasy_standings_stats_loaded_at"] = _utc_now_iso()
                session["_fantasy_standings_stats_source"] = f"MLB API {season}"
                session["standings_api_season"] = season
                result["source"] = f"MLB API {season}"
                result["hitter_stats"] = fetched.copy()
                try:
                    from fantasy_in_season_state import sync_fantasy_in_season_state

                    sync_fantasy_in_season_state(session, reason="lineup_auto_fetch")
                except ImportError:
                    pass
            else:
                result["error"] = f"MLB API returned no hitter stats for {season}."
        except Exception as exc:
            result["error"] = f"Could not load current hitter stats: {type(exc).__name__}: {exc}"

    if result["hitter_stats"] is None or getattr(result["hitter_stats"], "empty", True):
        return result

    if not isinstance(context, dict):
        result["ok"] = True
        return result

    roster_stats = session.get("fantasy_current_roster_stats", pd.DataFrame())
    if isinstance(roster_stats, pd.DataFrame) and not roster_stats.empty:
        result["roster_stats"] = roster_stats.copy()
        result["ok"] = True
        return result

    try:
        from fantasy_league_context import (
            build_roster_stats_from_league_context,
            has_full_league_rosters,
        )

        if has_full_league_rosters(context):
            norm = normalize_name_fn
            if norm is None:
                from streamlit_app import normalize_player_name_for_merge

                norm = normalize_player_name_for_merge
            built = build_roster_stats_from_league_context(
                context,
                result["hitter_stats"],
                normalize_name_fn=norm,
            )
            if isinstance(built, pd.DataFrame) and not built.empty:
                session["fantasy_current_roster_stats"] = built.copy()
                try:
                    from fantasy_lineup_scope import resolve_lineup_scope, stamp_roster_stats_cache_scope

                    scope = resolve_lineup_scope(session, context, week=1)
                    if scope:
                        stamp_roster_stats_cache_scope(session, scope)
                except ImportError:
                    pass
                result["roster_stats"] = built.copy()
                try:
                    from fantasy_in_season_state import sync_fantasy_in_season_state

                    sync_fantasy_in_season_state(session, reason="lineup_roster_merge")
                except ImportError:
                    pass
    except ImportError:
        pass

    result["ok"] = not getattr(result["hitter_stats"], "empty", True)
    return result
