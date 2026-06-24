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


def _series_is_default(col: pd.Series, default: float | str) -> pd.Series:
    numeric = pd.to_numeric(col, errors="coerce")
    if col.dtype == object and not numeric.notna().any():
        return col.fillna("").astype(str).eq(str(default))
    if isinstance(default, float):
        return numeric.isna() | numeric.eq(float(default))
    return numeric.isna() | col.fillna("").astype(str).eq(str(default))


def count_scoring_value_quality(pool: pd.DataFrame | None) -> dict[str, dict[str, int]]:
    """Count real vs default-filled values for rank/edge columns."""
    out: dict[str, dict[str, int]] = {}
    if pool is None or not isinstance(pool, pd.DataFrame) or pool.empty:
        return out
    checks: tuple[tuple[str, float | str], ...] = (
        ("Model Rank", _RANK_DEFAULT),
        ("Market Rank", _RANK_DEFAULT),
        ("Fantasy Edge", 0.0),
    )
    n = len(pool)
    for col, default in checks:
        if col not in pool.columns:
            out[col] = {"real": 0, "default": n, "missing_column": n}
            continue
        default_mask = _series_is_default(pool[col], default)
        default_n = int(default_mask.sum())
        out[col] = {"real": n - default_n, "default": default_n}
    return out


def prepare_pool_for_compact_serialization(
    pool: pd.DataFrame | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Ensure scoring columns exist before compact shared-room serialization."""
    if pool is None or not isinstance(pool, pd.DataFrame) or pool.empty:
        return pd.DataFrame(), {"source_columns": [], "compact_columns": []}
    source_columns = [str(c) for c in pool.columns]
    prepared, report = _ensure_draft_scoring_pool_columns(pool, mutate=True)
    compact_columns = select_live_draft_compact_columns(prepared)
    report["source_columns"] = source_columns
    report["source_column_count"] = len(source_columns)
    report["compact_columns"] = compact_columns
    report["compact_column_count"] = len(compact_columns)
    report["scoring_quality"] = count_scoring_value_quality(prepared)
    return prepared, report


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
    prepared, prep_report = prepare_pool_for_compact_serialization(pool)
    compact_cols = prep_report.get("compact_columns") or select_live_draft_compact_columns(prepared)
    missing = [c for c in LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS if c not in src_cols]
    _, report = _ensure_draft_scoring_pool_columns(prepared, mutate=False)
    return {
        "pool_count": len(pool),
        "source_columns": src_cols,
        "source_column_count": len(src_cols),
        "compact_columns": compact_cols,
        "compact_column_count": len(compact_cols),
        "missing_required": missing,
        "default_filled_counts": report.get("default_filled_counts") or {},
        "derived_columns": report.get("derived_columns") or prep_report.get("derived_columns") or [],
        "scoring_quality": prep_report.get("scoring_quality") or count_scoring_value_quality(prepared),
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

    def _needs_column(col: str) -> bool:
        if col not in out.columns:
            return True
        series = pd.to_numeric(out[col], errors="coerce") if col != "Primary Position" else out[col]
        if col in ("Model Rank", "Market Rank"):
            nums = pd.to_numeric(series, errors="coerce")
            return nums.isna().all() or nums.eq(_RANK_DEFAULT).all()
        if col == "Fantasy Edge":
            return series.isna().all() or series.fillna(0).eq(0).all()
        return series.isna().all()

    if _needs_column("Market Rank"):
        if "ADP Rank" in out.columns:
            out["Market Rank"] = pd.to_numeric(out["ADP Rank"], errors="coerce")
            _derive("Market Rank")
        elif "ADP" in out.columns:
            out["Market Rank"] = pd.to_numeric(out["ADP"], errors="coerce")
            _derive("Market Rank")
        elif "FantasyPros Rank" in out.columns:
            out["Market Rank"] = pd.to_numeric(out["FantasyPros Rank"], errors="coerce")
            _derive("Market Rank")

    if _needs_column("Model Rank"):
        if "App Rank" in out.columns:
            out["Model Rank"] = pd.to_numeric(out["App Rank"], errors="coerce")
            _derive("Model Rank")
        elif "Expected Fantasy Value" in out.columns:
            efv = pd.to_numeric(out["Expected Fantasy Value"], errors="coerce")
            out["Model Rank"] = efv.rank(ascending=False, method="min")
            _derive("Model Rank")

    if _needs_column("Fantasy Edge"):
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
