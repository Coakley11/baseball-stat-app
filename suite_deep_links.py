"""
Build Continue / resume deep links for suite Streamlit apps.

Query params (read by suite_resume_launch in each app):
  suite_resume  — resume item key (e.g. song:pick-123, compare:Judge:Soto)
  suite_page    — target page/tab label
  suite_pick_key, suite_song, suite_display_key, suite_instrument, suite_section_focus — music shortcuts
  suite_holdings_fp — investment portfolio fingerprint
  suite_player_a, suite_player_b — baseball comparison players
  suite_team — NBA favorite team
  suite_sim, suite_fl_domain, suite_fl_area, suite_fl_timeline_year, suite_fl_sim_year — Future Lens
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
    ("trendcompare:", "Trend Value"),
    ("trend:", "Trend Value"),
    ("baseball:draft", "Draft Simulation"),
    ("baseball:draft_prep", "Draft Simulation"),
    ("bb:draft", "Draft Simulation"),
    ("baseball:projections", "ML Projections"),
    ("bb:proj", "ML Projections"),
    ("baseball:trade", "Fantasy Lineup Assistant"),
    ("bb:trade", "Fantasy Lineup Assistant"),
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

_MUSIC_STUDIO_ALIASES: dict[str, str] = {
    "practice log": "practice",
    "practice studio": "practice",
    "backing track studio": "backing",
    "recording analysis": "recording",
    "chord coach": "practice",
}


def app_base_url(app: str) -> str:
    key = str(app or "").strip()
    if key == "math":
        key = "applied_intelligence"
    return APP_BASE_URLS.get(key, "").strip()


def _normalize_music_page(page: str, resume_key: str) -> str:
    if resume_key.startswith("backing:"):
        return "backing"
    raw = str(page or "").strip()
    if not raw:
        return "practice"
    alias = _MUSIC_STUDIO_ALIASES.get(raw.lower())
    if alias:
        return alias
    if raw in {"practice", "backing", "recording", "picker", "custom"}:
        return raw
    return "practice"


def _parse_compare_resume(resume_key: str) -> tuple[str, str]:
    rk = str(resume_key or "").strip()
    if rk.startswith("trendcompare:"):
        parts = rk.split(":", 2)
        if len(parts) >= 3:
            return parts[1].strip(), parts[2].strip()
        return "", ""
    if not rk.startswith("compare:"):
        return "", ""
    parts = rk.split(":", 2)
    if len(parts) < 3:
        return "", ""
    return parts[1].strip(), parts[2].strip()


def _resolve_page(app: str, resume_key: str, page: str, metrics: dict[str, Any]) -> str:
    rk = resume_key.strip()
    if app == "music":
        return _normalize_music_page(page, rk)
    if page.strip():
        return page.strip()
    if not rk:
        return ""
    if app == "baseball":
        for prefix, target in _BASEBALL_PAGE_BY_RESUME:
            if rk.startswith(prefix):
                return target
        return str(metrics.get("page") or "")
    if app == "investment":
        for prefix, target in _INVESTMENT_PAGE_BY_RESUME:
            if rk.startswith(prefix):
                return target
        return page or "Portfolio Health"
    if app == "nba":
        for prefix, target in _NBA_PAGE_BY_RESUME:
            if rk.startswith(prefix):
                return target
        return str(metrics.get("page") or "")
    if app == "future_lens":
        if rk.startswith("timeline:"):
            return "timeline"
        if rk.startswith("career:") or rk.startswith("sim:"):
            return "simulation"
        if rk.startswith("future:"):
            return "skills"
        return "simulation"
    if app == "applied_intelligence":
        return str(metrics.get("page") or "lessons")
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
        display_key = str(m.get("display_key") or "").strip()
        if display_key:
            params["suite_display_key"] = display_key[:40]
        instrument = str(m.get("instrument") or "").strip()
        if instrument:
            params["suite_instrument"] = instrument[:40]
        section = str(
            m.get("practice_focus_section") or m.get("focus") or ""
        ).strip()
        if section:
            params["suite_section_focus"] = section[:80]
    elif app_key == "baseball":
        pa = str(m.get("player_a") or "").strip()
        pb = str(m.get("player_b") or "").strip()
        if not pa or not pb:
            pa, pb = _parse_compare_resume(rk)
        if pa:
            params["suite_player_a"] = pa[:120]
        if pb:
            params["suite_player_b"] = pb[:120]
        trend_player = str(m.get("player") or "").strip()
        if not trend_player and rk.startswith("trend:"):
            trend_player = rk.split(":", 1)[-1].strip()
        if trend_player:
            params["suite_trend_player"] = trend_player[:120]
    elif app_key == "investment":
        hfp = str(m.get("holdings_fingerprint") or m.get("holdings_fp") or "").strip()
        if hfp:
            params["suite_holdings_fp"] = hfp[:240]
        tickers = m.get("tickers")
        if not hfp and isinstance(tickers, list) and tickers:
            params["suite_holdings_fp"] = "|".join(str(t) for t in tickers[:12])[:240]
    elif app_key == "nba":
        team = str(m.get("team") or "").strip()
        if not team and rk.count(":") >= 2:
            team = rk.split(":", 2)[-1].strip()
        if team:
            params["suite_team"] = team[:80]
    elif app_key == "future_lens":
        sim = str(m.get("simulation") or m.get("specific_skill") or m.get("project") or "").strip()
        if not sim and rk.startswith("sim:"):
            sim = rk.split(":", 1)[-1].strip()
        if not sim and rk.startswith("career:"):
            sim = rk.split(":", 1)[-1].strip()
        if sim:
            params["suite_sim"] = sim[:120]
        domain = str(m.get("domain") or m.get("broad_domain") or "").strip()
        if not domain and rk.startswith("timeline:"):
            domain = str(m.get("project") or "").split(" / ")[0].strip()
        if domain:
            params["suite_fl_domain"] = domain[:80]
        area = str(m.get("area") or "").strip()
        if area:
            params["suite_fl_area"] = area[:80]
        timeline_year = m.get("timeline_year")
        if timeline_year is not None and str(timeline_year).strip():
            params["suite_fl_timeline_year"] = str(timeline_year)[:10]
        sim_year = m.get("sim_year")
        if sim_year is not None and str(sim_year).strip():
            params["suite_fl_sim_year"] = str(sim_year)[:10]
        fl_view = str(m.get("_suite_fl_view") or m.get("view") or "").strip()
        if fl_view:
            params["suite_fl_view"] = fl_view[:40]
    elif app_key == "applied_intelligence":
        lesson = str(m.get("lesson") or m.get("next_lesson") or "").strip()
        if lesson:
            params["suite_lesson"] = lesson[:120]
        question = str(m.get("question") or "").strip()
        if question:
            params["suite_ai_question"] = question[:500]
        qid = str(m.get("question_id") or m.get("dedupe_fingerprint") or "").strip()
        if qid:
            params["suite_ai_question_id"] = qid[:40]
        source_app = str(m.get("source_app") or "").strip()
        if source_app:
            params["suite_ai_source_app"] = source_app[:40]
        source_page = str(m.get("source_page") or "").strip()
        if source_page:
            params["suite_ai_source_page"] = source_page[:80]
        area = str(m.get("quant_area") or m.get("area") or "").strip()
        if area:
            params["suite_ai_area"] = area[:40]
        ctx = str(m.get("context_summary") or "").strip()
        ctx_json = str(m.get("context_json") or "").strip()
        if qid:
            params["suite_ai_context"] = ctx_json[:400] if ctx_json else ""
        elif ctx_json:
            params["suite_ai_context"] = ctx_json[:800]
        elif ctx:
            params["suite_ai_context"] = ctx[:400]

    if not params:
        return f"{base}/"
    return f"{base}/?{urlencode(params, quote_via=quote)}"


def resume_metrics_from_item_key(app: str, item_key: str, *, subtitle: str = "") -> tuple[str, dict[str, Any]]:
    """Infer page + metrics from a stored resume item key (for URL rebuild)."""
    app_key = str(app or "").strip()
    key = str(item_key or "").strip()
    metrics: dict[str, Any] = {}
    page = str(subtitle or "").strip()

    if app_key == "music":
        if key.startswith("song:") or key.startswith("backing:"):
            metrics["pick_key"] = key.split(":", 1)[-1].strip()
        page = _normalize_music_page(page, key)
    elif app_key == "baseball":
        if key.startswith("compare:"):
            pa, pb = _parse_compare_resume(key)
            if pa:
                metrics["player_a"] = pa
            if pb:
                metrics["player_b"] = pb
            page = "Comparison Tool"
        elif "draft" in key.lower():
            page = "Draft Simulation"
        elif "trade" in key.lower():
            page = "Fantasy Lineup Assistant"
        elif key.startswith("trend:"):
            metrics["player"] = key.split(":", 1)[-1].strip()
            page = "Trend Value"
        elif key.startswith("trendcompare:"):
            pa, pb = _parse_compare_resume(key)
            if pa:
                metrics["player_a"] = pa
            if pb:
                metrics["player_b"] = pb
            if pa and pb:
                metrics["players"] = [pa, pb]
            page = "Trend Value"
        elif "proj" in key.lower():
            page = "ML Projections"
    elif app_key == "investment":
        if "health" in key.lower():
            page = "Portfolio Health"
        elif "scenario" in key.lower():
            page = "Efficient Frontier"
        elif "main" in key.lower() or "holdings" in key.lower():
            page = "Portfolio Inputs"
    elif app_key == "nba":
        if key.count(":") >= 2:
            metrics["team"] = key.split(":", 2)[-1].strip()
        if key.startswith("nba:game:"):
            page = "🔴 Live Game Center"
        elif key.startswith("nba:injury:"):
            page = "🧠 Matchup Intelligence"
        elif key.startswith("nba:matchup:"):
            page = "🧠 Matchup Intelligence"
        elif key.startswith("nba:playoff:"):
            page = "🏆 Playoff Bracket"
    elif app_key == "future_lens":
        if key.startswith("career:"):
            scenario = key.split(":", 1)[-1].strip()
            metrics["simulation"] = scenario
            metrics["scenario"] = scenario
            page = page or "simulation"
        elif key.startswith("sim:"):
            metrics["simulation"] = key.split(":", 1)[-1].strip()
            page = page or "simulation"
        elif key.startswith("timeline:"):
            metrics["timeline_year"] = key.split(":", 1)[-1].strip()
            page = page or "timeline"
        elif key.startswith("future:"):
            page = page or "skills"
    elif app_key == "applied_intelligence":
        if key.startswith("ai:question:"):
            page = "Solve a Problem"
            qid = key.split(":", 2)[-1].strip() if key.count(":") >= 2 else ""
            if qid:
                metrics["question_id"] = qid
                metrics["dedupe_fingerprint"] = qid
            if subtitle:
                if "__ctx_json__:" in subtitle:
                    q_part, _, ctx_part = subtitle.partition("\n__ctx_json__:")
                    metrics["question"] = q_part.strip()
                    try:
                        import json

                        parsed = json.loads(ctx_part)
                        if isinstance(parsed, dict):
                            metrics["context"] = parsed
                            metrics["context_json"] = ctx_part
                    except Exception:
                        pass
                elif subtitle.startswith("Question:"):
                    first_line, _, rest = subtitle.partition("\n")
                    metrics["question"] = first_line.replace("Question:", "", 1).strip()
                    metrics["context_summary"] = rest.strip() or subtitle
                else:
                    metrics["question"] = subtitle.split("\n", 1)[0].strip()[:500]
                    if "\n" in subtitle:
                        metrics["context_summary"] = subtitle
                ctx: dict[str, Any] = dict(metrics.get("context") or {})
                if not ctx:
                    for line in subtitle.splitlines():
                        stripped = line.strip().lstrip("•").strip()
                        if ":" in stripped:
                            label, _, val = stripped.partition(":")
                            label_key = label.strip().lower().replace(" ", "_")
                            val = val.strip()
                            if label_key == "source_app":
                                ctx["source_app"] = val
                                metrics.setdefault("source_app", val.lower())
                            elif label_key == "page":
                                ctx["page"] = val
                                metrics.setdefault("source_page", val)
                            elif val:
                                ctx[label_key] = val
                if ctx and "context" not in metrics:
                    metrics["context"] = ctx
                    try:
                        import json

                        metrics["context_json"] = json.dumps(ctx, ensure_ascii=False)
                    except Exception:
                        pass

    return page, metrics
