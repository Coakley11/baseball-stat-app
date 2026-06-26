"""Reusable AMI send-time context for non-draft Baseball pages."""

from __future__ import annotations

import copy
import re
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


def detect_trend_send_intent(question: str) -> str:
    """Classify trend-page AMI send intent from question text."""
    q = str(question or "").strip()
    if not q:
        return "trend_significance"
    low = q.lower()
    try:
        from applied_math_context import extract_comparison_players_from_question

        comp_a, comp_b = extract_comparison_players_from_question(q)
        if comp_a and comp_b:
            return "trend_player_comparison"
    except ImportError:
        pass
    if any(p in low for p in ("better pick", "better option", "better target", "better fantasy")):
        return "trend_player_comparison"
    if any(p in low for p in ("sustainable", "buy low", "sell high", "projection", "buy or sell")):
        return "trend_sustainability"
    return "trend_significance"


def finalize_trend_context_for_send(
    ctx: dict[str, Any],
    session_state: dict[str, Any],
    *,
    question: str = "",
) -> None:
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

    # Detect comparison intent from the question.  If two players were already extracted into
    # player_a/player_b (by attach_question_player_to_context), preserve them and set a
    # comparison-aware routing hint so AMI knows this is a cross-player trend question.
    q = str(question or ctx.get("question") or "").strip()
    intent = detect_trend_send_intent(q)
    has_player_a = bool(str(ctx.get("player_a") or "").strip())
    has_player_b = bool(str(ctx.get("player_b") or "").strip())

    if intent == "trend_player_comparison" and has_player_a and has_player_b:
        # Keep player_a/b; routing hint signals cross-player trend comparison.
        ctx["routing_hint"] = "trend_player_comparison"
        ctx["problem_type_hint"] = "trend_player_comparison"
        ctx["intent"] = "trend_comparison_analysis"
        ctx["trend_comparison_mode"] = True
        # Override any stale chart player with the comparison subject so the solver
        # doesn't anchor on a previously-viewed player (e.g. A.J. Burnett on chart).
        ctx["player"] = ctx["player_a"]
        ctx["players"] = [ctx["player_a"], ctx["player_b"]]
        # Enrich trend snapshot with both player names for the solver
        trend_snap = ctx.get("trend_snapshot") if isinstance(ctx.get("trend_snapshot"), dict) else {}
        trend_snap["comparison_player_a"] = ctx["player_a"]
        trend_snap["comparison_player_b"] = ctx["player_b"]
        ctx["trend_snapshot"] = trend_snap
        # Attach BOTH players' real trend metrics (slope deltas, projections, latest
        # season) from the cached trend index so the solver can produce a data-driven
        # verdict instead of generic "open the comparison tool" advice.
        pa = ctx["player_a"]
        pb = ctx["player_b"]
        try:
            from applied_math_context import lookup_trend_player_entry

            entry_a = lookup_trend_player_entry(session_state, pa)
            entry_b = lookup_trend_player_entry(session_state, pb)
            if entry_a or entry_b:
                tc: dict[str, Any] = {}
                if entry_a:
                    tc["player_a"] = entry_a
                if entry_b:
                    tc["player_b"] = entry_b
                metrics = ctx.get("metrics")
                if isinstance(metrics, list) and metrics:
                    tc["metric"] = str(metrics[0])
                elif isinstance(metrics, str) and metrics.strip():
                    tc["metric"] = metrics.strip()
                ctx["trend_comparison"] = tc
        except ImportError:
            pass
        ctx["ami_guidance"] = (
            f"Compare {pa}'s statistical trend trajectory against {pb}'s using the "
            f"trend_comparison block (slope deltas, next-season projections, latest-season "
            f"levels for both). State which player is the better pick and explain WHY with "
            f"specific numbers — trend direction, projected production, and current level. "
            f"Do not tell the user to open another tool; answer the comparison directly."
        )
    else:
        # Pure trend significance question — clear stale comparison players
        ctx.pop("player_a", None)
        ctx.pop("player_b", None)
        ctx["routing_hint"] = "trend_significance"
        ctx["problem_type_hint"] = "trend_significance"
        ctx["intent"] = "trend_analysis"


def build_trend_send_diagnostics(ctx: dict[str, Any], *, source_page: str) -> dict[str, Any]:
    trend = ctx.get("trend_summary") if isinstance(ctx.get("trend_summary"), dict) else {}
    metrics = ctx.get("metrics") if isinstance(ctx.get("metrics"), list) else []
    player = str(
        ctx.get("player")
        or ctx.get("question_player")
        or trend.get("player")
        or ((ctx.get("players") or [""])[0] if isinstance(ctx.get("players"), list) else "")
    ).strip()
    routing_hint = str(ctx.get("routing_hint") or "")
    return {
        "source_page": source_page,
        "trend_context_present": bool(trend),
        "trend_player": player,
        "trend_metric_count": len(metrics),
        "trend_summary_present": bool(trend),
        "trend_mode_selected": routing_hint or ("baseball_trend_significance" if trend or player else ""),
        "routing_hint": routing_hint,
        "routing_reason": "trend_page_send_promotion",
        "player_a_present": bool(str(ctx.get("player_a") or "").strip()),
        "player_b_present": bool(str(ctx.get("player_b") or "").strip()),
        "trend_comparison_mode": bool(ctx.get("trend_comparison_mode")),
    }


_BUST_SECTION_PHRASES = (
    "market bust",
    "bust risk",
    "bust risks",
    "busts that",
    "busts in",
    "any bust",
    "draft any bust",
    "risky but draftable",
    "should i draft any bust",
    "consider drafting any bust",
    "players in market bust",
)

_STALE_SLEEPER_PLAYER_KEYS = (
    "sleeper_focus",
    "question_player",
    "question_player_row",
    "player",
    "players",
    "routing_hint",
    "problem_type_hint",
    "intent",
    "bust_focus",
)


def detect_sleepers_send_intent(question: str) -> str:
    """Classify sleepers-page AMI send intent from question text."""
    q = str(question or "").strip()
    low = q.lower()
    if not low:
        return "sleepers_general"
    try:
        from applied_math_context import extract_player_from_question, is_named_player_team_fit_question

        named_player = extract_player_from_question(q)
        if named_player and is_named_player_team_fit_question(q):
            return "team_fit"
    except ImportError:
        named_player = ""
    if named_player and "bust" in low and re.search(r"\b(?:draft|consider|take|pick|should|target)\b", low):
        return "bust_take"
    if any(phrase in low for phrase in _BUST_SECTION_PHRASES):
        return "bust_risk_review"
    if "bust" in low and re.search(r"\b(?:draft|consider|take|pick|should|target)\b", low):
        return "bust_risk_review"
    if "sleeper" in low and (
        "combination" in low
        or ("upside" in low and ("safety" in low or "safest" in low))
        or "balanced" in low
        or "highest upside" in low
        or re.search(r"best.{0,30}(upside|balance|combination|safety)", low)
        or "risk-adjusted" in low
    ):
        return "sleeper_ranking"
    if named_player or "sleeper" in low:
        return "sleeper_take"
    return "sleepers_general"


def _clear_stale_sleepers_player_context(ctx: dict[str, Any], question: str) -> None:
    """Drop prior-question sleeper bindings unless the question names the same player."""
    try:
        from applied_math_context import extract_player_from_question
    except ImportError:
        extract_player_from_question = None  # type: ignore[assignment]

    target = extract_player_from_question(question) if extract_player_from_question else ""
    target_token = str(target or "").strip().lower()
    stale_focus = ctx.get("sleeper_focus")
    if isinstance(stale_focus, dict) and target_token:
        row_name = str(stale_focus.get("player") or stale_focus.get("Player") or "").strip().lower()
        if row_name and row_name == target_token:
            return
    for key in _STALE_SLEEPER_PLAYER_KEYS:
        ctx.pop(key, None)


def _find_market_row_for_name(candidates: Any, name: str) -> dict[str, Any] | None:
    return _find_sleeper_row_for_name(candidates, name)


def build_sleepers_send_diagnostics(ctx: dict[str, Any], *, question: str = "") -> dict[str, Any]:
    intent = detect_sleepers_send_intent(question)
    bust_rows = ctx.get("bust_risks") or ctx.get("bust_risk_candidates") or []
    sleeper_rows = ctx.get("sleeper_candidates") or []
    return {
        "sleepers_send_intent": intent,
        "market_section": str(ctx.get("market_section") or ""),
        "routing_hint": str(ctx.get("routing_hint") or ""),
        "sleeper_focus_present": bool(ctx.get("sleeper_focus")),
        "bust_focus_present": bool(ctx.get("bust_focus")),
        "sleeper_candidate_count": len(sleeper_rows) if isinstance(sleeper_rows, list) else 0,
        "bust_risk_count": len(bust_rows) if isinstance(bust_rows, list) else 0,
        "question_player_present": bool(str(ctx.get("question_player") or "").strip()),
    }


def _promote_sleepers_snapshot_fields(ctx: dict[str, Any], snap: dict[str, Any]) -> None:
    if not snap:
        return
    ctx["sleepers_snapshot"] = snap
    if snap.get("sleeper_candidates"):
        ctx["sleeper_candidates"] = copy.deepcopy(snap["sleeper_candidates"])
    if snap.get("bust_risks"):
        bust_rows = copy.deepcopy(snap["bust_risks"])
        ctx["bust_risks"] = bust_rows
        ctx["bust_risk_candidates"] = bust_rows
    if snap.get("roster_needs"):
        ctx.setdefault("needed_positions", snap["roster_needs"])


def apply_market_bust_context_at_send(
    ctx: dict[str, Any],
    session_state: dict[str, Any],
    *,
    question: str = "",
    intent: str = "",
) -> None:
    """Promote bust-risk context and routing for any page (prevents draft-value fallback)."""
    try:
        from applied_math_context import extract_player_from_question, gather_sleepers_ami_snapshot
    except ImportError:
        return

    q = str(question or ctx.get("question") or "").strip()
    bust_intent = intent or detect_sleepers_send_intent(q)
    if bust_intent not in ("bust_risk_review", "bust_take"):
        return

    snap = gather_sleepers_ami_snapshot(session_state)
    cached = session_state.get("_ami_sleepers_snapshot")
    if isinstance(cached, dict) and (cached.get("sleeper_candidates") or cached.get("bust_risks")):
        snap = {**snap, **copy.deepcopy(cached)}
    _promote_sleepers_snapshot_fields(ctx, snap)

    for key in _STALE_SLEEPER_PLAYER_KEYS:
        ctx.pop(key, None)
    ctx.pop("player_a", None)
    ctx.pop("player_b", None)
    ctx["routing_hint"] = "bust_risk_review" if bust_intent == "bust_risk_review" else "bust_take"
    ctx["problem_type_hint"] = "bust_risk_take" if bust_intent == "bust_take" else "bust_risk_scan"
    ctx["intent"] = "bust_risk_analysis"
    ctx["market_section"] = "Market Bust Risks"
    ctx["source_mode"] = "market_bust_review"
    if bust_intent == "bust_take":
        target = extract_player_from_question(q)
        if target:
            ctx["question_player"] = target
            ctx["player"] = target
            ctx["players"] = [target]
            row = _find_market_row_for_name(ctx.get("bust_risk_candidates"), target)
            if row:
                ctx["question_player_row"] = row
                ctx["bust_focus"] = row


def finalize_sleepers_context_for_send(
    ctx: dict[str, Any],
    session_state: dict[str, Any],
    *,
    question: str = "",
) -> None:
    """Promote sleepers cache into send payload."""
    try:
        from applied_math_context import (
            extract_comparison_players_from_question,
            extract_player_from_question,
            gather_sleepers_ami_snapshot,
            is_named_player_team_fit_question,
        )
    except ImportError:
        return

    q = str(question or ctx.get("question") or "").strip()
    low_q = q.lower()
    intent = detect_sleepers_send_intent(q)
    _clear_stale_sleepers_player_context(ctx, q)

    snap = gather_sleepers_ami_snapshot(session_state)
    cached = session_state.get("_ami_sleepers_snapshot")
    if isinstance(cached, dict) and (cached.get("sleeper_candidates") or cached.get("bust_risks")):
        snap = {**snap, **copy.deepcopy(cached)}
    if snap:
        _promote_sleepers_snapshot_fields(ctx, snap)

    if is_named_player_team_fit_question(q):
        target = extract_player_from_question(q) or str(ctx.get("question_player") or "").strip()
        if target:
            ctx.pop("player_a", None)
            ctx.pop("player_b", None)
            ctx["question_player"] = target
            ctx["player"] = target
            ctx["players"] = [target]
            ctx["routing_hint"] = "player_why"
            ctx["problem_type_hint"] = "team_fit"
            ctx["intent"] = "team_fit_analysis"
            row = _find_sleeper_row_for_name(ctx.get("sleeper_candidates"), target)
            if row:
                ctx["question_player_row"] = row
            return

    if intent in ("bust_risk_review", "bust_take"):
        # Bust context path: clear comparison players, apply bust routing
        ctx.pop("player_a", None)
        ctx.pop("player_b", None)
        apply_market_bust_context_at_send(ctx, session_state, question=q, intent=intent)
        return

    if intent == "sleeper_ranking":
        ctx.pop("player_a", None)
        ctx.pop("player_b", None)
        ctx.pop("question_player", None)
        ctx.pop("player", None)
        ctx.pop("sleeper_focus", None)
        ctx["routing_hint"] = "sleeper_ranking"
        ctx["problem_type_hint"] = "sleeper_ranking"
        ctx["intent"] = "sleeper_ranking_analysis"
        ctx["market_section"] = "Fantasy Sleepers & Busts"
        return

    # Two-player comparison on sleepers page: validate sleeper recommendation using snapshot data.
    # This handles "Is X really better than Y since X is a curve adjusted sleeper?" style questions.
    comp_a = str(ctx.get("player_a") or "").strip()
    comp_b = str(ctx.get("player_b") or "").strip()
    if not (comp_a and comp_b):
        # Try extracting comparison from question text directly
        comp_a, comp_b = extract_comparison_players_from_question(q)
    sleeper_comparison = bool(
        comp_a
        and comp_b
        and any(kw in low_q for kw in ("sleeper", "better", "really", "actually", "curve", "adp", "rank"))
    )
    if sleeper_comparison:
        ctx["player_a"] = comp_a
        ctx["player_b"] = comp_b
        ctx["players"] = [comp_a, comp_b]
        ctx["routing_hint"] = "sleeper_comparison"
        ctx["problem_type_hint"] = "sleeper_comparison"
        ctx["intent"] = "sleeper_comparison_analysis"
        ctx["market_section"] = "Fantasy Sleepers & Busts"
        # Look up both players in the sleeper candidates and attach their rows
        for label, player_name, focus_key in (
            ("player_a_row", comp_a, "sleeper_focus_a"),
            ("player_b_row", comp_b, "sleeper_focus_b"),
        ):
            row = _find_sleeper_row_for_name(ctx.get("sleeper_candidates"), player_name)
            if not row and isinstance(cached, dict):
                row = _find_sleeper_row_for_name(cached.get("sleeper_candidates"), player_name)
            if row:
                ctx[label] = row
                ctx[focus_key] = row
        # Also attach the first named player as primary sleeper_focus for backward compat
        if ctx.get("player_a_row"):
            ctx["sleeper_focus"] = ctx["player_a_row"]
        return

    # Single-player sleeper path
    ctx.pop("player_a", None)
    ctx.pop("player_b", None)

    target = extract_player_from_question(q) or str(ctx.get("question_player") or "").strip()
    if not target:
        return

    ctx["question_player"] = target
    ctx["player"] = target
    ctx["players"] = [target]
    ctx["routing_hint"] = "sleeper_take"
    ctx["problem_type_hint"] = "sleeper_take"
    ctx["intent"] = "sleeper_analysis"
    row = _find_sleeper_row_for_name(ctx.get("sleeper_candidates"), target)
    if row:
        ctx["question_player_row"] = row
        ctx["sleeper_focus"] = row
    elif ctx.get("question_player_row"):
        ctx["sleeper_focus"] = ctx["question_player_row"]


def _find_sleeper_row_for_name(candidates: Any, name: str) -> dict[str, Any] | None:
    target = str(name or "").strip().lower()
    if not target or not isinstance(candidates, list):
        return None
    for item in candidates:
        if not isinstance(item, dict):
            continue
        row_name = str(item.get("player") or item.get("Player") or item.get("fullName") or "").strip()
        if row_name.lower() == target:
            return item
    return None


def detect_comparison_send_intent(question: str) -> str:
    """Classify Comparison Tool AMI send intent from question text."""
    q = str(question or "").strip().lower()
    if not q:
        return "comparison_general"
    try:
        from applied_math_context import (
            extract_age_constraint_from_question,
            extract_comparison_players_from_question,
            extract_season_constraint_from_question,
        )

        comp_a, comp_b = extract_comparison_players_from_question(question)
        has_age = bool(extract_age_constraint_from_question(question))
        has_season = bool(extract_season_constraint_from_question(question))
    except ImportError:
        comp_a, comp_b = "", ""
        has_age = has_season = False

    if comp_a and comp_b:
        # Historical constraints override other intent signals
        if has_age:
            return "comparison_historical_age"
        if has_season:
            return "comparison_historical_season"
        if any(p in q for p in ("was ", "were ", "historically", "career", "all-time", "at their peak")):
            return "comparison_historical"
        if any(p in q for p in COMPARISON_QUESTION_CATEGORIES["draft_pick"]):
            return "comparison_draft_pick"
        if any(p in q for p in COMPARISON_QUESTION_CATEGORIES["long_term_value"]):
            return "comparison_long_term"
        if any(p in q for p in COMPARISON_QUESTION_CATEGORIES["rest_of_season"]):
            return "comparison_ros"
        return "comparison_head_to_head"
    if any(p in q for p in COMPARISON_QUESTION_CATEGORIES["draft_pick"]):
        return "comparison_draft_pick"
    if any(p in q for p in COMPARISON_QUESTION_CATEGORIES["long_term_value"]):
        return "comparison_long_term"
    if any(p in q for p in ("better", "who should i", "which player")):
        return "comparison_head_to_head"
    return "comparison_general"


def build_comparison_send_diagnostics(ctx: dict[str, Any], *, question: str = "") -> dict[str, Any]:
    intent = detect_comparison_send_intent(question)
    return {
        "comparison_send_intent": intent,
        "routing_hint": str(ctx.get("routing_hint") or ""),
        "player_a_present": bool(str(ctx.get("player_a") or "").strip()),
        "player_b_present": bool(str(ctx.get("player_b") or "").strip()),
        "comparison_stat": str((ctx.get("metrics") or [""])[0] if ctx.get("metrics") else ""),
        "comparison_differences_count": len(ctx.get("comparison_differences") or []),
    }


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

    cmp_meta = session_state.get("comparison_state")
    if isinstance(cmp_meta, dict):
        if cmp_meta.get("player_a") and not ctx.get("player_a"):
            ctx["player_a"] = str(cmp_meta["player_a"]).strip()
        if cmp_meta.get("player_b") and not ctx.get("player_b"):
            ctx["player_b"] = str(cmp_meta["player_b"]).strip()
        chart = cmp_meta.get("chart")
        if isinstance(chart, dict) and chart:
            ctx["comparison_chart"] = copy.deepcopy(chart)
        if cmp_meta.get("players") and not ctx.get("players"):
            ctx["players"] = [str(p).strip() for p in cmp_meta["players"][:3] if p]

    extra = ctx.get("_ami_comparison_context") if isinstance(ctx.get("_ami_comparison_context"), dict) else {}
    if not extra:
        extra = session_state.get("_ami_comparison_context")
    if isinstance(extra, dict):
        if extra.get("comparison_differences"):
            ctx["comparison_differences"] = copy.deepcopy(extra["comparison_differences"])
        if extra.get("comparison_stats") and not ctx.get("metrics"):
            ctx["metrics"] = [str(s) for s in extra["comparison_stats"][:4]]

    q = str(question or ctx.get("question") or "").strip()
    intent = detect_comparison_send_intent(q)
    if ctx.get("player_a") and ctx.get("player_b"):
        ctx["players"] = [ctx["player_a"], ctx["player_b"]]

    # Extract age and season constraints from the question (e.g. "between the ages of 22-30").
    # These are carried in the solver context so the AMI can restrict its analysis window.
    try:
        from applied_math_context import (
            extract_age_constraint_from_question,
            extract_season_constraint_from_question,
        )

        age_range = extract_age_constraint_from_question(q)
        season_range = extract_season_constraint_from_question(q)
    except ImportError:
        age_range, season_range = "", ""

    if age_range:
        ctx["comparison_age_range"] = age_range
        ctx["comparison_constraint_note"] = f"Compare players at ages {age_range} only"
        ctx["historical_comparison"] = True
        ctx["filters_applied"] = f"Age window: {age_range}"
        # Upgrade intent to historical if age constraint present and not already flagged
        if intent in ("comparison_head_to_head", "comparison_general"):
            intent = "comparison_historical_age"
        # Give the solver explicit guidance; routing_hint alone may not be read.
        pa = str(ctx.get("player_a") or ctx.get("player") or "Player A").strip()
        pb = str(ctx.get("player_b") or "Player B").strip()
        ctx["ami_guidance"] = (
            f"Use historical season-by-season data to compare {pa} and {pb} "
            f"ONLY during the age window {age_range}. "
            f"Filter all statistics to seasons where each player was in that age range. "
            f"Do not use present-day or career totals — restrict entirely to the specified ages. "
            f"Explain who performed better across key categories during those ages."
        )
    if season_range and not age_range:
        ctx["comparison_season_range"] = season_range
        ctx.setdefault("comparison_constraint_note", f"Compare players during seasons {season_range} only")
        ctx["historical_comparison"] = True
        ctx.setdefault("filters_applied", f"Season range: {season_range}")
        if intent in ("comparison_head_to_head", "comparison_general"):
            intent = "comparison_historical_season"
        pa = str(ctx.get("player_a") or ctx.get("player") or "Player A").strip()
        pb = str(ctx.get("player_b") or "Player B").strip()
        ctx.setdefault("ami_guidance", (
            f"Use historical season-by-season data to compare {pa} and {pb} "
            f"ONLY during seasons {season_range}. "
            f"Filter all statistics to that season range. "
            f"Do not use present-day stats — restrict entirely to the specified seasons. "
            f"Explain who performed better across key categories during those seasons."
        ))

    # Also promote widget-level year/age range if the page has filters active
    compare_age = session_state.get("compare_age_range") or session_state.get("comparison_age_range")
    if compare_age and not age_range:
        ctx.setdefault("comparison_age_range", str(compare_age))
    compare_year = session_state.get("compare_year_range") or session_state.get("comparison_year_range")
    if compare_year and not season_range:
        ctx.setdefault("comparison_season_range", str(compare_year))

    ctx["routing_hint"] = intent
    ctx["problem_type_hint"] = intent
    ctx["intent"] = "comparison_analysis"
    ctx["comparison_mode"] = intent
    # Only apply generic comparison guidance when a specific guidance (e.g. the
    # age/season historical-window guidance built above) hasn't already been set —
    # otherwise the constraint-aware guidance gets clobbered by a draft template.
    if not ctx.get("ami_guidance"):
        try:
            from draft_ami_helpers import draft_ami_guidance

            ctx["ami_guidance"] = draft_ami_guidance("Comparison Tool")
        except ImportError:
            pass


def finalize_valuation_context_for_send(ctx: dict[str, Any], session_state: dict[str, Any]) -> None:
    """Promote Valuation page snapshot into send payload."""
    snap = session_state.get("_ami_valuation_snapshot")
    if isinstance(snap, dict) and snap:
        ctx.setdefault("valuation_snapshot", copy.deepcopy(snap))
        if snap.get("selected_player"):
            ctx.setdefault("player", _player_name(snap["selected_player"]))
        if snap.get("top_valuation_players") and not ctx.get("players"):
            ctx["players"] = [
                r.get("player") for r in snap["top_valuation_players"][:6] if isinstance(r, dict)
            ]
        if snap.get("draft_status"):
            ctx.setdefault("draft_status", snap["draft_status"])

    sel = session_state.get("valuation_selected_player")
    if sel:
        ctx.setdefault("player", _player_name(sel))

    ctx["routing_hint"] = "valuation_analysis"
    ctx["intent"] = "valuation_analysis"
    ctx.pop("player_a", None)
    ctx.pop("player_b", None)
    try:
        from draft_ami_helpers import draft_ami_guidance

        ctx["ami_guidance"] = draft_ami_guidance("Valuation")
    except ImportError:
        pass


def build_valuation_send_diagnostics(ctx: dict[str, Any]) -> dict[str, Any]:
    snap = ctx.get("valuation_snapshot") if isinstance(ctx.get("valuation_snapshot"), dict) else {}
    return {
        "valuation_snapshot_present": bool(snap),
        "player": str(ctx.get("player") or ""),
        "top_players_count": len(snap.get("top_valuation_players") or []),
        "routing_hint": str(ctx.get("routing_hint") or ""),
        "draft_status_present": bool(ctx.get("draft_status")),
    }


def finalize_historical_context_for_send(
    ctx: dict[str, Any],
    session_state: dict[str, Any],
    *,
    question: str = "",
) -> None:
    """Promote Historical Explorer snapshot + active filters into send payload."""
    snap = session_state.get("_ami_historical_snapshot")
    if isinstance(snap, dict) and snap:
        ctx.setdefault("historical_snapshot", copy.deepcopy(snap))
        if snap.get("top_players") and not ctx.get("players"):
            ctx["players"] = snap["top_players"][:5]
        if snap.get("sort_stat") and not ctx.get("metrics"):
            ctx["metrics"] = [str(snap["sort_stat"])]
        if snap.get("year_range"):
            ctx.setdefault("filters_applied", f"Years {snap['year_range']}")
            ctx.setdefault("year_range", snap["year_range"])

    sel = session_state.get("historical_selected_player") or session_state.get("hist_selected_player")
    if sel:
        ctx.setdefault("player", _player_name(sel))

    yr = session_state.get("historical_year_range_filter")
    if isinstance(yr, (list, tuple)) and len(yr) >= 2:
        ctx.setdefault("year_range", f"{yr[0]}-{yr[1]}")
        ctx.setdefault("filters_applied", f"Years {yr[0]}–{yr[1]}")
    sort_stat = session_state.get("historical_sort_stat_filter")
    if sort_stat:
        ctx.setdefault("metrics", [str(sort_stat)])

    q = str(question or ctx.get("question") or "").strip()
    try:
        from applied_math_context import extract_comparison_players_from_question, is_peak_comparison_question

        comp_a, comp_b = extract_comparison_players_from_question(q)
    except ImportError:
        comp_a, comp_b = "", ""
        is_peak_comparison_question = lambda _q: False  # type: ignore[assignment]

    if comp_a and comp_b:
        ctx["player_a"] = comp_a
        ctx["player_b"] = comp_b
        ctx["players"] = [comp_a, comp_b]
        ctx["historical_comparison"] = True
        if is_peak_comparison_question(q):
            ctx["peak_comparison_mode"] = True
            ctx["routing_hint"] = "historical_peak_comparison"
            ctx["problem_type_hint"] = "historical_peak_comparison"
            ctx["intent"] = "historical_peak_comparison"
            sort_stat = str(ctx.get("metrics") or ["OPS"])[0] if isinstance(ctx.get("metrics"), list) else "OPS"
            ctx["ami_guidance"] = (
                f"Compare the career peak of {comp_a} vs {comp_b} using Historical Explorer "
                f"season data. Identify each player's best single-season (or best multi-year "
                f"stretch if asked) in {sort_stat} and supporting categories under the active "
                f"filters ({ctx.get('filters_applied') or ctx.get('year_range') or 'all years'}). "
                f"State which player had the stronger peak and cite the actual peak-season values."
            )
        else:
            ctx["routing_hint"] = "historical_player_comparison"
            ctx["intent"] = "historical_player_comparison"
    else:
        ctx["routing_hint"] = "historical_analysis"
        ctx["intent"] = "historical_analysis"
        ctx.pop("player_a", None)
        ctx.pop("player_b", None)


def build_historical_send_diagnostics(ctx: dict[str, Any]) -> dict[str, Any]:
    snap = ctx.get("historical_snapshot") if isinstance(ctx.get("historical_snapshot"), dict) else {}
    return {
        "historical_snapshot_present": bool(snap),
        "top_rows_count": len(snap.get("top_rows") or []),
        "year_range": str(ctx.get("year_range") or ""),
        "player": str(ctx.get("player") or ""),
        "metrics": ctx.get("metrics") or [],
        "routing_hint": str(ctx.get("routing_hint") or ""),
    }


def finalize_career_context_for_send(ctx: dict[str, Any], session_state: dict[str, Any]) -> None:
    """Promote Career Explorer filters and top rows into send payload."""
    try:
        from hall_of_fame_data import HOF_CASE_PACKET_KEY, hof_case_ami_guidance
    except ImportError:
        HOF_CASE_PACKET_KEY = "_hof_case_packet"
        hof_case_ami_guidance = None  # type: ignore[assignment]

    hof_packet = session_state.get(HOF_CASE_PACKET_KEY)
    if isinstance(hof_packet, dict) and hof_packet.get("mode") == "hall_of_fame_case":
        ctx["hof_case_packet"] = copy.deepcopy(hof_packet)
        if hof_packet.get("target_player"):
            ctx["player"] = str(hof_packet["target_player"])
        ctx["routing_hint"] = "hof_case_analysis"
        ctx["intent"] = "hof_case_analysis"
        if hof_case_ami_guidance is not None:
            ctx["ami_guidance"] = hof_case_ami_guidance()

    snap = session_state.get("_ami_career_snapshot") or session_state.get("_ami_career_totals_snapshot")
    if isinstance(snap, dict) and snap:
        ctx.setdefault("career_snapshot", copy.deepcopy(snap))
        if snap.get("top_players") and not ctx.get("players"):
            ctx["players"] = snap["top_players"][:5]
        if snap.get("sort_stat") and not ctx.get("metrics"):
            ctx["metrics"] = [str(snap["sort_stat"])]

    yr = session_state.get("career_year_range_filter")
    if isinstance(yr, (list, tuple)) and len(yr) >= 2:
        ctx.setdefault("year_range", f"{yr[0]}-{yr[1]}")
        ctx.setdefault("filters_applied", f"Years {yr[0]}–{yr[1]}")
    sort_stat = session_state.get("career_sort_stat_filter")
    if sort_stat:
        ctx.setdefault("metrics", [str(sort_stat)])
    team = session_state.get("career_team_filter")
    if team:
        ctx.setdefault("team_filter", str(team))

    if ctx.get("routing_hint") != "hof_case_analysis":
        ctx["routing_hint"] = "career_analysis"
        ctx["intent"] = "career_analysis"
    ctx.pop("player_a", None)
    ctx.pop("player_b", None)


def build_career_send_diagnostics(ctx: dict[str, Any]) -> dict[str, Any]:
    snap = ctx.get("career_snapshot") if isinstance(ctx.get("career_snapshot"), dict) else {}
    hof_packet = ctx.get("hof_case_packet") if isinstance(ctx.get("hof_case_packet"), dict) else {}
    return {
        "career_snapshot_present": bool(snap),
        "hof_case_packet_present": bool(hof_packet),
        "year_range": str(ctx.get("year_range") or ""),
        "metrics": ctx.get("metrics") or [],
        "routing_hint": str(ctx.get("routing_hint") or ""),
        "team_filter": str(ctx.get("team_filter") or ""),
        "target_player": str(hof_packet.get("target_player") or ctx.get("player") or ""),
    }


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
        finalize_trend_context_for_send(ctx, session_state, question=question)
        diag = build_trend_send_diagnostics(ctx, source_page=source_page)
        ctx["trend_send_diagnostics"] = diag
    elif "sleeper" in low or "bust" in low:
        finalize_sleepers_context_for_send(ctx, session_state, question=question)
        diag = build_sleepers_send_diagnostics(ctx, question=question)
        ctx["sleepers_send_diagnostics"] = diag
    elif "comparison" in low:
        finalize_comparison_context_for_send(ctx, session_state, question=question)
        diag = build_comparison_send_diagnostics(ctx, question=question)
        ctx["comparison_send_diagnostics"] = diag
    elif "valuation" in low:
        finalize_valuation_context_for_send(ctx, session_state)
        diag = build_valuation_send_diagnostics(ctx)
        ctx["valuation_send_diagnostics"] = diag
    elif "historical" in low:
        finalize_historical_context_for_send(ctx, session_state, question=question)
        diag = build_historical_send_diagnostics(ctx)
        ctx["historical_send_diagnostics"] = diag
    elif "career" in low:
        finalize_career_context_for_send(ctx, session_state)
        diag = build_career_send_diagnostics(ctx)
        ctx["career_send_diagnostics"] = diag
    return diag
