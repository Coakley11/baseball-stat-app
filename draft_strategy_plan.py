"""Guided planning for the Draft Strategy Assistant: needs, depth and explained targets.

Pure data over the app's existing calculations — nothing here scores players. The pool is the
canonical projection pool already scored for the active team's roster (Decision Score, need and
scarcity components from ``apply_draft_pick_scoring``); the team, drafted players and position
needs come from ``active_team_context``; category needs from ``draft_needs``; the one-line
reasons are the same ones the Live Draft recommendation cards use.

Recommendations only ever suggest. Adding to the queue is the user's action.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

DEPTH_POSITIONS = ("C", "1B", "2B", "3B", "SS", "OF", "DH")
DEPTH_TOP_N = 150  # "startable" pool: the top of the remaining board by Decision Score
SCORE_COL = "Decision Score"


# Scored pools by signature (team, format, board picks, projection settings). Lives in this
# imported module because streamlit_app.py re-executes, and its globals reset, on every rerun.
_POOL_MEMO: dict[tuple, Any] = {}
_POOL_MEMO_MAX = 8


def memoized_pool(signature: tuple, build):
    """The scored pool for ``signature``, built once; the signature covers everything it depends on."""
    if signature not in _POOL_MEMO:
        if len(_POOL_MEMO) >= _POOL_MEMO_MAX:
            _POOL_MEMO.pop(next(iter(_POOL_MEMO)))
        _POOL_MEMO[signature] = build()
    return _POOL_MEMO[signature]


def _names(values: Any) -> list[str]:
    if values is None:
        return []
    return [str(v).strip() for v in list(values) if str(v).strip() and str(v).strip().lower() != "nan"]


def _category_specs(fantasy_format: str) -> list[tuple[str, str, str]]:
    try:
        from draft_needs import _hitter_category_specs

        return _hitter_category_specs(fantasy_format)
    except ImportError:
        return []


def team_profile(session: dict[str, Any], pool: pd.DataFrame | None) -> dict[str, Any]:
    """Active team, its roster, open positions, weak and strong categories."""
    from active_team_context import resolve_active_team_context

    ctx = resolve_active_team_context(session, pool_df=pool)
    roster = ctx.my_roster_df if isinstance(ctx.my_roster_df, pd.DataFrame) else pd.DataFrame()
    roster_names = _names(roster["fullName"]) if "fullName" in roster.columns else (
        _names(roster["Player"]) if "Player" in roster.columns else []
    )
    roster_rows = pd.DataFrame()
    if isinstance(pool, pd.DataFrame) and not pool.empty and roster_names and "fullName" in pool.columns:
        roster_rows = pool[pool["fullName"].astype(str).isin(set(roster_names))]
    levels: list[dict[str, str]] = []
    strengths: list[str] = []
    if not roster_rows.empty and isinstance(pool, pd.DataFrame):
        try:
            from draft_needs import infer_hitter_category_need_levels

            levels = infer_hitter_category_need_levels(roster_rows, pool, fantasy_format=ctx.fantasy_format)
        except ImportError:
            levels = []
        weak = {lvl["label"] for lvl in levels}
        strengths = [label for _col, label, _kind in _category_specs(ctx.fantasy_format) if label not in weak]
    return {
        "source": ctx.source,
        "team": ctx.active_team,
        "fantasy_format": ctx.fantasy_format,
        "roster": roster_names,
        "drafted": list(ctx.drafted_names),
        "position_needs": list(ctx.position_needs or []),
        "category_needs": levels,
        "strengths": strengths,
        "_ctx": ctx,
    }


def available_pool(session: dict[str, Any], pool: pd.DataFrame | None, profile: dict[str, Any]) -> pd.DataFrame:
    """The pool without anyone already drafted, best first."""
    if not isinstance(pool, pd.DataFrame) or pool.empty:
        return pd.DataFrame()
    ctx = profile.get("_ctx")
    out = ctx.available_pool(pool) if ctx is not None else pool
    drafted = {n.lower() for n in profile.get("drafted") or []}
    if drafted and "fullName" in out.columns:
        out = out[~out["fullName"].astype(str).str.lower().isin(drafted)]
    if SCORE_COL in out.columns:
        out = out.sort_values(SCORE_COL, ascending=False, kind="mergesort")
    return out.reset_index(drop=True)


def positional_depth(available: pd.DataFrame) -> list[dict[str, Any]]:
    """Per position: how many of the top remaining players play it, and the best one left."""
    if available is None or available.empty or "Primary Position" not in available.columns:
        return []
    top = available.head(DEPTH_TOP_N)
    rows = []
    for pos in DEPTH_POSITIONS:
        at_pos = top[top["Primary Position"].astype(str).str.upper() == pos]
        best = at_pos.iloc[0] if not at_pos.empty else None
        rows.append({
            "position": pos,
            "startable_left": int(len(at_pos)),
            "best_available": str(best["fullName"]) if best is not None else "",
            "best_score": float(best[SCORE_COL]) if best is not None and SCORE_COL in at_pos.columns else None,
        })
    return rows


def _reason(rank: int, row: pd.Series, profile: dict[str, Any], available: pd.DataFrame) -> str:
    needs = profile.get("position_needs") or []
    cats = [lvl["label"] for lvl in profile.get("category_needs") or []]
    strengths = profile.get("strengths") or []
    try:
        from live_draft_rec_badges import primary_recommendation_reason

        text = primary_recommendation_reason(rank, row, gaps=needs, category_needs=cats, strengths=None, rec_df=available)
        if text:
            return str(text)
    except Exception:
        pass
    try:
        from live_draft_room_ui import build_why_this_pick_summary

        return str(build_why_this_pick_summary(row, str(row.get("Primary Position") or ""), gaps=needs,
                                               category_needs=cats, strengths=strengths, include_position_need=True))
    except Exception:
        return ""


def recommended_targets(
    session: dict[str, Any],
    available: pd.DataFrame,
    profile: dict[str, Any],
    *,
    queue: list[str],
    position: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Best remaining players not already queued, each with the reason it is recommended."""
    if available is None or available.empty or "fullName" not in available.columns:
        return []
    queued = {q.lower() for q in queue}
    pool = available[~available["fullName"].astype(str).str.lower().isin(queued)]
    if position:
        pool = pool[pool["Primary Position"].astype(str).str.upper() == position.upper()]
    out = []
    for rank, (_idx, row) in enumerate(pool.head(limit).iterrows(), start=1):
        out.append({
            "rank": rank,
            "name": str(row["fullName"]),
            "position": str(row.get("Primary Position") or ""),
            "team": str(row.get("Team") or row.get("teamID") or ""),
            "score": float(row[SCORE_COL]) if SCORE_COL in pool.columns else None,
            "adp": float(row["ADP"]) if "ADP" in pool.columns and pd.notna(row.get("ADP")) else None,
            "fills_need": str(row.get("Primary Position") or "") in (profile.get("position_needs") or []),
            "reason": _reason(rank, row, profile, available),
        })
    return out


def backups_for_queue(available: pd.DataFrame, queue: list[str], *, per_player: int = 2) -> dict[str, list[str]]:
    """If a queued target is drafted: the next best remaining players at his position."""
    if available is None or available.empty or "fullName" not in available.columns:
        return {}
    queued = {q.lower() for q in queue}
    by_name = {str(n).lower(): pos for n, pos in zip(available["fullName"], available.get("Primary Position", ""))}
    out: dict[str, list[str]] = {}
    for name in queue:
        pos = str(by_name.get(name.lower()) or "").upper()
        if not pos:
            continue
        alts = available[
            (available["Primary Position"].astype(str).str.upper() == pos)
            & ~available["fullName"].astype(str).str.lower().isin(queued)
        ]["fullName"].astype(str).head(per_player).tolist()
        if alts:
            out[name] = alts
    return out


def queue_status(queue: list[str], profile: dict[str, Any]) -> list[dict[str, Any]]:
    """The working queue in order, flagging anyone already drafted in the active draft."""
    drafted = {n.lower() for n in profile.get("drafted") or []}
    return [{"rank": i, "name": name, "drafted": name.lower() in drafted} for i, name in enumerate(queue, start=1)]
