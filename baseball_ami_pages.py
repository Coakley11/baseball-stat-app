"""Reusable AMI send-time context for non-draft Baseball pages."""

from __future__ import annotations

import copy
from typing import Any

TREND_QUESTION_CATEGORIES: dict[str, tuple[str, ...]] = {
    "trend_standout": ("what trend stands out", "trend stands out", "notable trend"),
    "sustainability": ("is this sustainable", "sustainable", "regression or breakout", "mean reversion"),
    "buy_sell": ("buy low", "sell high", "buy or sell"),
}

SLEEPER_QUESTION_CATEGORIES: dict[str, tuple[str, ...]] = {
    "best_sleeper": ("best sleeper", "top sleeper", "who should i target"),
    "upside": ("highest upside", "most upside", "ceiling"),
    "breakout": ("breakout candidate", "biggest breakout", "breakout"),
    "undervalued": ("most undervalued", "undervalued player", "underpriced"),
}

COMPARISON_QUESTION_CATEGORIES: dict[str, tuple[str, ...]] = {
    "head_to_head": (" vs ", " versus ", "compare "),
    "long_term_value": ("better long-term value", "long term value", "long-term outlook"),
    "draft_pick": ("better draft pick", "draft value", "draft sooner"),
    "rest_of_season": ("rest-of-season", "rest of season", "ros outlook"),
}


def _page_key(source_page: str) -> str:
    return str(source_page or "").strip().lower()


def finalize_trend_context_for_send(ctx: dict[str, Any], session_state: dict[str, Any]) -> None:
    """Promote trend intel into send payload for Trends / Trend Value."""
    summary = session_state.get("_ami_trend_summary")
    if isinstance(summary, dict) and summary:
        ctx["trend_summary"] = {**dict(ctx.get("trend_summary") or {}), **copy.deepcopy(summary)}
        if summary.get("player"):
            ctx.setdefault("player", summary["player"])
    snap = session_state.get("_ami_trend_snapshot")
    if isinstance(snap, dict) and snap:
        ctx["trend_snapshot"] = copy.deepcopy(snap)
        if snap.get("player"):
            ctx.setdefault("player", snap["player"])
        if snap.get("metrics"):
            ctx.setdefault("metrics", snap["metrics"])
    lag = session_state.get("trend_lag")
    if lag is not None and not ctx.get("trend_window"):
        ctx["trend_window"] = f"{lag} seasons"


def finalize_sleepers_context_for_send(ctx: dict[str, Any], session_state: dict[str, Any]) -> None:
    """Promote sleepers cache into send payload."""
    try:
        from applied_math_context import gather_sleepers_ami_snapshot
    except ImportError:
        return

    snap = gather_sleepers_ami_snapshot(session_state)
    cached = session_state.get("_ami_sleepers_snapshot")
    if isinstance(cached, dict) and cached.get("sleeper_candidates"):
        snap = {**snap, **copy.deepcopy(cached)}
    if snap:
        ctx["sleepers_snapshot"] = snap
        if snap.get("sleeper_candidates"):
            ctx["sleeper_candidates"] = copy.deepcopy(snap["sleeper_candidates"])
        if snap.get("roster_needs"):
            ctx.setdefault("needed_positions", snap["roster_needs"])


def finalize_comparison_context_for_send(
    ctx: dict[str, Any],
    session_state: dict[str, Any],
    *,
    question: str = "",
) -> None:
    """Promote Comparison Tool player slots and stats into send payload."""
    try:
        from applied_math_context import extract_comparison_players_from_question
    except ImportError:
        extract_comparison_players_from_question = None  # type: ignore[assignment]

    extra = session_state.get("_ami_comparison_context")
    if isinstance(extra, dict):
        ctx.update(copy.deepcopy(extra))

    pa = session_state.get("sig_player_a_clean")
    pb = session_state.get("sig_player_b_clean")
    if pa:
        ctx.setdefault("player_a", str(pa).strip())
    if pb:
        ctx.setdefault("player_b", str(pb).strip())
    if ctx.get("player_a") and ctx.get("player_b"):
        ctx.setdefault("players", [ctx["player_a"], ctx["player_b"]])

    if extract_comparison_players_from_question and question:
        comp_a, comp_b = extract_comparison_players_from_question(question)
        if comp_a:
            ctx["player_a"] = comp_a
        if comp_b:
            ctx["player_b"] = comp_b
        if comp_a and comp_b:
            ctx["players"] = [comp_a, comp_b]

    stat = session_state.get("compare_stat")
    if stat:
        ctx.setdefault("metrics", [str(stat)])


def promote_page_ami_context_at_send(
    ctx: dict[str, Any],
    session_state: dict[str, Any],
    *,
    source_page: str,
    question: str = "",
) -> None:
    """Dispatch page-specific AMI context promotion at send time."""
    low = _page_key(source_page)
    if "trend" in low:
        finalize_trend_context_for_send(ctx, session_state)
    elif "sleeper" in low:
        finalize_sleepers_context_for_send(ctx, session_state)
    elif "comparison" in low:
        finalize_comparison_context_for_send(ctx, session_state, question=question)
