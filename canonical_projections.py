"""Canonical fantasy projection stat lines shared across draft/analytics pages."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

# Counting/rate columns shown in ``Proj:`` stat lines (from unified draft pool only).
CANONICAL_PROJ_STAT_COLUMNS: tuple[str, ...] = (
    "proj_R",
    "proj_HR",
    "proj_RBI",
    "proj_SB",
    "proj_BB",
    "proj_BA",
    "proj_OBP",
    "proj_SLG",
    "proj_OPS",
    "proj_H",
    "proj_2B",
    "proj_3B",
    "proj_XBH",
)

CANONICAL_PROJ_MERGE_KEYS: tuple[str, ...] = ("playerID", "fullName")


def apply_ml_blend_to_projection_stats(
    pool: pd.DataFrame,
    *,
    use_ml_blend: bool,
    ml_blend_weight: float,
) -> pd.DataFrame:
    """Scale stabilized ``proj_*`` counting stats when global ML blend is enabled."""
    if pool is None or getattr(pool, "empty", True):
        return pool
    out = pool.copy()
    if not use_ml_blend or float(ml_blend_weight or 0) <= 0:
        out["Projection Source"] = "baseline"
        return out
    ml_adj = pd.to_numeric(out.get("ML Adjustment", 0), errors="coerce").fillna(0.0)
    # Match EFV sensitivity: ML Adjustment is already style-aware; weight scales global blend strength.
    weight_scale = float(ml_blend_weight) / 0.12 if float(ml_blend_weight) > 0 else 0.0
    factor = (1.0 + ml_adj * weight_scale).clip(0.82, 1.18)
    for col in CANONICAL_PROJ_STAT_COLUMNS:
        if col not in out.columns:
            continue
        base = pd.to_numeric(out[col], errors="coerce")
        out[col] = base * factor
    out["Projection Source"] = "ml_blended"
    return out


def canonical_projection_columns(pool: pd.DataFrame | None) -> list[str]:
    if pool is None or getattr(pool, "empty", True):
        return []
    return [c for c in CANONICAL_PROJ_STAT_COLUMNS if c in pool.columns]


def merge_canonical_projections(
    target_df: pd.DataFrame | None,
    canonical_pool: pd.DataFrame | None,
    *,
    on: str = "playerID",
    name_col: str = "fullName",
) -> pd.DataFrame:
    """Replace ``proj_*`` on *target_df* with values from the canonical unified pool."""
    if target_df is None or getattr(target_df, "empty", True):
        return target_df if target_df is not None else pd.DataFrame()
    if canonical_pool is None or getattr(canonical_pool, "empty", True):
        return target_df.copy()
    proj_cols = canonical_projection_columns(canonical_pool)
    if not proj_cols:
        return target_df.copy()
    merge_keys = [k for k in (on, name_col) if k in target_df.columns and k in canonical_pool.columns]
    if not merge_keys:
        if name_col in target_df.columns and name_col in canonical_pool.columns:
            merge_keys = [name_col]
        else:
            return target_df.copy()
    src = canonical_pool[merge_keys + proj_cols].drop_duplicates(subset=merge_keys, keep="first")
    out = target_df.copy()
    for col in proj_cols:
        if col in out.columns:
            out = out.drop(columns=[col])
    out = out.merge(src, on=merge_keys, how="left")
    if "Projection Source" in canonical_pool.columns and "Projection Source" not in out.columns:
        src_mode = canonical_pool[merge_keys + ["Projection Source"]].drop_duplicates(subset=merge_keys, keep="first")
        out = out.merge(src_mode, on=merge_keys, how="left")
    return out


def lookup_canonical_projection_row(
    name: str,
    canonical_pool: pd.DataFrame | None,
    *,
    name_col: str = "fullName",
) -> pd.Series | None:
    if canonical_pool is None or getattr(canonical_pool, "empty", True) or not name:
        return None
    if name_col not in canonical_pool.columns:
        return None
    want = str(name).strip().lower()
    hits = canonical_pool[canonical_pool[name_col].astype(str).str.strip().str.lower() == want]
    if hits.empty:
        return None
    return hits.iloc[0]


def projection_consistency_signature(row: Any, proj_cols: Iterable[str] | None = None) -> tuple:
    cols = tuple(proj_cols or CANONICAL_PROJ_STAT_COLUMNS)
    if row is None:
        return tuple()
    get = row.get if hasattr(row, "get") else lambda k, d=None: row[k] if k in row else d
    parts: list[Any] = []
    for col in cols:
        val = pd.to_numeric(get(col, np.nan), errors="coerce")
        parts.append(round(float(val), 4) if pd.notna(val) else None)
    return tuple(parts)
