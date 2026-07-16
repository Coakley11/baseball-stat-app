"""
Build Continue / resume deep links for suite Streamlit apps.

Query params (read by suite_resume_launch in each app):
  suite_resume  — resume item key (e.g. song:pick-123, compare:Judge:Soto)
  suite_page    — target page/tab label
  suite_workspace — active workspace profile (daniel, ariel, guest, test_user)
  suite_pick_key, suite_song, suite_display_key, suite_instrument, suite_section_focus — music shortcuts
  suite_resume_kind, suite_resume_payload — typed Music Continue restore envelope (base64url JSON)
  suite_bpm, suite_backing_scope, suite_backing_sections, suite_groove, suite_mood, suite_intensity — music scalars
  suite_multitrack_id, suite_creative_mode, suite_entry_mode — music task shortcuts
  suite_holdings_fp — investment portfolio fingerprint
  suite_player_a, suite_player_b — baseball comparison players
  suite_draft_room, suite_draft_section — live draft / draft lab resume
  suite_trade_proposal, suite_league, suite_invite, suite_lineup_week, suite_waiver_tx — fantasy workflow resume
  suite_team — NBA favorite team
  suite_sim, suite_fl_domain, suite_fl_area, suite_fl_timeline_year, suite_fl_sim_year — Future Lens
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

from music_resume_payload import (
    decode_payload_b64,
    encode_payload_b64,
    legacy_resume_key_for_payload,
    normalize_resume_kind,
)

from suite_workspace import append_suite_workspace_param, normalize_workspace_id, resolve_workspace_id

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
    ("bb:live_draft:", "Live Draft Room"),
    ("bb:draft_lab:", "Draft Simulation Test Mode"),
    ("bb:draft_lab", "Draft Simulation Test Mode"),
    ("baseball:projections", "ML Projections"),
    ("bb:proj", "ML Projections"),
    ("bb:trade_center:", "Trade Center"),
    ("bb:trade_center", "Trade Center"),
    ("baseball:trade", "Fantasy Lineup Assistant"),
    ("bb:trade", "Fantasy Lineup Assistant"),
    ("bb:waiver:", "Waiver Wire / Add-Drop Center"),
    ("bb:waiver", "Waiver Wire / Add-Drop Center"),
    ("bb:lineup:", "Fantasy Lineup Assistant"),
    ("bb:lineup", "Fantasy Lineup Assistant"),
    ("bb:invite:", "Saved Draft Library"),
    ("bb:library:", "Saved Draft Library"),
    ("bb:library", "Saved Draft Library"),
    ("bb:saved_draft:", "Saved Draft Library"),
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
    "practice log": "log",
    "practice studio": "practice",
    "song selection": "picker",
    "song picker": "picker",
    "songs": "picker",
    "backing track studio": "backing",
    "backing track": "backing",
    "recording analysis": "analysis",
    "recording": "analysis",
    "upload analysis": "analysis",
    "upload": "analysis",
    "multitrack": "multitrack",
    "creative progression": "custom",
    "custom progression": "custom",
    "creative lab": "creative",
    "karaoke": "backing",
    "karaoke mode": "backing",
    "chord coach": "practice",
    "openai": "openai",
    "openai hub": "openai",
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
    coach_aliases = {
        "practice": "practice",
        "backing track studio": "backing",
        "backing track": "backing",
        "creative progression": "custom",
        "custom progression": "custom",
        "karaoke": "backing",
        "karaoke mode": "backing",
    }
    low = raw.lower()
    if low in coach_aliases:
        return coach_aliases[low]
    alias = _MUSIC_STUDIO_ALIASES.get(low)
    if alias:
        return alias
    if raw in {
        "practice",
        "backing",
        "picker",
        "custom",
        "creative",
        "multitrack",
        "analysis",
        "log",
        "openai",
    }:
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
        payload = m.get("resume_payload")
        if isinstance(payload, dict) and payload.get("resume_kind"):
            return build_music_continue_url(payload, base_url=base)
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
        trend_players = m.get("trend_players")
        if isinstance(trend_players, list) and trend_players:
            params["suite_trend_players"] = "|".join(str(x) for x in trend_players[:4])[:240]
        qid = str(m.get("question_id") or "").strip()
        if qid:
            params["suite_ai_question_id"] = qid[:40]
        draft_room = str(m.get("draft_room_id") or "").strip()
        if not draft_room and rk.startswith("bb:live_draft:"):
            draft_room = rk.split(":", 2)[-1].strip()
        if not draft_room and rk.startswith("bb:draft_lab:"):
            tail = rk.split(":", 2)[-1].strip()
            if tail and tail not in {"team", "team_analysis"}:
                draft_room = tail.split(":", 1)[-1].strip() if tail.startswith("team:") else tail
        if draft_room:
            params["suite_draft_room"] = draft_room[:80]
        draft_section = str(m.get("draft_section") or "").strip()
        if not draft_section and rk.startswith("bb:draft_lab:team:"):
            draft_section = "team_analysis"
        if draft_section:
            params["suite_draft_section"] = draft_section[:40]
        proposal_id = str(m.get("proposal_id") or "").strip()
        if not proposal_id and rk.startswith("bb:trade_center:"):
            proposal_id = rk.split(":", 2)[-1].strip()
        if proposal_id:
            params["suite_trade_proposal"] = proposal_id[:80]
        league_id = str(m.get("league_id") or m.get("league_context_id") or "").strip()
        if not league_id and rk.startswith("bb:library:"):
            league_id = rk.split(":", 2)[-1].strip()
        if league_id:
            params["suite_league"] = league_id[:80]
        my_team = str(m.get("my_team") or m.get("team") or m.get("claimed_team") or "").strip()
        if my_team:
            params["suite_my_team"] = my_team[:80]
        league_context_id = str(m.get("league_context_id") or "").strip()
        if league_context_id:
            params["suite_league_context"] = league_context_id[:80]
        invite_id = str(m.get("invite_id") or "").strip()
        if not invite_id and rk.startswith("bb:invite:"):
            invite_id = rk.split(":", 2)[-1].strip()
        if invite_id:
            params["suite_invite"] = invite_id[:80]
        saved_draft = str(m.get("draft_id") or "").strip()
        if not saved_draft and rk.startswith("bb:saved_draft:"):
            saved_draft = rk.split(":", 2)[-1].strip()
        if saved_draft:
            params["suite_saved_draft"] = saved_draft[:80]
        week = m.get("week")
        if week is None and rk.startswith("bb:lineup:"):
            tail = rk.split(":", 2)[-1].strip()
            if tail.startswith("w") and tail[1:].isdigit():
                week = tail[1:]
            elif ":w" in rk:
                week = rk.rsplit(":w", 1)[-1].strip()
        if week is not None and str(week).strip():
            params["suite_lineup_week"] = str(week).strip()[:8]
        waiver_tx = str(m.get("waiver_tx_id") or m.get("transaction_id") or "").strip()
        if not waiver_tx and rk.startswith("bb:waiver:"):
            waiver_tx = rk.split(":", 2)[-1].strip()
        if waiver_tx and waiver_tx not in {"", "bb"}:
            params["suite_waiver_tx"] = waiver_tx[:80]
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
        return append_suite_workspace_param(f"{base}/", workspace_id=resolve_workspace_id())
    ami_insight = str(m.get("ami_insight") or "").strip()
    if ami_insight:
        params["suite_ami_insight"] = ami_insight[:40]
    ws = str(m.get("workspace_id") or "").strip()
    if not ws:
        ws = resolve_workspace_id()
    params["suite_workspace"] = normalize_workspace_id(ws)
    return append_suite_workspace_param(f"{base}/?{urlencode(params, quote_via=quote)}", workspace_id=ws)


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
        elif key.startswith("bb:live_draft:"):
            metrics["draft_room_id"] = key.split(":", 2)[-1].strip()
            page = "Live Draft Room"
        elif key.startswith("bb:draft_lab:team:"):
            metrics["draft_room_id"] = key.split(":", 3)[-1].strip()
            metrics["draft_section"] = "team_analysis"
            page = "Draft Simulation Test Mode"
        elif key.startswith("bb:draft_lab:"):
            metrics["draft_room_id"] = key.split(":", 2)[-1].strip()
            page = "Draft Simulation Test Mode"
        elif key.startswith("bb:trade_center:"):
            metrics["proposal_id"] = key.split(":", 2)[-1].strip()
            page = "Trade Center"
        elif key.startswith("bb:trade_center"):
            page = "Trade Center"
        elif key.startswith("bb:waiver:"):
            metrics["waiver_tx_id"] = key.split(":", 2)[-1].strip()
            page = "Waiver Wire / Add-Drop Center"
        elif key.startswith("bb:waiver"):
            page = "Waiver Wire / Add-Drop Center"
        elif key.startswith("bb:lineup:"):
            page = "Fantasy Lineup Assistant"
            tail = key.split(":", 2)[-1].strip()
            if ":w" in key:
                parts = key.split(":")
                if parts and parts[-1].startswith("w"):
                    metrics["week"] = parts[-1][1:]
                if len(parts) >= 3 and parts[2] and not parts[2].startswith("w"):
                    metrics["league_id"] = parts[2]
            elif tail.startswith("w"):
                metrics["week"] = tail[1:]
        elif key.startswith("bb:lineup"):
            page = "Fantasy Lineup Assistant"
        elif key.startswith("bb:invite:"):
            metrics["invite_id"] = key.split(":", 2)[-1].strip()
            page = "Saved Draft Library"
        elif key.startswith("bb:library:"):
            metrics["league_id"] = key.split(":", 2)[-1].strip()
            page = "Saved Draft Library"
        elif key.startswith("bb:library") or key.startswith("bb:saved_draft:"):
            if key.startswith("bb:saved_draft:"):
                metrics["draft_id"] = key.split(":", 2)[-1].strip()
            page = "Saved Draft Library"
        elif "draft" in key.lower():
            page = "Draft Simulation"
        elif key.startswith("bb:trade") or "trade" in key.lower():
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
        if key.startswith("ai:question:") or key.startswith("ai:practice_log_analysis:"):
            page = "Solve a Problem"
            qid = key.split(":", 2)[-1].strip() if key.count(":") >= 2 else ""
            if qid:
                metrics["question_id"] = qid
                metrics["dedupe_fingerprint"] = qid
            if key.startswith("ai:practice_log_analysis:"):
                metrics.setdefault("source_app", "music")
                metrics.setdefault("handoff_kind", "practice_log_analysis")
                metrics.setdefault("display_category", "analysis_handoff")
                metrics.setdefault(
                    "context",
                    {
                        "user_request": "analyze_practice",
                        "handoff_kind": "practice_log_analysis",
                        "display_category": "analysis_handoff",
                    },
                )
            if subtitle:
                if key.startswith("ai:practice_log_analysis:") and subtitle.startswith("Updated"):
                    metrics["context_summary"] = subtitle
                elif "__ctx_json__:" in subtitle:
                    q_part, _, ctx_part = subtitle.partition("\n__ctx_json__:")
                    metrics["question"] = q_part.strip()
                    try:
                        import json

                        parsed = json.loads(ctx_part)
                        if isinstance(parsed, dict):
                            metrics["context"] = parsed
                            metrics["context_json"] = ctx_part
                            try:
                                from suite_analytical_question import normalize_source_app_id

                                metrics["source_app"] = normalize_source_app_id(
                                    str(metrics.get("source_app") or ""),
                                    parsed,
                                )
                            except Exception:
                                pass
                    except Exception:
                        pass
                elif subtitle.startswith("Question:"):
                    first_line, _, rest = subtitle.partition("\n")
                    metrics["question"] = first_line.replace("Question:", "", 1).strip()
                    metrics["context_summary"] = rest.strip() or subtitle
                elif not key.startswith("ai:practice_log_analysis:"):
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


def merge_handoff_metrics_from_action_url(metrics: dict[str, Any], action_url: str) -> dict[str, Any]:
    """Pull latest handoff ids from stored Continue URLs (practice log analysis)."""
    out = dict(metrics or {})
    url = str(action_url or "").strip()
    if not url:
        return out
    try:
        qs = parse_qs(urlparse(url).query)
        run_id = str((qs.get("suite_practice_analysis_run_id") or [""])[0] or "").strip()
        insight = str((qs.get("suite_ami_insight") or [""])[0] or "").strip()
        qid = str((qs.get("suite_ai_question_id") or [""])[0] or "").strip()
        if run_id:
            out["analysis_run_id"] = run_id
        if insight:
            out["ami_insight"] = insight
        if qid:
            out.setdefault("question_id", qid)
        out.setdefault("continue_action_url", url)
    except Exception:
        pass
    return out


def _music_scalar_params_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Flatten common Music resume scalars into query params."""
    params: dict[str, str] = {}
    pick = str(payload.get("pick_key") or "").strip()
    if pick:
        params["suite_pick_key"] = pick
    song = str(payload.get("song") or "").strip()
    if song:
        params["suite_song"] = song[:120]
    display_key = str(payload.get("display_key") or "").strip()
    if display_key:
        params["suite_display_key"] = display_key[:40]
    instrument = str(payload.get("instrument") or "").strip()
    if instrument:
        params["suite_instrument"] = instrument[:40]
    section = str(payload.get("practice_focus_section") or "").strip()
    if section:
        params["suite_section_focus"] = section[:80]
    bpm = payload.get("bpm") or payload.get("backing_track_bpm")
    if bpm is not None:
        try:
            params["suite_bpm"] = str(int(bpm))
        except (TypeError, ValueError):
            pass
    kind = normalize_resume_kind(str(payload.get("resume_kind") or ""))
    params["suite_resume_kind"] = kind
    params["suite_entry_mode"] = "continue"
    if kind == "backing":
        scope = str(payload.get("backing_track_scope") or "").strip()
        if scope:
            params["suite_backing_scope"] = scope[:40]
        multi = payload.get("backing_track_multi_sections")
        if isinstance(multi, list) and multi:
            params["suite_backing_sections"] = "|".join(str(s) for s in multi[:8])[:240]
        groove = str(payload.get("backing_groove_style") or payload.get("style") or "").strip()
        if groove:
            params["suite_groove"] = groove[:40]
        mood = str(payload.get("mood") or "").strip()
        if mood:
            params["suite_mood"] = mood[:40]
        intensity = str(payload.get("intensity") or "").strip()
        if intensity:
            params["suite_intensity"] = intensity[:40]
    elif kind == "creative":
        mode = str(payload.get("improv_entry_mode") or "").strip()
        if mode:
            params["suite_creative_mode"] = mode[:80]
    elif kind == "multitrack":
        mt = str(payload.get("multitrack_id") or "").strip()
        if mt:
            params["suite_multitrack_id"] = mt[:80]
    elif kind == "tone":
        params["suite_open_tone"] = "1"
    return params


def build_music_continue_url(
    payload: dict[str, Any],
    *,
    base_url: str = "",
) -> str:
    """Deep link that restores a specific Music task (Continue card)."""
    base = (base_url or app_base_url("music")).strip().rstrip("/")
    if not base or not payload:
        return ""
    rk = legacy_resume_key_for_payload(payload)
    page = str(payload.get("studio_page") or "practice").strip()
    page = _normalize_music_page(page, rk)
    params: dict[str, str] = {"suite_entry_mode": "continue"}
    if rk:
        params["suite_resume"] = rk
    if page:
        params["suite_page"] = page
    params.update(_music_scalar_params_from_payload(payload))
    encoded = encode_payload_b64(payload)
    if encoded:
        params["suite_resume_payload"] = encoded
    ws = normalize_workspace_id(str(payload.get("workspace_id") or resolve_workspace_id()))
    params["suite_workspace"] = ws
    return append_suite_workspace_param(f"{base}/?{urlencode(params, quote_via=quote)}", workspace_id=ws)


def build_music_workstream_url(
    page: str,
    *,
    workspace_id: str = "",
    base_url: str = "",
) -> str:
    """Soft Music entry for App Directory — current workspace, no stale song restore."""
    base = (base_url or app_base_url("music")).strip().rstrip("/")
    if not base:
        return ""
    page_norm = _normalize_music_page(str(page or "practice"), "")
    ws = normalize_workspace_id(workspace_id or resolve_workspace_id())
    params = {
        "suite_entry_mode": "workstream",
        "suite_page": page_norm,
        "suite_workspace": ws,
    }
    return append_suite_workspace_param(f"{base}/?{urlencode(params, quote_via=quote)}", workspace_id=ws)
