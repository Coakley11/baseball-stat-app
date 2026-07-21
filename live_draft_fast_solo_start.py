"""Fast Solo Live Draft start — open active page before full projection pool build."""

from __future__ import annotations

import time
from typing import Any

DEFERRED_FULL_POOL_KEY = "_live_draft_deferred_full_pool_build"
DEFERRED_FULL_POOL_DONE_KEY = "_live_draft_deferred_full_pool_done"
START_STAGES_KEY = "_live_draft_start_stage_timings"
DEFER_HEAVY_PAINT_KEY = "_live_draft_defer_heavy_first_paint"


def _mono() -> float:
    return time.perf_counter()


def note_start_stage(session: dict[str, Any], stage: str, **fields: Any) -> None:
    """Record per-stage timings for Cloud acceptance reports."""
    stages = dict(session.get(START_STAGES_KEY) or {})
    t0 = float(session.get("_live_draft_start_stage_t0") or 0.0)
    if t0 <= 0:
        t0 = _mono()
        session["_live_draft_start_stage_t0"] = t0
    elapsed_ms = int(max(0.0, (_mono() - t0) * 1000))
    entry = {"elapsed_ms": elapsed_ms, "at": time.time(), **fields}
    stages[str(stage)] = entry
    session[START_STAGES_KEY] = stages
    try:
        from live_draft_cloud_diagnostics import log_start_stage

        log_start_stage(session, stage, elapsed_ms=elapsed_ms, **fields)
    except ImportError:
        pass
    try:
        from live_draft_solo_create import note_timed_step

        note_timed_step(session, stage, ok=True, **fields)
    except ImportError:
        pass
    try:
        from live_draft_start_progress import mark_start_step

        mark_start_step(session, stage, **fields)
    except ImportError:
        pass


def get_start_stage_report(session: dict[str, Any]) -> dict[str, Any]:
    return dict(session.get(START_STAGES_KEY) or {})


def mark_defer_heavy_first_paint(session: dict[str, Any]) -> None:
    """Skip recommendations/photos/decision panels on the first active-page paint."""
    session[DEFER_HEAVY_PAINT_KEY] = True
    session.pop("_live_draft_defer_heavy_loading", None)
    session.pop("_live_draft_heavy_paint_done", None)


def should_defer_heavy_first_paint(session: dict[str, Any]) -> bool:
    return bool(session.get(DEFER_HEAVY_PAINT_KEY))


def clear_defer_heavy_first_paint(session: dict[str, Any]) -> None:
    session.pop(DEFER_HEAVY_PAINT_KEY, None)


def should_use_fast_solo_pool(
    session: dict[str, Any],
    *,
    solo_mode: bool,
    from_simulator: bool,
    prepare_shared: bool,
) -> bool:
    if not solo_mode or from_simulator or prepare_shared:
        return False
    if session.get(DEFERRED_FULL_POOL_DONE_KEY):
        return False
    return True


def build_fast_market_pool(market_df: Any, *, min_rows: int = 400) -> Any:
    """Lightweight pool from market data only — enough for autopick/manual until full pool loads."""
    import pandas as pd

    if market_df is None or getattr(market_df, "empty", True):
        return pd.DataFrame()
    df = market_df.copy()
    name_col = "Player" if "Player" in df.columns else ("fullName" if "fullName" in df.columns else None)
    if name_col is None:
        return pd.DataFrame()
    if "fullName" not in df.columns:
        df["fullName"] = df[name_col].astype(str).str.strip()
    if "playerID" not in df.columns:
        df["playerID"] = df.index.astype(str)
    if "Primary Position" not in df.columns and "Position" in df.columns:
        df["Primary Position"] = df["Position"]
    if "Primary Position" not in df.columns:
        df["Primary Position"] = "UTIL"
    if "Market Rank" not in df.columns:
        df["Market Rank"] = range(1, len(df) + 1)
    if "Expected Fantasy Value" not in df.columns:
        rank = pd.to_numeric(df["Market Rank"], errors="coerce").fillna(len(df))
        df["Expected Fantasy Value"] = (len(df) + 1 - rank).clip(lower=1)
    if "Model Rank" not in df.columns:
        df["Model Rank"] = pd.to_numeric(df["Market Rank"], errors="coerce").fillna(999)
    if "Fantasy Edge" not in df.columns:
        df["Fantasy Edge"] = 0
    df = df.drop_duplicates(subset=["fullName"], keep="first")
    if len(df) > int(min_rows):
        df = df.head(int(min_rows)).copy()
    return df.reset_index(drop=True)


def mark_deferred_full_pool(session: dict[str, Any], *, params: dict[str, Any]) -> None:
    session[DEFERRED_FULL_POOL_KEY] = dict(params)
    session.pop(DEFERRED_FULL_POOL_DONE_KEY, None)


def maybe_build_deferred_full_pool(session: dict[str, Any]) -> bool:
    """After first active-page paint, attach the full projection pool to the live room."""
    pending = session.get(DEFERRED_FULL_POOL_KEY)
    if not isinstance(pending, dict) or session.get(DEFERRED_FULL_POOL_DONE_KEY):
        return False
    room = session.get("live_draft_room")
    if not isinstance(room, dict) or str(room.get("status") or "") not in ("in_progress", "paused"):
        session.pop(DEFERRED_FULL_POOL_KEY, None)
        return False
    t0 = _mono()
    note_start_stage(session, "deferred_full_pool_start")
    try:
        import importlib

        app_mod = importlib.import_module("streamlit_app")
        pool = app_mod.get_cached_unified_projection_pool(
            int(pending.get("lahman_max_year") or 0),
            int(pending.get("draft_window") or 3),
            str(pending.get("fantasy_format") or "5x5 Roto"),
            str(pending.get("projection_style") or "Balanced"),
            bool(pending.get("use_ml_blend")),
            float(pending.get("ml_blend_weight") or 0),
            int(pending.get("ml_min_games_for_signal") or 50),
        )
    except Exception as exc:
        note_start_stage(session, "deferred_full_pool_failed", error=str(exc)[:160])
        return False
    if pool is None or getattr(pool, "empty", True):
        note_start_stage(session, "deferred_full_pool_failed", error="empty_pool")
        return False
    room["pool"] = pool.copy()
    session["live_draft_room"] = room
    session[DEFERRED_FULL_POOL_DONE_KEY] = True
    session.pop(DEFERRED_FULL_POOL_KEY, None)
    note_start_stage(
        session,
        "deferred_full_pool_done",
        pool_live_count=int(len(pool)),
        duration_ms=int((_mono() - t0) * 1000),
    )
    try:
        from live_draft_ui_cache import invalidate_live_draft_ui_caches

        invalidate_live_draft_ui_caches(session)
    except ImportError:
        session.pop("_live_draft_rec_cache", None)
    return True
