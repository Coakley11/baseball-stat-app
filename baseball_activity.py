"""
Command Center activity hooks — meaningful baseball work only (no page opens).
"""

from __future__ import annotations

from typing import Any


def _record(
    event: str,
    *,
    page: str = "",
    metrics: dict[str, Any] | None = None,
    summary: str = "",
    resume_key: str = "",
    resume_title: str = "",
    resume_subtitle: str = "",
) -> None:
    try:
        from suite_activity_client import record_activity

        record_activity(
            "baseball",
            event,
            page=page or "Baseball Analytics",
            metrics=metrics or {},
            summary=summary,
            resume_key=resume_key,
            resume_title=resume_title,
            resume_subtitle=resume_subtitle,
        )
    except Exception:
        pass


def log_player_comparison(
    player_a: str,
    player_b: str,
    *,
    extra: str | None = None,
) -> None:
    a = str(player_a or "").strip()
    b = str(player_b or "").strip()
    if not a or not b:
        return
    pair = f"{a} vs {b}"
    _record(
        "player_comparison",
        page="Comparison Tool",
        metrics={"player_a": a, "player_b": b, "player": a},
        summary=f"Compared {pair}",
        resume_key=f"compare:{a}:{b}",
        resume_title="Continue player comparison",
        resume_subtitle=pair,
    )


def log_draft_prep(*, context: str = "", teams: str = "") -> None:
    _record(
        "draft_prep",
        page="Draft Simulation",
        metrics={"league": context, "team": teams},
        summary="Completed fantasy draft prep",
        resume_key="baseball:draft",
        resume_title="Continue fantasy draft prep",
        resume_subtitle=context or teams or "Draft board & rankings",
    )


def log_projection_report(*, style: str = "", player_count: int | None = None) -> None:
    metrics: dict[str, Any] = {}
    if style:
        metrics["projection"] = style
        metrics["report"] = style
    if player_count is not None:
        metrics["player_count"] = int(player_count)
    _record(
        "projection_report",
        page="ML Projections",
        metrics=metrics,
        summary="Generated player projection report"
        + (f" ({style})" if style else ""),
        resume_key="baseball:projections",
        resume_title="Continue player projection research",
        resume_subtitle=style or "ML projections",
    )


def log_trade_analysis(
    *,
    give: list[str] | None = None,
    get: list[str] | None = None,
    verdict: str = "",
) -> None:
    g = [str(x).strip() for x in (give or []) if str(x).strip()]
    r = [str(x).strip() for x in (get or []) if str(x).strip()]
    trade = ""
    if g and r:
        trade = f"{' + '.join(g[:2])} for {' + '.join(r[:2])}"
    _record(
        "trade_analysis",
        page="Fantasy Lineup Assistant",
        metrics={"trade": trade, "verdict": verdict, "give": g, "get": r},
        summary="Evaluated trade proposal" + (f": {trade}" if trade else ""),
        resume_key="baseball:trade",
        resume_title="Review trade analysis",
        resume_subtitle=verdict or trade or "Trade analyzer",
    )


def log_roster_build(*, team: str = "") -> None:
    _record(
        "roster_build",
        page="Draft Room",
        metrics={"team": team},
        summary=f"Built fantasy roster ({team})" if team else "Built fantasy roster",
        resume_key=f"roster:{team}" if team else "baseball:roster",
        resume_title="Continue roster building",
        resume_subtitle=team or "Draft room",
    )


def log_sleeper_research(*, count: int | None = None) -> None:
    _record(
        "sleeper_research",
        page="Fantasy Market",
        metrics={"count": count} if count is not None else {},
        summary="Reviewed sleeper candidates",
        resume_key="baseball:sleepers",
        resume_title="Continue sleeper research",
        resume_subtitle="Fantasy market",
    )


def log_trend_analysis(*, player: str = "", trend: str = "") -> None:
    _record(
        "trend_analysis",
        page="Trend Value",
        metrics={"player": player, "trend": trend},
        summary=f"Reviewed recent trends{f' for {player}' if player else ''}",
        resume_key=f"trend:{player}" if player else "baseball:trends",
        resume_title="Continue trend analysis",
        resume_subtitle=player or "Trend value",
    )


def log_breakout_analysis(*, count: int | None = None) -> None:
    _record(
        "breakout_analysis",
        page="Trend Value",
        metrics={"count": count} if count is not None else {},
        summary="Analyzed breakout candidates",
        resume_key="baseball:breakouts",
        resume_title="Continue breakout candidate research",
        resume_subtitle="Trend & breakout lists",
    )
