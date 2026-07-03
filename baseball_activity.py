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
    cc_card_kind: str = "continue",
    workstream: str = "baseball",
) -> None:
    global _LAST_ACTIVITY
    m = dict(metrics or {})
    if resume_key:
        m.setdefault("cc_card_kind", cc_card_kind)
    else:
        m.setdefault("cc_card_kind", "activity")
    m.setdefault("workstream", workstream)
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
        page="Draft Room Simulator",
        metrics={"league": context, "team": teams},
        summary="Completed fantasy draft prep",
        resume_key="bb:simulator_draft",
        resume_title="Continue mock draft",
        resume_subtitle=context or teams or "Draft board & rankings",
        workstream="baseball_draft",
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


def log_historical_analysis(
    *,
    sort_stat: str = "",
    year_start: int | str = "",
    year_end: int | str = "",
    row_count: int | None = None,
    top_player: str = "",
) -> None:
    """Meaningful Historical Explorer table run — not every filter tick."""
    stat = str(sort_stat or "stats").strip()
    yr = f"{year_start}–{year_end}" if year_start or year_end else ""
    sig_player = str(top_player or "").strip()
    resume_key = f"historical:{stat}:{year_start}-{year_end}".replace(" ", "_")[:80]
    subtitle = f"{stat} · {yr}" if yr else stat
    if sig_player:
        subtitle = f"{sig_player} · {subtitle}" if subtitle else sig_player
    metrics: dict[str, Any] = {
        "sort_stat": stat,
        "year_start": year_start,
        "year_end": year_end,
        "workstream": "baseball_research",
    }
    if row_count is not None:
        metrics["row_count"] = int(row_count)
    if sig_player:
        metrics["player"] = sig_player
    _record(
        "historical_analysis",
        page="Historical Explorer",
        metrics=metrics,
        summary="Ran historical analysis" + (f" ({stat}, {yr})" if yr else f" ({stat})"),
        resume_key=resume_key,
        resume_title="Continue historical analysis",
        resume_subtitle=subtitle,
        workstream="baseball_research",
    )


def log_standings_updated(
    *,
    team: str = "",
    season: int | str = "",
    scoring_format: str = "",
    team_count: int | None = None,
    source: str = "",
    saved_draft_name: str = "",
) -> None:
    fmt = str(scoring_format or "").strip() or "5x5 Roto"
    season_s = str(season or "").strip() or "current"
    resume_key = f"bb:standings:{season_s}:{fmt.replace(' ', '_')[:24]}"
    subtitle_parts = [p for p in (saved_draft_name, team, fmt, f"{season_s} season") if p]
    metrics: dict[str, Any] = {
        "scoring_format": fmt,
        "season": season_s,
        "stats_source": source,
        "workstream": "baseball_season",
    }
    if team:
        metrics["team"] = team
    if team_count is not None:
        metrics["team_count"] = int(team_count)
    if saved_draft_name:
        metrics["saved_draft_name"] = saved_draft_name
    _record(
        "standings_updated",
        page="Fantasy Standings Tracker",
        metrics=metrics,
        summary="Updated fantasy standings analysis"
        + (f" — {saved_draft_name}" if saved_draft_name else ""),
        resume_key=resume_key,
        resume_title="Continue standings analysis",
        resume_subtitle=" · ".join(subtitle_parts[:3]) or "Fantasy Standings Tracker",
        workstream="baseball_season",
    )


def log_saved_draft_team_saved(
    *,
    draft_id: str,
    draft_name: str,
    team_name: str = "",
    draft_type: str = "simulator",
    player_count: int = 0,
    metrics_extra: dict[str, Any] | None = None,
) -> None:
    m = dict(metrics_extra or {})
    m.update(
        {
            "draft_id": draft_id,
            "draft_name": draft_name,
            "team_name": team_name,
            "draft_type": draft_type,
            "player_count": player_count,
        }
    )
    _record(
        "saved_draft_archived",
        page="Saved Draft Library",
        metrics=m,
        summary=f"Saved draft team: {draft_name}",
        resume_key=f"bb:saved_draft:{draft_id}",
        resume_title=f"Continue {draft_name}",
        resume_subtitle=team_name or draft_type.replace("_", " "),
        workstream="baseball_draft",
    )


def log_saved_draft_team_loaded(
    *,
    draft_id: str,
    draft_name: str,
    team_name: str = "",
    target_page: str = "Fantasy Standings Tracker",
    metrics_extra: dict[str, Any] | None = None,
) -> None:
    m = dict(metrics_extra or {})
    m.update({"draft_id": draft_id, "draft_name": draft_name, "team_name": team_name, "target_page": target_page})
    page_label = target_page.replace("Fantasy ", "")
    _record(
        "saved_draft_activated",
        page=target_page,
        metrics=m,
        summary=f"Loaded saved team into {page_label}: {draft_name}",
        resume_key=f"bb:saved_draft:{draft_id}",
        resume_title=f"Continue {draft_name}",
        resume_subtitle=f"{team_name} · {page_label}" if team_name else page_label,
        workstream="baseball_draft",
    )


def log_draft_assistant_session(
    *,
    current_pick: int = 0,
    draft_round: int = 0,
    top_player: str = "",
    team_name: str = "",
) -> None:
    top = str(top_player or "").strip()
    subtitle = f"Pick {current_pick}" + (f" · {top}" if top else "")
    if team_name:
        subtitle = f"{team_name} · {subtitle}"
    metrics: dict[str, Any] = {
        "current_pick": int(current_pick or 0),
        "draft_round": int(draft_round or 0),
        "workstream": "baseball_draft",
    }
    if top:
        metrics["player"] = top
    if team_name:
        metrics["team"] = team_name
    _record(
        "draft_assistant_session",
        page="Draft Assistant Simulator",
        metrics=metrics,
        summary="Draft Assistant recommendations updated"
        + (f" — top: {top}" if top else ""),
        resume_key="bb:draft_assistant",
        resume_title="Continue Draft Assistant",
        resume_subtitle=subtitle or "Next-pick recommendations",
        workstream="baseball_draft",
    )


def log_simulator_board_session(*, pick_count: int = 0, team_name: str = "") -> None:
    """Continue card for Draft Room Simulator with logged picks."""
    team = str(team_name or "").strip()
    _record(
        "simulator_draft_session",
        page="Draft Room Simulator",
        metrics={"pick_count": int(pick_count or 0), "team": team, "workstream": "baseball_draft"},
        summary=f"Draft Room Simulator — {pick_count} pick(s) logged",
        resume_key="bb:simulator_draft",
        resume_title="Continue mock draft",
        resume_subtitle=team or f"{pick_count} picks on board",
        workstream="baseball_draft",
    )


def log_app_directory_entry(*, page: str, summary: str = "") -> None:
    """App Directory card — general baseball entry, not a specific Continue task."""
    page_name = str(page or "Baseball Analytics").strip()
    _record(
        "app_session",
        page=page_name,
        metrics={"cc_card_kind": "app_entry", "workstream": "baseball"},
        summary=str(summary or f"Working in {page_name}"),
        resume_key="",
        cc_card_kind="app_entry",
        workstream="baseball",
    )
