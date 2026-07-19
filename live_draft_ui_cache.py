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
DA_WHY_CACHE_KEY = "_draft_assistant_why_cache"


def invalidate_live_draft_ui_caches(session: dict[str, Any] | None) -> None:
    """Clear recommendation, pool, and decision-panel caches after a pick or poll change."""
    if not session:
        return
    session.pop(REC_CACHE_KEY, None)
    session.pop(AVAILABLE_CACHE_KEY, None)
    session.pop(DECISION_CACHE_KEY, None)
    session.pop(WHY_COLUMN_CACHE_KEY, None)


def _filter_player_from_df(df: Any, *, player_id: str = "", player_name: str = "") -> Any:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    out = df
    pid = str(player_id or "").strip()
    name = str(player_name or "").strip().lower()
    if pid and "playerID" in out.columns:
        out = out[out["playerID"].astype(str).str.strip() != pid]
    if pid and "player_id" in out.columns:
        out = out[out["player_id"].astype(str).str.strip() != pid]
    name_col = "fullName" if "fullName" in out.columns else ("Player" if "Player" in out.columns else "")
    if name and name_col:
        out = out[out[name_col].astype(str).str.strip().str.lower() != name]
    return out


def drafted_identity_sets(room: dict[str, Any] | None) -> tuple[set[str], set[str]]:
    """Authoritative drafted IDs + normalized names from the committed Draft Board."""
    ids: set[str] = set()
    names: set[str] = set()
    if not isinstance(room, dict):
        return ids, names
    try:
        from live_draft_state import reconcile_drafted_player_ids

        for pid in reconcile_drafted_player_ids(room) or []:
            s = str(pid or "").strip()
            if s:
                ids.add(s)
                ids.add(s.lower())
    except ImportError:
        pass
    for pid in room.get("drafted_player_ids") or []:
        s = str(pid or "").strip()
        if s:
            ids.add(s)
            ids.add(s.lower())
    for row in room.get("draft_board") or []:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("playerID") or row.get("player_id") or "").strip()
        if pid:
            ids.add(pid)
            ids.add(pid.lower())
        name = str(row.get("fullName") or row.get("Player") or "").strip()
        if name:
            names.add(name.lower())
    return ids, names


def filter_df_excluding_drafted(df: Any, room: dict[str, Any] | None) -> Any:
    """Drop every drafted player from a recommendation/available table (id then name)."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    ids, names = drafted_identity_sets(room)
    if not ids and not names:
        return df
    out = df
    if ids and "playerID" in out.columns:
        out = out[~out["playerID"].astype(str).str.strip().isin(ids)]
        out = out[~out["playerID"].astype(str).str.strip().str.lower().isin(ids)]
    if ids and "player_id" in out.columns:
        out = out[~out["player_id"].astype(str).str.strip().isin(ids)]
        out = out[~out["player_id"].astype(str).str.strip().str.lower().isin(ids)]
    name_col = "fullName" if "fullName" in out.columns else ("Player" if "Player" in out.columns else "")
    if names and name_col:
        out = out[~out[name_col].astype(str).str.strip().str.lower().isin(names)]
    return out


def filter_recommendation_tables_for_drafted(
    room: dict[str, Any] | None,
    top_rec: Any,
    best_avail: Any,
    pos_fit: Any,
    value_sleep: Any,
) -> tuple[Any, Any, Any, Any]:
    """Safety filter before paint — never show a drafted player as a recommendation."""
    return (
        filter_df_excluding_drafted(top_rec, room),
        filter_df_excluding_drafted(best_avail, room),
        filter_df_excluding_drafted(pos_fit, room),
        filter_df_excluding_drafted(value_sleep, room),
    )


def patch_live_draft_caches_after_pick(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    player_id: str = "",
    player_name: str = "",
    top_n: int = 10,
) -> None:
    """Keep prior recommendations visible minus every drafted player (board-authoritative).

    Updates the cache key to the post-pick board fingerprint so the next paint hits
    without a full rescoring pass.
    """
    if not isinstance(session, dict) or not isinstance(room, dict):
        return
    entry = session.get(REC_CACHE_KEY)
    if isinstance(entry, dict):
        top = _filter_player_from_df(entry.get("top_rec"), player_id=player_id, player_name=player_name)
        best = _filter_player_from_df(entry.get("best_avail"), player_id=player_id, player_name=player_name)
        pos = _filter_player_from_df(entry.get("pos_fit"), player_id=player_id, player_name=player_name)
        sleep = _filter_player_from_df(entry.get("value_sleep"), player_id=player_id, player_name=player_name)
        top, best, pos, sleep = filter_recommendation_tables_for_drafted(room, top, best, pos, sleep)
        patched = {
            "key": live_draft_ui_cache_key(session, room, top_n=top_n, team=None),
            "top_rec": top,
            "best_avail": best,
            "pos_fit": pos,
            "value_sleep": sleep,
            "optimistic_hold": True,
        }
        session[REC_CACHE_KEY] = patched
    else:
        # No prior tables — leave miss path for a later deferred refresh.
        session.pop(REC_CACHE_KEY, None)

    avail = session.get(AVAILABLE_CACHE_KEY)
    if isinstance(avail, dict) and isinstance(avail.get("df"), pd.DataFrame):
        df = _filter_player_from_df(avail.get("df"), player_id=player_id, player_name=player_name)
        session[AVAILABLE_CACHE_KEY] = {
            "key": available_pool_cache_key(room),
            "df": filter_df_excluding_drafted(df, room),
        }
    else:
        session.pop(AVAILABLE_CACHE_KEY, None)

    # Decision / why stale relative to new roster — drop without forcing full score now.
    session.pop(DECISION_CACHE_KEY, None)
    session.pop(WHY_COLUMN_CACHE_KEY, None)


def invalidate_draft_assistant_scoring_cache(session: dict[str, Any] | None) -> None:
    if session:
        session.pop(DA_SCORING_CACHE_KEY, None)
        session.pop(DA_WHY_CACHE_KEY, None)


def invalidate_draft_assistant_why_cache(session: dict[str, Any] | None) -> None:
    if session:
        session.pop(DA_WHY_CACHE_KEY, None)


def invalidate_draft_assistant_ui_caches(session: dict[str, Any] | None) -> None:
    """Clear Draft Assistant scoring + why-text caches after settings or board changes."""
    if not session:
        return
    invalidate_draft_assistant_scoring_cache(session)
    invalidate_draft_assistant_why_cache(session)


def draft_assistant_pool_revision(session: dict[str, Any]) -> tuple[Any, ...]:
    """Fingerprint for unified projection pool inputs (@st.cache_data 7-arg key + canonical stamp)."""
    try:
        from shared_draft_context import draft_pool_kwargs_from_session, read_canonical_draft_settings

        kw = draft_pool_kwargs_from_session(session)
        canon = read_canonical_draft_settings(session)
    except ImportError:
        return ()
    try:
        max_y = int(session.get("_lahman_max_year") or 0)
    except (TypeError, ValueError):
        max_y = 0
    return (
        max_y,
        int(kw.get("draft_window") or 0),
        str(kw.get("fantasy_format") or ""),
        str(kw.get("projection_style") or ""),
        bool(kw.get("use_ml_blend")),
        float(kw.get("ml_blend_weight") or 0),
        int(kw.get("ml_min_games_for_signal") or 0),
        str(canon.get("updated_at") or ""),
    )


def draft_assistant_board_revision(session: dict[str, Any]) -> tuple[Any, ...]:
    """Fingerprint for draft board state feeding recommendations."""
    pick_count = 0
    try:
        from draft_room_state import effective_board_pick_count

        pick_count = int(effective_board_pick_count(session))
    except ImportError:
        pass
    rev = str(session.get("_canonical_live_sync_revision") or "").strip()
    try:
        adj = int(session.get("draft_pick_adjustment") or 0)
    except (TypeError, ValueError):
        adj = 0
    team = str(
        session.get("draft_assistant_synced_team")
        or session.get("room_your_team")
        or ""
    ).strip()
    return (pick_count, rev, adj, team)


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
    drafted_ids, drafted_names = drafted_identity_sets(room)
    drafted_sig = (
        tuple(sorted(i for i in drafted_ids if i == i.lower() or " " not in i)[:64]),
        tuple(sorted(drafted_names)[:64]),
    )
    return (idx, board_len, team_s, int(top_n), slots_key, rev, scoring, roster_sig, pool_sig, drafted_sig)


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
    from table_dataframe_guard import ensure_dataframe

    def _enrich_one(df: Any) -> pd.DataFrame:
        return ensure_dataframe(
            add_why_this_pick_column(
                ensure_dataframe(df, caller="enrich_why.input"),
                gaps=gaps,
                category_needs=category_needs,
                pool_df=pool_df,
                config=config,
            ),
            caller="enrich_why.output",
        )

    if ui_cache_key is None:
        return {name: _enrich_one(df) for name, df in tables.items()}
    entry = session.get(WHY_COLUMN_CACHE_KEY)
    if isinstance(entry, dict) and entry.get("key") == ui_cache_key:
        stored = entry.get("tables")
        if isinstance(stored, dict) and all(name in stored for name in tables):
            try:
                from page_perf_phases import record_cache_event

                record_cache_event(session, "live_draft_why_columns", hit=True)
            except ImportError:
                pass
            return {name: ensure_dataframe(stored[name], caller="enrich_why.cache_hit") for name in tables}
    try:
        from page_perf_phases import record_cache_event

        record_cache_event(session, "live_draft_why_columns", hit=False)
    except ImportError:
        pass
    enriched: dict[str, pd.DataFrame] = {name: _enrich_one(df) for name, df in tables.items()}
    session[WHY_COLUMN_CACHE_KEY] = {
        "key": ui_cache_key,
        "tables": {name: frame.copy() for name, frame in enriched.items()},
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
    research_sig: Any = None,
) -> tuple[Any, ...]:
    slots_key = tuple(sorted((k, int(v or 0)) for k, v in (target_counts or {}).items()))
    lookback = 0
    projection_style = ""
    fantasy_fmt = str(draft_format)
    try:
        from shared_draft_context import read_canonical_draft_settings

        canon = read_canonical_draft_settings(session)
        lookback = int(canon.get("lookback_window") or 0)
        projection_style = str(canon.get("projection_style") or "")
        fantasy_fmt = str(canon.get("fantasy_format") or draft_format)
    except ImportError:
        lookback = int(session.get("draft_window") or 0)
        projection_style = str(session.get("fantasy_draft_projection_style") or "")
    return (
        frozenset(str(n).strip().lower() for n in drafted_names if str(n).strip()),
        tuple(sorted(str(n) for n in my_roster)),
        int(current_pick),
        tuple(needed_positions or []),
        tuple(category_needs or []),
        slots_key,
        str(fantasy_fmt),
        int(lookback),
        str(projection_style),
        bool(use_ml_blend),
        float(ml_blend_weight or 0),
        int(draft_top_n),
        draft_assistant_pool_revision(session),
        draft_assistant_board_revision(session),
        research_sig,
    )


def enrich_draft_assistant_recs_with_why(
    session: dict[str, Any],
    scoring_cache_key: tuple[Any, ...] | None,
    recs_df: pd.DataFrame,
    *,
    needed_positions: list[str] | None = None,
    category_needs: list[str] | None = None,
    pool_df: Any = None,
    draft_format: str = "5x5 Roto",
) -> pd.DataFrame:
    """Cache expensive Why-this-pick column enrichment across Draft Assistant reruns."""
    from live_draft_room_ui import build_draft_assistant_why_this_pick

    if recs_df is None or recs_df.empty:
        return recs_df
    if scoring_cache_key is None:
        out = recs_df.copy()
        out["Why this pick"] = out.apply(
            lambda r: build_draft_assistant_why_this_pick(
                r,
                needed_positions=needed_positions,
                category_needs=category_needs,
                pool_df=pool_df,
                draft_format=draft_format,
            ),
            axis=1,
        )
        return out
    entry = session.get(DA_WHY_CACHE_KEY)
    if isinstance(entry, dict) and entry.get("key") == scoring_cache_key:
        stored = entry.get("df")
        if isinstance(stored, pd.DataFrame) and len(stored) == len(recs_df):
            try:
                from page_perf_phases import record_cache_event

                record_cache_event(session, "draft_assistant_why_text", hit=True)
            except ImportError:
                pass
            return stored.copy()
    try:
        from page_perf_phases import record_cache_event

        record_cache_event(session, "draft_assistant_why_text", hit=False)
    except ImportError:
        pass
    out = recs_df.copy()
    out["Why this pick"] = out.apply(
        lambda r: build_draft_assistant_why_this_pick(
            r,
            needed_positions=needed_positions,
            category_needs=category_needs,
            pool_df=pool_df,
            draft_format=draft_format,
        ),
        axis=1,
    )
    session[DA_WHY_CACHE_KEY] = {"key": scoring_cache_key, "df": out.copy()}
    return out.copy()
