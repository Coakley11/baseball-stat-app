"""Fast Solo Live Draft start — open active page before full projection pool build."""

from __future__ import annotations

import time
from typing import Any

DEFERRED_FULL_POOL_KEY = "_live_draft_deferred_full_pool_build"
DEFERRED_FULL_POOL_DONE_KEY = "_live_draft_deferred_full_pool_done"
START_STAGES_KEY = "_live_draft_start_stage_timings"
DEFER_HEAVY_PAINT_KEY = "_live_draft_defer_heavy_first_paint"

# Process-wide: once a unified projection pool has been built in this Streamlit
# process, subsequent Solo Starts may attach it from @st.cache_data without a
# cold ~90s rebuild on the Start critical path.
_PROCESS_PROJECTION_POOL_WARM = False


def mark_process_projection_pool_warm() -> None:
    global _PROCESS_PROJECTION_POOL_WARM
    _PROCESS_PROJECTION_POOL_WARM = True


def process_projection_pool_is_warm() -> bool:
    return bool(_PROCESS_PROJECTION_POOL_WARM)


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
    # Market feeds often ship Primary Position as UTIL (or omit it) while ADP /
    # FantasyPros still have real eligibility. Scoring hard-filters illegal slots,
    # so UTIL-only pools yield empty recommendation cards.
    try:
        from draft_scoring_pool import ensure_draft_scoring_pool_columns

        df = ensure_draft_scoring_pool_columns(df)
    except ImportError:
        pos = df["Primary Position"].fillna("").astype(str).str.strip()
        bad = pos.eq("") | pos.str.upper().eq("UTIL")
        if bad.any():
            for src in ("ADP Position", "FantasyPros Position", "Position"):
                if src not in df.columns:
                    continue
                still = bad & df["Primary Position"].fillna("").astype(str).str.strip().str.upper().isin(
                    {"", "UTIL"}
                )
                if not still.any():
                    break
                raw = df.loc[still, src].fillna("").astype(str)
                derived = (
                    raw.str.replace(r"\d+$", "", regex=True)
                    .str.split(r"[,/\+]", regex=True)
                    .str[0]
                    .str.strip()
                    .str.upper()
                )
                fill = still & derived.ne("")
                df.loc[fill, "Primary Position"] = derived.loc[fill]
    if "Market Rank" not in df.columns:
        df["Market Rank"] = range(1, len(df) + 1)
    # Fast path: temporary 0–1 Player Grade proxy until deferred full projection pool.
    # Do not stamp ADP-count-scale values into Expected Fantasy Value.
    try:
        from draft_scoring_pool import (
            POOL_KIND_FAST_MARKET_FALLBACK,
            POOL_VALUE_KIND_KEY,
            _efv_series_is_unusable,
            _market_rank_proxy_player_grade,
            ensure_draft_scoring_pool_columns,
        )

        if "Expected Fantasy Value" not in df.columns or _efv_series_is_unusable(
            df["Expected Fantasy Value"] if "Expected Fantasy Value" in df.columns else None
        ):
            rank = pd.to_numeric(df["Market Rank"], errors="coerce").fillna(len(df))
            df["Expected Fantasy Value"] = _market_rank_proxy_player_grade(rank, n_rows=len(df))
        if "Model Rank" not in df.columns:
            df["Model Rank"] = pd.to_numeric(df["Market Rank"], errors="coerce").fillna(999)
        if "Fantasy Edge" not in df.columns:
            df["Fantasy Edge"] = 0
        df = ensure_draft_scoring_pool_columns(df)
        df.attrs[POOL_VALUE_KIND_KEY] = POOL_KIND_FAST_MARKET_FALLBACK
    except ImportError:
        if "Expected Fantasy Value" not in df.columns:
            rank = pd.to_numeric(df["Market Rank"], errors="coerce").fillna(len(df))
            n = max(len(df), 1)
            df["Expected Fantasy Value"] = ((n + 1 - rank) / float(n)).clip(lower=0.01, upper=1.0)
        else:
            efv = pd.to_numeric(df["Expected Fantasy Value"], errors="coerce")
            if (not efv.notna().any()) or float(efv.fillna(0).max()) == 0.0 or float(efv.fillna(0).max()) > 1.5:
                rank = pd.to_numeric(df["Market Rank"], errors="coerce").fillna(len(df))
                n = max(len(df), 1)
                df["Expected Fantasy Value"] = ((n + 1 - rank) / float(n)).clip(lower=0.01, upper=1.0)
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


def _pool_has_projection_player_grades(pool: Any) -> bool:
    """True when pool carries real projection Player Grade inputs (not fast-market only)."""
    if pool is None or getattr(pool, "empty", True):
        return False
    cols = set(str(c) for c in getattr(pool, "columns", []))
    if cols.intersection(
        {
            "Blended Projection Score",
            "Projected Production Score",
            "Realistic Base Projection Score",
            "proj_HR",
            "proj_RBI",
        }
    ):
        return True
    try:
        from draft_scoring_pool import POOL_KIND_FAST_MARKET_FALLBACK, POOL_VALUE_KIND_KEY

        if getattr(pool, "attrs", {}).get(POOL_VALUE_KIND_KEY) == POOL_KIND_FAST_MARKET_FALLBACK:
            return False
    except ImportError:
        pass
    return False


def _deferred_pool_params_from_room(session: dict[str, Any], room: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(room.get("config") or {})
    lahman_year = int(
        session.get("_lahman_max_year")
        or session.get("lahman_max_year")
        or cfg.get("lahman_max_year")
        or 0
    )
    if lahman_year <= 0:
        # Match streamlit_app year_max fallback so deferred rebuild is not empty.
        try:
            from datetime import datetime

            lahman_year = int(datetime.now().year) - 1
        except Exception:
            lahman_year = 2024
    return {
        "lahman_max_year": lahman_year,
        "draft_window": int(cfg.get("projection_window") or session.get("live_draft_proj_window") or 3),
        "fantasy_format": str(
            cfg.get("fantasy_format") or cfg.get("scoring_type") or "5x5 Roto"
        ),
        "projection_style": str(
            cfg.get("projection_style") or session.get("live_draft_proj_style") or "Balanced"
        ),
        "use_ml_blend": bool(cfg.get("use_ml_blend")),
        "ml_blend_weight": float(cfg.get("ml_blend_weight") or 0),
        "ml_min_games_for_signal": int(cfg.get("ml_min_games_for_signal") or 50),
    }


def maybe_build_deferred_full_pool(session: dict[str, Any], *, force: bool = False) -> bool:
    """After first active-page paint, attach the full projection pool to the live room."""
    room = session.get("live_draft_room")
    if not isinstance(room, dict) or str(room.get("status") or "") not in ("in_progress", "paused"):
        session.pop(DEFERRED_FULL_POOL_KEY, None)
        return False

    existing = room.get("pool")
    needs_upgrade = force or not _pool_has_projection_player_grades(existing)
    pending = session.get(DEFERRED_FULL_POOL_KEY)
    if not isinstance(pending, dict):
        if not needs_upgrade:
            return False
        # Solo may have attached a fast market pool without a pending upgrade ticket.
        pending = _deferred_pool_params_from_room(session, room)
        session[DEFERRED_FULL_POOL_KEY] = dict(pending)
        session.pop(DEFERRED_FULL_POOL_DONE_KEY, None)
    elif session.get(DEFERRED_FULL_POOL_DONE_KEY) and not needs_upgrade:
        return False
    elif session.get(DEFERRED_FULL_POOL_DONE_KEY) and needs_upgrade:
        # Prior "done" stamped after a fast pool — allow a real projection rebuild.
        session.pop(DEFERRED_FULL_POOL_DONE_KEY, None)

    t0 = _mono()
    note_start_stage(session, "deferred_full_pool_start", force=bool(force))
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
    try:
        from draft_scoring_pool import (
            POOL_KIND_VALID_PROJECTION,
            POOL_VALUE_KIND_KEY,
            ensure_draft_scoring_pool_columns,
        )

        pool = ensure_draft_scoring_pool_columns(pool)
        pool.attrs[POOL_VALUE_KIND_KEY] = POOL_KIND_VALID_PROJECTION
    except ImportError:
        pass
    room["pool"] = pool.copy()
    session["live_draft_room"] = room
    session[DEFERRED_FULL_POOL_DONE_KEY] = True
    session.pop(DEFERRED_FULL_POOL_KEY, None)
    mark_process_projection_pool_warm()
    note_start_stage(
        session,
        "deferred_full_pool_done",
        pool_live_count=int(len(pool)),
        duration_ms=int((_mono() - t0) * 1000),
        projection_grades=True,
    )
    try:
        from live_draft_ui_cache import invalidate_live_draft_ui_caches_after_board_change

        # Pool upgrade must not wipe the interactive top_rec snapshot while DONE:
        # the next full ScriptRun may be a button-trigger consumer that must
        # re-register Add-to-Queue on that same run (not a later recovery rerun).
        invalidate_live_draft_ui_caches_after_board_change(
            session, reason="deferred_full_pool"
        )
    except ImportError:
        session.pop("_live_draft_rec_cache", None)
    return True


def ensure_solo_player_pool_for_recs(session: dict[str, Any], room: dict[str, Any] | None = None) -> bool:
    """Guarantee Solo rooms have a non-empty pool before recommendation card paint.

    Restored Solo sessions and fast-start rooms can land on the active page with an
    empty ``room['pool']`` (persistence strip / deferred upgrade not yet applied).
    Early Recommended picks paint then stays on "Loading…" forever.
    """
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        return False

    # Never steal Shared's local-pool rebuild path.
    try:
        from live_draft_setup_mode import is_shared_multiplayer_intent

        if is_shared_multiplayer_intent(session, room=live):
            return False
    except ImportError:
        if str(session.get("active_shared_draft_room_code") or "").strip():
            # Ambiguous: only skip when room itself is stamped shared.
            cfg0 = dict(live.get("config") or {})
            if "shared" in str(cfg0.get("draft_setup_mode") or cfg0.get("draft_mode") or "").lower():
                return False

    solo = False
    try:
        from live_draft_solo_timer import is_solo_live_draft

        solo = bool(is_solo_live_draft(session, live))
    except ImportError:
        solo = False
    if not solo:
        cfg = dict(live.get("config") or {})
        mode = str(
            cfg.get("draft_setup_mode")
            or cfg.get("draft_mode")
            or session.get("live_draft_setup_mode")
            or ""
        ).lower()
        solo = mode in {"solo", "solo_draft"} or mode.startswith("solo")
    if not solo:
        return False

    status = str(live.get("status") or "").strip()
    if status not in ("in_progress", "paused"):
        return False

    # Prefer an already-attached projection pool. Do not force a synchronous
    # unified-pool rebuild here — that either blanks Solo first paint for minutes
    # or fails silently under ``except Exception``. End-of-page deferred upgrade
    # (+ one rerun) owns the Player Grade attach.
    pool = live.get("pool") if isinstance(live, dict) else None
    if pool is not None and not getattr(pool, "empty", True):
        if not _pool_has_projection_player_grades(pool):
            if not isinstance(session.get(DEFERRED_FULL_POOL_KEY), dict):
                try:
                    mark_deferred_full_pool(
                        session, params=_deferred_pool_params_from_room(session, live)
                    )
                except Exception:
                    pass
            session["_solo_needs_projection_player_grades"] = True
        return True

    # Cold restore / stripped pool: attach a fast market pool so cards can paint.
    try:
        import importlib

        app_mod = importlib.import_module("streamlit_app")
        market_df = app_mod.load_fantasypros_market_data()
    except Exception as exc:
        session["_solo_pool_ensure_error"] = f"market:{type(exc).__name__}:{exc}"[:200]
        note_start_stage(session, "solo_pool_ensure_failed", error=str(exc)[:160])
        return False
    try:
        cfg = dict(live.get("config") or {})
        total_picks = int(cfg.get("total_picks") or 0) or (
            int(cfg.get("num_teams") or 2) * int(cfg.get("picks_per_team") or 15)
        )
        fast = build_fast_market_pool(market_df, min_rows=max(400, int(total_picks) * 40))
    except Exception as exc:
        session["_solo_pool_ensure_error"] = f"fast:{type(exc).__name__}:{exc}"[:200]
        note_start_stage(session, "solo_pool_ensure_failed", error=str(exc)[:160])
        return False
    if fast is None or getattr(fast, "empty", True):
        session["_solo_pool_ensure_error"] = "empty_fast_market_pool"
        note_start_stage(session, "solo_pool_ensure_failed", error="empty_fast_market_pool")
        return False
    live["pool"] = fast.copy()
    session["live_draft_room"] = live
    session["_solo_needs_projection_player_grades"] = True
    note_start_stage(
        session,
        "solo_pool_ensure_fast_attached",
        pool_live_count=int(len(fast)),
    )
    # Queue a full-pool upgrade when Start did not already mark one.
    if not session.get(DEFERRED_FULL_POOL_DONE_KEY) and not isinstance(
        session.get(DEFERRED_FULL_POOL_KEY), dict
    ):
        try:
            mark_deferred_full_pool(
                session,
                params=_deferred_pool_params_from_room(session, live),
            )
        except Exception:
            pass
    return True
