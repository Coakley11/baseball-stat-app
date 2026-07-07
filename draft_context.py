"""Canonical runtime draft context — one source of truth for the live draft board state.

This module composes existing draft primitives (draft board, live room, roster slots,
needs inference) into a single ``DraftContext`` that every draft-aware page can consume:

- ``drafted_players``   — every player already drafted onto any roster (names, lowercased keys)
- ``available_players`` — the pool minus drafted players (when a pool is supplied)
- ``open_positions``    — the active team's remaining required roster slots (position codes)
- ``active_team``       — the user's fantasy team in the active draft
- ``roster_construction`` — filled/target slots + per-position fill state + progress

Research Mode pages should use ``available_players`` + ``open_positions`` (position needs only).
Live Draft Room and the Draft Assistant Simulator additionally use category needs + roster fit
via the existing ``apply_draft_pick_scoring`` engine.

The distinction from ``shared_draft_context.py``: that module owns draft *settings*
(lookback window, projection style, format, ML blend, position-need sync flag). This module
owns the live draft *board state* (who's been drafted, what's open, whose team).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


def _norm_key(name: Any) -> str:
    """Stable lowercase key for drafted-player membership tests."""
    return str(name or "").strip().lower()


def _first_name_col(df: pd.DataFrame) -> str | None:
    for col in ("fullName", "Player", "Name", "player", "PlayerName"):
        if col in df.columns:
            return col
    return None


@dataclass
class DraftContext:
    """Immutable-ish snapshot of the active draft board state for one render pass."""

    active: bool = False
    active_team: str = ""
    drafted_names: list[str] = field(default_factory=list)
    drafted_keys: frozenset[str] = field(default_factory=frozenset)
    open_positions: list[str] = field(default_factory=list)
    filled_positions: dict[str, int] = field(default_factory=dict)
    roster_construction: dict[str, Any] = field(default_factory=dict)
    fantasy_format: str = "5x5 Roto"
    draft_complete: bool = False
    source: str = ""

    def is_drafted(self, player_name: Any) -> bool:
        return _norm_key(player_name) in self.drafted_keys

    def filter_available(self, df: pd.DataFrame | None, *, name_col: str | None = None) -> pd.DataFrame:
        """Return only undrafted rows. When no active draft, the pool is returned unchanged."""
        if df is None or getattr(df, "empty", True):
            return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
        if not self.active or not self.drafted_keys:
            return df
        col = name_col or _first_name_col(df)
        if col is None:
            return df
        keys = df[col].map(_norm_key)
        return df.loc[~keys.isin(self.drafted_keys)].copy()

    def open_position_set(self) -> set[str]:
        """Unique open position codes (deduped) for boost membership tests."""
        return {str(p).strip().upper() for p in self.open_positions if str(p).strip()}


def _resolve_active_team(session: dict[str, Any]) -> str:
    try:
        from draft_actions import draft_action_context

        ctx = draft_action_context(session)
        team = str(ctx.get("your_team") or "").strip()
        if team:
            return team
    except Exception:
        pass
    # Fallbacks that don't require the full action context.
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        cfg = dict(room.get("config") or {})
        team = str(cfg.get("your_team") or cfg.get("user_team") or "").strip()
        if team:
            return team
    return str(session.get("room_your_team") or "").strip()


def _drafted_player_names(session: dict[str, Any]) -> list[str]:
    try:
        from draft_room_state import get_all_drafted_player_names

        names = get_all_drafted_player_names(session)
        if names:
            return [str(n).strip() for n in names if str(n).strip()]
    except Exception:
        pass
    # Live-room fallback (before canonical board sync).
    room = session.get("live_draft_room")
    names: list[str] = []
    if isinstance(room, dict):
        board = room.get("draft_board") or []
        if isinstance(board, list):
            for entry in board:
                if isinstance(entry, dict):
                    nm = str(entry.get("fullName") or entry.get("Player") or "").strip()
                    if nm:
                        names.append(nm)
    return list(dict.fromkeys(names))


def _active_team_roster_df(session: dict[str, Any], team: str) -> pd.DataFrame:
    """The active team's drafted players as a DataFrame (rich rows when available)."""
    if not team:
        return pd.DataFrame()
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        rows = list((room.get("rosters") or {}).get(str(team), []) or [])
        if rows:
            return pd.DataFrame(rows)
    # Simulator / synced board fallback.
    try:
        from draft_room_state import get_canonical_draft_board

        board = get_canonical_draft_board(session)
        if isinstance(board, pd.DataFrame) and not board.empty and "Team" in board.columns:
            rows = board[board["Team"].astype(str).str.strip() == str(team).strip()]
            names = [str(p).strip() for p in rows.get("Player", pd.Series(dtype=str)).dropna() if str(p).strip()]
            if names:
                return pd.DataFrame({"Player": names, "Primary Position": ["" for _ in names]})
    except Exception:
        pass
    return pd.DataFrame()


def _slot_config(session: dict[str, Any]) -> dict[str, Any]:
    try:
        from live_draft_roster_slots import resolve_draft_slot_config_from_session

        return resolve_draft_slot_config_from_session(session)
    except Exception:
        return {}


def _fantasy_format(session: dict[str, Any]) -> str:
    try:
        from shared_draft_context import read_canonical_draft_settings

        return str(read_canonical_draft_settings(session).get("fantasy_format") or "5x5 Roto")
    except Exception:
        return "5x5 Roto"


def _is_draft_active(session: dict[str, Any]) -> bool:
    try:
        from shared_draft_context import has_active_draft_context

        return bool(has_active_draft_context(session))
    except Exception:
        return False


def resolve_draft_context(
    session: dict[str, Any],
    *,
    pool_df: pd.DataFrame | None = None,
) -> DraftContext:
    """Build the canonical runtime draft context from session state.

    ``pool_df`` is optional: when provided, callers can immediately call
    ``ctx.filter_available(pool_df)`` — the pool itself is not stored on the context.
    """
    active = _is_draft_active(session)
    fmt = _fantasy_format(session)
    if not active:
        return DraftContext(active=False, fantasy_format=fmt)

    team = _resolve_active_team(session)
    drafted_names = _drafted_player_names(session)
    drafted_keys = frozenset(_norm_key(n) for n in drafted_names if _norm_key(n))

    cfg = _slot_config(session)
    roster_df = _active_team_roster_df(session, team)

    open_positions: list[str] = []
    filled: dict[str, int] = {}
    construction: dict[str, Any] = {}
    draft_complete = False
    if cfg.get("slots"):
        try:
            from live_draft_roster_slots import (
                assign_roster_to_slot_instances,
                get_filled_position_counts,
                get_remaining_position_needs,
            )

            construction = assign_roster_to_slot_instances(roster_df, cfg)
            open_positions = get_remaining_position_needs(roster_df, cfg)
            filled = get_filled_position_counts(roster_df)
            draft_complete = bool(construction.get("target")) and int(construction.get("filled") or 0) >= int(
                construction.get("target") or 0
            )
        except Exception:
            pass

    return DraftContext(
        active=True,
        active_team=team,
        drafted_names=drafted_names,
        drafted_keys=drafted_keys,
        open_positions=open_positions,
        filled_positions=filled,
        roster_construction=construction,
        fantasy_format=fmt,
        draft_complete=draft_complete,
        source="live_or_simulator",
    )


def scoring_position_needs(ctx: DraftContext) -> list[str]:
    """Open positions normalized for scoring (empty when only flex/bench remain)."""
    try:
        from draft_needs import normalize_position_needs_for_scoring

        return normalize_position_needs_for_scoring(ctx.open_positions)
    except Exception:
        seen: list[str] = []
        for p in ctx.open_positions:
            s = str(p).strip().upper()
            if s and s not in ("BN", "BENCH", "DH", "UTIL") and s not in seen:
                seen.append(s)
        return seen
