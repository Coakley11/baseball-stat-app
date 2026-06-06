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
from typing import Any
from urllib.parse import quote

from activity_time import utc_now_iso

log = logging.getLogger(__name__)

AMI_SIDEBAR_DEPLOY_LABEL = "Applied Math question sender live"
AMI_SIDEBAR_DEPLOY_VERSION = "2026-06-06-ami-sidebar-v1"
ANALYTICAL_QUESTION_CONTINUE_PRIORITY = 64
ANALYTICAL_QUESTION_BUTTON_LABEL = "Continue in Applied Mathematics →"

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


def default_area_for_source(source_app: str) -> str:
    return _SOURCE_AREA.get(str(source_app or "").strip(), "abstract")


def source_app_label(source_app: str) -> str:
    key = str(source_app or "").strip()
    return _SOURCE_LABELS.get(key, key.replace("_", " ").title())


def question_id(question: str, *, source_app: str = "") -> str:
    blob = f"{source_app}|{question.strip()}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _safe_widget_suffix(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", str(text or "page"))[:48]


def format_context_lines(context: dict[str, Any] | None) -> list[str]:
    """Human-readable context lines for Continue cards and Applied Intelligence."""
    ctx = dict(context or {})
    lines: list[str] = []
    ordered_keys = (
        ("source_page", "page", "tab"),
        ("team",),
        ("player",),
        ("player_a", "player_b"),
        ("league_format", "draft_format", "scoring"),
        ("draft_round", "current_pick"),
        ("health_score",),
        ("objective", "portfolio_preset"),
        ("tickers",),
        ("macro_summary",),
    )
    seen: set[str] = set()
    labels = {
        "source_page": "Page",
        "page": "Page",
        "tab": "Tab",
        "team": "Team",
        "player": "Player",
        "player_a": "Player A",
        "player_b": "Player B",
        "league_format": "League",
        "draft_format": "Draft format",
        "scoring": "Scoring",
        "draft_round": "Draft round",
        "current_pick": "Current pick",
        "health_score": "Health score",
        "objective": "Objective",
        "portfolio_preset": "Portfolio preset",
        "tickers": "Holdings",
        "macro_summary": "Macro outlook",
    }
    for group in ordered_keys:
        for key in group:
            if key in seen or key not in ctx:
                continue
            val = ctx.get(key)
            if val is None or val == "":
                continue
            seen.add(key)
            label = labels.get(key, key.replace("_", " ").title())
            if isinstance(val, list):
                text = ", ".join(str(v) for v in val[:8])
            else:
                text = str(val)
            if text.strip():
                lines.append(f"{label}: {text.strip()}")
    for key, val in sorted(ctx.items()):
        if key in seen or val in (None, ""):
            continue
        if key.startswith("_"):
            continue
        text = ", ".join(str(v) for v in val[:8]) if isinstance(val, list) else str(val)
        if text.strip():
            lines.append(f"{key.replace('_', ' ').title()}: {text.strip()}")
    return lines[:8]


def analytical_question_continue_copy(payload: dict[str, Any]) -> tuple[str, str, str]:
    """Return (title, subtitle, button_label) for Command Center Continue cards."""
    label = source_app_label(str(payload.get("source_app") or ""))
    question = str(payload.get("question") or "").strip()
    ctx_lines = format_context_lines(payload.get("context") if isinstance(payload.get("context"), dict) else {})
    subtitle_parts = [f"Question: {question}"]
    if ctx_lines:
        subtitle_parts.append("Context: " + " · ".join(ctx_lines))
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
    summary = str(context_summary or "").strip()
    if not summary:
        parts = [p for p in (ctx.get("player_a"), ctx.get("player_b")) if p]
        if parts:
            summary = " vs ".join(str(p) for p in parts[:2])
        elif ctx.get("player"):
            summary = str(ctx["player"])
        elif ctx.get("team"):
            summary = str(ctx["team"])
        elif ctx.get("tickers"):
            tickers = ctx["tickers"]
            if isinstance(tickers, list) and tickers:
                summary = ", ".join(str(t) for t in tickers[:6])
    qid = question_id(q, source_app=app)
    ctx = dict(context or {})
    ctx.setdefault("page", page)
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


def submit_analytical_question(
    *,
    source_app: str,
    source_page: str,
    question: str,
    context: dict[str, Any] | None = None,
    context_summary: str = "",
    quant_area: str = "",
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
    label = source_app_label(payload["source_app"])
    action_url = build_applied_math_resume_url(payload)
    metrics = metrics_for_applied_math_resume(payload)
    card_title, card_subtitle, _ = analytical_question_continue_copy(payload)
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
    return {
        **payload,
        "action_url": action_url,
        "continue_title": card_title,
        "continue_subtitle": card_subtitle,
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
) -> None:
    """Always-visible sidebar block: question → Command Center → Applied Intelligence."""
    label = source_app_label(source_app)
    page_suffix = _safe_widget_suffix(source_page)
    st.sidebar.markdown("### Analyze with Applied Math")
    st.sidebar.caption(f"Send a quantitative question from {label} to Applied Intelligence.")
    if context_summary:
        st.sidebar.caption(f"Context: {context_summary}")
    question = st.sidebar.text_area(
        "Your question",
        value=str(default_question or "").strip(),
        placeholder="e.g. Is this trend meaningful statistically?",
        height=90,
        key=f"ami_question_{source_app}_{page_suffix}",
        label_visibility="visible",
    )
    if st.sidebar.button(
        "Send to Command Center",
        key=f"ami_submit_{source_app}_{page_suffix}",
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
            )
            st.session_state["_last_analytical_question"] = result
            st.sidebar.success("Question saved — open Command Center to continue in Applied Intelligence.")
    last = st.session_state.get("_last_analytical_question")
    if isinstance(last, dict) and last.get("source_app") == source_app:
        st.sidebar.caption(f"Last sent: {str(last.get('question') or '')[:60]}…")
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
            ctx = {**ctx, **context_extra}
            if context_extra.get("team"):
                summary = str(context_extra["team"])
            elif context_extra.get("player") and not summary.startswith("Trend"):
                summary = str(context_extra["player"])
        render_analyze_with_applied_math_sidebar(
            st,
            source_app=source_app,
            source_page=source_page,
            context=ctx,
            context_summary=summary,
            developer_mode=developer_mode,
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
    """Lightweight page context for cross-app analytical questions."""
    ctx: dict[str, Any] = {"page": source_page}
    summary = str(source_page or "").strip() or "Current page"
    app = str(source_app or "").strip()

    if app == "baseball":
        low_page = source_page.lower()
        if "draft" in low_page:
            fmt = str(
                session_state.get("draft_format")
                or session_state.get("draft_lab_scoring_type")
                or session_state.get("draft_lab_format")
                or ""
            ).strip()
            if fmt:
                ctx["draft_format"] = fmt
                ctx["league_format"] = fmt
            room = session_state.get("draft_room_state") or {}
            if isinstance(room, dict):
                idx = int(room.get("current_pick_index") or 0)
                num_teams = int(room.get("num_teams") or session_state.get("draft_num_teams") or 12)
                if idx >= 0 and num_teams > 0:
                    ctx["current_pick"] = idx + 1
                    ctx["draft_round"] = (idx // num_teams) + 1
            dq = session_state.get("draft_queue") or []
            if isinstance(dq, list) and dq:
                ctx["player"] = str(dq[0]).split(" (")[0].strip()
            summary = f"Draft · pick {ctx.get('current_pick', '?')} · {fmt or source_page}"
        elif source_page == "Trend Value":
            pl = session_state.get("single_trend_dashboard_player")
            if pl:
                name = str(pl).split(" (")[0].strip()
                ctx["player"] = name
                summary = f"Trend: {name}"
            labels = session_state.get("trend_chart_labels") or []
            if isinstance(labels, list) and len(labels) >= 2:
                pa = str(labels[0]).split(" (")[0].strip()
                pb = str(labels[1]).split(" (")[0].strip()
                ctx["player_a"] = pa
                ctx["player_b"] = pb
                summary = f"{pa} vs {pb} trends"
        elif source_page == "Comparison Tool":
            pa = session_state.get("sig_player_a_clean")
            pb = session_state.get("sig_player_b_clean")
            if pa and pb:
                ctx["player_a"] = str(pa).split(" (")[0].strip()
                ctx["player_b"] = str(pb).split(" (")[0].strip()
                summary = f"{ctx['player_a']} vs {ctx['player_b']}"
    elif app == "nba":
        team = session_state.get("_nba_persist_team") or session_state.get("favorite_team")
        if team:
            ctx["team"] = str(team)
            summary = str(team)
    elif app == "investment":
        tab = str(session_state.get("investment_active_tab") or source_page or "").strip()
        if tab:
            ctx["tab"] = tab
            summary = tab
        health = session_state.get("health_result")
        if health is not None:
            score = getattr(health, "score", None)
            if score is None and isinstance(health, dict):
                score = health.get("score")
            if score is not None:
                ctx["health_score"] = score
        objective = str(session_state.get("portfolio_objective") or session_state.get("investment_objective") or "").strip()
        if objective:
            ctx["objective"] = objective
        preset = str(session_state.get("portfolio_preset") or session_state.get("asset_preset") or "").strip()
        if preset:
            ctx["portfolio_preset"] = preset
        try:
            from components.macro_engine import macro_assumption_summary, macro_assumptions_from_session

            assumptions = macro_assumptions_from_session()
            if assumptions:
                ctx["macro_summary"] = macro_assumption_summary(assumptions)
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
            ctx["tickers"] = tickers
            summary = f"{summary} · {', '.join(tickers[:4])}"

    return ctx, summary
