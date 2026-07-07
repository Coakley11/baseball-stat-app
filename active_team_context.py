"""Unified active-team context — one resolver for the whole app.

This module encodes the single source-of-truth priority rule requested by the
product owner:

    Active League Team  >  Draft Assistant Simulator Team

- If an **Active League** (saved Active Draft) is selected, it wins: use that
  league's user team, its rostered players, and its position/category context.
- Otherwise, fall back to the **Draft Assistant Simulator** (the live/simulator
  draft board via ``draft_context.resolve_draft_context``): the simulator team
  becomes the active team.

Every draft- and research-aware page should resolve context through
``resolve_active_team_context`` instead of reaching into league context or the
draft board directly. That guarantees consistent answers to:

- who is my team?
- which players are already drafted / rostered (unavailable)?
- what positions do I still need?
- what hitter categories are weak?
- which players are still available (recalculated pool)?

The two upstream primitives this composes:

- ``fantasy_league_context`` — saved Active Draft (``league_rosters``, ownership).
- ``draft_context.DraftContext`` — live/simulator board state (drafted, open slots).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

SOURCE_LEAGUE = "active_league"
SOURCE_SIMULATOR = "simulator"
SOURCE_NONE = "none"


def _norm_key(name: Any) -> str:
    return str(name or "").strip().lower()


def _first_name_col(df: pd.DataFrame) -> str | None:
    for col in ("fullName", "Player", "player_name", "Name", "player", "PlayerName"):
        if col in df.columns:
            return col
    return None


@dataclass
class ActiveTeamContext:
    """Resolved active-team snapshot for a single render pass.

    ``source`` records which layer supplied the context so pages can badge it and
    tests can assert the priority rule.
    """

    source: str = SOURCE_NONE
    active_team: str = ""
    fantasy_format: str = "5x5 Roto"
    # Everyone drafted/rostered anywhere in the active draft/league — unavailable.
    drafted_names: list[str] = field(default_factory=list)
    drafted_keys: frozenset[str] = field(default_factory=frozenset)
    # The active team's own roster (drafted rows).
    my_roster_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Open required roster slots (position codes), normalized for scoring.
    position_needs: list[str] = field(default_factory=list)
    # Weak hitter categories (labels: HR, RBI, SB, AVG, ...).
    category_needs: list[str] = field(default_factory=list)
    draft_complete: bool = False

    @property
    def has_active_team(self) -> bool:
        return bool(self.active_team) and self.source != SOURCE_NONE

    def is_unavailable(self, player_name: Any) -> bool:
        """True when the player is already drafted/rostered in the active context."""
        return _norm_key(player_name) in self.drafted_keys

    def available_pool(
        self,
        df: pd.DataFrame | None,
        *,
        name_col: str | None = None,
    ) -> pd.DataFrame:
        """Return only available (undrafted / unrostered) rows.

        When there is no active context, the pool is returned unchanged. This is
        the recalculation entry point — callers should re-rank / re-score the
        returned frame rather than merely hiding rows in a display layer.
        """
        if df is None or getattr(df, "empty", True):
            return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
        if not self.drafted_keys:
            return df
        col = name_col or _first_name_col(df)
        if col is None:
            return df
        keys = df[col].map(_norm_key)
        return df.loc[~keys.isin(self.drafted_keys)].reset_index(drop=True)


# ── Active League branch ─────────────────────────────────────────────────────


def _league_drafted_names(context: dict[str, Any]) -> list[str]:
    try:
        from fantasy_waiver_wire import rostered_player_names

        names = rostered_player_names(context)
        if names:
            return sorted(names)
    except Exception:
        pass
    names: list[str] = []
    rosters = context.get("league_rosters") or {}
    if isinstance(rosters, dict):
        for entry in rosters.values():
            if not isinstance(entry, dict):
                continue
            for player in entry.get("players") or []:
                if isinstance(player, dict):
                    nm = str(player.get("player_name") or "").strip()
                    if nm:
                        names.append(nm)
    return list(dict.fromkeys(names))


def _league_my_roster_df(context: dict[str, Any]) -> pd.DataFrame:
    try:
        from fantasy_waiver_wire import my_team_roster_dataframe

        return my_team_roster_dataframe(context)
    except Exception:
        return pd.DataFrame()


def _league_position_needs(context: dict[str, Any], roster_df: pd.DataFrame) -> list[str]:
    try:
        from fantasy_league_context import (
            context_has_roster_slots,
            resolve_context_open_position_needs,
        )

        if not context_has_roster_slots(context):
            return []
        gaps = resolve_context_open_position_needs(context, roster_df)
    except Exception:
        return []
    try:
        from draft_needs import normalize_position_needs_for_scoring

        return normalize_position_needs_for_scoring(gaps)
    except Exception:
        return list(dict.fromkeys(gaps or []))


def _resolve_from_league(
    context: dict[str, Any],
    *,
    pool_df: pd.DataFrame | None,
) -> ActiveTeamContext:
    team = str(context.get("my_team_name") or "").strip()
    fmt = str(context.get("fantasy_format") or "5x5 Roto").strip() or "5x5 Roto"
    drafted_names = _league_drafted_names(context)
    drafted_keys = frozenset(_norm_key(n) for n in drafted_names if _norm_key(n))
    my_roster = _league_my_roster_df(context)
    position_needs = _league_position_needs(context, my_roster)
    category_needs = _hitter_category_needs(my_roster, pool_df, fmt)
    return ActiveTeamContext(
        source=SOURCE_LEAGUE,
        active_team=team,
        fantasy_format=fmt,
        drafted_names=drafted_names,
        drafted_keys=drafted_keys,
        my_roster_df=my_roster,
        position_needs=position_needs,
        category_needs=category_needs,
        draft_complete=False,
    )


# ── Simulator branch ─────────────────────────────────────────────────────────


def _resolve_from_simulator(
    session: dict[str, Any],
    *,
    pool_df: pd.DataFrame | None,
) -> ActiveTeamContext | None:
    try:
        from draft_context import resolve_draft_context, scoring_position_needs
    except Exception:
        return None
    ctx = resolve_draft_context(session, pool_df=pool_df)
    if not getattr(ctx, "active", False):
        return None
    my_roster = getattr(ctx, "_active_roster_df", None)
    if my_roster is None or getattr(my_roster, "empty", True):
        my_roster = _simulator_my_roster_df(session, ctx.active_team)
    category_needs = _hitter_category_needs(my_roster, pool_df, ctx.fantasy_format)
    return ActiveTeamContext(
        source=SOURCE_SIMULATOR,
        active_team=ctx.active_team,
        fantasy_format=ctx.fantasy_format,
        drafted_names=list(ctx.drafted_names),
        drafted_keys=ctx.drafted_keys,
        my_roster_df=my_roster,
        position_needs=scoring_position_needs(ctx),
        category_needs=category_needs,
        draft_complete=bool(ctx.draft_complete),
    )


def _simulator_my_roster_df(session: dict[str, Any], team: str) -> pd.DataFrame:
    try:
        from draft_context import _active_team_roster_df

        return _active_team_roster_df(session, team)
    except Exception:
        return pd.DataFrame()


# ── Shared category-need inference ───────────────────────────────────────────


def _hitter_category_needs(
    roster_df: pd.DataFrame | None,
    pool_df: pd.DataFrame | None,
    fantasy_format: str,
) -> list[str]:
    if roster_df is None or getattr(roster_df, "empty", True):
        return []
    if pool_df is None or getattr(pool_df, "empty", True):
        return []
    try:
        from draft_needs import infer_hitter_category_needs

        return infer_hitter_category_needs(
            roster_df,
            pool_df,
            fantasy_format=fantasy_format or "5x5 Roto",
        )
    except Exception:
        return []


# ── Public entry point ───────────────────────────────────────────────────────


def resolve_active_team_context(
    session: dict[str, Any],
    *,
    pool_df: pd.DataFrame | None = None,
) -> ActiveTeamContext:
    """Resolve the active team context using the Active League > Simulator rule.

    1. If a saved Active League context exists with a user team, use it.
    2. Otherwise fall back to the live/simulator draft board.
    3. If neither is present, return an empty context (general MLB mode).

    ``pool_df`` (the unified projection pool) is optional but recommended: it lets
    the resolver compute hitter category needs and lets callers immediately call
    ``ctx.available_pool(pool_df)`` to recalculate on the remaining player pool.
    """
    context = None
    try:
        from fantasy_league_context import get_active_league_context

        context = get_active_league_context(session)
    except Exception:
        context = None

    if isinstance(context, dict) and str(context.get("my_team_name") or "").strip():
        return _resolve_from_league(context, pool_df=pool_df)

    sim = _resolve_from_simulator(session, pool_df=pool_df)
    if sim is not None:
        return sim

    fmt = "5x5 Roto"
    try:
        from shared_draft_context import read_canonical_draft_settings

        fmt = str(read_canonical_draft_settings(session).get("fantasy_format") or fmt)
    except Exception:
        pass
    return ActiveTeamContext(source=SOURCE_NONE, fantasy_format=fmt)


_POSITION_COLS = ("Primary Position", "Position", "positions", "primaryPos", "Pos")
_POSITION_ALIASES: dict[str, set[str]] = {
    "C": {"C"},
    "1B": {"1B"},
    "2B": {"2B"},
    "3B": {"3B"},
    "SS": {"SS"},
    "OF": {"OF", "LF", "CF", "RF"},
    "DH": {"DH", "UTIL"},
    "P": {"P", "SP", "RP"},
}


def _position_tokens(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        raw = [str(v) for v in value]
    else:
        raw = str(value).replace("/", ",").replace(";", ",").split(",")
    return {tok.strip().upper() for tok in raw if str(tok).strip()}


def player_helps_positions(row_positions: Any, needed: set[str]) -> bool:
    """True when a player's eligible positions intersect any needed position."""
    if not needed:
        return False
    tokens = _position_tokens(row_positions)
    if not tokens:
        return False
    for need in needed:
        aliases = _POSITION_ALIASES.get(str(need).strip().upper(), {str(need).strip().upper()})
        if tokens & aliases:
            return True
    return False


def apply_position_need_boost(
    df: pd.DataFrame | None,
    needed_positions: list[str] | None,
    *,
    score_col: str,
    boost: float = 0.12,
    position_col: str | None = None,
) -> pd.DataFrame:
    """Boost a recommendation score for players eligible at a needed position.

    Additive multiplier on ``score_col`` (default +12%) applied only to rows whose
    eligible positions match one of ``needed_positions``. Non-matching players are
    left unchanged so elite players at other positions still surface — this is a
    *boost*, not a filter. Returns the frame with an added ``Position Need Boost``
    flag column for transparency.
    """
    if df is None or getattr(df, "empty", True) or score_col not in getattr(df, "columns", []):
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    needed = {str(p).strip().upper() for p in (needed_positions or []) if str(p).strip()}
    out = df.copy()
    if not needed:
        out["Position Need Boost"] = False
        return out
    col = position_col
    if col is None:
        for candidate in _POSITION_COLS:
            if candidate in out.columns:
                col = candidate
                break
    if col is None:
        out["Position Need Boost"] = False
        return out
    mask = out[col].map(lambda v: player_helps_positions(v, needed))
    scores = pd.to_numeric(out[score_col], errors="coerce")
    out.loc[mask, score_col] = scores[mask] * (1.0 + float(boost))
    out["Position Need Boost"] = mask
    return out


_CATEGORY_STAT_ALIASES: dict[str, tuple[str, ...]] = {
    "HR": ("HR", "proj_HR"),
    "RBI": ("RBI", "proj_RBI"),
    "R": ("R", "proj_R"),
    "SB": ("SB", "proj_SB"),
    "AVG": ("AVG", "BA", "proj_BA", "proj_AVG"),
    "OPS": ("OPS", "proj_OPS"),
    "OBP": ("OBP", "proj_OBP"),
    "POWER": ("HR", "proj_HR"),
    "RUN PRODUCTION": ("RBI", "proj_RBI"),
    "SPEED": ("SB", "proj_SB"),
    "WALKS/OPS": ("OPS", "proj_OPS", "OBP", "proj_OBP"),
}


def _category_value_series(df: pd.DataFrame, category: str) -> pd.Series | None:
    key = str(category or "").strip().upper()
    for col in _CATEGORY_STAT_ALIASES.get(key, (key, f"proj_{key}")):
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce")
            if vals.notna().any():
                return vals
    return None


def apply_category_need_boost(
    df: pd.DataFrame | None,
    category_needs: list[str] | None,
    *,
    score_col: str,
    boost: float = 0.10,
) -> pd.DataFrame:
    """Boost recommendation scores for players who help weak team categories.

    Uses current-season or projected stat columns (HR, RBI, SB, AVG, etc.).
    Each weak category adds up to ``boost`` based on the player's relative
    contribution within the pool — power hitters rise when HR/RBI are weak,
    speed when SB is weak, contact when AVG is weak.
    """
    if df is None or getattr(df, "empty", True) or score_col not in getattr(df, "columns", []):
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    needs = [str(c).strip() for c in (category_needs or []) if str(c).strip()]
    out = df.copy()
    if not needs:
        out["Category Need Boost"] = False
        return out
    scores = pd.to_numeric(out[score_col], errors="coerce").fillna(0.0)
    total_boost = pd.Series(0.0, index=out.index)
    helped = pd.Series(False, index=out.index)
    rate_cats = frozenset({"AVG", "BA", "OBP", "OPS"})
    for cat in needs:
        vals = _category_value_series(out, cat)
        if vals is None:
            continue
        vmax = float(vals.max()) or 1.0
        if str(cat).upper() in rate_cats:
            norm = vals.fillna(0.0) / max(vmax, 0.001)
        else:
            norm = vals.fillna(0.0) / vmax
        cat_key = str(cat).upper()
        threshold = 0.55 if cat_key in rate_cats else 0.45
        mask = norm >= threshold
        total_boost = total_boost + norm * float(boost)
        helped = helped | mask
    out[score_col] = scores * (1.0 + total_boost)
    out["Category Need Boost"] = helped
    return out


def apply_research_recommendation_adjustments(
    session: dict[str, Any],
    df: pd.DataFrame | None,
    *,
    score_col: str,
    name_col: str = "fullName",
) -> pd.DataFrame:
    """Research Mode pipeline for research recommendation tables (not lookup pickers).

    1. Removes players already drafted in the active draft (Research Mode ON).
    2. Dense re-ranks the remaining available pool.
    3. Applies **position-need** boosts when the position-needs sync toggle is on.

    Category needs are intentionally NOT applied here — they stay local to the
    Draft Assistant Simulator, Live Draft Room, and Waiver Wire.
    """
    if df is None or getattr(df, "empty", True):
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    try:
        from fantasy_waiver_wire import filter_unrostered_players

        before = len(df)
        out = filter_unrostered_players(session, df, name_col=name_col)
        if len(out) != before:
            out = recalculate_pool_ranks(out)
        ctx = resolve_active_team_context(session)
        pos_boosts = effective_position_boosts(session, ctx)
        if pos_boosts and score_col in out.columns:
            out = apply_position_need_boost(out, pos_boosts, score_col=score_col)
        return out
    except Exception:
        return df


def recalculate_pool_ranks(df: pd.DataFrame | None) -> pd.DataFrame:
    """Recompute rank columns on a (possibly filtered) player pool.

    Research Mode must *recalculate* rankings on the remaining available players
    rather than merely hiding drafted ones. When a research page has already
    filtered the pool through the active-team context, call this to refresh the
    standard rank columns so ranks are dense over the available set (no gaps left
    by removed players).

    Recomputes ``Model Rank`` from ``Blended Projection Score`` /
    ``Expected Fantasy Value`` / ``Player Grade`` when present, and re-derives
    ``Fantasy Edge`` = Market Rank - Model Rank. Any ``*_Score`` column that has a
    matching ``* Rank`` column is also re-ranked. Unknown columns are untouched.
    """
    if df is None or getattr(df, "empty", True):
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = df.copy()
    value_col = None
    for candidate in ("Blended Projection Score", "Expected Fantasy Value", "Player Grade"):
        if candidate in out.columns:
            value_col = candidate
            break
    if value_col is not None and "Model Rank" in out.columns:
        values = pd.to_numeric(out[value_col], errors="coerce")
        out["Model Rank"] = values.rank(ascending=False, method="min")
        if "Market Rank" in out.columns:
            out["Fantasy Edge"] = (
                pd.to_numeric(out["Market Rank"], errors="coerce")
                - pd.to_numeric(out["Model Rank"], errors="coerce")
            )
    for col in list(out.columns):
        if not col.endswith("_Score"):
            continue
        rank_col = col[: -len("_Score")] + " Rank"
        if rank_col in out.columns:
            out[rank_col] = pd.to_numeric(out[col], errors="coerce").rank(
                ascending=False, method="min"
            )
    return out.reset_index(drop=True)


def effective_position_boosts(session: dict[str, Any], ctx: ActiveTeamContext) -> list[str]:
    """Position codes to boost on synced research pages (draft-time only).

    Position Needs are a **draft-time** feature. This returns needs only when:
    - the "Use Draft Assistant position needs on other fantasy pages" sync is ON, and
    - the draft is not complete (after completion, position needs no longer drive
      recommendations — the team already has all required slots).

    When OFF or draft-complete, returns an empty list so pages show all positions.
    """
    if getattr(ctx, "draft_complete", False):
        return []
    try:
        from fantasy_position_sync import is_position_sync_enabled

        if not is_position_sync_enabled(session):
            return []
    except Exception:
        return []
    return list(ctx.position_needs or [])


def effective_category_boosts(session: dict[str, Any], ctx: ActiveTeamContext) -> list[str]:
    """Hitter categories to boost — LOCAL pages only (not synced research pages).

    Category Needs stay local to Draft Assistant Simulator, Live Draft Room, and
    Waiver Wire, and remain active **after** the draft completes (a finished roster
    can still be weak in HR/RBI/SB/AVG). They intentionally do NOT sync to the
    general research pages, so this ignores the position-needs sync toggle.
    """
    return list(ctx.category_needs or [])


def research_mode_signature(session: dict[str, Any]) -> tuple[Any, ...]:
    """Stable cache signature reflecting Research Mode state + unavailable players.

    Include this in scoring cache keys so that toggling Research Mode (or changing
    the active draft) invalidates stale scored pools that still contain drafted
    players. Without it, a pool scored while Research Mode was OFF could be reused
    after it turns ON, re-surfacing already-drafted players.
    """
    try:
        from fantasy_waiver_wire import research_league_sync_enabled

        enabled = bool(research_league_sync_enabled(session))
    except Exception:
        enabled = False
    if not enabled:
        return ("research_off",)
    try:
        ctx = resolve_active_team_context(session)
        return ("research_on", ctx.source, tuple(sorted(ctx.drafted_keys)))
    except Exception:
        return ("research_on", "unknown", ())


def active_team_context_badge(ctx: ActiveTeamContext) -> str:
    """Human-readable badge describing which source supplied the active team."""
    if ctx.source == SOURCE_LEAGUE:
        return f"Active team: **{ctx.active_team}** (Active League)"
    if ctx.source == SOURCE_SIMULATOR:
        return f"Active team: **{ctx.active_team}** (Draft Simulator)"
    return "Active team: **Not set** — start a simulator draft or select an Active League"
