"""
Command Center activity hooks — meaningful baseball work only (no page opens).
"""

from __future__ import annotations

from typing import Any

from activity_time import utc_now_iso

_LAST_ACTIVITY: dict[str, Any] = {}


def last_activity_trace() -> dict[str, Any]:
    """Most recent activity hook call (for Developer mode diagnostics)."""
    return dict(_LAST_ACTIVITY)


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
    global _LAST_ACTIVITY
    m = dict(metrics or {})
    player = str(m.get("player") or "").strip()
    pa = str(m.get("player_a") or "").strip()
    pb = str(m.get("player_b") or "").strip()
    players_raw = m.get("players")
    if isinstance(players_raw, list):
        players_display = " vs ".join(str(x).strip() for x in players_raw if str(x).strip())
    elif pa and pb:
        players_display = f"{pa} vs {pb}"
    elif player:
        players_display = player
    else:
        players_display = "—"
    ts = utc_now_iso()
    _LAST_ACTIVITY = {
        "event_type": event,
        "event": event,
        "page": page,
        "metrics": m,
        "summary": summary,
        "resume_key": resume_key,
        "resume_title": resume_title,
        "player": player or (pa if pa else "—"),
        "players": players_display,
        "timestamp": ts,
        "recorded": False,
        "supabase_write_ok": False,
        "write_path": "none",
        "error": "",
    }
    try:
        from suite_activity_client import last_record_trace, record_activity

        record_activity(
            "baseball",
            event,
            page=page or "Baseball Analytics",
            metrics=m,
            summary=summary,
            resume_key=resume_key,
            resume_title=resume_title,
            resume_subtitle=resume_subtitle,
        )
        wt = last_record_trace()
        if wt:
            _LAST_ACTIVITY.update(
                {
                    "timestamp": str(wt.get("timestamp") or ts),
                    "recorded": bool(wt.get("recorded")),
                    "supabase_write_ok": bool(wt.get("supabase_write_ok")),
                    "write_path": str(wt.get("write_path") or "none"),
                    "error": str(wt.get("error") or ""),
                }
            )
        else:
            _LAST_ACTIVITY["recorded"] = True
    except Exception as exc:
        _LAST_ACTIVITY["recorded"] = False
        _LAST_ACTIVITY["error"] = str(exc)

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


def log_trend_filter_change() -> None:
    """Aggregate trend filters changed — activity only, not a Continue workflow."""
    _record(
        "trend_filter_changed",
        page="Trend Value",
        metrics={},
        summary="Adjusted trend filters",
    )


def log_trend_analysis(*, player: str = "", trend: str = "") -> None:
    """Legacy hook; prefer log_player_trend_chart for named-player dashboards."""
    if not str(player or "").strip():
        log_trend_filter_change()
        return
    log_player_trend_chart(player=player, trend_mode=trend)


def log_player_trend_chart(
    *,
    player: str,
    trend_mode: str = "",
    stats: list[str] | None = None,
) -> None:
    name = str(player or "").strip()
    if not name:
        return
    metrics: dict[str, Any] = {"player": name, "trend": trend_mode, "players": [name]}
    if stats:
        metrics["stats"] = list(stats)
    _record(
        "player_trend_viewed",
        page="Trend Value",
        metrics=metrics,
        summary=f"Opened trend chart for {name}",
        resume_key=f"trend:{name}",
        resume_title=f"Continue {name} trend chart",
        resume_subtitle="Trend Value",
    )


def log_trend_comparison_viewed(
    player_a: str,
    player_b: str,
    *,
    players: list[str] | None = None,
    trend_stat: str = "",
    chart_mode: str = "",
) -> None:
    a = str(player_a or "").strip()
    b = str(player_b or "").strip()
    if not a or not b:
        return
    ordered = [str(x).strip() for x in (players or [a, b]) if str(x).strip()]
    if len(ordered) < 2:
        ordered = [a, b]
    pair = f"{a} vs {b}"
    metrics: dict[str, Any] = {
        "player_a": a,
        "player_b": b,
        "players": ordered,
        "player": a,
    }
    if trend_stat:
        metrics["trend_stat"] = trend_stat
    if chart_mode:
        metrics["trend"] = chart_mode
    _record(
        "trend_comparison_viewed",
        page="Trend Value",
        metrics=metrics,
        summary=f"Compared trend charts for {pair}",
        resume_key=f"trendcompare:{a}:{b}",
        resume_title=f"Continue {pair} trend comparison",
        resume_subtitle="Trend Value",
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
