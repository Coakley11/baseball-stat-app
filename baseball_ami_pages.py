"""Reusable AMI send-time context for non-draft Baseball pages."""

from __future__ import annotations

import copy
from typing import Any

TREND_QUESTION_CATEGORIES: dict[str, tuple[str, ...]] = {
    "trend_standout": ("what trend stands out", "trend stands out", "notable trend"),
    "sustainability": ("is this sustainable", "sustainable", "regression or breakout", "mean reversion"),
    "buy_sell": ("buy low", "sell high", "buy or sell"),
    "projection": ("expected stat", "expected statistics", "projected", "2026", "next season"),
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


def _player_name(raw: Any) -> str:
    return str(raw or "").split(" (")[0].strip()


def finalize_trend_context_for_send(ctx: dict[str, Any], session_state: dict[str, Any]) -> None:
    """Promote trend intel into send payload for Trends / Trend Value."""
    try:
        from applied_math_context import extract_player_from_question
    except ImportError:
        extract_player_from_question = None  # type: ignore[assignment]

    summary = session_state.get("_ami_trend_summary")
    if isinstance(summary, dict) and summary:
        ctx["trend_summary"] = {**dict(ctx.get("trend_summary") or {}), **copy.deepcopy(summary)}
        if summary.get("player"):
            ctx.setdefault("player", summary["player"])

    pl = session_state.get("single_trend_dashboard_player")
    if pl:
        ctx.setdefault("player", _player_name(pl))

    stats = session_state.get("single_trend_dashboard_stats") or session_state.get("trend_plot_stat")
    if stats:
        metric_list = [str(s) for s in stats[:6]] if isinstance(stats, list) else [str(stats)]
        ctx.setdefault("metrics", metric_list)

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

    if not ctx.get("trend_summary") and ctx.get("player"):
        stat = (ctx.get("metrics") or ["stat"])[0]
        ctx["trend_summary"] = {
            "player": ctx["player"],
            "stat": str(stat),
            "window": ctx.get("trend_window") or "",
        }

    ctx.pop("player_a", None)
    ctx.pop("player_b", None)


def build_trend_send_diagnostics(ctx: dict[str, Any], *, source_page: str) -> dict[str, Any]:
    trend = ctx.get("trend_summary") if isinstance(ctx.get("trend_summary"), dict) else {}
    metrics = ctx.get("metrics") if isinstance(ctx.get("metrics"), list) else []
    return {
        "source_page": source_page,
        "trend_context_present": bool(trend),
        "trend_player_count": 1 if ctx.get("player") else 0,
        "trend_metric_count": len(metrics),
        "trend_mode_selected": "baseball_trend_significance" if trend or ctx.get("player") else "",
        "routing_reason": "trend_page_send_promotion",
    }


def finalize_sleepers_context_for_send(ctx: dict[str, Any], session_state: dict[str, Any]) -> None:
    """Promote sleepers cache into send payload."""
    try:
        from applied_math_context import extract_player_from_question, gather_sleepers_ami_snapshot
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

    ctx.pop("player_a", None)
    ctx.pop("player_b", None)


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
) -> dict[str, Any]:
    """Dispatch page-specific AMI context promotion at send time."""
    low = _page_key(source_page)
    diag: dict[str, Any] = {}
    if "trend" in low:
        finalize_trend_context_for_send(ctx, session_state)
        diag = build_trend_send_diagnostics(ctx, source_page=source_page)
        ctx["trend_send_diagnostics"] = diag
    elif "sleeper" in low:
        finalize_sleepers_context_for_send(ctx, session_state)
    elif "comparison" in low:
        finalize_comparison_context_for_send(ctx, session_state, question=question)
    return diag
