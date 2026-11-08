"""Recommendation Rankings tables: the same scored pool as the recommendation cards (owner review, 2026-11-08).

Root cause of the empty tables:
* The rankings paint step read its four tables into locals that light, timer-owned or poll-applied pick runs
  never recomputed. The cards rebuild from their own fallback chain, so the cards were full while the tables
  were empty.
* The "Why this pick" enrichment cache was keyed by the board fingerprint only, so it stored one run's empty
  tables and kept serving them for the whole pick.

This module only re-reads tables that already exist, never rescoring and never changing Auto Pick:
1. ``split_recommendation_tables`` is the one place the four tables are cut from a scored pool, used by both
   the scoring pass and the fallback.
2. ``fill_missing_ranking_tables`` fills empty tables, first from the cards' cache (``REC_CACHE_KEY``), then
   from this pick's scored pool (``SCORED_POOL_KEY``). Drafted players are always removed.
3. ``empty_tab_message`` is the plain explanation shown instead of a bare empty table.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

NAMES = ("top_rec", "best_avail", "pos_fit", "value_sleep")
REFRESHING = "Rankings are refreshing for this pick. The recommendation cards above are current."
NO_POSITIONAL_NEED = "No specific positional need flagged: take the best value."


def _empty(df: Any) -> bool:
    return not isinstance(df, pd.DataFrame) or df.empty


def split_recommendation_tables(scored: pd.DataFrame, gaps: list[str] | None, top_n: int) -> tuple:
    """(top_rec, best_avail, pos_fit, value_sleep) from one scored pool (identical to the scoring pass)."""
    from live_draft_recommendations import safe_sort_recommendations

    if _empty(scored):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    top_recommended = scored.head(top_n)
    best_available = safe_sort_recommendations(
        scored, ["Decision Score", "Expected Fantasy Value"], ascending=[False, False]
    ).head(top_n)
    if gaps and "Primary Position" in scored.columns:
        positional = safe_sort_recommendations(
            scored[scored["Primary Position"].isin(gaps)], ["Positional Fit", "Draft Fit Score"], ascending=[False, False]
        ).head(top_n)
    else:
        positional = pd.DataFrame()
    sleepers = safe_sort_recommendations(scored, ["Sleeper Score", "Draft Fit Score"], ascending=[False, False]).head(top_n)
    return top_recommended, best_available, positional, sleepers


def fill_missing_ranking_tables(session: Any, room: dict[str, Any] | None, tables: dict[str, Any], *,
                                gaps: list[str] | None = None, top_n: int = 10) -> tuple[dict[str, Any], str]:
    """``(tables, source)``. Empty tables are filled from the cards' cache, then from this pick's scored
    pool. Positional Fits stays empty when there are no positional gaps (that is a real answer)."""
    out = {n: tables.get(n) if isinstance(tables.get(n), pd.DataFrame) else pd.DataFrame() for n in NAMES}
    want = [n for n in NAMES if _empty(out[n]) and (n != "pos_fit" or gaps)]
    if not want or not isinstance(session, dict):
        return out, "current"
    from live_draft_ui_cache import REC_CACHE_KEY, filter_recommendation_tables_for_drafted

    source = "current"
    entry = session.get(REC_CACHE_KEY)
    if isinstance(entry, dict):
        for n in list(want):
            if not _empty(entry.get(n)):
                out[n], want, source = entry[n], [w for w in want if w != n], "cards_cache"
    if want:
        try:
            from draft_strategy_in_draft import SCORED_POOL_KEY, _pick_marker

            pool = session.get(SCORED_POOL_KEY)
            if isinstance(pool, dict) and pool.get("pick") == _pick_marker(room) and not _empty(pool.get("df")):
                rebuilt = dict(zip(NAMES, split_recommendation_tables(pool["df"], gaps, top_n)))
                for n in list(want):
                    if not _empty(rebuilt[n]):
                        out[n], want, source = rebuilt[n], [w for w in want if w != n], "scored_pool"
        except ImportError:
            pass
    filtered = filter_recommendation_tables_for_drafted(room, *(out[n] for n in NAMES))
    return dict(zip(NAMES, filtered)), source


def tables_signature(tables: dict[str, Any]) -> tuple:
    """Rows and the first players of each table: a cache can only reuse enrichment for these same tables."""
    sig = []
    for n in sorted(tables):
        df = tables[n]
        if not isinstance(df, pd.DataFrame):
            sig.append((n, -1, ()))
            continue
        col = next((c for c in ("playerID", "Player ID", "fullName", "Player") if c in df.columns), None)
        head = tuple(df[col].astype(str).head(10)) if col else ()
        sig.append((n, len(df), head))
    return tuple(sig)


def empty_tab_message(name: str, *, gaps: list[str] | None = None) -> str:
    if name == "pos_fit" and not gaps:
        return NO_POSITIONAL_NEED
    return REFRESHING
