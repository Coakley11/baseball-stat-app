#!/usr/bin/env python3
"""Draft Assistant Simulator baseline profiling (pre-optimization).

Run from repo root:
  python scripts/profile_draft_assistant_baseline.py

Simulates Draft Assistant hot paths without a full Streamlit rerun.
Uses draft_pool_engine for canonical pool/scoring (same code as the app).
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

MY_TEAM = "Daniel"
PAGE = "Draft Assistant Simulator"
_POOL_MEM_CACHE: dict[tuple, pd.DataFrame] = {}


def _pool_cache_key(session: dict) -> tuple:
    kw = _pool_kwargs(session)
    try:
        max_y = int(session.get("_lahman_max_year") or 0)
    except (TypeError, ValueError):
        max_y = 0
    return (
        max_y,
        int(kw["draft_window"]),
        str(kw["fantasy_format"]),
        str(kw["projection_style"]),
        bool(kw["use_ml_blend"]),
        float(kw["ml_blend_weight"]),
        int(kw["ml_min_games_for_signal"]),
    )


def _build_pool_cached(session: dict, yearly, market, *, label: str = "cold") -> pd.DataFrame:
    """Build pool; reuse in-memory entry when args match (@st.cache_data simulation)."""
    from draft_assistant_perf import PHASE_DA_PROJECTION_POOL, record_draft_assistant_cache_action
    from page_perf_phases import session_perf_phase

    key = _pool_cache_key(session)
    hit = key in _POOL_MEM_CACHE
    if hit:
        record_draft_assistant_cache_action(
            session, "projection_pool", phase=PHASE_DA_PROJECTION_POOL, hit=True, elapsed_sec=0.0
        )
        return _POOL_MEM_CACHE[key].copy()
    record_draft_assistant_cache_action(
        session, "projection_pool", phase=PHASE_DA_PROJECTION_POOL, hit=False
    )
    t0 = time.perf_counter()
    df = _build_pool(session, yearly, market)
    elapsed = time.perf_counter() - t0
    _POOL_MEM_CACHE[key] = df.copy()
    record_draft_assistant_cache_action(
        session, f"projection_pool_{label}", phase=PHASE_DA_PROJECTION_POOL, hit=False, elapsed_sec=elapsed
    )
    return df.copy()


def _fresh_session(*, pick_count: int = 36) -> dict:
    session: dict = {
        "_page_perf_ns": {"page": PAGE, "timings": {}, "started_at": time.perf_counter()},
        "active_page": PAGE,
        "main_sidebar_page": PAGE,
        "page_filter_state": {},
        "draft_window": 3,
        "draft_format": "5x5 Roto",
        "draft_top_n": 10,
        "fantasy_draft_projection_style": "Balanced",
        "draft_use_ml_blend": True,
        "draft_ml_blend_weight": 0.12,
        "draft_ml_min_games_signal": 50,
        "room_your_team": MY_TEAM,
        "room_team_count": 12,
        "room_format": "5x5 Roto",
        "room_window": 3,
        "draft_assistant_synced_team": MY_TEAM,
        "sync_draft_assistant_position_needs": False,
        "draft_pick_adjustment": 0,
        "live_slot_c": 1,
        "live_slot_1b": 1,
        "live_slot_2b": 1,
        "live_slot_3b": 1,
        "live_slot_ss": 1,
        "live_slot_of": 3,
        "live_slot_dh": 1,
        "live_slot_p": 5,
        "live_slot_bench": 3,
        "_pick_count_fixture": int(pick_count),
    }
    return session


def _mock_st(session: dict) -> MagicMock:
    st = MagicMock()
    st.session_state = session
    return st


@lru_cache(maxsize=1)
def _load_data():
    from draft_pool_engine import load_draft_market_data, load_yearly_stat_data

    t0 = time.perf_counter()
    yearly = load_yearly_stat_data()
    market = load_draft_market_data()
    return yearly, market, (time.perf_counter() - t0) * 1000.0


def _pool_kwargs(session: dict) -> dict:
    from shared_draft_context import draft_pool_kwargs_from_session

    return dict(draft_pool_kwargs_from_session(session))


def _build_pool(session: dict, yearly, market) -> pd.DataFrame:
    from draft_pool_engine import build_unified_draft_player_pool
    from draft_assistant_perf import PHASE_DA_PROJECTION_POOL
    from page_perf_phases import session_perf_phase

    kw = _pool_kwargs(session)
    with session_perf_phase(session, PHASE_DA_PROJECTION_POOL):
        return build_unified_draft_player_pool(yearly, market, **kw)


def _build_board(pool: pd.DataFrame, *, pick_count: int, my_team: str = MY_TEAM) -> pd.DataFrame:
    from draft_room_state import build_snake_board

    teams = [f"Team {i}" for i in range(1, 13)]
    if my_team not in teams:
        teams[0] = my_team
    board = build_snake_board(teams, rounds=20)
    names = pool["fullName"].dropna().astype(str).tolist() if "fullName" in pool.columns else []
    for i in range(min(pick_count, len(board), len(names))):
        board.at[i, "Player"] = names[i]
        if i % 12 == 0:
            board.at[i, "Team"] = my_team
    return board


def _install_board(session: dict, board: pd.DataFrame) -> None:
    from draft_room_state import DRAFT_ROOM_TABLE_KEY, write_canonical_draft_room_state

    session[DRAFT_ROOM_TABLE_KEY] = board.copy()
    write_canonical_draft_room_state(session, board, reason="da_profile_fixture", local_edit=False)


def _board_hydrate(session: dict) -> pd.DataFrame:
    from draft_assistant_perf import PHASE_DA_BOARD_HYDRATE
    from draft_room_state import get_canonical_draft_board
    from page_perf_phases import session_perf_phase

    with session_perf_phase(session, PHASE_DA_BOARD_HYDRATE):
        return get_canonical_draft_board(session)


def _shared_context_prep(session: dict) -> None:
    from draft_assistant_perf import PHASE_DA_SHARED_CONTEXT
    from live_draft_perf import PHASE_SETUP_SHARED_CONTEXT, live_draft_perf_action
    from shared_draft_context import prepare_shared_draft_context

    with live_draft_perf_action(session, "shared_context", phase=PHASE_SETUP_SHARED_CONTEXT):
        with live_draft_perf_action(session, "da_shared_context", phase=PHASE_DA_SHARED_CONTEXT):
            prepare_shared_draft_context(session, active_page=PAGE, force_mirror=True)


def _settings_onchange(session: dict, st: MagicMock, *, field: str, value: object) -> None:
    from draft_assistant_setup_persist import on_draft_assistant_settings_changed

    session[field] = value
    on_draft_assistant_settings_changed(session)


def _roster_from_board(board: pd.DataFrame, my_team: str) -> tuple[list[str], list[str]]:
    if board.empty or "Player" not in board.columns:
        return [], []
    my_roster = (
        board[board["Team"].astype(str) == str(my_team)]["Player"].dropna().astype(str).tolist()
    )
    drafted = (
        board[board["Team"].astype(str) != str(my_team)]["Player"].dropna().astype(str).tolist()
    )
    my_roster = sorted(list(dict.fromkeys(p for p in my_roster if p.strip())))
    drafted = sorted(list(dict.fromkeys(p for p in drafted if p.strip())))
    return my_roster, drafted


def _infer_needs(roster_df: pd.DataFrame, pool: pd.DataFrame, session: dict) -> tuple[list[str], list[str], dict]:
    from draft_ami_helpers import infer_draft_assistant_needs
    from live_draft_roster_slots import (
        get_required_position_counts,
        position_codes_in_slot_order,
        resolve_draft_slot_config_from_session,
    )

    slot_cfg = resolve_draft_slot_config_from_session(session)
    target_counts = get_required_position_counts(slot_cfg) if slot_cfg.get("slots") else {}
    pos_opts = position_codes_in_slot_order(slot_cfg) if slot_cfg.get("slots") else []
    fmt = str(session.get("draft_format") or "5x5 Roto")
    needed, cats = infer_draft_assistant_needs(roster_df, pool, draft_format=fmt, config=slot_cfg)
    needed = [p for p in needed if p in pos_opts] if pos_opts else needed
    return needed, cats, target_counts


def _score_available(
    session: dict,
    pool: pd.DataFrame,
    board: pd.DataFrame,
    *,
    cache_label: str = "miss",
) -> dict:
    from draft_assistant_perf import (
        PHASE_DA_CATEGORY_ANALYSIS,
        PHASE_DA_SCORING,
        draft_assistant_perf_action,
        record_draft_assistant_cache_action,
    )
    from draft_pool_engine import apply_draft_pick_scoring
    from draft_room_state import draft_board_summary_for_team
    from live_draft_roster_slots import resolve_draft_slot_config_from_session
    from live_draft_ui_cache import DA_SCORING_CACHE_KEY, draft_assistant_scoring_cache_key
    from page_perf_phases import session_perf_phase

    my_team = str(session.get("draft_assistant_synced_team") or MY_TEAM)
    my_roster, drafted = _roster_from_board(board, my_team)
    owned = set(drafted).union(set(my_roster))
    available = pool[~pool["fullName"].isin(owned)].copy()
    roster_df = pool[pool["fullName"].isin(set(my_roster))].copy()
    teams = [f"Team {i}" for i in range(1, int(session.get("room_team_count") or 12) + 1)]
    if my_team not in teams:
        teams[0] = my_team
    summary = draft_board_summary_for_team(
        board,
        your_team=my_team,
        team_names=teams,
        pick_adjustment=int(session.get("draft_pick_adjustment") or 0),
        num_teams=int(session.get("room_team_count") or 12),
    )
    needed, cats, target_counts = _infer_needs(roster_df, pool, session)
    kw = _pool_kwargs(session)
    cache_key = draft_assistant_scoring_cache_key(
        session,
        drafted_names=owned,
        my_roster=my_roster,
        current_pick=int(summary["current_pick"]),
        needed_positions=needed,
        category_needs=cats,
        target_counts=target_counts,
        draft_format=str(session.get("draft_format") or "5x5 Roto"),
        use_ml_blend=bool(kw.get("use_ml_blend")),
        ml_blend_weight=float(kw.get("ml_blend_weight") or 0),
        draft_top_n=int(session.get("draft_top_n") or 10),
    )
    entry = session.get(DA_SCORING_CACHE_KEY)
    if isinstance(entry, dict) and entry.get("key") == cache_key:
        record_draft_assistant_cache_action(
            session, "scoring", phase=PHASE_DA_SCORING, hit=True, elapsed_sec=0.0
        )
        return {
            "available": entry["available"].copy(),
            "recs_ranked": entry["recs_ranked"].copy(),
            "gaps": list(entry.get("gaps") or []),
            "position_summary_rows": list(entry.get("position_summary_rows") or []),
            "cache": "hit",
            "cache_key": cache_key,
        }

    slot_cfg = resolve_draft_slot_config_from_session(session)
    score_room = {"config": slot_cfg} if slot_cfg.get("slots") else None
    t0 = time.perf_counter()
    record_draft_assistant_cache_action(session, "scoring", phase=PHASE_DA_SCORING, hit=False)
    with draft_assistant_perf_action(session, "scoring", phase=PHASE_DA_SCORING, cache=cache_label):
        with session_perf_phase(session, PHASE_DA_CATEGORY_ANALYSIS):
            scored, gaps, pos_rows = apply_draft_pick_scoring(
                available,
                roster_df,
                fantasy_format=str(session.get("draft_format") or "5x5 Roto"),
                target_counts=target_counts,
                current_pick=int(summary["current_pick"]),
                category_needs=cats,
                needed_positions=needed,
                use_ml_blend=bool(kw.get("use_ml_blend")),
                ml_blend_weight=float(kw.get("ml_blend_weight") or 0),
                return_position_summary=True,
                recommendation_mode="draft_fit",
                room=score_room,
            )
    elapsed = time.perf_counter() - t0
    recs = scored.sort_values("Draft Fit Score", ascending=False).copy()
    session[DA_SCORING_CACHE_KEY] = {
        "key": cache_key,
        "available": scored.copy(),
        "gaps": list(gaps or []),
        "position_summary_rows": list(pos_rows or []),
        "recs_ranked": recs.copy(),
    }
    return {
        "available": scored,
        "recs_ranked": recs,
        "gaps": gaps,
        "position_summary_rows": pos_rows,
        "cache": "miss",
        "elapsed_sec": elapsed,
        "cache_key": cache_key,
    }


def _build_why_text(
    session: dict,
    recs: pd.DataFrame,
    available: pd.DataFrame,
    needed,
    cats,
    *,
    scoring_cache_key: tuple | None = None,
) -> pd.DataFrame:
    from draft_assistant_perf import PHASE_DA_WHY_TEXT
    from live_draft_ui_cache import enrich_draft_assistant_recs_with_why
    from page_perf_phases import session_perf_phase

    top = recs.head(int(session.get("draft_top_n") or 10)).copy()
    if top.empty:
        return top
    fmt = str(session.get("draft_format") or "5x5 Roto")
    with session_perf_phase(session, PHASE_DA_WHY_TEXT):
        return enrich_draft_assistant_recs_with_why(
            session,
            scoring_cache_key,
            top,
            needed_positions=needed,
            category_needs=cats,
            pool_df=available,
            draft_format=fmt,
        )


def _prep_rec_table(recs: pd.DataFrame) -> pd.DataFrame:
    rec_cols = [
        "fullName",
        "Team",
        "Primary Position",
        "Age",
        "Market Rank",
        "Model Rank",
        "Fantasy Edge",
        "ML Projection Score",
        "Expected Fantasy Value",
        "Decision Score",
        "Draft Fit Score",
        "Why this pick",
    ]
    out = recs[[c for c in rec_cols if c in recs.columns]].rename(columns={"fullName": "Player"})
    return out


def _cache_summary(audit: list) -> dict[str, dict[str, int]]:
    totals: Counter[str] = Counter()
    hits: Counter[str] = Counter()
    for row in audit:
        label = str(row.get("label") or "")
        if not label:
            continue
        totals[label] += 1
        if row.get("hit"):
            hits[label] += 1
    return {
        label: {"hit": hits[label], "miss": totals[label] - hits[label], "total": totals[label]}
        for label in sorted(totals)
    }


def _action_ms(actions: list, *, phase: str = "", cache: str = "") -> list[float]:
    out: list[float] = []
    for row in actions:
        if phase and row.get("phase") != phase:
            continue
        if cache and row.get("cache") != cache:
            continue
        out.append(float(row.get("elapsed_ms") or 0.0))
    return out


def _run_baseline(*, pick_count: int = 36) -> dict:
    from draft_assistant_perf import (
        PHASE_DA_NAV_RETURN,
        PHASE_DA_PROJECTION_POOL,
        PHASE_DA_ROSTER_CHANGE,
        PHASE_DA_TABLE_PREP,
        PHASE_DA_WHY_TEXT,
        draft_assistant_perf_action,
        recent_draft_assistant_actions,
        summarize_draft_assistant_phases,
    )
    from draft_assistant_perf import draft_assistant_phase_total_ms
    from live_draft_ui_cache import DA_SCORING_CACHE_KEY, invalidate_draft_assistant_scoring_cache

    yearly, market, data_load_ms = _load_data()
    session = _fresh_session(pick_count=pick_count)
    st = _mock_st(session)
    session2: dict = {}
    pool_cold = pd.DataFrame()
    score_cold: dict = {}
    score_warm: dict = {}

    patches = [
        patch("page_perf_phases.dev_perf_enabled", return_value=True),
        patch("suite_user_persistence.force_autosave", return_value=True),
    ]
    for p in patches:
        p.start()

    scenario_walls: dict[str, float] = {}
    try:
        # 1) Initial page load (cold pool)
        t0 = time.perf_counter()
        _shared_context_prep(session)
        pool_cold = _build_pool_cached(session, yearly, market, label="cold")
        board = _build_board(pool_cold, pick_count=pick_count)
        _install_board(session, board)
        _board_hydrate(session)
        score_cold = _score_available(session, pool_cold, board)
        scenario_walls["1_initial_load_cold_ms"] = (time.perf_counter() - t0) * 1000.0

        # Warm pool (@st.cache_data simulation — same 7-arg key)
        t0 = time.perf_counter()
        pool_warm = _build_pool_cached(session, yearly, market, label="warm")
        scenario_walls["1_projection_pool_warm_ms"] = (time.perf_counter() - t0) * 1000.0

        # Warm scoring cache
        t0 = time.perf_counter()
        score_warm = _score_available(session, pool_warm, board)
        scenario_walls["1_scoring_cache_warm_ms"] = (time.perf_counter() - t0) * 1000.0

        needed, cats, _ = _infer_needs(
            pool_cold[pool_cold["fullName"].isin(_roster_from_board(board, MY_TEAM)[0])],
            pool_cold,
            session,
        )
        _why_key = score_cold.get("cache_key")
        t0 = time.perf_counter()
        with draft_assistant_perf_action(session, "why_text", phase=PHASE_DA_WHY_TEXT):
            recs_with_why = _build_why_text(
                session,
                score_cold["recs_ranked"],
                score_cold["available"],
                needed,
                cats,
                scoring_cache_key=_why_key,
            )
        scenario_walls["why_text_cold_ms"] = (time.perf_counter() - t0) * 1000.0
        t0 = time.perf_counter()
        _build_why_text(
            session,
            score_cold["recs_ranked"],
            score_cold["available"],
            needed,
            cats,
            scoring_cache_key=_why_key,
        )
        scenario_walls["why_text_cached_ms"] = (time.perf_counter() - t0) * 1000.0
        with draft_assistant_perf_action(session, "table_prep", phase=PHASE_DA_TABLE_PREP):
            _prep_rec_table(recs_with_why)

        # 2) Settings change (deferred persist — no force_save on widget edit)
        session2 = _fresh_session(pick_count=pick_count)
        st2 = _mock_st(session2)
        _install_board(session2, board)
        _shared_context_prep(session2)
        _build_pool_cached(session2, yearly, market)
        t0 = time.perf_counter()
        _settings_onchange(session2, st2, field="draft_window", value=5)
        scenario_walls["2_settings_change_ms"] = (time.perf_counter() - t0) * 1000.0
        # Pool args changed — cache miss on next build
        _POOL_MEM_CACHE.clear()

        # 3) Recommendation refresh — scoring cache hit after identical inputs
        session3 = _fresh_session(pick_count=pick_count)
        _install_board(session3, board)
        pool3 = _build_pool_cached(session3, yearly, market)
        _score_available(session3, pool3, board)
        t0 = time.perf_counter()
        _score_available(session3, pool3, board)
        scenario_walls["3_recommendation_refresh_cached_ms"] = (time.perf_counter() - t0) * 1000.0

        # 4) Scoring refresh — cache miss after roster change
        session4 = _fresh_session(pick_count=pick_count)
        board4 = _build_board(pool_cold, pick_count=pick_count + 1)
        _install_board(session4, board4)
        pool4 = _build_pool_cached(session4, yearly, market)
        _score_available(session4, pool4, board4)
        invalidate_draft_assistant_scoring_cache(session4)
        t0 = time.perf_counter()
        _score_available(session4, pool4, board4)
        scenario_walls["4_scoring_refresh_miss_ms"] = (time.perf_counter() - t0) * 1000.0

        # 5) Projection change — new window rebuilds pool (cache key not in scoring cache)
        session5 = _fresh_session(pick_count=pick_count)
        session5["draft_window"] = 5
        _install_board(session5, board)
        _POOL_MEM_CACHE.clear()
        t0 = time.perf_counter()
        pool_new_window = _build_pool_cached(session5, yearly, market, label="window_change")
        _score_available(session5, pool_new_window, board)
        scenario_walls["5_projection_change_ms"] = (time.perf_counter() - t0) * 1000.0

        # 6) Roster/team change
        session6 = _fresh_session(pick_count=pick_count)
        _install_board(session6, board)
        pool6 = _build_pool_cached(session6, yearly, market)
        _score_available(session6, pool6, board)
        with draft_assistant_perf_action(session6, "roster_change", phase=PHASE_DA_ROSTER_CHANGE):
            board6 = _build_board(pool6, pick_count=pick_count + 3)
            _install_board(session6, board6)
            invalidate_draft_assistant_scoring_cache(session6)
            _score_available(session6, pool6, board6)
        scenario_walls["6_roster_change_ms"] = _action_ms(
            recent_draft_assistant_actions(session6), phase=PHASE_DA_ROSTER_CHANGE
        )[-1] if recent_draft_assistant_actions(session6) else 0.0

        # 7) Navigation back — warm session re-entry
        session7 = session.copy()
        session7["_page_perf_ns"] = {"page": PAGE, "timings": {}, "started_at": time.perf_counter()}
        session7[DA_SCORING_CACHE_KEY] = session.get(DA_SCORING_CACHE_KEY)
        with draft_assistant_perf_action(session7, "nav_return", phase=PHASE_DA_NAV_RETURN):
            _shared_context_prep(session7)
            pool7 = _build_pool_cached(session7, yearly, market, label="nav_warm")
            _board_hydrate(session7)
            _score_available(session7, pool7, board)
        scenario_walls["7_nav_return_ms"] = _action_ms(
            recent_draft_assistant_actions(session7), phase=PHASE_DA_NAV_RETURN
        )[-1] if recent_draft_assistant_actions(session7) else 0.0

    finally:
        for p in patches:
            p.stop()

    timings = dict(session.get("_page_perf_ns", {}).get("timings") or {})
    actions = recent_draft_assistant_actions(session, limit=32)
    audit = list(session.get("_page_perf_cache_audit") or [])

    return {
        "pick_count": pick_count,
        "pool_size": len(pool_cold),
        "data_load_ms": data_load_ms,
        "scenario_walls_ms": scenario_walls,
        "top_phases": summarize_draft_assistant_phases(session, limit=16),
        "instrumented_total_ms": draft_assistant_phase_total_ms(session),
        "timings_ms": {k: round(v * 1000.0, 2) for k, v in timings.items()},
        "actions": actions,
        "cache_audit": _cache_summary(audit),
        "score_cold_cache": score_cold.get("cache", ""),
        "score_warm_cache": score_warm.get("cache", ""),
        "pool_cold_rows": len(pool_cold),
        "action_summary": {
            "settings_onchange_ms": _action_ms(actions, phase="draft_assistant_settings_onchange"),
            "force_save_ms": _action_ms(actions, phase="draft_assistant_force_save"),
            "page_state_save_ms": _action_ms(actions, phase="draft_assistant_page_state_save"),
            "scoring_cold_ms": _action_ms(actions, phase="draft_assistant_scoring", cache="miss"),
            "scoring_warm_ms": _action_ms(actions, phase="draft_assistant_scoring", cache="hit"),
            "why_text_ms": _action_ms(actions, phase=PHASE_DA_WHY_TEXT),
            "table_prep_ms": _action_ms(actions, phase=PHASE_DA_TABLE_PREP),
            "board_hydrate_ms": _action_ms(actions, phase="draft_assistant_board_hydrate"),
            "shared_context_ms": _action_ms(actions, phase="draft_assistant_shared_context"),
            "projection_pool_ms": _action_ms(actions, phase=PHASE_DA_PROJECTION_POOL),
        },
        "settings_session2_actions": recent_draft_assistant_actions(session2, limit=12) if session2 else [],
    }


def main() -> int:
    print("=== Draft Assistant Simulator — baseline profiling ===\n")
    print("Loading Lahman + market data (one-time)...")
    report = _run_baseline(pick_count=36)
    print(f"Data load: {report['data_load_ms']:.0f} ms")
    print(f"Pool size: {report.get('pool_cold_rows', 0)} players ({report['pick_count']} picks on board)\n")

    walls = report.get("scenario_walls_ms") or {}
    print("--- Scenario wall times ---")
    labels = [
        ("1_initial_load_cold_ms", "Initial page load (cold pool + scoring)"),
        ("1_projection_pool_warm_ms", "Projection pool rebuild (warm / same args)"),
        ("1_scoring_cache_warm_ms", "Scoring cache hit (same board)"),
        ("2_settings_change_ms", "Settings change (deferred — no force_save)"),
        ("why_text_cold_ms", "Why-this-pick text (cold)"),
        ("why_text_cached_ms", "Why-this-pick text (cached)"),
        ("3_recommendation_refresh_cached_ms", "Recommendation refresh (cached scoring)"),
        ("4_scoring_refresh_miss_ms", "Scoring refresh (board changed, cache miss)"),
        ("5_projection_change_ms", "Projection window change (pool + scoring)"),
        ("6_roster_change_ms", "Roster change (+3 picks, rescoring)"),
        ("7_nav_return_ms", "Navigation back (warm pool + cached scoring)"),
    ]
    for key, label in labels:
        val = walls.get(key)
        if val is not None:
            print(f"  {label}: {val:.1f} ms")

    print("\n--- 1. Top slowest Draft Assistant phases ---")
    for i, (name, sec) in enumerate(report.get("top_phases") or [], start=1):
        print(f"  {i}. {name}: {sec * 1000:.1f} ms")

    s = report.get("action_summary") or {}
    print("\n--- 2. Cold vs warm ---")
    pool_cold_ms = walls.get("1_initial_load_cold_ms", 0)
    pool_warm_ms = walls.get("1_projection_pool_warm_ms", 0)
    score_cold = (s.get("scoring_cold_ms") or [0])
    score_cold_ms = score_cold[-1] if score_cold else 0
    score_warm_ms = walls.get("1_scoring_cache_warm_ms", 0)
    print(f"  Projection pool build: ~{pool_cold_ms:.0f} ms first load (includes scoring + context)")
    print(f"  Projection pool @st.cache_data hit: ~{pool_warm_ms:.0f} ms (same 7-arg key)")
    print(f"  Recommendation scoring: cold ~{score_cold_ms:.0f} ms vs cached ~{score_warm_ms:.0f} ms")
    settings_ms = walls.get("2_settings_change_ms", 0)
    s2_actions = report.get("settings_session2_actions") or []
    force_ms = next(
        (float(a.get("elapsed_ms") or 0) for a in s2_actions if a.get("phase") == "draft_assistant_force_save"),
        0.0,
    )
    print(f"  Settings on_change total: ~{settings_ms:.0f} ms (force_save ~{force_ms:.0f} ms)")

    print("\n--- 3. Cache hit/miss ---")
    audit = report.get("cache_audit") or {}
    if audit:
        for label, counts in audit.items():
            total = counts["total"]
            pct = 100.0 * counts["hit"] / total if total else 0
            print(f"  {label}: {pct:.0f}% hit ({counts['hit']}/{total})")
    else:
        print("  (no cache events)")

    print("\n--- 4. Slice 1 status (post-optimization) ---")
    print("  * Settings on_change: deferred persist (dirty flag; flush on page leave / 3s debounce)")
    print("  * Scoring cache key: includes window, style, format, pool revision, board revision")
    print("  * Why-this-pick: session cache keyed on scoring cache key")
    print("  * Board hydrate + projection pool rewrite: unchanged this slice")

    print("\n--- 5. Estimated user impact ---")
    init_ms = walls.get("1_initial_load_cold_ms", 0)
    settings_ms = walls.get("2_settings_change_ms", 0)
    if init_ms > 3000:
        print(f"  * Initial visit: ~{init_ms/1000:.1f}s before recommendations — dominant cost is projection pool + scoring")
    elif init_ms > 0:
        print(f"  * Initial visit: ~{init_ms/1000:.1f}s — acceptable locally; scales with pool size on Cloud")
    if settings_ms > 500:
        print(f"  * Each settings tweak triggers ~{settings_ms/1000:.1f}s persist path — feels laggy on every slider/select")
    elif settings_ms > 0:
        print(f"  * Settings widget on_change: ~{settings_ms:.0f}ms (deferred; flush on page leave)")
    why_cold = walls.get("why_text_cold_ms", 0)
    why_warm = walls.get("why_text_cached_ms", 0)
    if why_cold > 0:
        print(f"  * Why-this-pick: cold ~{why_cold:.0f}ms vs cached ~{why_warm:.0f}ms per rerun")

    print("\n--- 6. Before / after (slice 1 targets) ---")
    before = {
        "settings_change_ms": 978.0,
        "why_text_cold_ms": 501.0,
        "why_text_cached_ms": 501.0,
        "recommendation_refresh_ms": 31.9,
        "nav_return_ms": 51.4,
    }
    after = {
        "settings_change_ms": settings_ms,
        "why_text_cold_ms": why_cold,
        "why_text_cached_ms": why_warm,
        "recommendation_refresh_ms": walls.get("3_recommendation_refresh_cached_ms", 0),
        "nav_return_ms": walls.get("7_nav_return_ms", 0),
    }
    for label, key in [
        ("Settings change", "settings_change_ms"),
        ("Why-text cold", "why_text_cold_ms"),
        ("Why-text cached", "why_text_cached_ms"),
        ("Recommendation refresh", "recommendation_refresh_ms"),
        ("Navigation back", "nav_return_ms"),
    ]:
        b = before[key]
        a = after[key]
        delta = b - a
        print(f"  {label}: {b:.0f} ms -> {a:.0f} ms ({delta:+.0f} ms)")

    print("\n--- 7. Recommended next optimization targets ---")
    targets: list[tuple[str, float]] = []
    for name, sec in report.get("top_phases") or []:
        ms = sec * 1000
        if ms > 50 and name == "projection_pool":
            targets.append((name, ms))
    targets.extend([
        ("Short-circuit board hydrate when draft_room revision unchanged", (s.get("board_hydrate_ms") or [0])[0] if s.get("board_hydrate_ms") else 0),
        ("Shared context prep skip when canonical unchanged", (s.get("shared_context_ms") or [0])[0] if s.get("shared_context_ms") else 0),
    ])
    seen: set[str] = set()
    for i, (name, ms) in enumerate(targets, start=1):
        if name in seen:
            continue
        seen.add(name)
        ms_s = f"{ms:.0f} ms saved (est.)" if ms and ms > 0 else "verify in UI"
        print(f"  {i}. {name} — {ms_s}")

    out_path = ROOT / "data" / "draft_assistant_baseline_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nFull report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
