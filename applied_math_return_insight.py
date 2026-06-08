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
INSIGHT_DISMISSAL_ITEM_TYPE = "applied_math_insight_dismissal"
SESSION_PENDING_KEY = "_ami_pending_insight"
SESSION_RETURN_PAGE_KEY = "_ami_return_page"
SESSION_RETURN_CONTEXT_KEY = "_ami_return_context"
SESSION_DISMISSED_KEY = "_ami_dismissed_insight_ids"
SESSION_DISMISSED_AT_KEY = "_ami_dismissed_insight_at"
SESSION_PERSIST_INSIGHT_DIRTY = "_suite_persist_insight_dirty"

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


_INSIGHT_PAGE_LABEL_TO_KEY: dict[str, str] = {
    "🔎 Historical Explorer": "Historical Explorer",
    "📚 Career Totals": "Career Totals",
    "🏆 Leaderboards": "Leaderboards",
    "📈 Comparison Tool": "Comparison Tool",
    "🔥 Trend Value": "Trend Value",
    "💰 Valuation": "Valuation",
    "🤖 ML Predictions": "ML Predictions",
    "💎 Fantasy Sleepers & Busts": "Fantasy Sleepers & Busts",
    "🧾 Draft Room Simulator": "Draft Room Simulator",
    "🧩 Draft Assistant Simulator": "Draft Assistant Simulator",
    "🧪 Draft Simulation Test Mode": "Draft Simulation Test Mode",
    "📡 Live Draft Room": "Live Draft Room",
    "📊 Fantasy Standings Tracker": "Fantasy Standings Tracker",
    "🧠 Fantasy Lineup Assistant": "Fantasy Lineup Assistant",
}

_INSIGHT_PAGE_ALIASES: dict[str, str] = {
    "trends": "Trend Value",
    "trend value": "Trend Value",
    "comparison": "Comparison Tool",
    "comparison tool": "Comparison Tool",
}


def _normalize_insight_page(page: str) -> str:
    p = str(page or "").strip()
    if not p:
        return ""
    if p in _INSIGHT_PAGE_LABEL_TO_KEY:
        return _INSIGHT_PAGE_LABEL_TO_KEY[p]
    eligible_union: set[str] = set()
    for pages in INSIGHT_ELIGIBLE_PAGES.values():
        eligible_union.update(pages)
    if p in eligible_union:
        return p
    if p.startswith("🔴 "):
        p = p.replace("🔴 ", "", 1)
    if p.startswith("🧠 "):
        p = p.replace("🧠 ", "", 1)
    if p.startswith("👑 "):
        p = p.replace("👑 ", "", 1)
    p = p.strip()
    if p in _INSIGHT_PAGE_LABEL_TO_KEY:
        return _INSIGHT_PAGE_LABEL_TO_KEY[p]
    if p in eligible_union:
        return p
    import re

    stripped = re.sub(r"^[^\w]+", "", p).strip()
    if stripped in eligible_union:
        return stripped
    alias = _INSIGHT_PAGE_ALIASES.get(stripped.lower())
    if alias:
        return alias
    return stripped or p


def _resolve_insight_source_page(insight: dict[str, Any]) -> str:
    """Canonical originating page for a pending insight (strict, no current-page fallback)."""
    raw = str(insight.get("source_page") or "").strip()
    page = _normalize_insight_page(raw)
    if page:
        return page
    for container_key in ("source_state", "return_context"):
        container = insight.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("source_page", "page"):
            page = _normalize_insight_page(str(container.get(key) or ""))
            if page:
                return page
        page_params = container.get("page_params")
        if isinstance(page_params, dict):
            page = _normalize_insight_page(str(page_params.get("page") or ""))
            if page:
                return page
        chart = container.get("chart_params")
        if isinstance(chart, dict):
            snap = chart.get("chart_snapshot")
            if isinstance(snap, dict):
                page = _normalize_insight_page(str(snap.get("page") or ""))
                if page:
                    return page
    return ""


def insight_page_scope_decision(
    source_app: str,
    current_page: str,
    insight: dict[str, Any],
) -> dict[str, Any]:
    """Strict page scope decision with normalized fields for ?dev=1 diagnostics."""
    app = str(source_app or insight.get("source_app") or "").strip().lower()
    cur = _normalize_insight_page(current_page)
    raw_source = str(insight.get("source_page") or "").strip()
    insight_page = _resolve_insight_source_page(insight)
    eligible = INSIGHT_ELIGIBLE_PAGES.get(app, frozenset())
    cur_eligible = cur in eligible or any(_normalize_insight_page(x) == cur for x in eligible)
    should_render = False
    skip_reason = ""
    if not cur_eligible:
        skip_reason = f"current_page_not_eligible ({cur!r})"
    elif not insight_page:
        skip_reason = "missing_normalized_source_page"
    elif insight_page == cur:
        should_render = True
    elif "draft" in insight_page.lower() and "draft" in cur.lower():
        should_render = True
    else:
        skip_reason = f"normalized_page_mismatch (insight={insight_page!r}, current={cur!r})"
    return {
        "source_page_raw": raw_source or None,
        "source_page_normalized": insight_page or None,
        "current_page_raw": str(current_page or "").strip() or None,
        "current_page_normalized": cur or None,
        "should_render_insight_on_page": should_render,
        "render_skip_reason": skip_reason or None,
    }


def should_render_insight_on_page(source_app: str, current_page: str, insight: dict[str, Any]) -> bool:
    """True when pending insight belongs on this page."""
    return bool(
        insight_page_scope_decision(source_app, current_page, insight).get(
            "should_render_insight_on_page"
        )
    )


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
    ss = dict(data.get("source_state") or {})
    ctx = dict(data.get("return_context") or ss)
    ent = dict(ss.get("entity_params") or ctx.get("entity_params") or {})
    wp = dict(ss.get("widget_params") or ctx.get("widget_params") or {})
    chart = dict(ss.get("chart_params") or ctx.get("chart_params") or {})
    page = (
        data.get("source_page")
        or ss.get("source_page")
        or ctx.get("source_page")
        or ctx.get("page")
        or ss.get("page_params", {}).get("page")
        or ""
    )
    pa = (
        ent.get("player_a_label")
        or wp.get("sig_player_a_clean")
        or ctx.get("player_a")
        or ent.get("player_a")
    )
    pb = (
        ent.get("player_b_label")
        or wp.get("sig_player_b_clean")
        or ctx.get("player_b")
        or ent.get("player_b")
    )
    player = (
        ent.get("player_label")
        or wp.get("single_trend_dashboard_player")
        or ctx.get("player")
        or ent.get("player")
    )
    trend_players = ent.get("trend_players_multi") or chart.get("trend_players_multi")
    return {
        "page": page,
        "source_page": page,
        "player_a": pa,
        "player_b": pb,
        "player": player,
        "trend_players": trend_players,
        "team": ent.get("team") or ctx.get("team"),
        "opponent": ent.get("opponent") or ctx.get("opponent"),
        "tickers": ent.get("holdings") or ctx.get("holdings"),
        "holdings_fingerprint": ent.get("holdings_fingerprint") or ctx.get("holdings_fingerprint"),
        "ami_insight": data.get("insight_id") or "",
        "question_id": data.get("question_id") or "",
    }


def build_return_resume_key(
    insight: AppliedMathInsight | dict[str, Any],
    *,
    source_state: dict[str, Any] | None = None,
) -> str:
    """Prefer page-native resume keys (compare:/trend:) over ai:question: when possible."""
    data = insight.to_dict() if isinstance(insight, AppliedMathInsight) else dict(insight)
    app = str(data.get("source_app") or "").strip().lower()
    qid = str(data.get("question_id") or "").strip()
    ss = dict(source_state or data.get("source_state") or data.get("return_context") or {})
    page = str(ss.get("source_page") or data.get("source_page") or "").strip()
    ent = dict(ss.get("entity_params") or {})
    wp = dict(ss.get("widget_params") or {})

    if app == "baseball":
        if page == "Comparison Tool":
            pa = (
                ent.get("player_a_label")
                or wp.get("sig_player_a_clean")
                or ent.get("player_a")
                or ss.get("player_a")
            )
            pb = (
                ent.get("player_b_label")
                or wp.get("sig_player_b_clean")
                or ent.get("player_b")
                or ss.get("player_b")
            )
            cp = ent.get("compare_players") or wp.get("compare_players")
            if (not pa or not pb) and isinstance(cp, list) and len(cp) >= 2:
                pa = pa or cp[0]
                pb = pb or cp[1]
            if pa and pb:
                return f"compare:{pa}:{pb}"
        if page == "Trend Value":
            pl = ent.get("player_label") or wp.get("single_trend_dashboard_player")
            if pl:
                return f"trend:{pl}"
    if qid:
        return f"ai:question:{qid}"
    return str(data.get("resume_key") or "").strip()


def apply_return_source_state(st: Any, app_key: str, source_state: dict[str, Any] | None) -> None:
    """Apply stored page snapshot to source app session (pending keys + navigation)."""
    if not isinstance(source_state, dict) or not source_state:
        return
    ss = st.session_state
    key = _normalize_app_key(app_key or source_state.get("source_app") or "")
    ss[SESSION_RETURN_CONTEXT_KEY] = dict(source_state)
    page = str(
        source_state.get("source_page")
        or source_state.get("page_params", {}).get("page")
        or ""
    ).strip()
    if page:
        ss[SESSION_RETURN_PAGE_KEY] = page
    schedule_navigation = _should_apply_ami_return_navigation(st, key, page)
    if page and schedule_navigation:
        ss["_skip_page_restore_for"] = page
        ss["ami_return_forced_page"] = page
        ss["active_page_source"] = "ami_return_source_state"
    elif not schedule_navigation:
        ss.pop("_skip_page_restore_for", None)
        ss.pop("_navigate_to_page", None)

    app = key
    try:
        if app == "baseball":
            from applied_math_context import apply_source_state_to_session

            apply_source_state_to_session(ss, source_state, schedule_navigation=schedule_navigation)
        elif app == "nba":
            from applied_math_context import apply_source_state_to_session

            apply_source_state_to_session(ss, source_state, schedule_navigation=schedule_navigation)
        elif app == "investment":
            from applied_math_context import apply_source_state_to_session

            apply_source_state_to_session(ss, source_state, schedule_navigation=schedule_navigation)
    except TypeError:
        try:
            if app == "baseball":
                from applied_math_context import apply_source_state_to_session

                apply_source_state_to_session(ss, source_state)
            elif app in ("nba", "investment"):
                from applied_math_context import apply_source_state_to_session

                apply_source_state_to_session(ss, source_state)
            if not schedule_navigation:
                ss.pop("_navigate_to_page", None)
        except Exception as exc:
            log.warning("apply_return_source_state failed for %s: %s", app, exc)
    except Exception as exc:
        log.warning("apply_return_source_state failed for %s: %s", app, exc)


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
    source_state: dict[str, Any] | None = None,
) -> str:
    """Persist insight for retrieval on source app return."""
    data = insight.to_dict() if isinstance(insight, AppliedMathInsight) else dict(insight)
    iid = str(data.get("insight_id") or "").strip()
    if not iid:
        return ""
    blob = dict(data)
    rc = dict(return_context or source_state or data.get("return_context") or data.get("source_state") or {})
    ss = dict(source_state or data.get("source_state") or rc)
    if rc:
        blob["return_context"] = rc
    if ss:
        blob["source_state"] = ss
    try:
        from suite_account import remember_saved_item

        for store_app in (
            str(data.get("source_app") or "applied_intelligence"),
            "applied_intelligence",
        ):
            remember_saved_item(
                store_app,
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

        for app_key in ([app] if app else []) + [
            "applied_intelligence",
            "baseball",
            "nba",
            "investment",
        ]:
            rows = load_saved_items(app=app_key, item_type=INSIGHT_ITEM_TYPE, limit=80)
            for row in rows:
                if str(row.get("item_key") or "") == iid:
                    payload = row.get("payload")
                    if isinstance(payload, dict):
                        return dict(payload)
    except Exception as exc:
        log.warning("load_applied_math_insight failed: %s", exc)
    return {}


def _get_dismissed_insight_ids(st: Any) -> set[str]:
    raw = st.session_state.get(SESSION_DISMISSED_KEY)
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(x).strip() for x in raw if str(x).strip()}


def _get_dismissed_insight_at(st: Any, insight_id: str) -> str:
    meta = st.session_state.get(SESSION_DISMISSED_AT_KEY)
    if not isinstance(meta, dict):
        return ""
    return str(meta.get(str(insight_id or "").strip()) or "").strip()


def load_dismissed_insight_ids_from_cloud(source_app: str) -> dict[str, str]:
    """Cross-device dismissals: {insight_id: dismissed_at_iso}."""
    app = _normalize_app_key(source_app)
    if not app:
        return {}
    out: dict[str, str] = {}
    try:
        from suite_account import load_saved_items

        for app_key in (app, "applied_intelligence"):
            rows = load_saved_items(app=app_key, item_type=INSIGHT_DISMISSAL_ITEM_TYPE, limit=80)
            for row in rows:
                iid = str(row.get("item_key") or "").strip()
                payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
                if not iid and isinstance(payload, dict):
                    iid = str(payload.get("insight_id") or "").strip()
                if not iid:
                    continue
                ts = str(payload.get("dismissed_at") or row.get("updated_at") or "").strip()
                out[iid] = ts
    except Exception as exc:
        log.warning("load_dismissed_insight_ids_from_cloud failed: %s", exc)
    return out


def sync_dismissed_insights_from_cloud(st: Any, app_key: str) -> None:
    """Merge cloud dismissals into session; drop pending insight if dismissed remotely."""
    key = _normalize_app_key(app_key)
    cloud = load_dismissed_insight_ids_from_cloud(key)
    if not cloud:
        return
    dismissed = _get_dismissed_insight_ids(st)
    dismissed.update(cloud.keys())
    st.session_state[SESSION_DISMISSED_KEY] = sorted(dismissed)
    meta = dict(st.session_state.get(SESSION_DISMISSED_AT_KEY) or {})
    if not isinstance(meta, dict):
        meta = {}
    meta.update(cloud)
    st.session_state[SESSION_DISMISSED_AT_KEY] = meta
    pending = st.session_state.get(SESSION_PENDING_KEY)
    if isinstance(pending, dict):
        iid = str(pending.get("insight_id") or "").strip()
        if iid and iid in cloud:
            clear_pending_insight(st)


def persist_insight_dismissal_to_cloud(app_key: str, insight_id: str, *, dismissed_at: str | None = None) -> None:
    """Write dismissal to cloud saved items for cross-device hide on refresh."""
    iid = str(insight_id or "").strip()
    app = _normalize_app_key(app_key)
    if not iid or not app:
        return
    ts = dismissed_at or datetime.now(timezone.utc).isoformat()
    payload = {"insight_id": iid, "dismissed_at": ts, "source_app": app}
    try:
        from suite_account import remember_saved_item

        remember_saved_item(
            app,
            INSIGHT_DISMISSAL_ITEM_TYPE,
            iid,
            title=f"Dismissed insight {iid[:12]}",
            payload=payload,
        )
    except Exception as exc:
        log.warning("persist_insight_dismissal_to_cloud failed: %s", exc)


def record_ami_sidebar_nav_result(st: Any, app_key: str, *, selected_page: str = "") -> None:
    """Call after sidebar page selection to trace manual nav post-AMI return."""
    ss = st.session_state
    final_page = str(selected_page or ss.get("active_page") or ss.get("main_sidebar_page") or "").strip()
    ss["final_page_after_sidebar_click"] = final_page
    ss["manual_nav_after_ami_return"] = bool(ami_resume_consumed(st, app_key) and ss.get("_suite_page_user_nav"))
    _record_insight_return_diagnostics(st, phase="sidebar_nav")


def _insight_is_dismissed(st: Any, insight_id: str) -> bool:
    iid = str(insight_id or "").strip()
    return bool(iid and iid in _get_dismissed_insight_ids(st))


def _query_param(st: Any, name: str) -> str:
    try:
        raw = st.query_params.get(name)
    except Exception:
        return ""
    if raw is None:
        return ""
    if isinstance(raw, list):
        return str(raw[0] or "").strip()
    return str(raw).strip()


def insight_return_query_id(st: Any) -> str:
    """suite_ami_insight query param when returning from Applied Math."""
    return _query_param(st, "suite_ami_insight")


_AMI_RETURN_QP_KEYS: tuple[str, ...] = (
    "suite_ami_insight",
    "suite_page",
    "suite_resume",
    "suite_player_a",
    "suite_player_b",
    "suite_trend_player",
    "suite_ai_question_id",
    "suite_trend_players",
)


def _normalize_app_key(app_key: str) -> str:
    key = str(app_key or "").strip().lower()
    if key == "math":
        return "applied_intelligence"
    return key


def _ami_resume_consumed_flag(app_key: str) -> str:
    return f"_ami_resume_consumed_{_normalize_app_key(app_key)}"


def ami_resume_consumed(st: Any, app_key: str) -> bool:
    """True after AMI return URL/resume state was consumed (manual nav may proceed)."""
    return bool(st.session_state.get(_ami_resume_consumed_flag(app_key)))


def _active_ami_return_query_param_keys(st: Any) -> list[str]:
    return [k for k in _AMI_RETURN_QP_KEYS if _query_param(st, k)]


def ami_return_navigation_active(st: Any, app_key: str) -> bool:
    """True while AMI return URL/resume may force page navigation (before consume)."""
    key = _normalize_app_key(app_key)
    if ami_resume_consumed(st, key):
        return False
    if insight_return_query_id(st) or _active_ami_return_query_param_keys(st):
        return True
    if st.session_state.get("_ami_insight_return_preserve"):
        return True
    return False


def reconcile_stale_page_navigation(st: Any, app_key: str) -> None:
    """Clear lingering page-forcing flags when AMI return is not actively steering."""
    if ami_return_navigation_active(st, app_key):
        return
    ss = st.session_state
    for flag in (
        "_navigate_to_page",
        "_skip_page_restore_for",
        "_suite_cloud_target_page",
        "ami_return_forced_page",
        "ami_return_force_active_page",
    ):
        ss.pop(flag, None)


def maybe_consume_ami_return_on_page_match(
    st: Any,
    app_key: str,
    *,
    current_page: str = "",
) -> bool:
    """Consume AMI return once the user is on the source page (even if insight card skipped)."""
    key = _normalize_app_key(app_key)
    if ami_resume_consumed(st, key):
        return False
    ret = _normalize_insight_page(str(st.session_state.get(SESSION_RETURN_PAGE_KEY) or ""))
    current = _normalize_insight_page(
        str(
            current_page
            or st.session_state.get("active_page")
            or st.session_state.get("main_sidebar_page")
            or ""
        )
    )
    if not ret or not current or ret != current:
        return False
    if not (
        ami_return_navigation_active(st, key)
        or st.session_state.get("_ami_insight_hydrate_source") in ("url", "cloud_saved_items")
    ):
        return False
    return consume_ami_return_resume(st, key)


def _should_apply_ami_return_navigation(st: Any, app_key: str, return_page: str) -> bool:
    """Whether AMI return may schedule _navigate_to_page (first return only)."""
    ss = st.session_state
    if ss.get("_suite_page_user_nav") or ss.get("_suite_user_owned_page"):
        return False
    if ami_resume_consumed(st, app_key):
        return False
    active = str(ss.get("active_page") or "").strip()
    ret = str(return_page or ss.get(SESSION_RETURN_PAGE_KEY) or "").strip()
    persisted = str(ss.get("_suite_last_persisted_page") or "").strip()
    owned = str(ss.get("_suite_user_owned_page") or "").strip()
    if owned and active and owned == active and ret and ret != active:
        return False
    if active and ret and active != ret and persisted and active == persisted:
        return False
    return True


def _clear_ami_return_query_params(st: Any) -> list[str]:
    """Remove AMI return query keys from the URL; returns keys cleared."""
    present = _active_ami_return_query_param_keys(st)
    if not present:
        return []
    cleared: list[str] = []
    try:
        qp = st.query_params
        if hasattr(qp, "from_dict"):
            try:
                remaining = {k: v for k, v in dict(qp).items() if k not in _AMI_RETURN_QP_KEYS}
            except Exception:
                remaining = {}
                for k, v in qp.items():
                    if k not in _AMI_RETURN_QP_KEYS:
                        remaining[k] = v
            qp.from_dict(remaining)
            cleared = list(present)
        else:
            for key in present:
                try:
                    del qp[key]
                    cleared.append(key)
                except Exception:
                    try:
                        qp.pop(key, None)
                        cleared.append(key)
                    except Exception:
                        pass
    except Exception:
        pass
    return cleared


def consume_ami_return_resume(st: Any, app_key: str) -> bool:
    """
    Mark AMI return resume as consumed after first hydrate+render on the source page.
    Clears lingering URL params and preserve flags so manual sidebar navigation wins.
    """
    key = _normalize_app_key(app_key)
    flag = _ami_resume_consumed_flag(key)
    if st.session_state.get(flag):
        return False
    st.session_state[flag] = True
    st.session_state["ami_resume_consumed"] = True
    st.session_state.pop("_ami_insight_return_preserve", None)
    st.session_state.pop("_suite_resume_insight_hydration_only", None)
    st.session_state.pop("_navigate_to_page", None)
    st.session_state.pop("_skip_page_restore_for", None)
    st.session_state.pop("_suite_cloud_target_page", None)
    st.session_state.pop("ami_return_forced_page", None)
    st.session_state.pop("ami_return_force_active_page", None)
    st.session_state["active_page_source"] = "manual_nav_allowed"
    st.session_state["manual_nav_after_ami_return"] = True
    _clear_ami_return_query_params(st)
    return True


def _record_insight_return_diagnostics(st: Any, *, phase: str, insight: dict[str, Any] | None = None) -> None:
    """?dev=1 trace for AMI return → source app insight card."""
    ss = st.session_state
    url_iid = insight_return_query_id(st)
    pending = insight if isinstance(insight, dict) else _pending_insight_valid(st)
    scope = insight_page_scope_decision(
        str(ss.get("_suite_persist_app_id") or pending.get("source_app") or "baseball"),
        str(ss.get("active_page") or ""),
        pending,
    ) if pending else {}
    ss["_ami_insight_return_phase"] = phase
    ss["insight_return_detected"] = bool(url_iid)
    ss["insight_source_page_raw"] = (
        pending.get("source_page") if pending else scope.get("source_page_raw")
    )
    ss["insight_source_page_normalized"] = scope.get("source_page_normalized")
    ss["current_page_normalized"] = scope.get("current_page_normalized")
    ss["should_render_insight_on_page"] = scope.get("should_render_insight_on_page")
    ss["render_skip_reason"] = scope.get("render_skip_reason")
    ss["hydrate_attempted"] = ss.get("_ami_insight_hydrate_attempted")
    ss["hydrate_success"] = ss.get("_ami_insight_hydrate_success")
    ss["hydrate_source"] = ss.get("_ami_insight_hydrate_source")
    ss["pending_insight_exists"] = bool(pending.get("conclusion") or pending.get("question"))
    ss["insight_card_rendered"] = bool(ss.get("_ami_insight_card_rendered"))
    app_key = str(ss.get("_suite_persist_app_id") or (pending or {}).get("source_app") or "baseball")
    consumed = ami_resume_consumed(st, app_key)
    url_params = _active_ami_return_query_param_keys(st)
    forced_page = str(ss.get("_navigate_to_page") or ss.get("ami_return_forced_page") or "")
    ss["ami_resume_consumed"] = consumed
    ss["ami_url_params_present"] = url_params
    ss["query_params_present"] = url_params
    ss["insight_return_preserve"] = bool(ss.get("_ami_insight_return_preserve"))
    ss["resume_target_page"] = str(ss.get(SESSION_RETURN_PAGE_KEY) or "")
    ss["ami_return_forced_page"] = forced_page or str(ss.get(SESSION_RETURN_PAGE_KEY) or "")
    ss["ami_return_force_active_page"] = bool(forced_page) and not consumed
    ss["page_forced_by_ami_return"] = bool(forced_page)
    ss["manual_nav_after_ami_return"] = bool(consumed and ss.get("_suite_page_user_nav"))
    ss["manual_nav_blocked_by_ami_return"] = bool(
        not consumed
        and (
            bool(forced_page)
            or bool(ss.get("_ami_insight_return_preserve"))
            or bool(url_params)
            or bool(_query_param(st, "suite_resume"))
        )
    )
    ss["manual_nav_blocked_by_resume"] = ss["manual_nav_blocked_by_ami_return"]
    ss["active_page_source"] = ss.get("active_page_source") or (
        "ami_return" if not consumed and (forced_page or url_params) else "session"
    )
    ss["final_page_after_sidebar_click"] = ss.get("final_page_after_sidebar_click") or ss.get("active_page")


def _stage_insight_trace(
    st: Any,
    *,
    hydrate_attempted: bool = False,
    hydrate_success: bool = False,
    hydrate_source: str = "",
    insight: dict[str, Any] | None = None,
    loaded_from_cloud: bool = False,
    loaded_from_url: bool = False,
) -> None:
    if hydrate_attempted:
        st.session_state["_ami_insight_hydrate_attempted"] = True
    if hydrate_success:
        st.session_state["_ami_insight_hydrate_success"] = True
    if hydrate_source:
        st.session_state["_ami_insight_hydrate_source"] = hydrate_source
    if loaded_from_cloud:
        st.session_state["_ami_insight_loaded_from_cloud"] = True
    if loaded_from_url:
        st.session_state["_ami_insight_loaded_from_url"] = True
    if isinstance(insight, dict):
        st.session_state["_ami_insight_active_id"] = insight.get("insight_id") or ""
        st.session_state["_ami_insight_active_question_id"] = insight.get("question_id") or ""
    _record_insight_return_diagnostics(st, phase="trace", insight=insight)


def load_latest_applied_math_insight_for_app(
    source_app: str,
    *,
    exclude_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Most recent cloud-stored insight for a source app (cross-device)."""
    app = str(source_app or "").strip().lower()
    if not app:
        return {}
    excluded = exclude_ids or set()
    try:
        from suite_account import load_saved_items

        for app_key in (app, "applied_intelligence"):
            rows = load_saved_items(app=app_key, item_type=INSIGHT_ITEM_TYPE, limit=30)
            for row in rows:
                iid = str(row.get("item_key") or "").strip()
                if not iid or iid in excluded:
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                if str(payload.get("source_app") or "").strip().lower() not in ("", app):
                    if app_key != app:
                        continue
                if payload.get("conclusion") or payload.get("question"):
                    out = dict(payload)
                    out.setdefault("insight_id", iid)
                    return out
    except Exception as exc:
        log.warning("load_latest_applied_math_insight_for_app failed: %s", exc)
    return {}


def _pending_insight_valid(st: Any) -> dict[str, Any]:
    pending = st.session_state.get(SESSION_PENDING_KEY)
    if not isinstance(pending, dict):
        return {}
    iid = str(pending.get("insight_id") or "").strip()
    if iid and _insight_is_dismissed(st, iid):
        st.session_state.pop(SESSION_PENDING_KEY, None)
        return {}
    if pending.get("conclusion") or pending.get("question"):
        return pending
    return {}


def hydrate_applied_math_insight_for_session(st: Any, app_key: str) -> bool:
    """
    Load pending insight for this session from URL, workspace blob, or cloud store.

    Call before rendering the insight card on every rerun so cross-device refresh
    shows the same insight without requiring the return URL.
    """
    key = _normalize_app_key(app_key)
    reconcile_stale_page_navigation(st, key)
    sync_dismissed_insights_from_cloud(st, key)
    st.session_state["_ami_insight_hydrate_attempted"] = True
    url_iid = insight_return_query_id(st)
    if url_iid and _insight_is_dismissed(st, url_iid):
        _clear_ami_return_query_params(st)
        _record_insight_return_diagnostics(st, phase="hydrate_url_dismissed")
        url_iid = ""
    if url_iid:
        if ami_resume_consumed(st, key):
            pending = _pending_insight_valid(st)
            if pending:
                _stage_insight_trace(
                    st,
                    hydrate_success=True,
                    hydrate_source="session_consumed",
                    insight=pending,
                )
                _record_insight_return_diagnostics(st, phase="hydrate_url_consumed", insight=pending)
                return True
        else:
            pending = st.session_state.get(SESSION_PENDING_KEY)
            pending_iid = (
                str(pending.get("insight_id") or "").strip() if isinstance(pending, dict) else ""
            )
            force = not _pending_insight_valid(st) or (pending_iid and pending_iid != url_iid)
            if apply_ami_insight_from_query(st, key, force=force):
                pending = _pending_insight_valid(st)
                if pending:
                    _stage_insight_trace(
                        st,
                        hydrate_success=True,
                        hydrate_source="url",
                        insight=pending,
                        loaded_from_url=True,
                    )
                    st.session_state[SESSION_PERSIST_INSIGHT_DIRTY] = True
                    _record_insight_return_diagnostics(st, phase="hydrate_url", insight=pending)
                    return True

    pending = _pending_insight_valid(st)
    if pending:
        url_iid = insight_return_query_id(st)
        pending_iid = str(pending.get("insight_id") or "").strip()
        if url_iid and pending_iid and pending_iid != url_iid and not ami_resume_consumed(st, key):
            if apply_ami_insight_from_query(st, key, force=True):
                pending = _pending_insight_valid(st)
        _stage_insight_trace(
            st,
            hydrate_success=True,
            hydrate_source="session",
            insight=pending,
        )
        _record_insight_return_diagnostics(st, phase="hydrate_session", insight=pending)
        return True

    dismissed = _get_dismissed_insight_ids(st)
    latest = load_latest_applied_math_insight_for_app(key, exclude_ids=dismissed)
    if not latest:
        st.session_state["_ami_insight_hydrate_success"] = False
        st.session_state["_ami_insight_hydrate_source"] = "none"
        _record_insight_return_diagnostics(st, phase="hydrate_none")
        return False

    iid = str(latest.get("insight_id") or "").strip()
    st.session_state[SESSION_PENDING_KEY] = latest
    st.session_state[SESSION_RETURN_PAGE_KEY] = latest.get("source_page") or ""

    source_state = _resolve_return_source_state(
        st, key, latest, question_id_qp=_query_param(st, "suite_ai_question_id")
    )
    if isinstance(source_state, dict) and source_state:
        st.session_state[SESSION_RETURN_CONTEXT_KEY] = dict(source_state)
        # Cloud-only insight hydrate must not force page navigation (display-only).

    _stage_insight_trace(
        st,
        hydrate_success=True,
        hydrate_source="cloud_saved_items",
        insight=latest,
        loaded_from_cloud=True,
    )
    st.session_state["_ami_hydrated_insight_id"] = iid
    st.session_state[SESSION_PERSIST_INSIGHT_DIRTY] = True
    _record_insight_return_diagnostics(st, phase="hydrate_cloud", insight=latest)
    return True


def render_insight_sync_debug(st: Any) -> None:
    """Developer panel: insight hydration + render trace."""
    ss = st.session_state
    pending = ss.get(SESSION_PENDING_KEY) if isinstance(ss.get(SESSION_PENDING_KEY), dict) else {}
    cloud_exists = False
    try:
        latest = load_latest_applied_math_insight_for_app(
            str(ss.get("_suite_persist_app_id") or "baseball"),
            exclude_ids=set(),
        )
        cloud_exists = bool(latest.get("insight_id"))
    except Exception:
        cloud_exists = False

    cloud_rows = {
        "insight_id": pending.get("insight_id") or ss.get("_ami_insight_active_id"),
        "question_id": pending.get("question_id") or ss.get("_ami_insight_active_question_id"),
        "insight_exists_cloud": cloud_exists,
        "insight_loaded_from_cloud": ss.get("_ami_insight_loaded_from_cloud"),
        "insight_loaded_from_url": ss.get("_ami_insight_loaded_from_url"),
        "insight_timestamp": pending.get("created_at"),
    }
    local_rows = {
        "pending_insight": bool(pending.get("conclusion") or pending.get("question")),
        "active_insight": ss.get("_ami_insight_active_id"),
        "dismissed": ss.get(SESSION_DISMISSED_KEY),
        "last_loaded_insight_id": ss.get("_ami_hydrated_insight_id"),
    }
    scope = ss.get("_ami_insight_scope_decision")
    if not isinstance(scope, dict):
        scope = insight_page_scope_decision(
            str(ss.get("_suite_persist_app_id") or "baseball"),
            str(ss.get("active_page") or ""),
            pending,
        )
    decision_rows = {
        "insight_return_detected": ss.get("insight_return_detected"),
        "insight_source_page_raw": ss.get("insight_source_page_raw") or scope.get("source_page_raw"),
        "insight_source_page_normalized": ss.get("insight_source_page_normalized") or scope.get("source_page_normalized"),
        "current_page_normalized": ss.get("current_page_normalized") or scope.get("current_page_normalized"),
        "should_render_insight_on_page": ss.get("should_render_insight_on_page", scope.get("should_render_insight_on_page")),
        "render_skip_reason": ss.get("render_skip_reason") or scope.get("render_skip_reason"),
        "hydrate_attempted": ss.get("hydrate_attempted", ss.get("_ami_insight_hydrate_attempted")),
        "hydrate_success": ss.get("hydrate_success", ss.get("_ami_insight_hydrate_success")),
        "hydrate_source": ss.get("hydrate_source", ss.get("_ami_insight_hydrate_source")),
        "pending_insight_exists": ss.get("pending_insight_exists", bool(pending.get("conclusion"))),
        "insight_card_rendered": ss.get("insight_card_rendered", ss.get("_ami_insight_card_rendered")),
        "insight_return_phase": ss.get("_ami_insight_return_phase"),
        "insight_return_preserve": ss.get("insight_return_preserve", ss.get("_ami_insight_return_preserve")),
        "ami_resume_consumed": ss.get("ami_resume_consumed"),
        "ami_url_params_present": ss.get("ami_url_params_present", ss.get("query_params_present")),
        "query_params_present": ss.get("query_params_present"),
        "ami_return_forced_page": ss.get("ami_return_forced_page"),
        "ami_return_force_active_page": ss.get("ami_return_force_active_page"),
        "resume_target_page": ss.get("resume_target_page"),
        "page_forced_by_ami_return": ss.get("page_forced_by_ami_return"),
        "manual_nav_after_ami_return": ss.get("manual_nav_after_ami_return"),
        "manual_nav_blocked_by_ami_return": ss.get(
            "manual_nav_blocked_by_ami_return", ss.get("manual_nav_blocked_by_resume")
        ),
        "active_page_source": ss.get("active_page_source"),
        "final_page_after_sidebar_click": ss.get("final_page_after_sidebar_click"),
        "render_attempted": ss.get("_ami_insight_render_attempted"),
        "render_success": ss.get("_ami_insight_render_success"),
        "render_skipped_reason": ss.get("_ami_insight_render_skipped_reason"),
    }

    with st.sidebar.expander("Insight sync trace", expanded=True):
        st.caption("Applied Math insight — cloud-backed, cross-device.")
        st.markdown("**INSIGHT CLOUD**")
        for k, v in cloud_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        st.markdown("**INSIGHT LOCAL**")
        for k, v in local_rows.items():
            if v is not None and v != "" and v != []:
                st.text(f"{k}: {v}")
        st.markdown("**DECISION**")
        for k, v in decision_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        st.markdown("**FINAL**")
        st.text(f"final_page: {ss.get('active_page')}")
        st.text(f"final_has_insight_card: {bool(pending.get('conclusion'))}")


def _resolve_return_source_state(
    st: Any,
    app_key: str,
    insight: dict[str, Any],
    *,
    question_id_qp: str = "",
) -> dict[str, Any]:
    """Best-effort source_state from insight blob, return_context, or question send snapshot."""
    source_state = insight.get("source_state") or insight.get("return_context") or {}
    if isinstance(source_state, dict) and (
        source_state.get("source_page")
        or source_state.get("entity_params")
        or source_state.get("page_params")
        or "widget_params" in source_state
    ):
        return dict(source_state)
    qid = str(insight.get("question_id") or question_id_qp or "").strip()
    if qid:
        try:
            from suite_analytical_question import load_analytical_question_source_state

            loaded = load_analytical_question_source_state(qid)
            if loaded:
                return dict(loaded)
        except Exception:
            pass
    return dict(source_state) if isinstance(source_state, dict) else {}


def commit_ami_return_page_restore(st: Any, app_key: str) -> bool:
    """
    After page navigation is committed, re-apply source_state once so widgets
    pick up pending_compare_players / trend labels before render.
    Skipped once AMI return resume is consumed so manual sidebar nav wins.
    """
    key = _normalize_app_key(app_key)
    if ami_resume_consumed(st, key):
        return False
    flag = f"_ami_page_restore_committed_{key}"
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
    pending = st.session_state.get(SESSION_PENDING_KEY)
    if not iid and not isinstance(pending, dict):
        return False

    insight = dict(pending) if isinstance(pending, dict) else {}
    if iid and not insight.get("insight_id"):
        loaded = load_applied_math_insight(iid, source_app=app_key)
        if loaded:
            insight = loaded
            st.session_state[SESSION_PENDING_KEY] = insight

    source_state = st.session_state.get(SESSION_RETURN_CONTEXT_KEY)
    if not isinstance(source_state, dict) or not source_state:
        source_state = _resolve_return_source_state(
            st,
            app_key,
            insight,
            question_id_qp=_qp("suite_ai_question_id"),
        )
    if isinstance(source_state, dict) and source_state:
        st.session_state[SESSION_RETURN_CONTEXT_KEY] = dict(source_state)
        apply_return_source_state(st, app_key, source_state)
        st.session_state[flag] = True
        return True
    return False


def stage_pending_insight(st: Any, insight: AppliedMathInsight | dict[str, Any], *, return_context: dict[str, Any] | None = None) -> None:
    """Write insight into Streamlit session for AMI return button."""
    data = insight.to_dict() if isinstance(insight, AppliedMathInsight) else dict(insight)
    st.session_state[SESSION_PENDING_KEY] = data
    st.session_state[SESSION_RETURN_PAGE_KEY] = data.get("source_page") or ""
    if return_context:
        st.session_state[SESSION_RETURN_CONTEXT_KEY] = dict(return_context)


def apply_ami_insight_from_query(st: Any, app_key: str, *, force: bool = False) -> bool:
    """On source app load: hydrate pending insight from ?suite_ami_insight= (cloud-backed)."""
    iid = insight_return_query_id(st)
    if not iid:
        return False

    key = _normalize_app_key(app_key or "")
    st.session_state["insight_return_detected"] = True

    prev = str(st.session_state.get("_ami_hydrated_insight_id") or "").strip()
    pending = st.session_state.get(SESSION_PENDING_KEY)
    pending_iid = str(pending.get("insight_id") or "").strip() if isinstance(pending, dict) else ""
    if _insight_is_dismissed(st, iid):
        _clear_ami_return_query_params(st)
        _record_insight_return_diagnostics(st, phase="url_skip_dismissed", insight=pending if isinstance(pending, dict) else None)
        return False
    if ami_resume_consumed(st, key) and _pending_insight_valid(st):
        _record_insight_return_diagnostics(
            st,
            phase="url_skip_consumed",
            insight=pending if isinstance(pending, dict) else None,
        )
        return False
    if (
        not force
        and prev == iid
        and pending_iid == iid
        and _pending_insight_valid(st)
    ):
        _record_insight_return_diagnostics(st, phase="url_skip_already_loaded", insight=pending if isinstance(pending, dict) else None)
        return False

    st.session_state["_ami_insight_return_preserve"] = True

    insight = load_applied_math_insight(iid, source_app=app_key)
    if not insight:
        insight = {"insight_id": iid, "conclusion": "Applied Math insight loaded.", "question": ""}

    page = _normalize_insight_page(
        _query_param(st, "suite_page") or str(insight.get("source_page") or "")
    )
    if page:
        insight["source_page"] = page

    st.session_state[SESSION_PENDING_KEY] = insight
    st.session_state[SESSION_RETURN_PAGE_KEY] = page or insight.get("source_page") or ""

    source_state = _resolve_return_source_state(
        st,
        app_key,
        insight if isinstance(insight, dict) else {},
        question_id_qp=_query_param(st, "suite_ai_question_id"),
    )

    if isinstance(source_state, dict) and source_state:
        if page and not source_state.get("source_page"):
            source_state["source_page"] = page
        st.session_state[SESSION_RETURN_CONTEXT_KEY] = dict(source_state)
        apply_return_source_state(st, app_key, source_state)
    elif st.session_state.get(SESSION_RETURN_PAGE_KEY):
        ret_page = st.session_state[SESSION_RETURN_PAGE_KEY]
        if _should_apply_ami_return_navigation(st, key, ret_page):
            st.session_state["_navigate_to_page"] = ret_page
            st.session_state["_skip_page_restore_for"] = ret_page
            st.session_state["ami_return_forced_page"] = ret_page
            st.session_state["ami_return_force_active_page"] = True
            st.session_state["active_page_source"] = "ami_return_query"
        else:
            st.session_state.pop("_navigate_to_page", None)
            st.session_state.pop("ami_return_force_active_page", None)

    st.session_state["_ami_hydrated_insight_id"] = iid
    st.session_state[SESSION_PERSIST_INSIGHT_DIRTY] = True
    _stage_insight_trace(
        st,
        hydrate_success=True,
        hydrate_source="url",
        insight=insight if isinstance(insight, dict) else {},
        loaded_from_url=True,
    )
    _record_insight_return_diagnostics(st, phase="url_applied", insight=insight)
    return True


def dismiss_applied_math_insight(st: Any, *, app_key: str = "") -> None:
    """Dismiss insight locally and persist dismissal for cross-device sync."""
    pending = st.session_state.get(SESSION_PENDING_KEY)
    iid = ""
    if isinstance(pending, dict):
        iid = str(pending.get("insight_id") or "").strip()
    source_app = _normalize_app_key(
        app_key or (pending.get("source_app") if isinstance(pending, dict) else "") or st.session_state.get("_suite_persist_app_id") or "baseball"
    )
    dismissed_at = datetime.now(timezone.utc).isoformat()
    clear_pending_insight(st)
    if iid:
        dismissed = _get_dismissed_insight_ids(st)
        dismissed.add(iid)
        st.session_state[SESSION_DISMISSED_KEY] = sorted(dismissed)
        meta = dict(st.session_state.get(SESSION_DISMISSED_AT_KEY) or {})
        if not isinstance(meta, dict):
            meta = {}
        meta[iid] = dismissed_at
        st.session_state[SESSION_DISMISSED_AT_KEY] = meta
        persist_insight_dismissal_to_cloud(source_app, iid, dismissed_at=dismissed_at)
    st.session_state[SESSION_PERSIST_INSIGHT_DIRTY] = True


def clear_pending_insight(st: Any) -> None:
    st.session_state.pop(SESSION_PENDING_KEY, None)
    st.session_state.pop(SESSION_RETURN_PAGE_KEY, None)
    st.session_state.pop(SESSION_RETURN_CONTEXT_KEY, None)


def render_applied_math_insight_panel(st: Any) -> bool:
    """Display-only insight card on source app pages. Returns True if rendered."""
    insight = _pending_insight_valid(st)
    if not insight or not insight.get("conclusion"):
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
                dismiss_applied_math_insight(st)
                st.rerun()
    return True


def render_suite_applied_math_insight_for_page(
    st: Any,
    *,
    source_app: str,
    source_page: str,
) -> bool:
    """Render insight card when pending insight matches this page (source apps)."""
    st.session_state["_ami_insight_render_attempted"] = True
    maybe_consume_ami_return_on_page_match(st, source_app, current_page=source_page)
    insight = _pending_insight_valid(st)
    if not insight:
        st.session_state["_ami_insight_render_skipped_reason"] = "no pending insight"
        st.session_state["_ami_insight_render_success"] = False
        return False
    scope = insight_page_scope_decision(source_app, source_page, insight)
    st.session_state["_ami_insight_scope_decision"] = scope
    _record_insight_return_diagnostics(st, phase="render_check", insight=insight)
    if not scope.get("should_render_insight_on_page"):
        st.session_state["_ami_insight_render_skipped_reason"] = (
            scope.get("render_skip_reason")
            or f"page mismatch (current={source_page!r}, insight={insight.get('source_page')!r})"
        )
        st.session_state["_ami_insight_render_success"] = False
        st.session_state["_ami_insight_card_rendered"] = False
        return False
    ok = render_applied_math_insight_panel(st)
    st.session_state["_ami_insight_render_success"] = ok
    st.session_state["_ami_insight_card_rendered"] = ok
    if not ok:
        st.session_state["_ami_insight_render_skipped_reason"] = "panel render failed"
    else:
        st.session_state.pop("_ami_insight_render_skipped_reason", None)
        consume_ami_return_resume(
            st,
            str(st.session_state.get("_suite_persist_app_id") or source_app or "baseball"),
        )
    _record_insight_return_diagnostics(st, phase="render_done", insight=insight)
    return ok


def render_return_to_source_button(
    st: Any,
    insight: AppliedMathInsight | dict[str, Any],
    *,
    resume_key: str = "",
    return_context: dict[str, Any] | None = None,
    source_state: dict[str, Any] | None = None,
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

    ss = dict(source_state or {})
    if not ss:
        try:
            ss = dict(st.session_state.get("_suite_ai_source_state") or {})
        except Exception:
            ss = {}
    if not ss and return_context and isinstance(return_context.get("widget_params"), dict):
        ss = dict(return_context)
    if not ss and return_context:
        page = _normalize_insight_page(
            str(data.get("source_page") or return_context.get("page") or "")
        )
        ent: dict[str, Any] = {
            k: v
            for k, v in return_context.items()
            if k in ("player_a", "player_b", "player", "team", "opponent", "holdings", "compare_players")
        }
        if page == "Comparison Tool":
            if ent.get("player_a") and not ent.get("player_a_label"):
                ent["player_a_label"] = ent["player_a"]
            if ent.get("player_b") and not ent.get("player_b_label"):
                ent["player_b_label"] = ent["player_b"]
        ss = {
            "source_app": app,
            "source_page": page,
            "entity_params": ent,
            "widget_params": dict(return_context.get("widget_params") or {}),
            "page_params": {"page": page},
        }
    qid = str(data.get("question_id") or "").strip()
    if qid and not ss:
        try:
            from suite_analytical_question import load_analytical_question_source_state

            ss = load_analytical_question_source_state(qid)
        except Exception:
            pass

    blob_data = dict(data)
    page = _normalize_insight_page(str(data.get("source_page") or ss.get("source_page") or ""))
    if page:
        blob_data["source_page"] = page
        if ss and not ss.get("source_page"):
            ss["source_page"] = page
    if ss:
        blob_data["source_state"] = ss
        blob_data["return_context"] = ss

    rk = str(resume_key or build_return_resume_key(blob_data, source_state=ss) or "").strip()
    store_applied_math_insight(blob_data, return_context=ss or return_context, source_state=ss)
    url = build_source_app_return_url(
        blob_data,
        resume_key=rk,
        metrics=metrics_for_source_app_return({**blob_data, "source_state": ss, "return_context": ss or {}}),
    )
    if not url:
        st.caption(f"Return link unavailable for {label}.")
        return

    st.link_button(
        f"Return to {label} with insight →",
        url,
        use_container_width=True,
        help="Restores your page context and shows this conclusion in the source app — display only, no auto-changes.",
    )
