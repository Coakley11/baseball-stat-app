"""Session caches for Live Draft Room and Draft Assistant — invalidate when board changes."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

REC_CACHE_KEY = "_live_draft_rec_cache"
AVAILABLE_CACHE_KEY = "_live_draft_available_cache"
DECISION_CACHE_KEY = "_live_draft_decision_cache"
WHY_COLUMN_CACHE_KEY = "_live_draft_why_column_cache"
DA_SCORING_CACHE_KEY = "_draft_assistant_scoring_cache"


def invalidate_live_draft_ui_caches(session: dict[str, Any] | None) -> None:
    """Clear recommendation, pool, and decision-panel caches after a pick or poll change."""
    if not session:
        return
    session.pop(REC_CACHE_KEY, None)
    session.pop(AVAILABLE_CACHE_KEY, None)
    session.pop(DECISION_CACHE_KEY, None)
    session.pop(WHY_COLUMN_CACHE_KEY, None)


def invalidate_draft_assistant_scoring_cache(session: dict[str, Any] | None) -> None:
    if session:
        session.pop(DA_SCORING_CACHE_KEY, None)


def live_draft_ui_cache_key(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    top_n: int = 8,
    team: str | None = None,
) -> tuple[Any, ...]:
    idx = int(room.get("current_pick_index") or 0)
    board_len = len(room.get("draft_board") or [])
    team_s = str(team or "")
    cfg = dict(room.get("config") or {})
    slots = dict(cfg.get("slots") or {})
    slots_key = tuple(sorted((k, int(v or 0)) for k, v in slots.items()))
    rev = int(((room.get("meta") or {}).get("sync") or {}).get("revision") or 0)
    scoring = (
        str(cfg.get("fantasy_format") or cfg.get("scoring_type") or ""),
        bool(cfg.get("use_ml_blend")),
        float(cfg.get("ml_blend_weight") or 0),
        str(cfg.get("auto_pick_rule") or ""),
    )
    roster_sig = tuple(
        sorted(
            (str(t), len(list(players or [])))
            for t, players in (room.get("rosters") or {}).items()
        )
    )
    pool_sig: tuple[Any, ...] = ()
    try:
        from shared_draft_context import draft_pool_kwargs_from_session

        pool_sig = tuple(sorted(draft_pool_kwargs_from_session(session).items()))
    except ImportError:
        pass
    return (idx, board_len, team_s, int(top_n), slots_key, rev, scoring, roster_sig, pool_sig)


def available_pool_cache_key(room: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(room.get("draft_room_id") or ""),
        int(room.get("current_pick_index") or 0),
        len(room.get("draft_board") or []),
        len(room.get("drafted_player_ids") or []),
    )


def cached_live_draft_get_available(session: dict[str, Any], room: dict[str, Any]) -> pd.DataFrame:
    """Reuse undrafted pool within the same pick when drafted ids have not changed."""
    from live_draft_state import live_draft_get_available

    if not isinstance(room, dict):
        return pd.DataFrame()
    key = available_pool_cache_key(room)
    entry = session.get(AVAILABLE_CACHE_KEY)
    if isinstance(entry, dict) and entry.get("key") == key:
        df = entry.get("df")
        if isinstance(df, pd.DataFrame):
            try:
                from live_draft_perf import record_cache_action

                record_cache_action(
                    session,
                    "available_pool",
                    phase="live_draft_available_pool",
                    hit=True,
                )
            except ImportError:
                try:
                    from page_perf_phases import record_cache_event

                    record_cache_event(session, "live_draft_available_pool", hit=True)
                except ImportError:
                    pass
            return df.copy()
    t0 = time.perf_counter()
    try:
        from page_perf_phases import session_perf_phase

        with session_perf_phase(session, "live_draft_available_pool"):
            df = live_draft_get_available(room)
    except ImportError:
        df = live_draft_get_available(room)
    elapsed = time.perf_counter() - t0
    try:
        from live_draft_perf import PHASE_AVAILABLE_POOL, record_cache_action

        record_cache_action(
            session,
            "available_pool",
            phase=PHASE_AVAILABLE_POOL,
            hit=False,
            elapsed_sec=elapsed,
        )
    except ImportError:
        try:
            from page_perf_phases import record_cache_event

            record_cache_event(session, "live_draft_available_pool", hit=False)
        except ImportError:
            pass
    session[AVAILABLE_CACHE_KEY] = {"key": key, "df": df}
    return df.copy()


def enrich_live_draft_recommendations_with_why(
    session: dict[str, Any],
    ui_cache_key: tuple[Any, ...] | None,
    tables: dict[str, pd.DataFrame],
    *,
    gaps: list[str] | None = None,
    category_needs: list[str] | None = None,
    pool_df: Any = None,
    config: dict[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    """Cache expensive Why-this-pick column enrichment across tab reruns."""
    from live_draft_room_ui import add_why_this_pick_column

    if ui_cache_key is None:
        return {
            name: add_why_this_pick_column(
                df,
                gaps=gaps,
                category_needs=category_needs,
                pool_df=pool_df,
                config=config,
            )
            for name, df in tables.items()
        }
    entry = session.get(WHY_COLUMN_CACHE_KEY)
    if isinstance(entry, dict) and entry.get("key") == ui_cache_key:
        stored = entry.get("tables")
        if isinstance(stored, dict) and all(name in stored for name in tables):
            try:
                from page_perf_phases import record_cache_event

                record_cache_event(session, "live_draft_why_columns", hit=True)
            except ImportError:
                pass
            return {name: stored[name].copy() for name in tables}
    try:
        from page_perf_phases import record_cache_event

        record_cache_event(session, "live_draft_why_columns", hit=False)
    except ImportError:
        pass
    enriched: dict[str, pd.DataFrame] = {}
    for name, df in tables.items():
        enriched[name] = add_why_this_pick_column(
            df,
            gaps=gaps,
            category_needs=category_needs,
            pool_df=pool_df,
            config=config,
        )
    session[WHY_COLUMN_CACHE_KEY] = {
        "key": ui_cache_key,
        "tables": {name: enriched[name].copy() for name in enriched},
    }
    return enriched


def get_cached_live_draft_decision_context(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    tracker_team: str,
    cache_key: tuple[Any, ...],
) -> dict[str, Any] | None:
    entry = session.get(DECISION_CACHE_KEY)
    if not isinstance(entry, dict):
        return None
    if entry.get("key") != cache_key or entry.get("team") != str(tracker_team or ""):
        return None
    return entry


def store_live_draft_decision_context(
    session: dict[str, Any],
    *,
    cache_key: tuple[Any, ...],
    tracker_team: str,
    tracker: dict[str, Any],
    outlook: dict[str, Any],
    gaps: list[str],
    category_needs: list[str],
) -> None:
    session[DECISION_CACHE_KEY] = {
        "key": cache_key,
        "team": str(tracker_team or ""),
        "tracker": tracker,
        "outlook": outlook,
        "gaps": list(gaps),
        "category_needs": list(category_needs),
    }


def draft_assistant_scoring_cache_key(
    session: dict[str, Any],
    *,
    drafted_names: set[str] | frozenset[str],
    my_roster: list[str],
    current_pick: int,
    needed_positions: list[str],
    category_needs: list[str],
    target_counts: dict[str, int],
    draft_format: str,
    use_ml_blend: bool,
    ml_blend_weight: float,
    draft_top_n: int = 10,
) -> tuple[Any, ...]:
    slots_key = tuple(sorted((k, int(v or 0)) for k, v in (target_counts or {}).items()))
    return (
        frozenset(str(n).strip().lower() for n in drafted_names if str(n).strip()),
        tuple(sorted(str(n) for n in my_roster)),
        int(current_pick),
        tuple(needed_positions or []),
        tuple(category_needs or []),
        slots_key,
        str(draft_format),
        bool(use_ml_blend),
        float(ml_blend_weight or 0),
        int(draft_top_n),
    )
