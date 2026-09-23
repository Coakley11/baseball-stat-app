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
        # Never paint Model Rank := Market Rank as if it were analytics.
        # Leave Model Rank / Fantasy Edge pending until projection upgrade patches them.
        df["Model Rank"] = pd.NA
        df["Fantasy Edge"] = pd.NA
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
        df["Model Rank"] = pd.NA
        df["Fantasy Edge"] = pd.NA
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
    try:
        from draft_scoring_pool import POOL_KIND_FAST_MARKET_FALLBACK, POOL_VALUE_KIND_KEY

        if getattr(pool, "attrs", {}).get(POOL_VALUE_KIND_KEY) == POOL_KIND_FAST_MARKET_FALLBACK:
            return False
    except ImportError:
        pass
    cols = set(str(c) for c in getattr(pool, "columns", []))
    # Require a real blended score column — proj_* alone can be zero placeholders.
    if "Blended Projection Score" in cols or "Projected Production Score" in cols:
        try:
            import pandas as pd

            blend_col = (
                "Blended Projection Score"
                if "Blended Projection Score" in cols
                else "Projected Production Score"
            )
            vals = pd.to_numeric(pool[blend_col], errors="coerce")
            if vals.notna().any() and float(vals.fillna(0).max()) > 0:
                return True
        except Exception:
            return True
    if "proj_HR" in cols and "proj_RBI" in cols:
        try:
            import pandas as pd

            hr = pd.to_numeric(pool["proj_HR"], errors="coerce").fillna(0)
            if float(hr.max()) > 0:
                return True
        except Exception:
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


def _backfill_drafted_analytics_from_pool(room: dict[str, Any], pool: Any) -> int:
    """Overwrite frozen Model Rank / Market Rank / Fantasy Edge / MLB Team on pick rows.

    Fast Solo Start may stamp Model Rank = Market Rank (Edge 0) onto early picks.
    After the real projection pool loads, refresh drafted board/roster analytics from
    the upgraded pool by playerID (then fullName) without changing Decision Score formulas.
    """
    if pool is None or getattr(pool, "empty", True) or not isinstance(room, dict):
        return 0
    import pandas as pd

    df = pool if isinstance(pool, pd.DataFrame) else pd.DataFrame(pool)
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    name_col = "fullName" if "fullName" in df.columns else ("Player" if "Player" in df.columns else None)
    for _, row in df.iterrows():
        rec = row.to_dict()
        pid = str(row.get("playerID") or "").strip()
        if pid and "playerID" in df.columns:
            by_id[pid] = rec
        if name_col:
            nm = str(row.get(name_col) or "").strip().lower()
            if nm:
                by_name[nm] = rec
    fields = (
        "Model Rank",
        "Market Rank",
        "Fantasy Edge",
        "Expected Fantasy Value",
        "Scarcity Score",
        "Position Scarcity Score",
        "Blended Projection Score",
        "MLB Team",
        "proj_HR",
        "proj_RBI",
        "proj_R",
        "proj_SB",
        "proj_BA",
        "proj_OPS",
        "proj_AB",
        "AB",
        "proj_W",
        "proj_SV",
        "proj_K",
        "proj_ERA",
        "proj_WHIP",
        "playerID",
    )
    updated = 0

    def _patch(rec: dict[str, Any]) -> None:
        nonlocal updated
        if not isinstance(rec, dict):
            return
        pid = str(rec.get("playerID") or rec.get("player_id") or "").strip()
        src = by_id.get(pid) if pid else None
        if not src:
            nm = str(rec.get("fullName") or rec.get("Player") or "").strip().lower()
            src = by_name.get(nm) if nm else None
        if not src:
            return
        # Preserve fantasy Team / Fantasy Team; restore MLB club from pool.
        pool_team = str(src.get("Team") or src.get("MLB Team") or "").strip()
        fantasy = str(rec.get("Fantasy Team") or "").strip()
        if pool_team and pool_team != fantasy:
            rec["MLB Team"] = pool_team
        if not pid and src.get("playerID"):
            rec["playerID"] = src.get("playerID")
        for col in fields:
            if col == "MLB Team":
                continue
            if col in src and src.get(col) is not None:
                rec[col] = src.get(col)
        # Historical Fantasy Edge = Market Rank − Model Rank when both present.
        try:
            market = pd.to_numeric(rec.get("Market Rank"), errors="coerce")
            model = pd.to_numeric(rec.get("Model Rank"), errors="coerce")
            if pd.notna(market) and pd.notna(model):
                rec["Fantasy Edge"] = float(market) - float(model)
        except Exception:
            pass
        updated += 1

    for rec in room.get("draft_board") or []:
        if isinstance(rec, dict):
            _patch(rec)
    for _team, players in (room.get("rosters") or {}).items():
        if not isinstance(players, list):
            continue
        for rec in players:
            if isinstance(rec, dict):
                _patch(rec)
    return updated


def maybe_build_deferred_full_pool(session: dict[str, Any], *, force: bool = False) -> bool:
    """After first active-page paint (or Solo Ready), attach the canonical projection pool.

    Also allowed for ``not_started`` Ready lobbies so Start Draft does not begin on a
    market-only pool (zeros / Model≈Market).
    """
    room = session.get("live_draft_room")
    if not isinstance(room, dict) or str(room.get("status") or "") not in (
        "not_started",
        "in_progress",
        "paused",
        "complete",
    ):
        session.pop(DEFERRED_FULL_POOL_KEY, None)
        return False

    # Prefer the shared canonical attach helper (same pool as Draft Assistant).
    try:
        from live_draft_canonical_pool import attach_canonical_pool_to_room

        attached = attach_canonical_pool_to_room(session, room, force=force)
        if attached.get("ok") and (attached.get("attached") or not force):
            if attached.get("attached"):
                note_start_stage(session, "deferred_full_pool_done", via="canonical_attach")
            return bool(attached.get("attached") or attached.get("reason") == "already_has_projections")
    except ImportError:
        pass

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
    session.pop("_solo_needs_projection_player_grades", None)
    try:
        _backfill_drafted_analytics_from_pool(room, pool)
    except Exception:
        pass
    mark_process_projection_pool_warm()
    note_start_stage(
        session,
        "deferred_full_pool_done",
        pool_live_count=int(len(pool)),
        duration_ms=int((_mono() - t0) * 1000),
        projection_grades=True,
    )
    try:
        from live_draft_ui_cache import invalidate_live_draft_ui_caches
        from live_draft_rerun_scope import force_live_draft_expensive_recompute

        # Keep the interactive snapshot identity (same player → same Add-to-Queue keys).
        # Patch Model/Market/Edge from the upgraded pool onto those frozen rows so
        # ranks refresh without remounting action widgets mid-click.
        invalidate_live_draft_ui_caches(session, keep_interactive_snapshot=True)
        try:
            from live_draft_rec_live_paint import patch_interactive_top_rec_ranks_from_pool

            patch_interactive_top_rec_ranks_from_pool(session, room, pool)
        except ImportError:
            pass
        force_live_draft_expensive_recompute(session)
        # Prefer rank-patch path over wipe/rebuild (rebuild remounts clicked widgets).
        session["_solo_patch_ranks_after_pool_upgrade"] = True
        session.pop("_solo_force_rec_rebuild_after_pool_upgrade", None)
        session["_solo_deferred_pool_rerun"] = True
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
