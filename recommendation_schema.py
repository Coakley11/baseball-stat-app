"""Recommendation DataFrame schema contract — ranking columns before any sort."""

from __future__ import annotations

from typing import Any

import pandas as pd

# Columns the Live Draft / Draft Assistant ranking paths sort on.
REQUIRED_RANKING_COLUMNS: tuple[str, ...] = (
    "Draft Fit Score",
    "Decision Score",
    "Positional Fit",
    "Roster Need Score",
    "Expected Fantasy Value",
    "Sleeper Score",
    "Market Rank",
    "Model Rank",
    "Fantasy Edge",
    "Player Grade",
    "Risk",
    "Survival",
)

# Columns that must exist before any recommendation table sort (crash sites).
SORT_CRITICAL_COLUMNS: tuple[str, ...] = (
    "Draft Fit Score",
    "Decision Score",
    "Positional Fit",
    "Expected Fantasy Value",
    "Sleeper Score",
)


def missing_ranking_columns(
    df: pd.DataFrame | None,
    *,
    required: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    cols = tuple(required) if required is not None else SORT_CRITICAL_COLUMNS
    if df is None or not isinstance(df, pd.DataFrame):
        return list(cols)
    return [c for c in cols if c not in df.columns]


def recommendation_schema_diagnostics(
    df: pd.DataFrame | None,
    *,
    path: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    missing = missing_ranking_columns(df)
    out: dict[str, Any] = {
        "path": str(path or ""),
        "row_count": int(len(df)) if isinstance(df, pd.DataFrame) else 0,
        "columns": list(df.columns) if isinstance(df, pd.DataFrame) else [],
        "missing_ranking_columns": missing,
        "schema_ok": not missing and isinstance(df, pd.DataFrame),
    }
    if extra:
        out.update({k: v for k, v in extra.items() if v is not None})
    return out


def ensure_recommendation_ranking_schema(
    df: pd.DataFrame | None,
    *,
    fill_missing_numeric: bool = False,
) -> pd.DataFrame:
    """Guarantee sort-critical ranking columns exist.

    When ``fill_missing_numeric`` is False (default), missing columns are added as
    NaN — never as misleading 0.0 placeholders that look like real scores.
    Callers that need real scores must run ``apply_draft_pick_scoring`` first.
    """
    if df is None or not isinstance(df, pd.DataFrame):
        out = pd.DataFrame()
    else:
        out = df.copy()
    for col in REQUIRED_RANKING_COLUMNS:
        if col not in out.columns:
            out[col] = 0.0 if fill_missing_numeric else pd.NA
        else:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def safe_sort_recommendations(
    df: pd.DataFrame | None,
    columns: list[str] | tuple[str, ...],
    *,
    ascending: bool | list[bool] = False,
    ensure_schema: bool = True,
) -> pd.DataFrame:
    """Sort only on columns that exist; optionally ensure ranking schema first."""
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    frame = ensure_recommendation_ranking_schema(df) if ensure_schema else df.copy()
    if frame.empty:
        return frame
    cols = [c for c in columns if c in frame.columns]
    if not cols:
        return frame
    if isinstance(ascending, bool):
        asc: bool | list[bool] = ascending
    else:
        asc_list = list(ascending)
        if len(asc_list) < len(cols):
            asc_list = asc_list + [asc_list[-1] if asc_list else False] * (len(cols) - len(asc_list))
        asc = asc_list[: len(cols)]
    return frame.sort_values(cols, ascending=asc, na_position="last")


def score_or_empty_recommendations(
    available: pd.DataFrame | None,
    roster_df: pd.DataFrame | None,
    *,
    score_fn: Any = None,
    score_kwargs: dict[str, Any] | None = None,
    path: str = "",
    session: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    """Run scoring when possible; never return an unscored non-empty frame for sorting.

    Returns ``(scored_df, gaps, diagnostics)``.
    """
    diag = recommendation_schema_diagnostics(available, path=path or "score_or_empty")
    if available is None or not isinstance(available, pd.DataFrame) or available.empty:
        diag["status"] = "empty_pool"
        return pd.DataFrame(), [], diag

    gaps: list[str] = []
    scored = available
    try:
        if score_fn is None:
            from live_draft_pick_scoring import apply_draft_pick_scoring as score_fn

        result = score_fn(available, roster_df if roster_df is not None else pd.DataFrame(), **(score_kwargs or {}))
        if isinstance(result, tuple):
            scored = result[0]
            gaps = list(result[1] or []) if len(result) > 1 else []
        else:
            scored = result
    except Exception as exc:
        diag["status"] = "scoring_failed"
        diag["exception_type"] = type(exc).__name__
        diag["exception"] = str(exc)
        _store_admin_diag(session, diag)
        return pd.DataFrame(), [], diag

    missing = missing_ranking_columns(scored)
    diag = recommendation_schema_diagnostics(
        scored,
        path=path or "score_or_empty",
        extra={"gaps": gaps, "status": "ok" if not missing else "missing_after_score"},
    )
    if missing:
        # Do not hand unscored rows to sort sites — fail closed to empty tables.
        diag["missing_ranking_columns"] = missing
        _store_admin_diag(session, diag)
        return pd.DataFrame(), gaps, diag

    scored = ensure_recommendation_ranking_schema(scored)
    _store_admin_diag(session, diag)
    return scored, gaps, diag


def _store_admin_diag(session: dict[str, Any] | None, diag: dict[str, Any]) -> None:
    if not isinstance(session, dict):
        return
    session["_recommendation_schema_diag"] = dict(diag)


USER_REC_UNAVAILABLE = (
    "Recommendations could not be loaded right now. "
    "You can continue drafting from the available-player list."
)
USER_REC_EMPTY = "No eligible players are currently available."
USER_REC_TEMP = (
    "Recommendations are temporarily unavailable. You can still draft from the player list."
)
