"""Diagnostic lines for top raw-value players missing from recommendation tables."""

from __future__ import annotations

from typing import Any

import pandas as pd

from live_draft_roster_slots import (
    _eligible_for_draft_slot,
    _player_position_tokens,
    league_allows_pitcher_recommendations,
)
from recommendation_dedupe import recommendation_player_id

DEFAULT_TRACE_PLAYERS: tuple[str, ...] = (
    "Shohei Ohtani",
    "Aaron Judge",
    "Juan Soto",
)


def _player_name_col(df: pd.DataFrame) -> str:
    for col in ("fullName", "Player"):
        if col in df.columns:
            return col
    return "fullName"


def _normalize_name(name: str) -> str:
    return str(name or "").strip().casefold()


def _find_player_row(df: pd.DataFrame | None, player_name: str) -> pd.Series | None:
    if df is None or getattr(df, "empty", True):
        return None
    col = _player_name_col(df)
    if col not in df.columns:
        return None
    target = _normalize_name(player_name)
    matches = df[df[col].astype(str).str.strip().str.casefold() == target]
    if matches.empty:
        return None
    return matches.iloc[0]


def _player_in_frame(df: pd.DataFrame | None, player_name: str) -> bool:
    return _find_player_row(df, player_name) is not None


def _player_matches_position_needs(row: pd.Series, needed_positions: list[str] | None) -> bool:
    needed = [str(p).strip().upper() for p in (needed_positions or []) if str(p).strip()]
    if not needed:
        return True
    tokens = _player_position_tokens(row)
    for need in needed:
        slot = "DH" if need in ("UTIL", "DH") else need
        if _eligible_for_draft_slot(tokens, slot):
            return True
    return False


def _util_only_for_open_needs(row: pd.Series, needed_positions: list[str] | None) -> bool:
    needed = {str(p).strip().upper() for p in (needed_positions or []) if str(p).strip()}
    if not needed:
        return False
    tokens = set(_player_position_tokens(row))
    hitter_tokens = tokens - {"P", "SP", "RP"}
    if not hitter_tokens:
        return False
    flex_needed = needed & {"UTIL", "DH"}
    if flex_needed:
        return False
    specific_needed = needed - {"UTIL", "DH", "BN", "BENCH"}
    if not specific_needed:
        return False
    return not any(tok in specific_needed for tok in hitter_tokens)


def _fit_rank(
    available: pd.DataFrame | None,
    player_name: str,
    *,
    rank_col: str,
) -> int | None:
    if available is None or getattr(available, "empty", True) or rank_col not in available.columns:
        return None
    ranked = available.sort_values(rank_col, ascending=False).reset_index(drop=True)
    col = _player_name_col(ranked)
    for idx, row in ranked.iterrows():
        if _normalize_name(row.get(col)) == _normalize_name(player_name):
            return int(idx) + 1
    return None


def _exclusion_reason(
    *,
    player_name: str,
    in_source: bool,
    in_available: bool,
    in_recs: bool,
    drafted_or_rostered: bool,
    pitcher_excluded: bool,
    position_eligible: bool,
    util_not_needed: bool,
    cache_hit: bool,
    fit_rank: int | None,
    rec_limit: int,
) -> str:
    if not in_source:
        return "not in pool"
    if drafted_or_rostered:
        return "drafted or rostered"
    if pitcher_excluded:
        return "pitcher excluded (no P slots or hitter-only format)"
    if cache_hit and not in_available:
        return "scoring cache — refresh to rebuild available pool"
    if not in_available:
        return "filtered from available pool"
    if util_not_needed:
        return "UTIL not needed (position filter)"
    if not position_eligible:
        return "position filter"
    if in_recs:
        return "in recommendation table"
    if fit_rank is not None and fit_rank <= int(rec_limit):
        return "deduped from table (featured card or raw-value merge)"
    if fit_rank is not None:
        return f"below top {int(rec_limit)} by rank ({fit_rank})"
    return "excluded from recommendation table"


def diagnose_recommendation_player(
    player_name: str,
    *,
    source_pool: pd.DataFrame | None,
    available_pool: pd.DataFrame | None,
    recs: pd.DataFrame | None,
    drafted_or_rostered: set[str] | None = None,
    needed_positions: list[str] | None = None,
    cache_hit: bool = False,
    value_col: str = "Expected Fantasy Value",
    rank_col: str = "Draft Fit Score",
    rec_limit: int = 15,
    config: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    fantasy_format: str | None = None,
) -> dict[str, Any]:
    """Single-player diagnostic snapshot for recommendation debugging."""
    drafted = drafted_or_rostered or set()
    drafted_norm = {_normalize_name(n) for n in drafted}
    name_norm = _normalize_name(player_name)

    source_row = _find_player_row(source_pool, player_name)
    available_row = _find_player_row(available_pool, player_name)
    in_source = source_row is not None
    in_available = available_row is not None
    drafted_flag = name_norm in drafted_norm

    rec_ids: set[str] = set()
    if recs is not None and not getattr(recs, "empty", True):
        rec_ids = set(recs.apply(recommendation_player_id, axis=1))
    source_id = recommendation_player_id(source_row) if source_row is not None else ""
    in_recs = bool(source_id and source_id in rec_ids)

    row_for_checks = available_row if available_row is not None else source_row
    pitcher_excluded = False
    if row_for_checks is not None and not league_allows_pitcher_recommendations(
        config=config,
        session=session,
        context=context,
        fantasy_format=fantasy_format,
    ):
        try:
            from live_draft_roster_slots import _is_pitcher_only_player_row

            pitcher_excluded = bool(_is_pitcher_only_player_row(row_for_checks))
        except ImportError:
            pitcher_excluded = False

    position_eligible = True
    util_not_needed = False
    if row_for_checks is not None:
        position_eligible = _player_matches_position_needs(row_for_checks, needed_positions)
        util_not_needed = _util_only_for_open_needs(row_for_checks, needed_positions)

    fit_rank = _fit_rank(available_pool, player_name, rank_col=rank_col)
    reason = _exclusion_reason(
        player_name=player_name,
        in_source=in_source,
        in_available=in_available,
        in_recs=in_recs,
        drafted_or_rostered=drafted_flag,
        pitcher_excluded=pitcher_excluded,
        position_eligible=position_eligible,
        util_not_needed=util_not_needed,
        cache_hit=cache_hit,
        fit_rank=fit_rank,
        rec_limit=rec_limit,
    )

    return {
        "player": player_name,
        "available": "yes" if in_available else "no",
        "drafted_or_rostered": "yes" if drafted_flag else "no",
        "position_eligible": "yes" if position_eligible else "no",
        "draft_fit_rank": fit_rank if fit_rank is not None else "—",
        "reason_excluded": reason,
        "raw_value_rank": _fit_rank(source_pool, player_name, rank_col=value_col),
    }


def diagnose_recommendation_players(
    *,
    source_pool: pd.DataFrame | None,
    available_pool: pd.DataFrame | None,
    recs: pd.DataFrame | None,
    drafted_or_rostered: set[str] | None = None,
    needed_positions: list[str] | None = None,
    cache_hit: bool = False,
    value_col: str = "Expected Fantasy Value",
    rank_col: str = "Draft Fit Score",
    rec_limit: int = 15,
    trace_players: tuple[str, ...] | list[str] | None = None,
    config: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    fantasy_format: str | None = None,
) -> list[dict[str, Any]]:
    """Build diagnostic rows for trace players plus the top raw-value available name."""
    names: list[str] = []
    for name in tuple(trace_players or DEFAULT_TRACE_PLAYERS):
        clean = str(name or "").strip()
        if clean and clean not in names:
            names.append(clean)

    if source_pool is not None and not getattr(source_pool, "empty", True) and value_col in source_pool.columns:
        top = source_pool.sort_values(value_col, ascending=False).head(1)
        if not top.empty:
            col = _player_name_col(top)
            top_name = str(top.iloc[0].get(col) or "").strip()
            if top_name and top_name not in names:
                names.insert(0, top_name)

    common = {
        "source_pool": source_pool,
        "available_pool": available_pool,
        "recs": recs,
        "drafted_or_rostered": drafted_or_rostered,
        "needed_positions": needed_positions,
        "cache_hit": cache_hit,
        "value_col": value_col,
        "rank_col": rank_col,
        "rec_limit": rec_limit,
        "config": config,
        "session": session,
        "context": context,
        "fantasy_format": fantasy_format,
    }
    return [diagnose_recommendation_player(name, **common) for name in names]


def format_recommendation_diagnostic_line(row: dict[str, Any]) -> str:
    """Compact one-line diagnostic for UI captions."""
    player = str(row.get("player") or "—")
    return (
        f"**{player}** — Available: {row.get('available', '—')} · "
        f"Drafted/rostered: {row.get('drafted_or_rostered', '—')} · "
        f"Position eligible: {row.get('position_eligible', '—')} · "
        f"Draft Fit rank: {row.get('draft_fit_rank', '—')} · "
        f"Excluded: {row.get('reason_excluded', '—')}"
    )
