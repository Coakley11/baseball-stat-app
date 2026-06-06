"""
Cross-app "Analyze with Applied Math" — shared payload, submit, and deep links.

Source apps (Baseball, NBA, Investment) log ``analytical_question`` events;
Command Center surfaces Continue cards targeting Applied Intelligence.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import quote

from activity_time import utc_now_iso

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
    return {
        "question": q,
        "question_id": qid,
        "source_app": app,
        "source_page": page,
        "context_summary": summary,
        "context": ctx,
        "quant_area": area,
        "resume_key": f"ai:question:{qid}",
    }


def build_applied_math_resume_url(payload: dict[str, Any], *, base_url: str = "") -> str:
    from suite_deep_links import build_resume_action_url

    metrics = {
        "question": payload.get("question"),
        "source_app": payload.get("source_app"),
        "source_page": payload.get("source_page"),
        "context_summary": payload.get("context_summary"),
        "quant_area": payload.get("quant_area"),
        "context_json": json.dumps(payload.get("context") or {}, ensure_ascii=False),
    }
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
    title = f"Applied Math question from {label}"
    subtitle = str(payload["question"])[:120]
    action_url = build_applied_math_resume_url(payload)
    metrics = {
        "question": payload["question"],
        "question_id": payload["question_id"],
        "source_app": payload["source_app"],
        "source_page": payload["source_page"],
        "context_summary": payload["context_summary"],
        "context": payload["context"],
        "quant_area": payload["quant_area"],
    }
    summary = f"Asked Applied Math: {payload['question'][:80]}"
    try:
        from suite_activity_client import record_activity

        record_activity(
            payload["source_app"],
            "analytical_question",
            page=payload["source_page"],
            metrics=metrics,
            summary=summary,
            resume_key=payload["resume_key"],
            resume_title=title,
            resume_subtitle=subtitle,
            action_url=action_url,
        )
    except Exception:
        pass
    try:
        from suite_storage import upsert_resume_item

        upsert_resume_item(
            "applied_intelligence",
            payload["resume_key"],
            title=title,
            subtitle=subtitle,
            action_url=action_url,
        )
    except Exception:
        pass
    return {**payload, "action_url": action_url, "submitted_at": utc_now_iso()}


def render_analyze_with_applied_math_sidebar(
    st: Any,
    *,
    source_app: str,
    source_page: str,
    context: dict[str, Any] | None = None,
    context_summary: str = "",
    default_question: str = "",
) -> None:
    """Sidebar expander: question form → Command Center → Applied Intelligence."""
    label = source_app_label(source_app)
    with st.sidebar.expander("Analyze with Applied Math", expanded=False):
        st.caption(f"Send a quantitative question from {label} to Applied Intelligence.")
        if context_summary:
            st.caption(f"Context: {context_summary}")
        question = st.text_area(
            "Your question",
            value=str(default_question or "").strip(),
            placeholder="e.g. Is this trend meaningful statistically?",
            height=90,
            key=f"ami_question_{source_app}_{source_page}",
        )
        if st.button("Send to Command Center", key=f"ami_submit_{source_app}", use_container_width=True):
            q = str(question or "").strip()
            if not q:
                st.warning("Enter a question first.")
            else:
                result = submit_analytical_question(
                    source_app=source_app,
                    source_page=source_page,
                    question=q,
                    context=context,
                    context_summary=context_summary,
                )
                st.session_state["_last_analytical_question"] = result
                st.success("Question saved — open Command Center to continue in Applied Intelligence.")
        last = st.session_state.get("_last_analytical_question")
        if isinstance(last, dict) and last.get("source_app") == source_app:
            st.caption(f"Last sent: {str(last.get('question') or '')[:60]}…")


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
        if source_page == "Trend Value":
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
