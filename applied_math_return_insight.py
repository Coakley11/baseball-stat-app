"""Return Applied Math insight to source apps — v1 display-only."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

INSIGHT_ITEM_TYPE = "applied_math_insight"
SESSION_PENDING_KEY = "_ami_pending_insight"
SESSION_RETURN_PAGE_KEY = "_ami_return_page"
SESSION_RETURN_CONTEXT_KEY = "_ami_return_context"

# Pages where the insight card may appear (display-only v1).
INSIGHT_ELIGIBLE_PAGES: dict[str, frozenset[str]] = {
    "baseball": frozenset({
        "Comparison Tool",
        "Trend Value",
        "Historical Explorer",
        "Draft Assistant Simulator",
        "Live Draft Room",
        "Draft Room Simulator",
        "Draft Simulation Test Mode",
    }),
    "nba": frozenset({
        "Matchup Intelligence",
        "Legacy Tracker",
        "Live Game Center",
    }),
    "investment": frozenset({
        "Portfolio Health",
        "⑤ Portfolio Health",
        "Portfolio Analytics",
        "④ Analyze Portfolio",
        "Efficient Frontier",
        "⑩ Frontier (Optional)",
    }),
}


def _normalize_insight_page(page: str) -> str:
    p = str(page or "").strip()
    if p.startswith("🔴 "):
        p = p.replace("🔴 ", "", 1)
    if p.startswith("🧠 "):
        p = p.replace("🧠 ", "", 1)
    if p.startswith("👑 "):
        p = p.replace("👑 ", "", 1)
    return p.strip()


def should_render_insight_on_page(source_app: str, current_page: str, insight: dict[str, Any]) -> bool:
    """True when pending insight belongs on this page."""
    app = str(source_app or insight.get("source_app") or "").strip().lower()
    cur = _normalize_insight_page(current_page)
    eligible = INSIGHT_ELIGIBLE_PAGES.get(app, frozenset())
    if cur not in eligible and not any(_normalize_insight_page(x) == cur for x in eligible):
        return False
    insight_page = _normalize_insight_page(str(insight.get("source_page") or ""))
    if insight_page:
        if insight_page == cur:
            return True
        # Draft family: any draft page shows draft insight
        if "draft" in insight_page.lower() and "draft" in cur.lower():
            return True
        return False
    return True


@dataclass
class AppliedMathInsight:
    insight_id: str
    question_id: str
    question: str
    source_app: str
    source_page: str
    conclusion: str
    method: str
    model_name: str = ""
    math_summary: str = ""
    assumptions: list[str] = field(default_factory=list)
    confidence: str = "medium"
    confidence_pct: int | None = None
    key_numbers: dict[str, Any] = field(default_factory=dict)
    full_analysis_url: str = ""
    created_at: str = ""
    resume_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _confidence_word(pct: int | None) -> str:
    if pct is None:
        return "medium"
    if pct >= 75:
        return "high"
    if pct >= 50:
        return "medium"
    return "low"


def _insight_id(question_id: str, conclusion: str) -> str:
    blob = f"{question_id}|{conclusion}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def build_return_insight_payload(
    *,
    question: str,
    source_app: str,
    source_page: str = "",
    question_id: str = "",
    route: Any | None = None,
    result: Any | None = None,
    resume_key: str = "",
    full_analysis_url: str = "",
    context: dict[str, Any] | None = None,
) -> AppliedMathInsight:
    """Build display-only insight payload from a completed solve."""
    q = str(question or "").strip()
    app = str(source_app or "").strip().lower()
    page = str(source_page or "").strip()
    qid = str(question_id or "").strip()
    if not qid and q:
        try:
            from suite_analytical_question import question_id as make_qid

            qid = make_qid(q, source_app=app, source_page=page, context=context)
        except Exception:
            qid = hashlib.sha256(q.encode()).hexdigest()[:12]

    conclusion = ""
    method = ""
    model_name = ""
    math_summary = ""
    assumptions: list[str] = []
    confidence_pct: int | None = None
    key_numbers: dict[str, Any] = {}

    if result is not None:
        conclusion = str(getattr(result, "short_answer", "") or getattr(result, "conclusion", "") or "").strip()
        method = str(getattr(result, "math_idea", "") or getattr(result, "problem_type", "") or "").strip()
        model_name = str(getattr(result, "model_name", "") or "").strip()
        math_summary = str(getattr(result, "variables", "") or "").strip()[:400]
        assumptions = list(getattr(result, "assumptions", []) or [])[:6]
        confidence_pct = getattr(result, "confidence_pct", None)
        computed = getattr(result, "computed", None)
        live = getattr(result, "live_metrics", None)
        if isinstance(computed, dict):
            key_numbers.update({k: v for k, v in computed.items() if v is not None})
        if isinstance(live, dict):
            key_numbers.update({f"live_{k}": v for k, v in list(live.items())[:6]})

    if route is not None:
        if not model_name:
            model_name = str(getattr(route, "model_name", "") or getattr(route, "problem_type", "") or "").strip()
        if not method:
            method = str(getattr(route, "model_rationale", "") or method).strip()

    iid = _insight_id(qid, conclusion or q)
    return AppliedMathInsight(
        insight_id=iid,
        question_id=qid,
        question=q,
        source_app=app,
        source_page=page,
        conclusion=conclusion or "Analysis complete — open full analysis for details.",
        method=method or model_name or "Applied Math solver",
        model_name=model_name,
        math_summary=math_summary,
        assumptions=assumptions,
        confidence=_confidence_word(confidence_pct),
        confidence_pct=confidence_pct,
        key_numbers=key_numbers,
        full_analysis_url=full_analysis_url,
        created_at=datetime.now(timezone.utc).isoformat(),
        resume_key=str(resume_key or "").strip(),
    )


def build_applied_math_full_analysis_url(payload: dict[str, Any], *, base_url: str = "") -> str:
    """Deep link back into Applied Intelligence for the same question."""
    try:
        from suite_analytical_question import build_applied_math_resume_url

        return build_applied_math_resume_url(payload, base_url=base_url)
    except Exception:
        return ""


def metrics_for_source_app_return(insight: AppliedMathInsight | dict[str, Any]) -> dict[str, Any]:
    """Metrics bundle for return deep links."""
    data = insight.to_dict() if isinstance(insight, AppliedMathInsight) else dict(insight)
    ctx = dict(data.get("return_context") or {})
    return {
        "page": data.get("source_page") or ctx.get("page") or "",
        "source_page": data.get("source_page") or "",
        "player_a": ctx.get("player_a"),
        "player_b": ctx.get("player_b"),
        "player": ctx.get("player"),
        "team": ctx.get("team"),
        "tickers": ctx.get("holdings"),
        "ami_insight": data.get("insight_id") or "",
        "question_id": data.get("question_id") or "",
    }


def build_source_app_return_url(
    insight: AppliedMathInsight | dict[str, Any],
    *,
    resume_key: str = "",
    metrics: dict[str, Any] | None = None,
    base_url: str = "",
) -> str:
    """Build URL to return to source app with insight id in query params."""
    data = insight.to_dict() if isinstance(insight, AppliedMathInsight) else dict(insight)
    app = str(data.get("source_app") or "").strip().lower()
    if not app:
        return ""
    rk = str(resume_key or data.get("resume_key") or "").strip()
    m = dict(metrics or metrics_for_source_app_return(data))
    m["ami_insight"] = data.get("insight_id") or ""
    m["question_id"] = data.get("question_id") or ""
    m["page"] = data.get("source_page") or m.get("page") or ""
    try:
        from suite_deep_links import build_resume_action_url

        return build_resume_action_url(app, resume_key=rk, page=m.get("page", ""), metrics=m, base_url=base_url)
    except Exception as exc:
        log.warning("build_source_app_return_url failed: %s", exc)
        return ""


def store_applied_math_insight(
    insight: AppliedMathInsight | dict[str, Any],
    *,
    return_context: dict[str, Any] | None = None,
) -> str:
    """Persist insight for retrieval on source app return."""
    data = insight.to_dict() if isinstance(insight, AppliedMathInsight) else dict(insight)
    iid = str(data.get("insight_id") or "").strip()
    if not iid:
        return ""
    blob = dict(data)
    if return_context:
        blob["return_context"] = dict(return_context)
    try:
        from suite_account import remember_saved_item

        remember_saved_item(
            str(data.get("source_app") or "applied_intelligence"),
            INSIGHT_ITEM_TYPE,
            iid,
            title=str(data.get("conclusion") or "Applied Math insight")[:120],
            payload=blob,
        )
    except Exception as exc:
        log.warning("remember_saved_item insight failed: %s", exc)
    try:
        from suite_activity_client import record_activity

        record_activity(
            str(data.get("source_app") or "unknown"),
            "applied_math_insight",
            page=str(data.get("source_page") or ""),
            metrics=blob,
            summary=str(data.get("conclusion") or "")[:200],
            resume_key=str(data.get("resume_key") or ""),
        )
    except Exception as exc:
        log.warning("record_activity insight failed: %s", exc)
    return iid


def load_applied_math_insight(insight_id: str, *, source_app: str = "") -> dict[str, Any]:
    """Load stored insight by id."""
    iid = str(insight_id or "").strip()
    if not iid:
        return {}
    app = str(source_app or "").strip()
    try:
        from suite_account import load_saved_items

        for app_key in ([app] if app else []) + ["baseball", "nba", "investment", "applied_intelligence"]:
            rows = load_saved_items(app=app_key, item_type=INSIGHT_ITEM_TYPE, limit=40)
            for row in rows:
                if str(row.get("item_key") or "") == iid:
                    payload = row.get("payload")
                    if isinstance(payload, dict):
                        return dict(payload)
    except Exception as exc:
        log.warning("load_applied_math_insight failed: %s", exc)
    return {}


def stage_pending_insight(st: Any, insight: AppliedMathInsight | dict[str, Any], *, return_context: dict[str, Any] | None = None) -> None:
    """Write insight into Streamlit session for AMI return button."""
    data = insight.to_dict() if isinstance(insight, AppliedMathInsight) else dict(insight)
    st.session_state[SESSION_PENDING_KEY] = data
    st.session_state[SESSION_RETURN_PAGE_KEY] = data.get("source_page") or ""
    if return_context:
        st.session_state[SESSION_RETURN_CONTEXT_KEY] = dict(return_context)


def apply_ami_insight_from_query(st: Any, app_key: str) -> bool:
    """On source app load: hydrate pending insight from ?suite_ami_insight=."""
    flag = f"_ami_insight_applied_{app_key}"
    if st.session_state.get(flag):
        return False

    def _qp(name: str) -> str:
        try:
            raw = st.query_params.get(name)
        except Exception:
            return ""
        if raw is None:
            return ""
        if isinstance(raw, list):
            return str(raw[0] or "").strip()
        return str(raw).strip()

    iid = _qp("suite_ami_insight")
    if not iid:
        return False

    insight = load_applied_math_insight(iid, source_app=app_key)
    if not insight:
        insight = {"insight_id": iid, "conclusion": "Applied Math insight loaded.", "question": ""}

    st.session_state[SESSION_PENDING_KEY] = insight
    st.session_state[SESSION_RETURN_PAGE_KEY] = _qp("suite_page") or insight.get("source_page") or ""
    st.session_state[flag] = True
    return True


def clear_pending_insight(st: Any) -> None:
    st.session_state.pop(SESSION_PENDING_KEY, None)
    st.session_state.pop(SESSION_RETURN_PAGE_KEY, None)
    st.session_state.pop(SESSION_RETURN_CONTEXT_KEY, None)


def render_applied_math_insight_panel(st: Any) -> bool:
    """Display-only insight card on source app pages. Returns True if rendered."""
    insight = st.session_state.get(SESSION_PENDING_KEY)
    if not isinstance(insight, dict) or not insight.get("conclusion"):
        return False

    with st.container(border=True):
        st.markdown("#### Applied Math Insight")
        q = str(insight.get("question") or "").strip()
        if q:
            st.markdown(f"**Question:** *{q}*")
        st.markdown(f"**Conclusion:** {insight.get('conclusion')}")
        method = str(insight.get("method") or insight.get("model_name") or "").strip()
        if method:
            st.markdown(f"**Math used:** {method}")
        assumptions = insight.get("assumptions") or []
        if assumptions:
            st.markdown("**Assumptions:**")
            for a in assumptions[:4]:
                st.markdown(f"- {a}")
        conf = insight.get("confidence")
        if conf:
            extra = f" ({insight.get('confidence_pct')}%)" if insight.get("confidence_pct") else ""
            st.caption(f"Confidence: **{conf}**{extra}")
        url = str(insight.get("full_analysis_url") or "").strip()
        c1, c2 = st.columns(2)
        with c1:
            if url:
                st.link_button("Open full analysis →", url, use_container_width=True)
        with c2:
            if st.button("Dismiss insight", key="ami_insight_dismiss", use_container_width=True):
                clear_pending_insight(st)
                st.rerun()
    return True


def render_suite_applied_math_insight_for_page(
    st: Any,
    *,
    source_app: str,
    source_page: str,
) -> bool:
    """Render insight card when pending insight matches this page (source apps)."""
    insight = st.session_state.get(SESSION_PENDING_KEY)
    if not isinstance(insight, dict) or not insight.get("conclusion"):
        return False
    if not should_render_insight_on_page(source_app, source_page, insight):
        return False
    return render_applied_math_insight_panel(st)


def render_return_to_source_button(
    st: Any,
    insight: AppliedMathInsight | dict[str, Any],
    *,
    resume_key: str = "",
    return_context: dict[str, Any] | None = None,
) -> None:
    """AMI button: return insight to originating source app."""
    data = insight.to_dict() if isinstance(insight, AppliedMathInsight) else dict(insight)
    app = str(data.get("source_app") or "").strip().lower()
    if not app or app in ("unknown", "applied_intelligence", "math"):
        return

    try:
        from suite_analytical_question import source_app_label
    except Exception:
        source_app_label = lambda x: x  # noqa: E731

    label = source_app_label(app)
    store_applied_math_insight(data, return_context=return_context)
    url = build_source_app_return_url(data, resume_key=resume_key, metrics=metrics_for_source_app_return(data))
    if not url:
        st.caption(f"Return link unavailable for {label}.")
        return

    st.link_button(
        f"Return to {label} with insight →",
        url,
        use_container_width=True,
        help="Restores your page context and shows this conclusion in the source app — display only, no auto-changes.",
    )
