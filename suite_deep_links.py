"""
Build Continue / resume deep links for suite Streamlit apps.

Query params (read by suite_resume_launch in each app):
  suite_resume  — resume item key (e.g. song:pick-123, compare:Judge:Soto)
  suite_page    — target page/tab label
  suite_pick_key, suite_song, suite_team — app-specific shortcuts
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

# Mirror app_urls.py — updated when dev URLs change.
APP_BASE_URLS: dict[str, str] = {
    "music": "https://ai-music-practice-coach-6szqxqxqrqxdmryyewk8sq.streamlit.app",
    "investment": "https://investment-portfolio-analyzer-ty2sbzumvxsqwbqhkvf6rz.streamlit.app",
    "baseball": "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app",
    "nba": "https://nba-playoff-companion-ai-gd4sx677quejdfkvappv6o.streamlit.app",
    "applied_intelligence": "https://applied-mathematical-intelligence-8l8bqrzpp6fghaj7xuig53.streamlit.app",
    "future_lens": "https://future-lens-ai-transition-simulator-m6n4kaku28ztzlxfts2xt6.streamlit.app",
}

_NBA_PAGE_BY_RESUME: tuple[tuple[str, str], ...] = (
    ("nba:injury:", "🧠 Matchup Intelligence"),
    ("nba:matchup:", "🧠 Matchup Intelligence"),
    ("nba:playoff:", "🏆 Playoff Bracket"),
    ("nba:game:", "🔴 Live Game Center"),
    ("nba:compare:", "🧠 Matchup Intelligence"),
    ("nba:tracker:", "🏆 Playoff Bracket"),
)

_BASEBALL_PAGE_BY_RESUME: tuple[tuple[str, str], ...] = (
    ("compare:", "Comparison Tool"),
    ("baseball:draft", "Draft Simulation"),
    ("baseball:projections", "ML Projections"),
    ("baseball:trade", "Fantasy Lineup Assistant"),
    ("baseball:roster", "Draft Room"),
    ("baseball:sleepers", "Fantasy Market"),
    ("baseball:trends", "Trend Value"),
    ("baseball:breakouts", "Trend Value"),
)

_INVESTMENT_PAGE_BY_RESUME: tuple[tuple[str, str], ...] = (
    ("portfolio:health", "Portfolio Health"),
    ("portfolio:main", "Portfolio Inputs"),
    ("inv:health", "Portfolio Health"),
    ("inv:scenario", "Efficient Frontier"),
    ("inv:allocation", "Portfolio Health"),
)


def app_base_url(app: str) -> str:
    key = str(app or "").strip()
    if key == "math":
        key = "applied_intelligence"
    return APP_BASE_URLS.get(key, "").strip()


def _resolve_page(app: str, resume_key: str, page: str, metrics: dict[str, Any]) -> str:
    if page.strip():
        return page.strip()
    rk = resume_key.strip()
    if not rk:
        return ""
    if app == "music":
        if rk.startswith("backing:"):
            return "backing"
        if rk.startswith("song:"):
            return "practice"
        return "practice"
    if app == "baseball":
        for prefix, target in _BASEBALL_PAGE_BY_RESUME:
            if rk.startswith(prefix):
                return target
        return metrics.get("page") or ""
    if app == "investment":
        for prefix, target in _INVESTMENT_PAGE_BY_RESUME:
            if rk.startswith(prefix):
                return target
        return page or "Portfolio Health"
    if app == "nba":
        for prefix, target in _NBA_PAGE_BY_RESUME:
            if rk.startswith(prefix):
                return target
        return metrics.get("page") or ""
    if app == "future_lens":
        if rk.startswith("timeline:"):
            return "timeline"
        if rk.startswith("career:") or rk.startswith("sim:"):
            return "simulation"
        if rk.startswith("future:"):
            return "skills"
        return "simulation"
    if app == "applied_intelligence":
        return metrics.get("page") or "lessons"
    return ""


def build_resume_action_url(
    app: str,
    *,
    resume_key: str = "",
    page: str = "",
    metrics: dict[str, Any] | None = None,
    base_url: str = "",
) -> str:
    """Public viewer URL with query params for Continue buttons."""
    app_key = str(app or "").strip()
    if app_key == "math":
        app_key = "applied_intelligence"
    base = (base_url or app_base_url(app_key)).strip().rstrip("/")
    if not base:
        return ""

    m = metrics or {}
    rk = str(resume_key or "").strip()
    page_resolved = _resolve_page(app_key, rk, str(page or ""), m)

    params: dict[str, str] = {}
    if rk:
        params["suite_resume"] = rk
    if page_resolved:
        params["suite_page"] = page_resolved

    if app_key == "music":
        pick = str(m.get("pick_key") or "").strip()
        if not pick and rk.startswith("song:"):
            pick = rk.split(":", 1)[-1].strip()
        if not pick and rk.startswith("backing:"):
            pick = rk.split(":", 1)[-1].strip()
        if pick:
            params["suite_pick_key"] = pick
        song = str(m.get("song") or "").strip()
        if song:
            params["suite_song"] = song[:120]
    elif app_key == "nba":
        team = str(m.get("team") or "").strip()
        if not team and rk.count(":") >= 2:
            team = rk.split(":", 2)[-1].strip()
        if team:
            params["suite_team"] = team[:80]
    elif app_key == "future_lens":
        sim = str(m.get("simulation") or m.get("project") or "").strip()
        if not sim and rk.startswith("sim:"):
            sim = rk.split(":", 1)[-1].strip()
        if sim:
            params["suite_sim"] = sim[:120]
    elif app_key == "applied_intelligence":
        lesson = str(m.get("lesson") or m.get("next_lesson") or "").strip()
        if lesson:
            params["suite_lesson"] = lesson[:120]

    if not params:
        return f"{base}/"
    return f"{base}/?{urlencode(params, quote_via=quote)}"
