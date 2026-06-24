"""Defensive defaults for draft scoring on compact / shared-room player pools."""

from __future__ import annotations

import pandas as pd

# Columns read directly (not via safe_numeric_series) in apply_draft_pick_scoring.
_DRAFT_SCORING_DEFAULTS: dict[str, float | str] = {
    "Expected Fantasy Value": 0.0,
    "Fantasy Edge": 0.0,
    "Model Rank": 9999.0,
    "Market Rank": 9999.0,
    "Expert Std Dev": 0.0,
    "Sleeper Score": 0.0,
    "ML Adjustment": 0.0,
    "Projection Confidence Score": 0.5,
    "Primary Position": "",
}

# Optional scoring columns kept in compact shared-room payloads when present.
SHARED_DRAFT_SCORING_COLUMNS = (
    "Fantasy Edge",
    "Model Rank",
    "Market Rank",
    "Sleeper Score",
    "Expert Std Dev",
)


def ensure_draft_scoring_pool_columns(pool: pd.DataFrame | None) -> pd.DataFrame:
    """Fill missing draft-scoring columns so recommendation engines never KeyError."""
    if pool is None:
        return pd.DataFrame()
    if not isinstance(pool, pd.DataFrame) or pool.empty:
        return pool.copy() if isinstance(pool, pd.DataFrame) else pd.DataFrame()

    out = pool.copy()

    if "Market Rank" not in out.columns and "ADP" in out.columns:
        out["Market Rank"] = pd.to_numeric(out["ADP"], errors="coerce")
    if "Model Rank" not in out.columns and "App Rank" in out.columns:
        out["Model Rank"] = pd.to_numeric(out["App Rank"], errors="coerce")

    if "Fantasy Edge" not in out.columns:
        if "Market Rank" in out.columns and "Model Rank" in out.columns:
            out["Fantasy Edge"] = (
                pd.to_numeric(out["Market Rank"], errors="coerce").fillna(9999)
                - pd.to_numeric(out["Model Rank"], errors="coerce").fillna(9999)
            )
        else:
            out["Fantasy Edge"] = 0.0

    for col, default in _DRAFT_SCORING_DEFAULTS.items():
        if col not in out.columns:
            out[col] = default

    return out
