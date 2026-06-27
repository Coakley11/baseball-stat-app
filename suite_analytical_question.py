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
import copy
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

from activity_time import parse_activity_timestamp, utc_now_iso

log = logging.getLogger(__name__)

AMI_SIDEBAR_DEPLOY_LABEL = "Applied Math question sender live"
AMI_SIDEBAR_DEPLOY_VERSION = "2026-06-23-baseball-insight-label-v2"
AMI_SIDEBAR_RENDER_MODULE = "suite_analytical_question.render_analyze_with_applied_math_sidebar"
_CTX_JSON_SUBTITLE_LIMIT = 8000
_CONTEXT_ITEM_TYPE = "analytical_question_context"
ANALYTICAL_QUESTION_CONTINUE_PRIORITY = 64
ANALYTICAL_QUESTION_BUTTON_LABEL = "Continue in Applied Mathematics →"
BASEBALL_INSIGHT_BUTTON_LABEL = "⚾ Baseball Insight"
BASEBALL_INSIGHT_SECTION_TITLE = "Baseball Insight"
_SEND_COOLDOWN_SECONDS = 120

_SOURCE_AREA: dict[str, str] = {
    "baseball": "sports",
    "nba": "sports",
    "investment": "forecasting",
    "music": "music",
}

_SOURCE_LABELS: dict[str, str] = {
    "baseball": "Baseball",
    "nba": "NBA",
    "investment": "Investment",
    "music": "Music",
}

_SOURCE_APP_ID_ALIASES: dict[str, str] = {
    "music": "music",
    "music practice coach": "music",
    "music coach": "music",
    "music practice": "music",
    "baseball": "baseball",
    "baseball stat app": "baseball",
    "nba": "nba",
    "nba playoff companion": "nba",
    "investment": "investment",
    "investment portfolio analyzer": "investment",
}


def normalize_source_app_id(
    source_app: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Map display labels and context values to canonical suite app ids."""
    raw = str(source_app or "").strip().lower()
    if raw in _SOURCE_APP_ID_ALIASES:
        return _SOURCE_APP_ID_ALIASES[raw]
    if raw in _SOURCE_LABELS:
        return raw
    if context and isinstance(context, dict):
        ctx_raw = str(context.get("source_app") or "").strip().lower()
        if ctx_raw in _SOURCE_APP_ID_ALIASES:
            return _SOURCE_APP_ID_ALIASES[ctx_raw]
        if ctx_raw in _SOURCE_LABELS:
            return ctx_raw
        if "music" in ctx_raw and "math" not in ctx_raw:
            return "music"
    if "music" in raw and "math" not in raw:
        return "music"
    return raw

_MUSIC_COACH_PLACEHOLDERS: dict[str, str] = {
    "practice": "e.g. How should I practice this song?",
    "backing": "e.g. How do I use Backing Track Studio?",
    "custom": "e.g. What scale works over this progression?",
    "karaoke": "e.g. How do I use Karaoke mode?",
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
    "trend_summary",
    "trend_window",
    "comparison_stats",
    "comparison_differences",
    "stat_gap",
    "player",
    "draft_projection",
    "historical_snapshot",
    "table_summary",
    "filters_applied",
    "sharpe_ratio",
    "max_drawdown",
    "risk_level",
    "rebalance_drift",
    "target_weights",
    "current_weights",
    "macro_outlook",
    "model_assumptions",
    "experience_mode",
    "games_remaining",
    "rate_needed",
    "matchup_advantages",
    "injury_summary",
    "key_players",
    "series_record",
    "rebalance_recommendation",
    "total_drift",
    "historical_comparison",
    "draft_snapshot",
    "roster",
    "recommended_players",
    "sleepers",
    "scoring_settings",
    "ami_guidance",
    "projection",
    "watchlist",
    "hof_case_summary",
    "cohort_selectivity",
    "primary_position",
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
    "trend_summary": "Trend summary",
    "trend_window": "Trend window",
    "comparison_stats": "Comparison stats",
    "comparison_differences": "Key differences",
    "stat_gap": "Stat gap",
    "draft_projection": "Draft projection",
    "historical_snapshot": "Historical snapshot",
    "table_summary": "Table summary",
    "filters_applied": "Filters",
    "sharpe_ratio": "Sharpe ratio",
    "max_drawdown": "Max drawdown",
    "risk_level": "Risk level",
    "rebalance_drift": "Weight drift",
    "target_weights": "Target weights",
    "current_weights": "Current weights",
    "macro_outlook": "Macro outlook",
    "model_assumptions": "Model assumptions",
    "experience_mode": "Experience mode",
    "games_remaining": "Games remaining",
    "rate_needed": "Rate needed",
    "matchup_advantages": "Matchup advantages",
    "injury_summary": "Injury summary",
    "key_players": "Key players",
    "series_record": "Series record",
    "rebalance_recommendation": "Rebalance recommendation",
    "total_drift": "Total drift",
    "historical_comparison": "Historical comparison",
    "hof_case_summary": "Hall of Fame case",
    "cohort_selectivity": "Cohort selectivity",
    "primary_position": "Primary position",
}


def default_area_for_source(source_app: str) -> str:
    return _SOURCE_AREA.get(str(source_app or "").strip(), "abstract")


def source_app_label(source_app: str) -> str:
    key = str(source_app or "").strip().lower()
    if key == "music":
        return "Music Practice Coach"
    return _SOURCE_LABELS.get(key, key.replace("_", " ").title())


def infer_runtime_suite_app_id(session: dict[str, Any] | None = None) -> str:
    """Suite app id set by hosting app entrypoint (e.g. streamlit_app.py)."""
    ss = session or {}
    explicit = str(ss.get("_suite_runtime_app_id") or "").strip()
    if explicit:
        return normalize_source_app_id(explicit)
    return ""


def resolve_ami_sidebar_app_id(
    source_app: str,
    session: dict[str, Any] | None = None,
) -> str:
    """Canonical app id for AMI sidebar labels — prefers explicit baseball runtime."""
    passed = normalize_source_app_id(source_app)
    runtime = infer_runtime_suite_app_id(session)
    if passed == "baseball" or runtime == "baseball":
        return "baseball"
    if passed:
        return passed
    return runtime


def ami_sidebar_submit_label(
    source_app: str,
    session: dict[str, Any] | None = None,
) -> str:
    """Primary sidebar button label — baseball uses Baseball Insight; routing unchanged."""
    app = resolve_ami_sidebar_app_id(source_app, session)
    if app == "music":
        return "Ask the Music Coach"
    if app == "nba":
        return "Get NBA Insight"
    if app == "baseball":
        return BASEBALL_INSIGHT_BUTTON_LABEL
    return "Send to Command Center"


def ami_sidebar_build_marker() -> str:
    """Git/build stamp for AMI sidebar debug."""
    try:
        from suite_deploy_marker import GIT_BRANCH, GIT_COMMIT_SHORT, SUITE_BUILD_LABEL

        return f"{SUITE_BUILD_LABEL} · commit `{GIT_COMMIT_SHORT}` · branch `{GIT_BRANCH}`"
    except ImportError:
        return "build marker unavailable"


def _ami_sidebar_debug_visible(st: Any, session_state: dict[str, Any]) -> bool:
    """True only when the Developer Mode sidebar checkbox is on."""
    if session_state.get("dev_mode"):
        return True
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        return developer_mode_checkbox_enabled(st=st)
    except ImportError:
        return bool(session_state.get("app_developer_mode"))


def render_ami_sidebar_submit_debug(
    st: Any,
    *,
    source_app_raw: str,
    source_app_resolved: str,
    submit_label: str,
    session_state: dict[str, Any],
) -> None:
    """Dev-only marker beside the AMI submit button."""
    if not _ami_sidebar_debug_visible(st, session_state):
        return
    st.sidebar.caption(
        "🛠 **AMI submit debug** · "
        f"module `{AMI_SIDEBAR_RENDER_MODULE}` · "
        f"source_app={source_app_raw!r} → {source_app_resolved!r} · "
        f"label={submit_label!r} · "
        f"{AMI_SIDEBAR_DEPLOY_VERSION} · {ami_sidebar_build_marker()}"
    )


def source_question_card_title(
    source_app: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Normalized Continue / activity title for cross-app questions."""
    app = normalize_source_app_id(source_app, context)
    if app == "music":
        return "Music Coach question from Music"
    label = _SOURCE_LABELS.get(app, app.replace("_", " ").title())
    if app in {"baseball", "nba", "investment"}:
        return f"Applied Math question from {label}"
    return f"Question from {label}"


def music_coach_question_placeholder(source_page: str) -> str:
    page = str(source_page or "").strip().lower()
    return _MUSIC_COACH_PLACEHOLDERS.get(
        page,
        "e.g. What notes are in C minor?",
    )


NBA_INSIGHT_EXAMPLE_QUESTIONS: tuple[str, ...] = (
    "Is the Knicks' fourth-quarter scoring trend meaningful?",
    "Which player matchup matters most tonight?",
    "Is this playoff series shifting momentum?",
    "Are the Knicks relying too much on Brunson?",
    "What is the biggest risk for this team tonight?",
    "Which lineup has the best advantage?",
)


def nba_insight_question_placeholder(source_page: str) -> str:
    _ = source_page
    return f"e.g. {NBA_INSIGHT_EXAMPLE_QUESTIONS[0]}"


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


def merge_analytical_context(base: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
    """Deep-merge page extractor output into base context."""
    out = dict(base or {})
    for key, val in dict(extra or {}).items():
        if val is None or val == "":
            continue
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            merged = dict(out[key])
            merged.update(val)
            out[key] = merged
        else:
            out[key] = val
    return out


def _parse_context_from_resume_subtitle(subtitle: str) -> dict[str, Any]:
    text = str(subtitle or "")
    if "__ctx_json__:" not in text:
        return {}
    _, _, blob = text.partition("\n__ctx_json__:")
    try:
        raw = json.loads(blob.strip())
        return raw if isinstance(raw, dict) else {}
    except json.JSONDecodeError:
        return {}


def _hof_case_player_name(payload: dict[str, Any]) -> str:
    ctx = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    packet = ctx.get("hof_case_packet") if isinstance(ctx.get("hof_case_packet"), dict) else {}
    if not isinstance(packet, dict) or not packet:
        top = payload.get("hof_case_packet")
        packet = top if isinstance(top, dict) else {}
    for candidate in (payload.get("player"), payload.get("target_player"), ctx.get("player"), packet.get("target_player")):
        name = str(candidate or "").strip()
        if name:
            return name
    return ""


def _store_question_context_blob(payload: dict[str, Any]) -> None:
    """Persist full context server-side keyed by question_id (survives URL truncation)."""
    qid = str(payload.get("question_id") or "").strip()
    if not qid:
        return
    ctx = dict(payload.get("context") or {})
    hof_case = _is_hof_case_submission(str(payload.get("quant_area") or ""), ctx)
    blob = {
        "question": payload.get("question"),
        "question_id": qid,
        "source_app": payload.get("source_app"),
        "source_page": payload.get("source_page"),
        "quant_area": payload.get("quant_area"),
        "context": ctx,
        "source_state": dict(payload.get("source_state") or {}),
        "action_url": str(payload.get("action_url") or "").strip(),
        "blob_type": "baseball_hof_case" if hof_case else "analytical_question",
        "app_context_type": str(payload.get("app_context_type") or ("baseball_hof_case" if hof_case else "")).strip(),
    }
    if hof_case:
        player = _hof_case_player_name(payload)
        if player:
            blob["player"] = player
        packet = ctx.get("hof_case_packet")
        if not isinstance(packet, dict) or not packet:
            packet = payload.get("hof_case_packet")
        if isinstance(packet, dict) and packet:
            blob["hof_case_packet"] = copy.deepcopy(packet)
        for extra_key in (
            "context_type",
            "ami_source_app",
            "ami_source_page",
            "hof_ami_audit",
            "target_player",
            "target_player_name",
            "player_id",
            "resume_key",
            "workspace_snapshot_present",
            "workspace_snapshot_ref",
            "verdict_context",
        ):
            if extra_key in payload and payload[extra_key] not in (None, "", {}):
                blob[extra_key] = copy.deepcopy(payload[extra_key])
    if isinstance(payload.get("workspace_snapshot"), dict) and payload.get("workspace_snapshot"):
        blob["workspace_snapshot"] = dict(payload["workspace_snapshot"])
    if isinstance(payload.get("insight"), dict) and payload.get("insight"):
        blob["insight"] = dict(payload["insight"])
    try:
        from suite_account import remember_saved_item

        store_apps: list[str] = ["applied_intelligence"]
        src_app = str(payload.get("source_app") or "").strip().lower()
        if src_app and src_app not in store_apps:
            store_apps.append(src_app)
        for app_name in store_apps:
            remember_saved_item(
                app_name,
                _CONTEXT_ITEM_TYPE,
                qid,
                title=str(payload.get("question") or "Applied Math question")[:200],
                payload=blob,
            )
        return
    except Exception as exc:
        log.warning("remember_saved_item failed for analytical context: %s", exc)


def persist_question_context_blob(payload: dict[str, Any]) -> None:
    """Public wrapper: persist question send snapshot (context + source_state) by question_id."""
    _store_question_context_blob(payload)


def load_analytical_question_context(question_id: str) -> dict[str, Any]:
    """Load full context blob by question_id from saved items or resume subtitle."""
    return load_analytical_question_payload(question_id).get("context") or {}


_CONTEXT_SEARCH_APPS = ("applied_intelligence", "baseball", "baseball_analytics")
_HOF_RESUME_ITEM_TYPE = "hof_case_resume"


def _payload_from_saved_row(row: dict[str, Any], *, load_source: str) -> dict[str, Any]:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return {}
    out = copy.deepcopy(payload)
    out["blob_load_source"] = load_source
    out["blob_store_app"] = str(row.get("storage_app") or row.get("app") or "")
    return out


def _hof_resume_bundle_to_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    packet = bundle.get("hof_case_packet") if isinstance(bundle.get("hof_case_packet"), dict) else {}
    target = str(bundle.get("target_player") or packet.get("target_player") or "").strip()
    ctx = {
        "hof_case_packet": copy.deepcopy(packet),
        "player": target,
        "app_context_type": "baseball_hof_case",
        "routing_hint": "hof_case_analysis",
        "intent": "hof_case_analysis",
    }
    insight = bundle.get("insight") if isinstance(bundle.get("insight"), dict) else {}
    return {
        "question_id": str(bundle.get("question_id") or "").strip(),
        "question": str(packet.get("hof_case_summary") or f"Hall of Fame case — {target}").strip(),
        "source_app": "baseball",
        "source_page": "Career Totals",
        "quant_area": "hall_of_fame_case",
        "app_context_type": "baseball_hof_case",
        "context": ctx,
        "hof_case_packet": copy.deepcopy(packet),
        "player": target,
        "target_player": target,
        "source_state": copy.deepcopy(bundle.get("source_state") or {}),
        "insight": copy.deepcopy(insight) if insight else {},
        "blob_load_source": "hof_case_resume_bundle",
    }


def _load_hof_resume_bundle_fallback(
    question_id: str,
    *,
    hof_target_slug: str = "",
) -> dict[str, Any]:
    qid = str(question_id or "").strip()
    if not qid:
        return {}
    try:
        from suite_account import fetch_saved_item, load_saved_items
    except ImportError:
        return {}

    slug = str(hof_target_slug or "").strip().lower()
    if slug:
        row = fetch_saved_item("baseball", _HOF_RESUME_ITEM_TYPE, f"bb:hof_case:{slug}")
        if row:
            bundle = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            if isinstance(bundle, dict) and str(bundle.get("question_id") or qid) == qid:
                return _hof_resume_bundle_to_payload(bundle)

    for row in load_saved_items(app="baseball", item_type=_HOF_RESUME_ITEM_TYPE, limit=120):
        bundle = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if isinstance(bundle, dict) and str(bundle.get("question_id") or "") == qid:
            return _hof_resume_bundle_to_payload(bundle)
    return {}


def load_analytical_question_payload(
    question_id: str,
    *,
    hof_target_slug: str = "",
) -> dict[str, Any]:
    """Load full question blob (context + source_state) by question_id."""
    qid = str(question_id or "").strip()
    if not qid:
        return {}
    load_attempts: list[str] = []
    resume_key = f"ai:question:{qid}"
    hof_resume_key = f"hof:ami:{qid}"

    try:
        from suite_account import fetch_saved_item, fetch_saved_item_any_app

        for app_name in _CONTEXT_SEARCH_APPS:
            load_attempts.append(f"saved_item:{app_name}")
            row = fetch_saved_item(app_name, _CONTEXT_ITEM_TYPE, qid)
            if row:
                payload = _payload_from_saved_row(row, load_source=f"saved_item:{app_name}")
                payload["blob_load_candidates"] = load_attempts
                return payload
        load_attempts.append("saved_item:any_app")
        row = fetch_saved_item_any_app(_CONTEXT_ITEM_TYPE, qid)
        if row:
            payload = _payload_from_saved_row(row, load_source="saved_item:any_app")
            payload["blob_load_candidates"] = load_attempts
            return payload
    except Exception as exc:
        log.warning("direct saved-item lookup failed for question context: %s", exc)

    bundle_payload = _load_hof_resume_bundle_fallback(qid, hof_target_slug=hof_target_slug)
    if bundle_payload:
        bundle_payload["blob_load_candidates"] = load_attempts + ["hof_case_resume_bundle"]
        return bundle_payload

    try:
        from suite_account import load_saved_items

        for app_name in _CONTEXT_SEARCH_APPS:
            load_attempts.append(f"scan:{app_name}")
            rows = load_saved_items(app=app_name, item_type=_CONTEXT_ITEM_TYPE, limit=200)
            for row in rows:
                if str(row.get("item_key") or "") == qid:
                    payload = row.get("payload")
                    if isinstance(payload, dict):
                        out = copy.deepcopy(payload)
                        out["blob_load_source"] = f"scan:{app_name}"
                        out["blob_load_candidates"] = load_attempts
                        return out
    except Exception as exc:
        log.warning("load_saved_items scan failed for question context: %s", exc)

    try:
        from suite_storage_supabase import load_active_resume_items

        for app_filter in ("applied_intelligence", "baseball", None):
            load_attempts.append(f"resume:{app_filter or 'any'}")
            rows = load_active_resume_items(limit=40, app=app_filter)
            for row in rows:
                item_key = str(row.get("item_key") or "")
                if item_key not in (resume_key, hof_resume_key):
                    continue
                ctx = _parse_context_from_resume_subtitle(str(row.get("subtitle") or ""))
                if ctx:
                    return {
                        "context": ctx,
                        "question_id": qid,
                        "blob_load_source": f"resume_subtitle:{item_key}",
                        "blob_load_candidates": load_attempts,
                    }
    except Exception:
        pass

    return {"blob_load_candidates": load_attempts, "question_id": qid}


def load_analytical_question_source_state(question_id: str) -> dict[str, Any]:
    """Load page-restore snapshot saved at question send time."""
    payload = load_analytical_question_payload(question_id)
    ss = payload.get("source_state")
    return dict(ss) if isinstance(ss, dict) else {}


def hydrate_applied_intelligence_session(st: Any, *, metrics: dict[str, Any] | None = None) -> None:
    """Map URL params / resume metrics into Applied Intelligence session keys."""
    ss = st.session_state

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

    m = dict(metrics or {})
    question = str(m.get("question") or _qp("suite_ai_question") or "").strip()
    qid = str(m.get("question_id") or m.get("dedupe_fingerprint") or _qp("suite_ai_question_id") or "").strip()
    source_app = str(m.get("source_app") or _qp("suite_ai_source_app") or "").strip()
    source_page = str(m.get("source_page") or _qp("suite_ai_source_page") or "").strip()
    area = str(m.get("quant_area") or m.get("area") or _qp("suite_ai_area") or "").strip()
    page = str(m.get("page") or _qp("suite_page") or "Solve a Problem").strip()

    ctx: dict[str, Any] = {}
    source_state: dict[str, Any] = {}
    hydrate_source = "none"
    blob_payload: dict[str, Any] = {}

    # Blob-first: full context by question_id before metrics/URL (avoids truncated deep links).
    if qid:
        blob_payload = load_analytical_question_payload(qid, hof_target_slug=_qp("suite_hof_target"))
        blob_ctx = blob_payload.get("context") if isinstance(blob_payload.get("context"), dict) else {}
        if blob_ctx:
            ctx = copy.deepcopy(blob_ctx)
            hydrate_source = "question_id_blob"
        blob_ss = blob_payload.get("source_state") if isinstance(blob_payload.get("source_state"), dict) else {}
        if blob_ss:
            source_state = copy.deepcopy(blob_ss)
        if not area:
            area = str(blob_payload.get("quant_area") or "").strip()
        if not question:
            question = str(blob_payload.get("question") or "").strip()
        if not source_app:
            source_app = str(blob_payload.get("source_app") or "").strip()
        if not source_page:
            source_page = str(blob_payload.get("source_page") or "").strip()

    metrics_ctx: dict[str, Any] = {}
    if isinstance(m.get("context"), dict):
        metrics_ctx = copy.deepcopy(m["context"])
    elif m.get("context_json"):
        try:
            parsed = json.loads(str(m["context_json"]))
            if isinstance(parsed, dict):
                metrics_ctx = parsed
        except json.JSONDecodeError:
            pass
    if metrics_ctx:
        if not ctx:
            ctx = metrics_ctx
            hydrate_source = "metrics"
        else:
            for key, val in metrics_ctx.items():
                if key not in ctx or not ctx.get(key):
                    ctx[key] = val

    if not ctx:
        raw_ctx = _qp("suite_ai_context")
        if raw_ctx:
            try:
                parsed = json.loads(raw_ctx)
                if isinstance(parsed, dict):
                    ctx = parsed
                    hydrate_source = "url_query"
            except json.JSONDecodeError:
                pass

    if question:
        ss["_suite_ai_question"] = question
        ss["ps_library_problem"] = question
    if qid:
        ss["_suite_ai_question_id"] = qid
    if source_app:
        ss["_suite_ai_source_app"] = source_app
    if source_page:
        ss["_suite_ai_source_page"] = source_page
    if area:
        ss["_suite_ai_area"] = area
    if page:
        ss["_suite_ai_page"] = page
    if ctx:
        ss["_suite_ai_context"] = json.dumps(ctx, ensure_ascii=False)
    if source_state:
        ss["_suite_ai_source_state"] = copy.deepcopy(source_state)
    ss["_suite_ai_hydrate_source"] = hydrate_source
    url_params = {
        "suite_ai_question_id": qid or _qp("suite_ai_question_id"),
        "suite_ai_question": question or _qp("suite_ai_question"),
        "suite_ai_source_app": source_app or _qp("suite_ai_source_app"),
        "suite_ai_source_page": source_page or _qp("suite_ai_source_page"),
        "suite_ai_area": area or _qp("suite_ai_area"),
        "suite_page": page or _qp("suite_page"),
        "suite_hof_case": _qp("suite_hof_case"),
        "suite_hof_target": _qp("suite_hof_target"),
        "suite_ai_context_len": str(len(_qp("suite_ai_context") or "")),
    }

    is_hof = (
        area == "hall_of_fame_case"
        or str(blob_payload.get("app_context_type") or "").strip() == "baseball_hof_case"
        or str((ctx or {}).get("app_context_type") or "").strip() == "baseball_hof_case"
        or _qp("suite_hof_case") == "1"
        or str((ctx or {}).get("routing_hint") or "") == "hof_case_analysis"
        or str((ctx or {}).get("intent") or "") == "hof_case_analysis"
    )
    selected_renderer = "default_homepage"
    fallback_reason = ""
    packet_staged = False
    insight_staged = False

    if is_hof:
        ss["_suite_hof_case"] = True
        ss["_suite_ai_area"] = "hall_of_fame_case"
        ss["view_mode"] = "Solve a Problem"
        ss["_suite_ai_page"] = "Solve a Problem"
        selected_renderer = "hof_case_analysis"
        packet = blob_payload.get("hof_case_packet")
        if not isinstance(packet, dict):
            packet = ctx.get("hof_case_packet")
        if isinstance(packet, dict) and packet:
            ss["_hof_case_packet"] = copy.deepcopy(packet)
            packet_staged = True
        insight_blob = blob_payload.get("insight")
        if not isinstance(insight_blob, dict):
            insight_blob = ss.get("_hof_case_insight") if isinstance(ss.get("_hof_case_insight"), dict) else {}
        if isinstance(blob_payload.get("insight"), dict) and blob_payload.get("insight"):
            ss["_hof_case_insight"] = copy.deepcopy(blob_payload["insight"])
            insight_blob = blob_payload["insight"]
        verdict = blob_payload.get("verdict_context")
        if isinstance(verdict, dict) and verdict:
            ss["_hof_case_verdict"] = copy.deepcopy(verdict)
        target = str(
            blob_payload.get("target_player")
            or blob_payload.get("player")
            or (ctx or {}).get("player")
            or _qp("suite_hof_target")
            or ""
        ).strip()
        if target:
            ss["_suite_hof_target"] = target
        if isinstance(insight_blob, dict) and insight_blob.get("conclusion"):
            ss["_ami_pending_insight"] = copy.deepcopy(insight_blob)
            ss["_ami_force_insight_render"] = True
            ss["_ami_hydrated_insight_id"] = str(insight_blob.get("insight_id") or qid or "")
            insight_staged = True
        elif packet_staged:
            ss["_ami_force_insight_render"] = True
        if not packet_staged:
            fallback_reason = "hof_case_packet_missing_after_hydrate"
            selected_renderer = "hof_case_fallback_error"
        elif not insight_staged:
            fallback_reason = "hof_insight_missing_using_packet_only"
    elif qid and not (blob_payload.get("context") or blob_payload.get("hof_case_packet")):
        fallback_reason = "question_id_blob_not_found"
    elif not ctx:
        fallback_reason = "no_context_from_blob_url_or_metrics"

    ss["_suite_ai_selected_renderer"] = selected_renderer
    ss["_suite_ai_hydrate_diag"] = {
        "incoming_url_params": url_params,
        "question_id": qid,
        "suite_ai_question_id": qid,
        "hydrate_source": hydrate_source,
        "quant_area": area,
        "source_page": source_page,
        "source_app": source_app,
        "page": page,
        "blob_found": bool(blob_payload.get("context") or blob_payload.get("hof_case_packet")) if qid else False,
        "blob_keys": sorted(blob_payload.keys()) if isinstance(blob_payload, dict) else [],
        "blob_load_source": str(blob_payload.get("blob_load_source") or ""),
        "blob_store_app": str(blob_payload.get("blob_store_app") or ""),
        "blob_load_candidates": list(blob_payload.get("blob_load_candidates") or []),
        "context_keys": sorted(ctx.keys()) if isinstance(ctx, dict) else [],
        "hof_case_packet_present": packet_staged or isinstance((ctx or {}).get("hof_case_packet"), dict),
        "hof_case_packet_staged": packet_staged,
        "hof_insight_staged": insight_staged,
        "routing_hint": str((ctx or {}).get("routing_hint") or ""),
        "app_context_type": str(blob_payload.get("app_context_type") or (ctx or {}).get("app_context_type") or ""),
        "player": str((ctx or {}).get("player") or blob_payload.get("player") or ss.get("_suite_hof_target") or ""),
        "is_hof": bool(is_hof),
        "selected_renderer": selected_renderer,
        "fallback_reason": fallback_reason,
    }
    ss["_suite_ai_show_landing_diag"] = True


def _developer_tools_enabled(st: Any) -> bool:
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        return developer_mode_checkbox_enabled(st=st)
    except ImportError:
        return False


def render_applied_intelligence_landing_diagnostics(
    st: Any,
    *,
    expanded: bool | None = None,
    developer_mode: bool = False,
) -> None:
    """AMI landing diagnostics — developer mode only."""
    if not developer_mode:
        return
    ss = st.session_state
    diag = dict(ss.get("_suite_ai_hydrate_diag") or {})
    if not diag and not ss.get("_suite_ai_show_landing_diag"):
        return
    with st.expander("AMI landing diagnostics", expanded=False if expanded is None else bool(expanded)):
        st.caption("Handoff hydration status for Baseball → AMI deep links.")
        st.json(diag)
        if diag.get("fallback_reason"):
            st.error(f"Handoff fallback: {diag['fallback_reason']}")
        qid = str(diag.get("question_id") or "").strip()
        if qid and not diag.get("blob_found"):
            st.warning(
                f"No analytical_question_context blob found for question_id `{qid}`. "
                "Check cloud saved items for applied_intelligence and baseball apps."
            )


def render_hof_case_solve_problem_handoff(st: Any) -> bool:
    """Render Hall of Fame case analysis when hydrated from Baseball. Returns True if content shown."""
    ss = st.session_state
    packet = ss.get("_hof_case_packet")
    if not ss.get("_suite_hof_case"):
        if not (isinstance(packet, dict) and packet):
            return False
    verdict = ss.get("_hof_case_verdict")
    dev_mode = _developer_tools_enabled(st)

    if dev_mode:
        render_applied_intelligence_landing_diagnostics(st, developer_mode=True)

    if not isinstance(packet, dict) or not packet:
        st.error(
            "Hall of Fame case handoff failed: no `hof_case_packet` in session."
            + (" Enable Developer Mode for hydration diagnostics." if not dev_mode else "")
        )
        return False

    try:
        from hof_case_analysis import render_hof_case_full_analysis

        return render_hof_case_full_analysis(st, packet, verdict=verdict if isinstance(verdict, dict) else None)
    except ImportError:
        target = str(ss.get("_suite_hof_target") or packet.get("target_player") or "").strip()
        st.markdown(f"## Hall of Fame Case — {target}" if target else "## Hall of Fame Case Analysis")
        summary = str(packet.get("hof_case_summary") or "").strip()
        if summary:
            st.markdown(summary)
            return True
        return False


def render_applied_intelligence_handoff_page(st: Any) -> bool:
    """AMI Solve a Problem preamble — diagnostics + HOF case when present."""
    ss = st.session_state
    if ss.get("_suite_hof_case") or (isinstance(ss.get("_hof_case_packet"), dict) and ss.get("_hof_case_packet")):
        return render_hof_case_solve_problem_handoff(st)
    dev_mode = _developer_tools_enabled(st)
    if dev_mode and (ss.get("_suite_ai_show_landing_diag") or ss.get("_suite_ai_hydrate_diag")):
        render_applied_intelligence_landing_diagnostics(st, developer_mode=True)
    if ss.get("_suite_ai_hydrate_error"):
        st.error(f"AMI URL hydrate error: {ss['_suite_ai_hydrate_error']}")
    return False


def _format_context_value(key: str, val: Any) -> str:
    if key == "cohort_selectivity" and isinstance(val, dict):
        notes = val.get("threshold_notes") if isinstance(val.get("threshold_notes"), list) else []
        if notes:
            return "; ".join(str(n) for n in notes[:4])
        return str(val.get("selectivity") or "")
    if key == "trend_summary" and isinstance(val, dict):
        parts = []
        for sub, label in (
            ("stat", "metric"),
            ("direction", "direction"),
            ("slope", "slope"),
            ("r2", "R²"),
            ("delta", "change"),
            ("latest", "latest"),
            ("previous", "previous"),
            ("summary", "summary"),
        ):
            v = val.get(sub)
            if v is not None and str(v).strip() != "":
                parts.append(f"{label}={v}")
        return "; ".join(parts)
    if isinstance(val, dict):
        inner = ", ".join(f"{k}: {v}" for k, v in list(val.items())[:6] if v is not None and str(v).strip())
        return inner
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
    return lines[:16]


def _hof_case_card_subtitle(payload: dict[str, Any]) -> str:
    """Short cohort summary for Command Center cards — not the full model prompt."""
    ctx = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    packet = ctx.get("hof_case_packet") if isinstance(ctx.get("hof_case_packet"), dict) else {}
    if not packet:
        top = payload.get("hof_case_packet")
        packet = top if isinstance(top, dict) else {}
    summary = str(packet.get("hof_case_summary") or payload.get("context_summary") or "").strip()
    if summary:
        return summary
    player = _hof_case_player_name(payload)
    return f"Statistical case — {player}" if player else "Statistical case"


def analytical_question_continue_copy(payload: dict[str, Any]) -> tuple[str, str, str]:
    """Return (title, subtitle, button_label) for Command Center Continue cards."""
    ctx = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    app = normalize_source_app_id(str(payload.get("source_app") or ""), ctx)
    question = str(payload.get("question") or "").strip()
    if _is_hof_case_submission(str(payload.get("quant_area") or ""), ctx):
        player = _hof_case_player_name(payload)
        title = f"Open full Hall of Fame analysis — {player}" if player else "Open full Hall of Fame analysis"
        return (title, _hof_case_card_subtitle(payload), "Open analysis →")
    title = source_question_card_title(app, ctx)
    if app == "music":
        return (title, question, "Continue with Music Coach →")
    return (title, question, ANALYTICAL_QUESTION_BUTTON_LABEL)


def analytical_question_storage_subtitle(payload: dict[str, Any]) -> str:
    """Resume-item subtitle for storage/rebuild — question only on CC cards; context stays in metrics/URL."""
    if _is_hof_case_submission(str(payload.get("quant_area") or ""), dict(payload.get("context") or {})):
        return _hof_case_card_subtitle(payload)
    question = str(payload.get("question") or "").strip()
    ctx = dict(payload.get("context") or {})
    ctx_json = json.dumps(ctx, ensure_ascii=False) if ctx else ""
    if ctx_json:
        return f"{question}\n__ctx_json__:{ctx_json[:_CTX_JSON_SUBTITLE_LIMIT]}"
    return question


def metrics_for_applied_math_resume(payload: dict[str, Any]) -> dict[str, Any]:
    """Metrics bundle for deep links into Applied Intelligence."""
    ctx = dict(payload.get("context") or {})
    ctx_lines = format_context_lines(ctx)
    metrics = {
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
        "saved_item_type": _CONTEXT_ITEM_TYPE,
        "saved_item_key": payload.get("question_id"),
    }
    app_context_type = str(payload.get("app_context_type") or ctx.get("app_context_type") or "").strip()
    if app_context_type:
        metrics["app_context_type"] = app_context_type
    if _is_hof_case_submission(str(payload.get("quant_area") or ""), ctx):
        metrics["hof_case_mode"] = True
        metrics["activity_kind"] = "hof_case"
        metrics["exclude_from_recent_ami"] = True
        player = _hof_case_player_name(payload)
        if player:
            metrics["hof_case_target"] = player
            metrics["target_player"] = player
    try:
        from suite_workspace import get_active_workspace_id

        metrics["workspace_id"] = get_active_workspace_id()
    except ImportError:
        pass
    return metrics


def _upsert_applied_intelligence_resume(
    payload: dict[str, Any],
    *,
    action_url: str,
) -> None:
    title, _, _ = analytical_question_continue_copy(payload)
    subtitle = analytical_question_storage_subtitle(payload)
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
    source_state: dict[str, Any] | None = None,
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
        "source_state": dict(source_state or {}),
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
    metrics["source_app"] = normalize_source_app_id(
        str(payload.get("source_app") or ""),
        dict(payload.get("context") or {}),
    )
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


def _is_hof_case_submission(
    quant_area: str,
    context: dict[str, Any] | None,
) -> bool:
    if str(quant_area or "").strip() == "hall_of_fame_case":
        return True
    ctx = context if isinstance(context, dict) else {}
    return ctx.get("routing_hint") == "hof_case_analysis" or ctx.get("intent") == "hof_case_analysis"


HOF_CASE_ACTIVITY_EVENTS = frozenset({"hof_case_analysis_submitted"})


def should_exclude_from_recent_ami_questions(
    *,
    event: str = "",
    metrics: dict[str, Any] | None = None,
    resume_key: str = "",
    title: str = "",
    quant_area: str = "",
    app_context_type: str = "",
) -> bool:
    """True when an activity/resume row is a HOF statistical case, not a user-typed AMI question."""
    m = dict(metrics or {})
    if m.get("exclude_from_recent_ami") is True:
        return True
    if str(m.get("activity_kind") or "") == "hof_case":
        return True
    ctx = m.get("context") if isinstance(m.get("context"), dict) else {}
    actx = str(app_context_type or m.get("app_context_type") or ctx.get("app_context_type") or "").strip()
    if actx == "baseball_hof_case":
        return True
    qarea = str(quant_area or m.get("quant_area") or m.get("area") or "").strip()
    if qarea == "hall_of_fame_case":
        return True
    evt = str(event or m.get("event") or "").strip()
    if evt in HOF_CASE_ACTIVITY_EVENTS:
        return True
    rk = str(resume_key or m.get("resume_key") or "").strip()
    if rk.startswith("bb:hof_case:") or rk.startswith("hof:ami:"):
        return True
    if str(m.get("resume_key") or "").startswith("ai:question:") and _is_hof_case_submission(qarea, ctx):
        return True
    title_l = str(title or m.get("title") or m.get("summary") or "").strip().lower()
    if "hall of fame" in title_l and any(x in title_l for x in ("analysis", "case", "open full", "review")):
        return True
    if _is_hof_case_submission(qarea, ctx):
        return True
    return False


def load_recent_ami_questions(limit: int = 10) -> list[dict[str, Any]]:
    """Recent user-typed analytical_question events — excludes HOF statistical cases."""
    try:
        from suite_storage_supabase import load_events
    except ImportError:
        return []
    rows = load_events(limit=max(limit * 5, 40))
    out: list[dict[str, Any]] = []
    for row in rows:
        evt = str(row.get("event") or "")
        if evt != "analytical_question":
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        if should_exclude_from_recent_ami_questions(event=evt, metrics=metrics):
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def filter_resume_items_for_recent_ami(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop HOF case resume rows from a generic resume-item list."""
    out: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        if should_exclude_from_recent_ami_questions(
            resume_key=str(row.get("item_key") or ""),
            title=str(row.get("title") or ""),
        ):
            continue
        out.append(row)
    return out


def submit_analytical_question(
    *,
    source_app: str,
    source_page: str,
    question: str,
    context: dict[str, Any] | None = None,
    context_summary: str = "",
    quant_area: str = "",
    source_state: dict[str, Any] | None = None,
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
        source_state=source_state,
    )
    action_url = build_applied_math_resume_url(payload)
    duplicate = _recent_duplicate_send(session_state, payload["question_id"])
    hof_case = _is_hof_case_submission(quant_area, context)
    if not duplicate:
        metrics = metrics_for_applied_math_resume(payload)
        metrics["source_app"] = normalize_source_app_id(
            str(payload.get("source_app") or ""),
            dict(payload.get("context") or {}),
        )
        if not hof_case:
            if metrics["source_app"] == "music":
                summary = f"Asked Music Coach: {payload['question'][:80]}"
            else:
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
    if hof_case:
        player = _hof_case_player_name(payload)
        hof_payload = {
            **payload,
            "action_url": action_url,
            "app_context_type": "baseball_hof_case",
        }
        _store_question_context_blob(hof_payload)
        if not duplicate:
            metrics = metrics_for_applied_math_resume(hof_payload)
            metrics["source_app"] = normalize_source_app_id(
                str(hof_payload.get("source_app") or ""),
                dict(hof_payload.get("context") or {}),
            )
            metrics["app_context_type"] = "baseball_hof_case"
            if player:
                metrics["hof_case_target"] = player
                metrics["target_player"] = player
            hof_resume_key = f"hof:ami:{payload['question_id']}"
            try:
                from suite_activity_client import record_activity
                from baseball_hof_activity import HOF_CASE_ACTIVITY_EVENT

                record_activity(
                    "applied_intelligence",
                    HOF_CASE_ACTIVITY_EVENT,
                    page=str(hof_payload.get("source_page") or "Career Totals"),
                    metrics=metrics,
                    summary=f"Open full Hall of Fame analysis — {player}" if player else "Open full Hall of Fame analysis",
                    resume_key=hof_resume_key,
                    resume_title=f"Open full Hall of Fame analysis — {player}" if player else "Open full Hall of Fame analysis",
                    resume_subtitle=_hof_case_card_subtitle(hof_payload),
                    action_url=action_url,
                )
            except Exception as exc:
                log.warning("record_activity failed for HOF case analysis: %s", exc)
    else:
        _upsert_applied_intelligence_resume(payload, action_url=action_url)
    ss = payload.get("source_state")
    refresh_blob = not duplicate or (
        str(payload.get("source_app") or "").strip().lower() == "investment"
        and isinstance(ss, dict)
        and bool(ss.get("entity_params"))
    )
    if refresh_blob and not hof_case:
        _store_question_context_blob(payload)
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


def build_submit_context(
    source_app: str,
    source_page: str,
    session_state: dict[str, Any],
    *,
    context_extra_builder: Callable[[], dict[str, Any] | None] | None = None,
    context_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fresh context at Send time — page hooks may run after sidebar render."""
    ctx, _ = build_context_from_session(source_app, source_page, session_state)
    extra: dict[str, Any] | None = None
    if context_extra_builder is not None:
        try:
            extra = context_extra_builder()
        except Exception:
            log.exception("AMI context builder failed for %s (%s)", source_app, source_page)
    elif context_extra:
        extra = context_extra
    if extra:
        ctx = merge_analytical_context(ctx, extra)
    if str(source_app or "").strip().lower() == "baseball":
        try:
            from baseball_ami_pages import promote_page_ami_context_at_send

            question = ""
            if context_extra and isinstance(context_extra.get("question"), str):
                question = context_extra["question"]
            promote_page_ami_context_at_send(
                ctx,
                session_state,
                source_page=source_page,
                question=question,
            )
        except ImportError:
            try:
                from applied_math_context import build_baseball_applied_math_context

                ctx = merge_analytical_context(
                    ctx,
                    build_baseball_applied_math_context(source_page, session_state),
                )
            except ImportError:
                pass
    return ctx


def render_analyze_with_applied_math_sidebar(
    st: Any,
    *,
    source_app: str,
    source_page: str,
    context: dict[str, Any] | None = None,
    context_extra_builder: Callable[[], dict[str, Any] | None] | None = None,
    source_state_builder: Callable[[], dict[str, Any] | None] | None = None,
    context_summary: str = "",
    default_question: str = "",
    developer_mode: bool = False,
    session_state: dict[str, Any] | None = None,
    on_after_send: Callable[[], None] | None = None,
) -> None:
    """Always-visible sidebar block: question → Command Center → Applied Intelligence."""
    ss = session_state if session_state is not None else st.session_state
    page_suffix = _safe_widget_suffix(source_page)
    send_gen = int(ss.get(f"_ami_send_gen_{source_app}_{page_suffix}") or 0)
    question_key = f"ami_question_{source_app}_{page_suffix}_{send_gen}"
    submit_key = f"ami_submit_{source_app}_{page_suffix}"

    app_id = resolve_ami_sidebar_app_id(source_app, ss)
    is_baseball = app_id == "baseball"
    is_music = app_id == "music"
    is_nba = app_id == "nba"
    submit_label = ami_sidebar_submit_label(source_app, ss)
    debug_on = _ami_sidebar_debug_visible(st, ss)
    if debug_on:
        ss["_ami_sidebar_render_debug"] = {
            "module": AMI_SIDEBAR_RENDER_MODULE,
            "source_app_raw": str(source_app or ""),
            "source_app_resolved": app_id,
            "submit_label": submit_label,
            "deploy_version": AMI_SIDEBAR_DEPLOY_VERSION,
            "build_marker": ami_sidebar_build_marker(),
        }
    if is_music:
        st.sidebar.markdown("### Ask the Music Coach")
        st.sidebar.caption(
            "Get help with practice, theory, navigation, backing tracks, karaoke, or this app."
        )
    elif is_nba:
        st.sidebar.markdown("### Get Basketball Insight")
        st.sidebar.caption(
            "Ask an NBA or playoff question about the team, matchup, or page you're viewing."
        )
    elif is_baseball:
        st.sidebar.markdown(f"### {BASEBALL_INSIGHT_SECTION_TITLE}")
        st.sidebar.caption(
            "Ask about players, trades, sleepers, roster weaknesses, strategy, draft picks, "
            "projections, or team decisions."
        )
    else:
        st.sidebar.markdown("### Analyze with Applied Math")
        st.sidebar.caption("Ask a math question about what you are viewing.")

    last = ss.get("_ami_last_send")
    effective_source_app = app_id or str(source_app or "").strip()
    if (
        isinstance(last, dict)
        and str(last.get("source_app") or "").strip().lower() == str(effective_source_app).strip().lower()
        and _recent_duplicate_send(ss, str(last.get("question_id") or ""))
    ):
        sent_msg = (
            "Question sent to Command Center. Open Command Center to continue with the Music Coach."
            if is_music
            else (
                "NBA insight request saved. Open Command Center when you're ready to review it."
                if is_nba
                else (
                    "Baseball insight request saved. Open Command Center when you're ready to review it."
                    if is_baseball
                    else "Question sent to Command Center. Open Command Center to continue in Applied Intelligence."
                )
            )
        )
        st.sidebar.success(sent_msg)

    question = st.sidebar.text_area(
        "Question",
        value=str(ss.get(question_key) or default_question or "").strip(),
        placeholder=(
            music_coach_question_placeholder(source_page)
            if is_music
            else (
                nba_insight_question_placeholder(source_page)
                if is_nba
                else "e.g. Is this trend meaningful statistically?"
            )
        ),
        height=88,
        key=question_key,
        label_visibility="visible",
    )

    if debug_on:
        render_ami_sidebar_submit_debug(
            st,
            source_app_raw=str(source_app or ""),
            source_app_resolved=app_id,
            submit_label=submit_label,
            session_state=ss,
        )

    if st.sidebar.button(
        submit_label,
        key=submit_key,
        use_container_width=True,
        type="primary",
    ):
        q = str(question or "").strip()
        if not q:
            st.sidebar.warning("Enter a question first.")
        else:
            submit_ctx = build_submit_context(
                effective_source_app,
                source_page,
                ss,
                context_extra_builder=context_extra_builder,
                context_extra=context,
            )
            submit_source_state: dict[str, Any] | None = None
            if source_state_builder is not None:
                try:
                    submit_source_state = source_state_builder()
                except Exception:
                    log.exception("AMI source_state builder failed for %s (%s)", source_app, source_page)
            result = submit_analytical_question(
                source_app=app_id or source_app,
                source_page=source_page,
                question=q,
                context=submit_ctx,
                context_summary=context_summary,
                source_state=submit_source_state,
                session_state=ss,
            )
            ss["_last_analytical_question"] = result
            ss[f"_ami_send_gen_{source_app}_{page_suffix}"] = send_gen + 1
            dup_msg = (
                "That question was already sent recently. Open Command Center to continue with the Music Coach."
                if is_music
                else (
                    "That NBA insight was already requested recently. Open Command Center to review it."
                    if is_nba
                    else (
                        "That baseball insight was already requested recently. Open Command Center to review it."
                        if is_baseball
                        else "That question was already sent recently. Open Command Center to continue in Applied Intelligence."
                    )
                )
            )
            ok_msg = (
                "Question sent to Command Center. Open Command Center to continue with the Music Coach."
                if is_music
                else (
                    "NBA insight request saved. Open Command Center when you're ready to review it."
                    if is_nba
                    else (
                        "Baseball insight request saved. Open Command Center when you're ready to review it."
                        if is_baseball
                        else "Question sent to Command Center. Open Command Center to continue in Applied Intelligence."
                    )
                )
            )
            if result.get("duplicate"):
                st.sidebar.info(dup_msg)
            else:
                st.sidebar.success(ok_msg)
            if on_after_send is not None and not result.get("duplicate"):
                try:
                    on_after_send()
                except Exception:
                    log.exception("on_after_send hook failed for %s (%s)", source_app, source_page)
            st.rerun()

    if debug_on and developer_mode:
        st.sidebar.caption(f"🛠 {AMI_SIDEBAR_DEPLOY_LABEL} · {AMI_SIDEBAR_DEPLOY_VERSION}")
    st.sidebar.divider()


def render_applied_math_sidebar_entry(
    st: Any,
    *,
    source_app: str,
    source_page: str,
    session_state: dict[str, Any] | None = None,
    context_extra: dict[str, Any] | None = None,
    context_extra_builder: Callable[[], dict[str, Any] | None] | None = None,
    source_state_builder: Callable[[], dict[str, Any] | None] | None = None,
    developer_mode: bool = False,
    on_after_send: Callable[[], None] | None = None,
    **kwargs: Any,
) -> None:
    """Render AMI sidebar near the top; log and surface failures in Developer Mode."""
    if normalize_source_app_id(source_app) == "baseball":
        from baseball_ami_sidebar import render_baseball_insight_sidebar

        render_baseball_insight_sidebar(
            st,
            source_page=source_page,
            session_state=session_state,
            context_extra_builder=context_extra_builder,
            source_state_builder=source_state_builder,
            on_after_send=on_after_send,
        )
        return
    if context_extra_builder is None:
        legacy_builder = kwargs.pop("context_builder", None)
        if callable(legacy_builder):
            context_extra_builder = legacy_builder
    kwargs.pop("context", None)
    if kwargs:
        log.debug("render_applied_math_sidebar_entry ignored legacy kwargs: %s", sorted(kwargs))
    ss = session_state if session_state is not None else getattr(st, "session_state", {})
    try:
        builder = context_extra_builder
        if builder is None and context_extra is not None:
            frozen_extra = context_extra

            def builder() -> dict[str, Any] | None:
                return frozen_extra

        render_analyze_with_applied_math_sidebar(
            st,
            source_app=source_app,
            source_page=source_page,
            context_extra_builder=builder,
            source_state_builder=source_state_builder,
            context_summary="",
            developer_mode=developer_mode,
            session_state=ss,
            on_after_send=on_after_send,
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
                ami_trend = session_state.get("_ami_trend_summary")
                if isinstance(ami_trend, dict) and ami_trend:
                    ctx["trend_summary"] = {**dict(ctx.get("trend_summary") or {}), **ami_trend}
                lag = session_state.get("trend_lag")
                if lag is not None:
                    ctx["trend_window"] = f"{lag} seasons"
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
                ctx["macro_outlook"] = summary_text
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
        inv_extra = session_state.get("_ami_investment_context")
        if isinstance(inv_extra, dict) and inv_extra:
            for k, v in inv_extra.items():
                if v is not None and v != "":
                    ctx[k] = v
        hr_obj = session_state.get("health_result")
        if hr_obj is not None:
            for attr, key in (
                ("sharpe", "sharpe_ratio"),
                ("max_drawdown", "max_drawdown"),
                ("risk_level", "risk_level"),
            ):
                val = getattr(hr_obj, attr, None) if not isinstance(hr_obj, dict) else hr_obj.get(attr)
                if val is not None and val != "":
                    ctx[key] = val
    elif app == "music":
        try:
            from music_coach_context import (
                coach_page_display_name,
                resolve_coach_source_page,
            )

            coach_page = resolve_coach_source_page(session_state)
            ctx["page"] = coach_page_display_name(coach_page)
            ctx["workflow"] = "Music practice coach"
            song = session_state.get("selected_song")
            if isinstance(song, dict):
                title = str(song.get("title") or "").strip()
                artist = str(song.get("artist") or "").strip()
                if title:
                    ctx["song"] = f"{title} — {artist}" if artist else title
            instrument = str(session_state.get("instrument") or "").strip()
            if instrument:
                ctx["instrument"] = instrument
            display_key = str(session_state.get("display_key") or "").strip()
            if display_key:
                ctx["display_key"] = display_key
            section = str(session_state.get("practice_focus_section") or "").strip()
            if section:
                ctx["practice_section"] = section
            summary = ctx.get("song") or ctx["page"]
        except Exception:
            ctx["workflow"] = "Music practice coach"
            summary = page_display

    return ctx, summary


def render_music_coach_sidebar_entry(
    st: Any,
    *,
    source_page: str,
    session_state: dict[str, Any] | None = None,
    context_extra_builder: Callable[[], dict[str, Any] | None] | None = None,
    source_state_builder: Callable[[], dict[str, Any] | None] | None = None,
    developer_mode: bool = False,
    on_after_send: Callable[[], None] | None = None,
) -> None:
    """Music Practice Coach sidebar — Ask the Music Coach (not Applied Math wording)."""
    render_applied_math_sidebar_entry(
        st,
        source_app="music",
        source_page=source_page,
        session_state=session_state,
        context_extra_builder=context_extra_builder,
        source_state_builder=source_state_builder,
        developer_mode=developer_mode,
        on_after_send=on_after_send,
    )


def render_suite_applied_math_insight(
    st: Any,
    *,
    source_app: str = "",
    source_page: str = "",
) -> bool:
    """Source apps: show pending Applied Math insight card on eligible pages."""
    try:
        from applied_math_return_insight import render_suite_applied_math_insight_for_page

        return render_suite_applied_math_insight_for_page(
            st,
            source_app=source_app,
            source_page=source_page,
        )
    except Exception:
        return False
