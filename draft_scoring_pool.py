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


SCORING_TRACE_COLUMNS: tuple[str, ...] = (
    "Expected Fantasy Value",
    "Model Rank",
    "Market Rank",
    "Fantasy Edge",
    "ADP Rank",
    "ADP",
    "Sleeper Score",
)

DEFAULT_SCORING_TRACE_PLAYERS: tuple[str, ...] = (
    "Aaron Judge",
    "Shohei Ohtani",
    "Juan Soto",
)


def trace_player_scoring(
    pool: pd.DataFrame | None,
    player_names: tuple[str, ...] | list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Snapshot scoring fields for acceptance players (dev / stabilization)."""
    names = tuple(player_names or DEFAULT_SCORING_TRACE_PLAYERS)
    out: dict[str, dict[str, Any]] = {}
    if pool is None or not isinstance(pool, pd.DataFrame) or pool.empty or "fullName" not in pool.columns:
        return {name: {"found": False} for name in names}
    work = pool.copy()
    work["_trace_name"] = work["fullName"].astype(str).str.strip()
    for name in names:
        rows = work[work["_trace_name"].str.casefold() == str(name).strip().casefold()]
        if rows.empty:
            out[name] = {"found": False}
            continue
        row = rows.iloc[0]
        fields: dict[str, Any] = {"found": True, "playerID": str(row.get("playerID") or "")}
        for col in SCORING_TRACE_COLUMNS:
            if col in row.index:
                val = row.get(col)
                try:
                    if pd.isna(val):
                        fields[col] = None
                    elif isinstance(val, (int, float)):
                        fields[col] = float(val)
                    else:
                        fields[col] = val
                except Exception:
                    fields[col] = val
        out[name] = fields
    return out


def _series_is_default(col: pd.Series, default: float | str) -> pd.Series:
    numeric = pd.to_numeric(col, errors="coerce")
    if col.dtype == object and not numeric.notna().any():
        return col.fillna("").astype(str).eq(str(default))
    if isinstance(default, float):
        return numeric.isna() | numeric.eq(float(default))
    return numeric.isna() | col.fillna("").astype(str).eq(str(default))


def _bad_rank_mask(series: pd.Series) -> pd.Series:
    nums = pd.to_numeric(series, errors="coerce")
    return nums.isna() | nums.ge(_RANK_DEFAULT)


def _fill_bad_rows(
    out: pd.DataFrame,
    col: str,
    values: pd.Series,
    *,
    bad: pd.Series,
    report: dict[str, Any],
    derived_name: str | None = None,
) -> None:
    if not bad.any():
        return
    out.loc[bad, col] = values.loc[bad]
    if derived_name:
        derived = report.setdefault("derived_columns", [])
        if derived_name not in derived:
            derived.append(derived_name)


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

    if "Market Rank" not in out.columns:
        out["Market Rank"] = pd.NA
    market_bad = _bad_rank_mask(out["Market Rank"])
    if market_bad.any():
        if "ADP Rank" in out.columns:
            _fill_bad_rows(
                out,
                "Market Rank",
                pd.to_numeric(out["ADP Rank"], errors="coerce"),
                bad=market_bad,
                report=report,
                derived_name="Market Rank",
            )
            market_bad = _bad_rank_mask(out["Market Rank"])
        if market_bad.any() and "ADP" in out.columns:
            _fill_bad_rows(
                out,
                "Market Rank",
                pd.to_numeric(out["ADP"], errors="coerce"),
                bad=market_bad,
                report=report,
                derived_name="Market Rank",
            )
            market_bad = _bad_rank_mask(out["Market Rank"])
        if market_bad.any() and "FantasyPros Rank" in out.columns:
            _fill_bad_rows(
                out,
                "Market Rank",
                pd.to_numeric(out["FantasyPros Rank"], errors="coerce"),
                bad=market_bad,
                report=report,
                derived_name="Market Rank",
            )

    if "Model Rank" not in out.columns:
        out["Model Rank"] = pd.NA
    model_bad = _bad_rank_mask(out["Model Rank"])
    if model_bad.any() and "App Rank" in out.columns:
        _fill_bad_rows(
            out,
            "Model Rank",
            pd.to_numeric(out["App Rank"], errors="coerce"),
            bad=model_bad,
            report=report,
            derived_name="Model Rank",
        )
        model_bad = _bad_rank_mask(out["Model Rank"])
    if model_bad.any() and "Expected Fantasy Value" in out.columns:
        efv = pd.to_numeric(out["Expected Fantasy Value"], errors="coerce")
        if efv.notna().any():
            model_rank = efv.rank(ascending=False, method="min")
            _fill_bad_rows(
                out,
                "Model Rank",
                model_rank,
                bad=model_bad,
                report=report,
                derived_name="Model Rank",
            )

    if "Market Rank" in out.columns and "Model Rank" in out.columns:
        market = pd.to_numeric(out["Market Rank"], errors="coerce")
        model = pd.to_numeric(out["Model Rank"], errors="coerce")
        computed_edge = market - model
        if "Fantasy Edge" not in out.columns:
            out["Fantasy Edge"] = pd.NA
        edge_vals = pd.to_numeric(out["Fantasy Edge"], errors="coerce")
        edge_bad = edge_vals.isna() | _bad_rank_mask(out["Fantasy Edge"])
        edge_bad = edge_bad | (edge_vals.fillna(0).eq(0) & computed_edge.notna() & computed_edge.ne(0))
        _fill_bad_rows(
            out,
            "Fantasy Edge",
            computed_edge,
            bad=edge_bad,
            report=report,
            derived_name="Fantasy Edge",
        )

    for col, default in _SCORING_FALLBACK_DEFAULTS.items():
        if col not in out.columns:
            out[col] = default
            report["default_filled_counts"][col] = len(out)
            continue
        if col in ("Model Rank", "Market Rank"):
            bad = _bad_rank_mask(out[col])
        elif col == "Fantasy Edge":
            bad = pd.to_numeric(out[col], errors="coerce").isna()
        elif col == "Primary Position":
            bad = out[col].fillna("").astype(str).eq("")
        else:
            bad = pd.to_numeric(out[col], errors="coerce").isna()
        if bad.any():
            out.loc[bad, col] = default
            report["default_filled_counts"][col] = int(bad.sum())

    return out, report
