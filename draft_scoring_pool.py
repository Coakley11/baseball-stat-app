"""Live Draft player pool columns — compact shared-room serialization + scoring safety."""

from __future__ import annotations

from typing import Any

import pandas as pd

# Columns used by live_draft_recommendations, apply_draft_pick_scoring, manual draft
# sorting, scarcity/positional fit, sleeper/value, and availability-at-next-pick logic.
LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS: tuple[str, ...] = (
    # Identity / eligibility
    "playerID",
    "fullName",
    "Primary Position",
    "Team",
    "Age",
    "Eligible Positions",
    # Core ranks / value
    "Expected Fantasy Value",
    "Model Rank",
    "Market Rank",
    "Fantasy Edge",
    # Market / pick cost / availability inputs
    "ADP",
    "ADP Rank",
    "FantasyPros Rank",
    "Expert Avg Rank",
    "Expert Std Dev",
    # Sleeper / value / confidence signals
    "Sleeper Score",
    "Scarcity Score",
    "Projection Confidence Score",
    "ML Adjustment",
    "ML Projection Score",
    "App Ranking Score",
    "Market vs Model Score",
    "Trend Signal",
    "Capped Fantasy Edge",
    "Best Player Available Score",
    "Best Value Sleeper Score",
    # Category-need projections (roto / points)
    "proj_HR",
    "proj_RBI",
    "proj_R",
    "proj_SB",
    "proj_BA",
    "proj_OPS",
    "proj_BB",
    "AB",
    "G",
)

# Backward-compatible alias used by shared-room compact serialization.
SHARED_DRAFT_POOL_COLUMNS = LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS

_RANK_DEFAULT = 9999.0
_SCORING_FALLBACK_DEFAULTS: dict[str, float | str] = {
    "Expected Fantasy Value": 0.0,
    "Fantasy Edge": 0.0,
    "Model Rank": _RANK_DEFAULT,
    "Market Rank": _RANK_DEFAULT,
    "Expert Std Dev": 0.0,
    "Sleeper Score": 0.0,
    "Scarcity Score": 0.0,
    "ML Adjustment": 0.0,
    "Projection Confidence Score": 0.5,
    "Primary Position": "",
    "Trend Signal": 0.0,
    "App Ranking Score": 0.0,
    "Market vs Model Score": 0.0,
}


def select_live_draft_compact_columns(frame: pd.DataFrame) -> list[str]:
    """Columns to keep for compact shared-room pool — required scoring cols present in frame."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    present = [str(c) for c in frame.columns]
    keep = [c for c in LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS if c in present]
    # Preserve column order from the source frame for any extra required hits.
    ordered = [c for c in present if c in keep]
    return ordered


def analyze_compact_pool(
    pool: pd.DataFrame | None,
    *,
    source_columns: list[str] | None = None,
) -> dict[str, Any]:
    """Diagnostics for compact pool column coverage and default-filled scoring fields."""
    if pool is None or not isinstance(pool, pd.DataFrame) or pool.empty:
        return {
            "pool_count": 0,
            "compact_columns": [],
            "missing_required": list(LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS),
            "default_filled_counts": {},
            "derived_columns": [],
        }

    src_cols = source_columns if source_columns is not None else [str(c) for c in pool.columns]
    compact_cols = select_live_draft_compact_columns(pool)
    missing = [c for c in LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS if c not in src_cols]
    _, report = _ensure_draft_scoring_pool_columns(pool, mutate=False)
    return {
        "pool_count": len(pool),
        "source_column_count": len(src_cols),
        "compact_columns": compact_cols,
        "compact_column_count": len(compact_cols),
        "missing_required": missing,
        "default_filled_counts": report.get("default_filled_counts") or {},
        "derived_columns": report.get("derived_columns") or [],
    }


def ensure_draft_scoring_pool_columns(pool: pd.DataFrame | None) -> pd.DataFrame:
    """Fill missing draft-scoring columns only when truly absent; never overwrite real values."""
    df, _report = _ensure_draft_scoring_pool_columns(pool, mutate=True)
    return df


def ensure_draft_scoring_pool_columns_with_report(
    pool: pd.DataFrame | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    df, report = _ensure_draft_scoring_pool_columns(pool, mutate=True)
    return df, report


def _ensure_draft_scoring_pool_columns(
    pool: pd.DataFrame | None,
    *,
    mutate: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    report: dict[str, Any] = {
        "default_filled_counts": {},
        "derived_columns": [],
    }
    if pool is None:
        return pd.DataFrame(), report
    if not isinstance(pool, pd.DataFrame) or pool.empty:
        return pool.copy() if isinstance(pool, pd.DataFrame) else pd.DataFrame(), report

    out = pool if mutate else pool.copy()

    def _derive(col: str) -> None:
        report["derived_columns"].append(col)

    if "Market Rank" not in out.columns:
        if "ADP Rank" in out.columns:
            out["Market Rank"] = pd.to_numeric(out["ADP Rank"], errors="coerce")
            _derive("Market Rank")
        elif "ADP" in out.columns:
            out["Market Rank"] = pd.to_numeric(out["ADP"], errors="coerce")
            _derive("Market Rank")
        elif "FantasyPros Rank" in out.columns:
            out["Market Rank"] = pd.to_numeric(out["FantasyPros Rank"], errors="coerce")
            _derive("Market Rank")

    if "Model Rank" not in out.columns and "App Rank" in out.columns:
        out["Model Rank"] = pd.to_numeric(out["App Rank"], errors="coerce")
        _derive("Model Rank")

    if "Fantasy Edge" not in out.columns:
        if "Market Rank" in out.columns and "Model Rank" in out.columns:
            out["Fantasy Edge"] = (
                pd.to_numeric(out["Market Rank"], errors="coerce")
                - pd.to_numeric(out["Model Rank"], errors="coerce")
            )
            _derive("Fantasy Edge")

    for col, default in _SCORING_FALLBACK_DEFAULTS.items():
        if col not in out.columns:
            out[col] = default
            report["default_filled_counts"][col] = len(out)

    return out, report
