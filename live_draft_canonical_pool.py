"""Attach the app's canonical unified projection pool to Live Draft rooms.

Live Draft must not invent a second projection system. All proj_* / Model Rank /
Market Rank values come from ``get_cached_unified_projection_pool(_live)`` under
the same ``draft_shared_settings`` window/style as Draft Assistant and Draft Lab.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Room statuses where attaching the canonical pool is allowed (incl. Ready lobby).
_ATTACH_STATUSES = frozenset({"not_started", "in_progress", "paused", "complete"})


def _dedupe_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or getattr(df, "empty", True):
        return df if df is not None else pd.DataFrame()
    if df.columns.duplicated().any():
        return df.loc[:, ~df.columns.duplicated()].copy()
    return df


def collapse_identity_columns(df: pd.DataFrame) -> pd.DataFrame:
    """One Player / one fullName / unique column labels — never assign Series-as-column."""
    out = _dedupe_columns(df.copy() if df is not None else pd.DataFrame())
    if out.empty:
        return out

    def _series(col: str) -> pd.Series | None:
        if col not in out.columns:
            return None
        block = out[col]
        if isinstance(block, pd.DataFrame):
            block = block.iloc[:, 0]
        return pd.Series(block, index=out.index)

    player = _series("Player")
    full = _series("fullName")
    # Drop all identity duplicates then reattach one of each.
    drop_cols = [c for c in out.columns if str(c) in {"Player", "fullName"}]
    if drop_cols:
        out = out.drop(columns=drop_cols, errors="ignore")
    if full is not None and player is not None:
        merged = full.astype(str).where(full.notna() & (full.astype(str).str.strip() != ""), player)
        out["fullName"] = merged
        out["Player"] = merged
    elif full is not None:
        out["fullName"] = full
        out["Player"] = full
    elif player is not None:
        out["Player"] = player
        out["fullName"] = player
    return _dedupe_columns(out)


def load_canonical_unified_pool(session: dict[str, Any] | None = None) -> pd.DataFrame:
    """Resolve the same unified pool Draft Assistant uses (session-aware when possible).

    Rejects non-projection frames (raw batting / fast-market) so Ready never
    treats a placeholder table as canonical.
    """
    session = session if isinstance(session, dict) else {}
    errors: list[str] = []

    def _is_projection_pool(pool: Any) -> bool:
        if pool is None or getattr(pool, "empty", True):
            return False
        try:
            from live_draft_fast_solo_start import _pool_has_projection_player_grades

            return bool(_pool_has_projection_player_grades(pool))
        except ImportError:
            cols = set(str(c) for c in getattr(pool, "columns", []))
            return "Blended Projection Score" in cols or (
                "proj_HR" in cols and "proj_RBI" in cols
            )

    try:
        import importlib

        app_mod = importlib.import_module("streamlit_app")
        # Prefer explicit cached builder first — the live wrapper can return a
        # session-tainted non-projection frame under Ready / bare imports.
        room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
        cfg = dict((room or {}).get("config") or {})
        try:
            from shared_draft_context import draft_pool_kwargs_from_session

            kw = draft_pool_kwargs_from_session(session)
        except ImportError:
            kw = {}
        get_pool = getattr(app_mod, "get_cached_unified_projection_pool", None)
        if callable(get_pool):
            lahman = int(
                session.get("_lahman_max_year")
                or session.get("lahman_max_year")
                or cfg.get("lahman_max_year")
                or 0
            )
            if lahman <= 0:
                from datetime import datetime

                lahman = int(datetime.now().year) - 1
            for year_try in (lahman, lahman - 1, 2024, 2023):
                if year_try <= 0:
                    continue
                try:
                    pool = get_pool(
                        int(year_try),
                        int(kw.get("draft_window") or cfg.get("projection_window") or 3),
                        str(kw.get("fantasy_format") or cfg.get("scoring_type") or "5x5 Roto"),
                        str(kw.get("projection_style") or cfg.get("projection_style") or "Balanced"),
                        bool(kw.get("use_ml_blend", cfg.get("use_ml_blend"))),
                        float(kw.get("ml_blend_weight") or cfg.get("ml_blend_weight") or 0),
                        int(kw.get("ml_min_games_for_signal") or cfg.get("ml_min_games_for_signal") or 50),
                    )
                    if _is_projection_pool(pool):
                        return pool
                    errors.append(f"year_{year_try}_not_projection")
                except Exception as exc:
                    errors.append(f"year_{year_try}:{type(exc).__name__}")
        live_fn = getattr(app_mod, "get_cached_unified_projection_pool_live", None)
        if callable(live_fn):
            try:
                pool = live_fn()
                if _is_projection_pool(pool):
                    return pool
                errors.append("live_fn_not_projection")
            except Exception as exc:
                errors.append(f"live_fn:{type(exc).__name__}")
    except Exception as exc:
        errors.append(f"import:{type(exc).__name__}:{exc}"[:120])
    if errors:
        session["_canonical_pool_load_errors"] = errors[-8:]
    return pd.DataFrame()


def attach_canonical_pool_to_room(
    session: dict[str, Any],
    room: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Replace/upgrade ``room['pool']`` with the canonical unified projection pool.

    Safe for Ready (``not_started``), active, and completed rooms.
    """
    result = {"ok": False, "attached": False, "backfilled": 0, "reason": ""}
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        result["reason"] = "no_room"
        return result
    status = str(live.get("status") or "").strip()
    if status and status not in _ATTACH_STATUSES:
        result["reason"] = f"status_{status}"
        return result

    existing = live.get("pool")
    try:
        from live_draft_fast_solo_start import _pool_has_projection_player_grades

        has_proj = _pool_has_projection_player_grades(existing)
    except ImportError:
        has_proj = False
        if existing is not None and not getattr(existing, "empty", True):
            cols = set(str(c) for c in getattr(existing, "columns", []))
            has_proj = bool(cols.intersection({"Blended Projection Score", "proj_HR", "proj_RBI"}))

    if has_proj and not force:
        # Still refresh Model Rank hygiene + drafted backfill from existing pool.
        try:
            from draft_scoring_pool import (
                POOL_KIND_VALID_PROJECTION,
                POOL_VALUE_KIND_KEY,
                ensure_draft_scoring_pool_columns,
            )

            pool = ensure_draft_scoring_pool_columns(existing)
            pool.attrs[POOL_VALUE_KIND_KEY] = POOL_KIND_VALID_PROJECTION
            live["pool"] = pool
        except ImportError:
            pass
        try:
            from live_draft_fast_solo_start import _backfill_drafted_analytics_from_pool

            result["backfilled"] = int(_backfill_drafted_analytics_from_pool(live, live.get("pool")) or 0)
        except ImportError:
            pass
        session["live_draft_room"] = live
        result["ok"] = True
        result["reason"] = "already_has_projections"
        return result

    pool = load_canonical_unified_pool(session)
    if pool is None or getattr(pool, "empty", True):
        result["reason"] = "canonical_pool_empty"
        return result
    try:
        from live_draft_fast_solo_start import _pool_has_projection_player_grades

        if not _pool_has_projection_player_grades(pool):
            result["reason"] = "canonical_pool_missing_projections"
            return result
    except ImportError:
        cols = set(str(c) for c in getattr(pool, "columns", []))
        if "Blended Projection Score" not in cols and not (
            "proj_HR" in cols and "proj_RBI" in cols
        ):
            result["reason"] = "canonical_pool_missing_projections"
            return result
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

    live["pool"] = pool.copy()
    session["live_draft_room"] = live
    session["draft_room_player_pool"] = pool.copy()
    try:
        from live_draft_fast_solo_start import (
            DEFERRED_FULL_POOL_DONE_KEY,
            _backfill_drafted_analytics_from_pool,
            mark_process_projection_pool_warm,
        )

        result["backfilled"] = int(_backfill_drafted_analytics_from_pool(live, pool) or 0)
        session[DEFERRED_FULL_POOL_DONE_KEY] = True
        mark_process_projection_pool_warm()
    except ImportError:
        pass
    session.pop("_solo_needs_projection_player_grades", None)
    session["_solo_lobby_pool_warm_done"] = True
    result["ok"] = True
    result["attached"] = True
    result["reason"] = "attached_canonical"
    return result


def enrich_roster_frame_from_canonical(
    roster_df: pd.DataFrame,
    session: dict[str, Any] | None = None,
    room: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Ensure roster rows carry canonical proj_* and ranks (for totals / Queue / recap)."""
    if roster_df is None or getattr(roster_df, "empty", True):
        return roster_df if roster_df is not None else pd.DataFrame()
    out = collapse_identity_columns(roster_df)

    pool = None
    if isinstance(room, dict):
        pool = room.get("pool")
    if pool is None or getattr(pool, "empty", True) or "proj_HR" not in getattr(pool, "columns", []):
        pool = load_canonical_unified_pool(session)

    if pool is None or getattr(pool, "empty", True):
        return out

    try:
        from canonical_projections import (
            CANONICAL_DRAFT_METRIC_COLUMNS,
            CANONICAL_PROJ_STAT_COLUMNS,
            merge_canonical_draft_metrics,
            merge_canonical_projections,
        )

        # Align name columns for merge.
        if "fullName" not in out.columns and "Player" in out.columns:
            out["fullName"] = out["Player"]
        if "fullName" not in pool.columns and "Player" in pool.columns:
            pool = pool.copy()
            pool["fullName"] = pool["Player"]
        out = merge_canonical_projections(out, pool)
        out = merge_canonical_draft_metrics(out, pool)
        # Extra guarantee: copy proj_* / ranks by playerID when still missing.
        if "playerID" in out.columns and "playerID" in pool.columns:
            by_id = pool.drop_duplicates(subset=["playerID"]).set_index("playerID", drop=False)
            for col in list(CANONICAL_PROJ_STAT_COLUMNS) + list(CANONICAL_DRAFT_METRIC_COLUMNS) + [
                "proj_AB",
                "AB",
                "Primary Position",
                "Team",
            ]:
                if col not in by_id.columns:
                    continue
                if col not in out.columns:
                    out[col] = pd.NA
                missing = out[col].isna() if col in out.columns else pd.Series(True, index=out.index)
                if not missing.any():
                    # Also refill zeros for counting stats when pool has real values.
                    if str(col).startswith("proj_") and col not in {"proj_BA", "proj_OBP", "proj_SLG", "proj_OPS"}:
                        vals = pd.to_numeric(out[col], errors="coerce")
                        missing = vals.fillna(0).eq(0)
                    else:
                        continue
                mapped = out["playerID"].astype(str).map(
                    lambda pid, c=col: by_id.at[pid, c] if pid in by_id.index else pd.NA
                )
                out.loc[missing, col] = mapped[missing]
    except Exception:
        pass

    # Fantasy Edge from independent ranks.
    try:
        market = pd.to_numeric(out.get("Market Rank"), errors="coerce")
        model = pd.to_numeric(out.get("Model Rank"), errors="coerce")
        if market is not None and model is not None:
            out["Fantasy Edge"] = market - model
    except Exception:
        pass
    return collapse_identity_columns(out)
