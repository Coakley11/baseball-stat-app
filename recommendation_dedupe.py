"""Exclude featured recommendation players from follow-on lists (by player_id)."""

from __future__ import annotations

from typing import Any

import pandas as pd


def recommendation_player_id(row: Any) -> str:
    """Stable id for deduplication — prefers playerID over name."""
    if row is None:
        return ""
    for key in ("playerID", "player_id"):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    name = str(row.get("fullName") or row.get("Player") or "").strip()
    return f"name:{name.lower()}" if name else ""


def collect_featured_player_ids(*featured: Any) -> set[str]:
    """Unique player ids from Series rows and/or DataFrames."""
    ids: set[str] = set()
    for item in featured:
        if item is None:
            continue
        if isinstance(item, pd.DataFrame):
            if getattr(item, "empty", True):
                continue
            for _, row in item.iterrows():
                pid = recommendation_player_id(row)
                if pid:
                    ids.add(pid)
            continue
        if isinstance(item, pd.Series):
            pid = recommendation_player_id(item)
            if pid:
                ids.add(pid)
    return ids


def exclude_recommendation_player_ids(
    df: pd.DataFrame | None,
    exclude_ids: set[str],
) -> pd.DataFrame:
    """Drop rows whose player_id is in exclude_ids."""
    if df is None or getattr(df, "empty", True) or not exclude_ids:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    work = df.copy()
    pids = work.apply(recommendation_player_id, axis=1)
    return work.loc[~pids.isin(exclude_ids)].copy()


def remaining_recommendations(
    ranked_df: pd.DataFrame | None,
    featured_ids: set[str],
    *,
    limit: int,
) -> pd.DataFrame:
    """Next unique recommendations after featured cards, preserving rank order."""
    if ranked_df is None or getattr(ranked_df, "empty", True) or limit <= 0:
        return pd.DataFrame()
    return exclude_recommendation_player_ids(ranked_df, featured_ids).head(int(limit)).copy()


def ensure_top_raw_value_in_recommendations(
    recs: pd.DataFrame | None,
    available: pd.DataFrame | None,
    *,
    limit: int,
    value_col: str = "Expected Fantasy Value",
) -> pd.DataFrame:
    """Keep the highest raw-value available player visible in the recommendation table."""
    if available is None or getattr(available, "empty", True) or limit <= 0:
        return recs.copy() if isinstance(recs, pd.DataFrame) else pd.DataFrame()
    if value_col not in available.columns:
        return recs.copy() if isinstance(recs, pd.DataFrame) else pd.DataFrame()
    top_raw = available.sort_values(value_col, ascending=False).head(1)
    if top_raw.empty:
        return recs.copy() if isinstance(recs, pd.DataFrame) else pd.DataFrame()
    top_id = recommendation_player_id(top_raw.iloc[0])
    work = recs.copy() if isinstance(recs, pd.DataFrame) and not recs.empty else pd.DataFrame()
    if not work.empty:
        existing = set(work.apply(recommendation_player_id, axis=1))
        if top_id in existing:
            return work.head(int(limit)).copy()
    merged = pd.concat([top_raw.head(1), work], ignore_index=False)
    deduped: list[Any] = []
    seen: set[str] = set()
    for _, row in merged.iterrows():
        pid = recommendation_player_id(row)
        if pid and pid in seen:
            continue
        if pid:
            seen.add(pid)
        deduped.append(row)
    if not deduped:
        return pd.DataFrame()
    out = pd.DataFrame(deduped)
    return out.head(int(limit)).copy()


def add_recommendation_rank_column(
    df: pd.DataFrame | None,
    *,
    start_rank: int = 1,
) -> pd.DataFrame:
    """Prefix display table with 1-based rank numbers."""
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame()
    out = df.copy()
    out.insert(0, "Rank", range(int(start_rank), int(start_rank) + len(out)))
    return out
