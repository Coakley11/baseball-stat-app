"""
Cross-app "Analyze with Applied Math" — shared payload, submit, and deep links.

Source apps (Baseball, NBA, Investment) log ``analytical_question`` events;
Command Center surfaces Continue cards targeting Applied Intelligence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from activity_time import parse_activity_timestamp, utc_now_iso

log = logging.getLogger(__name__)

AMI_SIDEBAR_DEPLOY_LABEL = "Applied Math question sender live"
AMI_SIDEBAR_DEPLOY_VERSION = "2026-06-06-ami-sidebar-v2"
ANALYTICAL_QUESTION_CONTINUE_PRIORITY = 64
ANALYTICAL_QUESTION_BUTTON_LABEL = "Continue in Applied Mathematics →"
_SEND_COOLDOWN_SECONDS = 120

_SOURCE_AREA: dict[str, str] = {
    "baseball": "sports",
    "nba": "sports",
    "investment": "forecasting",
}

_SOURCE_LABELS: dict[str, str] = {
    "baseball": "Baseball",
    "nba": "NBA",
    "investment": "Investment",
}

# Only these keys may appear in user-facing context output.
_PUBLIC_CONTEXT_KEYS = (
    "source_app",
    "page",
    "workflow",
    "players",
    "player",
    "player_a",
    "player_b",
    "team",
    "opponent",
    "metrics",
    "league_format",
    "draft_format",
    "draft_round",
    "current_pick",
    "health_score",
    "portfolio_value",
    "expected_return",
    "volatility",
    "objective",
    "portfolio_preset",
    "holdings",
    "macro_summary",
    "win_probability",
    "series_probability",
)

_CONTEXT_LABELS = {
    "source_app": "Source app",
    "page": "Page",
    "workflow": "Workflow",
    "players": "Players",
    "player": "Player",
    "player_a": "Player A",
    "player_b": "Player B",
    "team": "Team",
    "opponent": "Opponent",
    "metrics": "Metric(s)",
    "league_format": "League",
    "draft_format": "Draft format",
    "draft_round": "Draft round",
    "current_pick": "Current pick",
    "health_score": "Health score",
    "portfolio_value": "Portfolio value",
    "expected_return": "Expected return",
    "volatility": "Volatility",
    "objective": "Goal",
    "portfolio_preset": "Portfolio preset",
    "holdings": "Holdings",
    "macro_summary": "Macro outlook",
    "win_probability": "Win probability",
    "series_probability": "Series probability",
}


def default_area_for_source(source_app: str) -> str:
    return _SOURCE_AREA.get(str(source_app or "").strip(), "abstract")


def source_app_label(source_app: str) -> str:
    key = str(source_app or "").strip()
    return _SOURCE_LABELS.get(key, key.replace("_", " ").title())


def _normalize_question(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _player_name(raw: Any) -> str:
    return str(raw or "").split(" (")[0].strip()


def question_dedupe_fingerprint(
    question: str,
    *,
    source_app: str = "",
    source_page: str = "",
    context: dict[str, Any] | None = None,
) -> str:
    """Stable id for dedupe — same app, page, question, and key entities → same card."""
    ctx = dict(context or {})
    parts = [
        str(source_app or "").strip().lower(),
        str(source_page or "").strip().lower(),
        _normalize_question(question),
    ]
    for key in (
        "workflow",
        "player",
        "player_a",
        "player_b",
        "team",
        "metrics",
        "players",
        "holdings",
        "health_score",
    ):
        val = ctx.get(key)
        if val is None or val == "":
            continue
        if isinstance(val, list):
            parts.append(",".join(sorted(str(v).lower() for v in val)))
        else:
            parts.append(str(val).lower())
    blob = "|".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def question_id(
    question: str,
    *,
    source_app: str = "",
    source_page: str = "",
    context: dict[str, Any] | None = None,
) -> str:
    return question_dedupe_fingerprint(
        question,
        source_app=source_app,
        source_page=source_page,
        context=context,
    )


def _safe_widget_suffix(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", str(text or "page"))[:48]


def _format_context_value(key: str, val: Any) -> str:
    if isinstance(val, list):
        return ", ".join(str(v) for v in val[:8] if str(v).strip())
    return str(val).strip()


def format_context_lines(context: dict[str, Any] | None) -> list[str]:
    """Human-readable context — whitelist only, no raw widget keys."""
    ctx = dict(context or {})
    lines: list[str] = []
    for key in _PUBLIC_CONTEXT_KEYS:
        val = ctx.get(key)
        if val is None or val == "":
            continue
        text = _format_context_value(key, val)
        if not text:
            continue
        label = _CONTEXT_LABELS.get(key, key.replace("_", " ").title())
        lines.append(f"{label}: {text}")
    return lines[:10]


def analytical_question_continue_copy(payload: dict[str, Any]) -> tuple[str, str, str]:
    """Return (title, subtitle, button_label) for Command Center Continue cards."""
    label = source_app_label(str(payload.get("source_app") or ""))
    question = str(payload.get("question") or "").strip()
    ctx_lines = format_context_lines(payload.get("context") if isinstance(payload.get("context"), dict) else {})
    subtitle_parts = [f"Question: {question}"]
    if ctx_lines:
        subtitle_parts.append("Context:\n" + "\n".join(f"  • {line}" for line in ctx_lines))
    return (
        f"Applied Math question from {label}",
        "\n".join(subtitle_parts),
        ANALYTICAL_QUESTION_BUTTON_LABEL,
    )


def metrics_for_applied_math_resume(payload: dict[str, Any]) -> dict[str, Any]:
    """Metrics bundle for deep links into Applied Intelligence."""
    ctx = dict(payload.get("context") or {})
    ctx_lines = format_context_lines(ctx)
    return {
        "question": payload.get("question"),
        "question_id": payload.get("question_id"),
        "source_app": payload.get("source_app"),
        "source_page": payload.get("source_page"),
        "context_summary": payload.get("context_summary"),
        "context_display": " · ".join(ctx_lines),
        "context": ctx,
        "quant_area": payload.get("quant_area"),
        "context_json": json.dumps(ctx, ensure_ascii=False),
        "dedupe_fingerprint": payload.get("question_id"),
    }


def _upsert_applied_intelligence_resume(
    payload: dict[str, Any],
    *,
    action_url: str,
) -> None:
    title, subtitle, _ = analytical_question_continue_copy(payload)
    resume_key = str(payload.get("resume_key") or "").strip()
    if not resume_key:
        return
    try:
        from suite_storage_supabase import upsert_resume_item

        upsert_resume_item(
            "applied_intelligence",
            resume_key,
            title=title,
            subtitle=subtitle,
            action_url=action_url,
        )
        return
    except Exception as exc:
        log.warning("suite_storage_supabase upsert_resume_item failed: %s", exc)
    try:
        from suite_storage import upsert_resume_item

        upsert_resume_item(
            "applied_intelligence",
            resume_key,
            title=title,
            subtitle=subtitle,
            action_url=action_url,
        )
    except Exception as exc:
        log.warning("suite_storage upsert_resume_item failed: %s", exc)


def build_question_payload(
    *,
    source_app: str,
    source_page: str,
    question: str,
    context: dict[str, Any] | None = None,
    context_summary: str = "",
    quant_area: str = "",
) -> dict[str, Any]:
    q = str(question or "").strip()
    if not q:
        raise ValueError("question is required")
    app = str(source_app or "").strip()
    page = str(source_page or "").strip()
    area = str(quant_area or "").strip() or default_area_for_source(app)
    ctx = dict(context or {})
    ctx.setdefault("source_app", source_app_label(app))
    ctx.setdefault("page", _display_page_name(app, page))
    summary = str(context_summary or "").strip()
    if not summary:
        summary = _short_context_summary(ctx)
    qid = question_id(q, source_app=app, source_page=page, context=ctx)
    ctx_display = format_context_lines(ctx)
    return {
        "question": q,
        "question_id": qid,
        "source_app": app,
        "source_page": page,
        "context_summary": summary,
        "context": ctx,
        "context_display": " · ".join(ctx_display),
        "quant_area": area,
        "resume_key": f"ai:question:{qid}",
    }


def _display_page_name(source_app: str, page: str) -> str:
    p = str(page or "").strip()
    if p == "Trend Value":
        return "Trends"
    return p


def _short_context_summary(ctx: dict[str, Any]) -> str:
    workflow = str(ctx.get("workflow") or "").strip()
    if workflow:
        players = ctx.get("players")
        if isinstance(players, list) and players:
            return f"{workflow} · {', '.join(str(p) for p in players[:3])}"
        return workflow
    if ctx.get("player"):
        return str(ctx["player"])
    if ctx.get("team"):
        return str(ctx["team"])
    return str(ctx.get("page") or "Current page")


def build_applied_math_resume_url(payload: dict[str, Any], *, base_url: str = "") -> str:
    from suite_deep_links import build_resume_action_url

    metrics = metrics_for_applied_math_resume(payload)
    return build_resume_action_url(
        "applied_intelligence",
        resume_key=str(payload.get("resume_key") or ""),
        page="Solve a Problem",
        metrics=metrics,
        base_url=base_url,
    )


def _recent_duplicate_send(
    session_state: dict[str, Any] | None,
    fingerprint: str,
) -> bool:
    if not session_state:
        return False
    last = session_state.get("_ami_last_send")
    if not isinstance(last, dict):
        return False
    if str(last.get("question_id") or "") != fingerprint:
        return False
    ts = parse_activity_timestamp(str(last.get("submitted_at") or ""))
    if ts is None:
        return False
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age < _SEND_COOLDOWN_SECONDS


def submit_analytical_question(
    *,
    source_app: str,
    source_page: str,
    question: str,
    context: dict[str, Any] | None = None,
    context_summary: str = "",
    quant_area: str = "",
    session_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Log event on source app and upsert Applied Intelligence resume item."""
    payload = build_question_payload(
        source_app=source_app,
        source_page=source_page,
        question=question,
        context=context,
        context_summary=context_summary,
        quant_area=quant_area,
    )
    action_url = build_applied_math_resume_url(payload)
    duplicate = _recent_duplicate_send(session_state, payload["question_id"])
    if not duplicate:
        metrics = metrics_for_applied_math_resume(payload)
        summary = f"Asked Applied Math: {payload['question'][:80]}"
        try:
            from suite_activity_client import record_activity

            record_activity(
                payload["source_app"],
                "analytical_question",
                page=payload["source_page"],
                metrics=metrics,
                summary=summary,
            )
        except Exception as exc:
            log.warning("record_activity failed for analytical_question: %s", exc)
    _upsert_applied_intelligence_resume(payload, action_url=action_url)
    if session_state is not None:
        session_state["_ami_last_send"] = {
            "question_id": payload["question_id"],
            "question": payload["question"],
            "source_app": payload["source_app"],
            "submitted_at": utc_now_iso(),
        }
    card_title, card_subtitle, _ = analytical_question_continue_copy(payload)
    return {
        **payload,
        "action_url": action_url,
        "continue_title": card_title,
        "continue_subtitle": card_subtitle,
        "duplicate": duplicate,
        "submitted_at": utc_now_iso(),
    }


def render_analyze_with_applied_math_sidebar(
    st: Any,
    *,
    source_app: str,
    source_page: str,
    context: dict[str, Any] | None = None,
    context_summary: str = "",
    default_question: str = "",
    developer_mode: bool = False,
    session_state: dict[str, Any] | None = None,
) -> None:
    """Always-visible sidebar block: question → Command Center → Applied Intelligence."""
    ss = session_state if session_state is not None else st.session_state
    page_suffix = _safe_widget_suffix(source_page)
    send_gen = int(ss.get(f"_ami_send_gen_{source_app}_{page_suffix}") or 0)
    question_key = f"ami_question_{source_app}_{page_suffix}_{send_gen}"
    submit_key = f"ami_submit_{source_app}_{page_suffix}"

    st.sidebar.markdown("### Analyze with Applied Math")
    st.sidebar.caption("Ask a math question about what you are viewing.")

    last = ss.get("_ami_last_send")
    if (
        isinstance(last, dict)
        and last.get("source_app") == source_app
        and _recent_duplicate_send(ss, str(last.get("question_id") or ""))
    ):
        st.sidebar.success(
            "Question sent to Command Center. Open Command Center to continue in Applied Intelligence."
        )

    question = st.sidebar.text_area(
        "Question",
        value=str(ss.get(question_key) or default_question or "").strip(),
        placeholder="e.g. Is this trend meaningful statistically?",
        height=88,
        key=question_key,
        label_visibility="visible",
    )

    if st.sidebar.button(
        "Send to Command Center",
        key=submit_key,
        use_container_width=True,
        type="primary",
    ):
        q = str(question or "").strip()
        if not q:
            st.sidebar.warning("Enter a question first.")
        else:
            result = submit_analytical_question(
                source_app=source_app,
                source_page=source_page,
                question=q,
                context=context,
                context_summary=context_summary,
                session_state=ss,
            )
            ss["_last_analytical_question"] = result
            ss[f"_ami_send_gen_{source_app}_{page_suffix}"] = send_gen + 1
            if result.get("duplicate"):
                st.sidebar.info(
                    "That question was already sent recently. Open Command Center to continue in Applied Intelligence."
                )
            else:
                st.sidebar.success(
                    "Question sent to Command Center. Open Command Center to continue in Applied Intelligence."
                )
            st.rerun()

    if developer_mode:
        st.sidebar.caption(f"🛠 {AMI_SIDEBAR_DEPLOY_LABEL} · {AMI_SIDEBAR_DEPLOY_VERSION}")
    st.sidebar.divider()


def render_applied_math_sidebar_entry(
    st: Any,
    *,
    source_app: str,
    source_page: str,
    session_state: dict[str, Any],
    context_extra: dict[str, Any] | None = None,
    developer_mode: bool = False,
) -> None:
    """Render AMI sidebar near the top; log and surface failures in Developer Mode."""
    try:
        ctx, summary = build_context_from_session(source_app, source_page, session_state)
        if context_extra:
            for key, val in context_extra.items():
                if val is None or val == "":
                    continue
                if key in ("page", "team", "opponent", "win_probability", "series_probability"):
                    ctx[key] = val
            if context_extra.get("team"):
                ctx["team"] = str(context_extra["team"])
        render_analyze_with_applied_math_sidebar(
            st,
            source_app=source_app,
            source_page=source_page,
            context=ctx,
            context_summary="",
            developer_mode=developer_mode,
            session_state=session_state,
        )
    except Exception as exc:
        log.exception("Applied Math sidebar failed for %s (%s)", source_app, source_page)
        if developer_mode:
            st.sidebar.warning(
                f"Applied Math sidebar failed: {type(exc).__name__}: {exc}"
            )


def build_context_from_session(
    source_app: str,
    source_page: str,
    session_state: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Clean human context from session — no raw widget keys."""
    app = str(source_app or "").strip()
    app_label = source_app_label(app)
    page_display = _display_page_name(app, source_page)
    ctx: dict[str, Any] = {
        "source_app": app_label,
        "page": page_display,
    }
    summary = page_display

    if app == "baseball":
        low_page = source_page.lower()
        if "draft" in low_page:
            ctx["workflow"] = "Fantasy draft"
            fmt = str(
                session_state.get("draft_format")
                or session_state.get("draft_lab_scoring_type")
                or session_state.get("draft_lab_format")
                or ""
            ).strip()
            if fmt:
                ctx["league_format"] = fmt
                ctx["draft_format"] = fmt
            room = session_state.get("draft_room_state") or {}
            if isinstance(room, dict):
                idx = int(room.get("current_pick_index") or 0)
                num_teams = int(room.get("num_teams") or session_state.get("draft_num_teams") or 12)
                if idx >= 0 and num_teams > 0:
                    ctx["current_pick"] = idx + 1
                    ctx["draft_round"] = (idx // num_teams) + 1
            dq = session_state.get("draft_queue") or []
            if isinstance(dq, list) and dq:
                ctx["player"] = _player_name(dq[0])
                ctx["players"] = [_player_name(x) for x in dq[:4]]
            summary = f"Draft · round {ctx.get('draft_round', '?')}"
        elif source_page == "Comparison Tool":
            ctx["workflow"] = "Player comparison"
            pa = session_state.get("sig_player_a_clean")
            pb = session_state.get("sig_player_b_clean")
            if pa and pb:
                ctx["player_a"] = _player_name(pa)
                ctx["player_b"] = _player_name(pb)
                ctx["players"] = [ctx["player_a"], ctx["player_b"]]
                summary = f"{ctx['player_a']} vs {ctx['player_b']}"
        elif source_page == "Trend Value":
            multi = session_state.get("trend_players_multi") or []
            multi_names = [_player_name(x) for x in multi if x][:6]
            plot_stat = str(session_state.get("trend_plot_stat") or "").strip()
            dash_stats = session_state.get("single_trend_dashboard_stats") or []
            metrics: list[str] = []
            if plot_stat:
                metrics.append(plot_stat)
            if isinstance(dash_stats, list):
                for s in dash_stats:
                    s_str = str(s).strip()
                    if s_str and s_str not in metrics:
                        metrics.append(s_str)
            if len(multi_names) >= 2:
                ctx["workflow"] = "Player trend comparison"
                ctx["players"] = multi_names
                if metrics:
                    ctx["metrics"] = metrics[:6]
                summary = f"{' vs '.join(multi_names[:2])} · {metrics[0] if metrics else 'trends'}"
            else:
                ctx["workflow"] = "Player trend analysis"
                pl = session_state.get("single_trend_dashboard_player")
                if pl:
                    ctx["player"] = _player_name(pl)
                    ctx["players"] = [ctx["player"]]
                if metrics:
                    ctx["metrics"] = metrics[:6]
                summary = f"{ctx.get('player', 'Player')} · {', '.join(metrics[:3]) if metrics else 'trends'}"
                trend_dir = session_state.get("_ami_trend_direction") or session_state.get("trend_direction_label")
                if trend_dir:
                    ctx["trend_summary"] = {"direction": str(trend_dir), "stat": metrics[0] if metrics else ""}
        elif "trade" in low_page:
            ctx["workflow"] = "Trade analysis"
            acquire = session_state.get("pending_trade_acquire_players") or []
            away = session_state.get("pending_trade_away_players") or []
            if isinstance(acquire, list) and acquire:
                ctx["players"] = [_player_name(x) for x in acquire[:4]]
            if isinstance(away, list) and away:
                ctx["player_a"] = _player_name(away[0]) if away else ""
                ctx["player_b"] = _player_name(acquire[0]) if acquire else ""
        elif "lineup" in low_page or "fantasy" in low_page:
            ctx["workflow"] = "Fantasy lineup"
    elif app == "nba":
        page_label = re.sub(r"^[^\w]+", "", str(source_page or "").strip()).strip() or page_display
        ctx["page"] = page_label
        low_page = page_label.lower()
        if "live" in low_page or "game" in low_page:
            ctx["workflow"] = "Live game analysis"
        elif "playoff" in low_page or "bracket" in low_page:
            ctx["workflow"] = "Playoff series outlook"
        elif "matchup" in low_page or "injury" in low_page:
            ctx["workflow"] = "Matchup intelligence"
        else:
            ctx["workflow"] = "NBA analysis"
        team = session_state.get("_nba_persist_team") or session_state.get("favorite_team")
        if team:
            ctx["team"] = str(team)
            summary = str(team)
        pst = session_state.get("playoff_team_state")
        if isinstance(pst, dict):
            opp = str(pst.get("current_opponent") or pst.get("opponent") or "").strip()
            if opp and opp not in ("TBD", "None"):
                ctx["opponent"] = opp
            series_prob = pst.get("series_win_probability") or pst.get("series_prob")
            if series_prob is not None:
                try:
                    ctx["series_probability"] = f"{float(series_prob):.0f}%"
                except (TypeError, ValueError):
                    ctx["series_probability"] = str(series_prob)
        live_prob = session_state.get("live_win_prob_display") or session_state.get("_last_win_prob")
        if live_prob is not None and ("live" in low_page or "game" in low_page):
            try:
                ctx["win_probability"] = f"{float(live_prob):.0f}%"
            except (TypeError, ValueError):
                ctx["win_probability"] = str(live_prob)
    elif app == "investment":
        tab = str(session_state.get("investment_active_tab") or source_page or "").strip()
        if tab:
            ctx["page"] = tab
        if "health" in tab.lower():
            ctx["workflow"] = "Portfolio health review"
        elif "macro" in tab.lower():
            ctx["workflow"] = "Macro analysis"
        elif "frontier" in tab.lower() or "scenario" in tab.lower():
            ctx["workflow"] = "Scenario analysis"
        else:
            ctx["workflow"] = "Portfolio analysis"
        summary = tab or page_display
        health = session_state.get("health_result")
        if health is not None:
            score = getattr(health, "score", None)
            if score is None and isinstance(health, dict):
                score = health.get("score")
            if score is not None:
                ctx["health_score"] = round(float(score), 1) if isinstance(score, (int, float)) else score
        objective = str(
            session_state.get("portfolio_objective")
            or session_state.get("investment_objective")
            or ""
        ).strip()
        if objective:
            ctx["objective"] = objective
        preset = str(session_state.get("portfolio_preset") or session_state.get("asset_preset") or "").strip()
        if preset:
            ctx["portfolio_preset"] = preset
        pv = session_state.get("sidebar_portfolio_value")
        if pv:
            ctx["portfolio_value"] = f"${int(float(pv)):,}"
        try:
            from components.macro_engine import macro_assumption_summary

            summary_text = macro_assumption_summary()
            if summary_text:
                ctx["macro_summary"] = summary_text
        except Exception:
            pass
        er = session_state.get("portfolio_expected_return") or session_state.get("expected_return_pct")
        vol = session_state.get("portfolio_volatility") or session_state.get("volatility_pct")
        if er is not None:
            try:
                ctx["expected_return"] = f"{float(er):.1f}%"
            except (TypeError, ValueError):
                ctx["expected_return"] = str(er)
        if vol is not None:
            try:
                ctx["volatility"] = f"{float(vol):.1f}%"
            except (TypeError, ValueError):
                ctx["volatility"] = str(vol)
        hr = session_state.get("health_result")
        if hr is not None and hasattr(hr, "expected_return"):
            try:
                ctx.setdefault("expected_return", f"{float(hr.expected_return):.1f}%")
            except Exception:
                pass
        if hr is not None and hasattr(hr, "volatility"):
            try:
                ctx.setdefault("volatility", f"{float(hr.volatility):.1f}%")
            except Exception:
                pass
        tickers: list[str] = []
        df = session_state.get("holdings_df")
        try:
            import pandas as pd

            if isinstance(df, pd.DataFrame) and "Ticker" in df.columns:
                tickers = [str(t).strip() for t in df["Ticker"].dropna().tolist()[:8] if str(t).strip()]
        except Exception:
            pass
        if tickers:
            ctx["holdings"] = tickers
            summary = f"{summary} · {', '.join(tickers[:4])}"

    return ctx, summary
