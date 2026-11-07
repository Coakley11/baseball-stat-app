"""The selected Draft Strategy shapes the recommendation cards inside Solo and Live/Shared drafts.

Balanced is the default and leaves the cards exactly as the Draft Assistant scores them. The other
four re-rank the whole scored pool of available players for this pick (not just the top cards):

- Best player available  — projected fantasy value, nothing else.
- Value-based            — value over the replacement level at the player's position (league size ×
                           starting slots at that position, from the draft's own settings).
- Positional scarcity    — value blended with how fast the position is drying up.
- Roster-aware           — value blended with how well the player fits the drafting team's needs.

Each card then leads its reason with the strategy's own explanation ("Value-based: +18 over
replacement at SS"). Only the current draft's available players are ever ranked (the scored pool is
built from them, and drafted players are filtered again). The choice is the viewer's own session
setting (the same key as the Draft Strategy page): it is never written to a Shared Draft room, never
changes who may pick, and never reaches another participant.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

APPROACH_KEY = "draft_strategy_approach"  # same key as draft_strategy_ui (one selection app-wide)
SCORED_POOL_KEY = "_live_draft_scored_pool"
APPROACHES = ("balanced", "best_available", "value_based", "positional_scarcity", "roster_aware")
LABELS = {
    "balanced": "Balanced (recommended)",
    "best_available": "Best player available",
    "value_based": "Value-based (over replacement)",
    "positional_scarcity": "Positional scarcity",
    "roster_aware": "Roster-aware (fill your needs)",
}
SHORT = {
    "best_available": "Best available",
    "value_based": "Value-based",
    "positional_scarcity": "Scarcity",
    "roster_aware": "Roster-aware",
}
_DEFAULT_STARTERS = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "SP": 2, "RP": 2, "P": 4}


def current_approach(session: Any) -> str:
    value = str((session or {}).get(APPROACH_KEY) or "balanced") if hasattr(session, "get") else "balanced"
    return value if value in APPROACHES else "balanced"


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=df.index)


def _scaled(series: pd.Series) -> pd.Series:
    """0..1 min-max (all equal -> 0)."""
    lo, hi = float(series.min()) if len(series) else 0.0, float(series.max()) if len(series) else 0.0
    return (series - lo) / (hi - lo) if hi > lo else series * 0.0


def _value_share(value: pd.Series) -> pd.Series:
    """Projected value as a share of the best available (0..1)."""
    top = float(value.max()) if len(value) else 0.0
    return value / top if top > 0 else value * 0.0


def _starters(room: dict[str, Any] | None) -> dict[str, int]:
    cfg = (room or {}).get("config") if isinstance((room or {}).get("config"), dict) else {}
    slots = cfg.get("slots") if isinstance(cfg.get("slots"), dict) else {}
    out = dict(_DEFAULT_STARTERS)
    for pos, n in slots.items():
        try:
            out[str(pos).upper()] = max(int(n), 0)
        except (TypeError, ValueError):
            continue
    return out


def _team_count(room: dict[str, Any] | None) -> int:
    room = room or {}
    teams = room.get("teams") or (room.get("config") or {}).get("teams") or []
    try:
        return max(len(teams), int((room.get("config") or {}).get("num_teams") or 0), 1)
    except (TypeError, ValueError):
        return max(len(teams), 1)


def rank_pool(pool: pd.DataFrame, approach: str, *, room: dict[str, Any] | None = None) -> pd.DataFrame:
    """The available pool ordered by ``approach``, with a ``Strategy Reason`` column. Pure."""
    if pool is None or not isinstance(pool, pd.DataFrame) or pool.empty or approach == "balanced":
        return pool
    df = pool.copy()
    value = _num(df, "Expected Fantasy Value")
    pos = df["Primary Position"].astype(str).str.upper() if "Primary Position" in df.columns else pd.Series("", index=df.index)
    reasons = pd.Series("", index=df.index, dtype=object)
    if approach == "best_available":
        score = value + _num(df, "Decision Score") * 1e-6
        board_rank = value.rank(ascending=False, method="min").astype(int)
        reasons = "Best available: #" + board_rank.astype(str) + " by projected value"
    elif approach == "value_based":
        starters, teams = _starters(room), _team_count(room)
        vor = pd.Series(0.0, index=df.index)
        for p, idx in pos.groupby(pos).groups.items():
            vals = value.loc[idx].sort_values(ascending=False)
            k = max(teams * max(starters.get(p, 1), 1), 1)
            repl = float(vals.iloc[min(k, len(vals)) - 1]) if len(vals) else 0.0
            vor.loc[idx] = value.loc[idx] - repl
        score = vor
        # Shown as a share of the best available value: right whatever the value scale (the scoring
        # pass normalizes Expected Fantasy Value to 0..1; raw projections are in points).
        best = float(value.max()) if len(value) else 0.0
        share = (vor / best * 100.0) if best > 0 else vor * 0.0
        reasons = share.round(0).astype(int).map(
            lambda v: f"Value-based: {v}% above the " if v >= 0 else f"Value-based: {abs(v)}% below the "
        ) + pos + " replacement level"
    elif approach == "positional_scarcity":
        scarcity = _num(df, "Position Scarcity Score")
        if not scarcity.any():
            scarcity = _num(df, "Scarcity Score")
        # A scarce position earns up to half the best player's value on top of the player's own.
        score = _value_share(value) + 0.5 * _scaled(scarcity)
        top = df.assign(_v=value).sort_values("_v", ascending=False).head(150)
        depth = top["Primary Position"].astype(str).str.upper().value_counts() if "Primary Position" in top.columns else pd.Series(dtype=int)
        left = pos.map(lambda p: int(depth.get(p, 0)))
        reasons = "Scarcity: " + left.astype(str) + " startable " + pos + " left"
    elif approach == "roster_aware":
        fit = _num(df, "Positional Fit") + _num(df, "Draft Fit Score") * 0.01 + _num(df, "Roster Fit Score") * 0.01
        # Filling a need earns up to 0.6 of the best player's value: a needed player beats a somewhat
        # better one, never a far better one.
        fit_scaled = _scaled(fit)
        score = _value_share(value) + 0.6 * fit_scaled
        strong = fit_scaled >= 0.75
        reasons = pd.Series(
            ["Roster-aware: fills a " + p + " need" if s else "Roster-aware: fits your roster" for p, s in zip(pos, strong)],
            index=df.index,
        )
    else:
        return pool
    df["_strategy_score"] = score
    df["Strategy Reason"] = reasons
    df = df.sort_values("_strategy_score", ascending=False, kind="mergesort").drop(columns=["_strategy_score"])
    return df


def remember_scored_pool(session: Any, room: dict[str, Any] | None, scored: pd.DataFrame) -> None:
    """Called by the scoring pass: keep this pick's full scored pool (a reference, not a copy)."""
    if not isinstance(session, dict) or not isinstance(scored, pd.DataFrame):
        return
    session[SCORED_POOL_KEY] = {"pick": _pick_marker(room), "df": scored}


def _pick_marker(room: dict[str, Any] | None) -> tuple:
    room = room or {}
    board = room.get("draft_board") if isinstance(room.get("draft_board"), list) else []
    return (str(room.get("draft_room_id") or room.get("draft_id") or ""), len(board))


def apply_strategy_to_recommendations(
    session: Any, room: dict[str, Any] | None, tables: tuple, *, top_n: int = 8
) -> tuple:
    """(top_rec, best_avail, pos_fit, value_sleep) with top_rec re-ranked by the viewer's strategy."""
    approach = current_approach(session)
    if approach == "balanced" or not isinstance(tables, tuple) or len(tables) != 4:
        return tables
    top_rec, best_avail, pos_fit, value_sleep = tables
    entry = session.get(SCORED_POOL_KEY) if isinstance(session, dict) else None
    pool = None
    if isinstance(entry, dict) and entry.get("pick") == _pick_marker(room):
        pool = entry.get("df")
    if not isinstance(pool, pd.DataFrame) or pool.empty:
        frames = [t for t in (top_rec, best_avail, pos_fit, value_sleep) if isinstance(t, pd.DataFrame) and not t.empty]
        if not frames:
            return tables
        pool = pd.concat(frames, ignore_index=True)
        key = "playerID" if "playerID" in pool.columns else ("fullName" if "fullName" in pool.columns else None)
        if key:
            pool = pool.drop_duplicates(subset=[key])
    try:
        from live_draft_ui_cache import filter_df_excluding_drafted

        # Only this draft's available players. A copy of the room: the filter caches drafted ids on
        # the dict it is given, and the strategy step never touches the room.
        pool = filter_df_excluding_drafted(pool, dict(room or {}))
    except ImportError:
        pass
    ranked = rank_pool(pool, approach, room=room)
    if not isinstance(ranked, pd.DataFrame) or ranked.empty:
        return tables
    return ranked.head(max(int(top_n or 8), 1)), best_avail, pos_fit, value_sleep


def _apply_saved_strategy(session: Any, picker_key: str, saved: list[dict[str, Any]]) -> None:
    """Callback (runs before the next paint): a saved strategy's approach becomes the selection."""
    name = str(session.get(picker_key) or "")
    strategy = next((s for s in saved if str(s.get("name") or "") == name), None)
    approach = str((strategy or {}).get("approach") or "")
    if approach in APPROACHES:
        session[APPROACH_KEY] = approach


def render_strategy_selector(st: Any, session: Any, *, key_prefix: str = "ldr") -> str:
    """A compact "Draft strategy" control above the recommendation cards (this viewer only).

    The control is bound to the same session key as the Draft Strategy page, so both always agree.
    Saved strategies are offered too: choosing one applies its approach here; loading its players
    into the queue stays on the Draft Strategy page, which asks before replacing the queue."""
    if session.get(APPROACH_KEY) not in APPROACHES:
        session[APPROACH_KEY] = "balanced"
    saved: list[dict[str, Any]] = []
    try:
        import draft_strategy_store as store

        saved = [s for s in store.list_strategies(session) if isinstance(s, dict)]
    except Exception:
        saved = []
    cols = st.columns([3, 2]) if saved else [st.container()]
    with cols[0]:
        st.selectbox(
            "Draft strategy",
            list(APPROACHES),
            format_func=lambda a: LABELS.get(a, a),
            key=APPROACH_KEY,
            help="Shapes these recommendation cards for you only. Balanced is the Draft Assistant's own ranking.",
        )
    if saved:
        picker_key = f"{key_prefix}_saved_strategy_select"
        with cols[1]:
            st.selectbox(
                "Saved strategy",
                ["—"] + [str(s.get("name") or "Strategy") for s in saved],
                key=picker_key,
                help="Use a saved strategy's approach here.",
                on_change=_apply_saved_strategy,
                args=(session, picker_key, saved),
            )
    approach = current_approach(session)
    if approach != "balanced":
        st.caption(f"Cards ranked by **{LABELS[approach]}**. Each card's first reason shows why.")
    return approach
