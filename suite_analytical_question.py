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
import time
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

from activity_time import parse_activity_timestamp, utc_now_iso

log = logging.getLogger(__name__)

AMI_SIDEBAR_DEPLOY_LABEL = "Applied Math question sender live"
AMI_SIDEBAR_DEPLOY_VERSION = "2026-05-27-ami-send-speed-v3"
_CTX_JSON_SUBTITLE_LIMIT = 8000
_CONTEXT_ITEM_TYPE = "analytical_question_context"
ANALYTICAL_QUESTION_CONTINUE_PRIORITY = 64
ANALYTICAL_QUESTION_BUTTON_LABEL = "Continue in Applied Mathematics →"
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
    "draft_projection",
    "roster",
    "draft_queue",
    "watchlist",
    "tracked_players",
    "drafted_players",
    "best_available",
    "needed_positions",
    "category_needs",
    "sleeper_candidates",
    "bust_risks",
    "drafted_exclusions",
    "valuation_snapshot",
    "draft_status",
    "ami_guidance",
    "ami_quality_rule",
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
    "draft_snapshot": "Draft snapshot",
    "roster": "Roster",
    "draft_queue": "Draft queue",
    "watchlist": "Watchlist",
    "tracked_players": "Tracked players",
    "drafted_players": "Drafted players",
    "best_available": "Best available",
    "needed_positions": "Needed positions",
    "category_needs": "Category needs",
    "sleeper_candidates": "Sleeper candidates",
    "bust_risks": "Bust risks",
    "drafted_exclusions": "Drafted exclusions",
    "valuation_snapshot": "Valuation snapshot",
    "draft_status": "Draft status",
    "ami_guidance": "AMI guidance",
    "ami_quality_rule": "AMI quality rule",
}


def default_area_for_source(source_app: str) -> str:
    return _SOURCE_AREA.get(str(source_app or "").strip(), "abstract")


def source_app_label(source_app: str) -> str:
    key = str(source_app or "").strip().lower()
    if key == "music":
        return "Music Practice Coach"
    return _SOURCE_LABELS.get(key, key.replace("_", " ").title())


def source_question_card_title(
    source_app: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Normalized Continue / activity title for cross-app questions."""
    app = normalize_source_app_id(source_app, context)
    if app == "music":
        return "Music Coach question from Music"
    label = _SOURCE_LABELS.get(app, app.replace("_", " ").title())
    if app == "baseball":
        return f"Baseball Insight question from {label}"
    if app in {"nba", "investment"}:
        return f"Applied Math question from {label}"
    return f"Question from {label}"


def music_coach_question_placeholder(source_page: str) -> str:
    page = str(source_page or "").strip().lower()
    return _MUSIC_COACH_PLACEHOLDERS.get(
        page,
        "e.g. What notes are in C minor?",
    )


def _normalize_question(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _draft_board_fingerprint_parts(ctx: dict[str, Any]) -> list[str]:
    """Draft board state for question_id — avoids stale blob collisions across pick/pool changes."""
    parts: list[str] = []
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    pick = ctx.get("current_pick")
    if pick is None:
        pick = snap.get("current_pick")
    rnd = ctx.get("draft_round")
    if rnd is None:
        rnd = snap.get("draft_round")
    if pick is not None:
        parts.append(f"pick={int(pick)}")
    if rnd is not None:
        parts.append(f"round={int(rnd)}")
    diag = ctx.get("send_pipeline_diagnostics") if isinstance(ctx.get("send_pipeline_diagnostics"), dict) else {}
    board_picks = diag.get("session_pick_count")
    if board_picks is not None:
        parts.append(f"board_picks={int(board_picks)}")
    pool_n = diag.get("session_projection_available_count")
    if pool_n is None:
        pool_n = diag.get("ctx_available_players_count")
    if pool_n is not None:
        parts.append(f"pool={int(pool_n)}")
    return parts


def _is_draft_context(ctx: dict[str, Any], source_page: str = "") -> bool:
    if "draft" in str(source_page or "").lower():
        return True
    workflow = str(ctx.get("workflow") or "").lower()
    return "draft" in workflow or bool(ctx.get("draft_snapshot"))


def _context_payload_hash(ctx: dict[str, Any]) -> str:
    text = json.dumps(ctx, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _blob_diagnostics_from_context(ctx: dict[str, Any]) -> dict[str, Any]:
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    avail = ctx.get("available_players") or snap.get("available_players") or []
    best = ctx.get("best_available") or snap.get("best_available_players") or []
    return {
        "available_players_count": len(avail) if isinstance(avail, list) else 0,
        "draft_snapshot_available_players_count": len(snap.get("available_players") or [])
        if isinstance(snap.get("available_players"), list)
        else 0,
        "best_available_count": len(best) if isinstance(best, list) else 0,
        "current_pick": ctx.get("current_pick") or snap.get("current_pick"),
        "draft_round": ctx.get("draft_round") or snap.get("draft_round"),
    }


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
    if _is_draft_context(ctx, source_page):
        parts.extend(_draft_board_fingerprint_parts(ctx))
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


def _store_question_context_blob(
    payload: dict[str, Any],
    *,
    store_apps: list[str] | None = None,
) -> dict[str, Any]:
    """Persist full context server-side keyed by question_id (survives URL truncation)."""
    qid = str(payload.get("question_id") or "").strip()
    if not qid:
        return {"blob_updated": False, "reason": "missing_question_id"}
    ctx = dict(payload.get("context") or {})
    saved_at = utc_now_iso()
    payload_hash = _context_payload_hash(ctx)
    blob_diag = _blob_diagnostics_from_context(ctx)
    blob = {
        "question": payload.get("question"),
        "question_id": qid,
        "source_app": payload.get("source_app"),
        "source_page": payload.get("source_page"),
        "quant_area": payload.get("quant_area"),
        "context": ctx,
        "source_state": dict(payload.get("source_state") or {}),
        "saved_at": saved_at,
        "payload_hash": payload_hash,
        "blob_diagnostics": blob_diag,
    }
    avail_n = blob_diag.get("available_players_count") or 0
    if "draft" in str(payload.get("source_page") or "").lower() and avail_n == 0:
        log.warning(
            "AMI blob save for %s has zero available_players (pick=%s hash=%s diag=%s)",
            qid,
            blob_diag.get("current_pick"),
            payload_hash,
            ctx.get("send_pipeline_diagnostics"),
        )
    if store_apps is None:
        store_apps = ["applied_intelligence"]
    store_results: list[dict[str, Any]] = []
    blob_save_ms_by_app: dict[str, float] = {}
    try:
        from suite_account import remember_saved_item

        for app_name in store_apps:
            t_app = time.perf_counter()
            result = remember_saved_item(
                app_name,
                _CONTEXT_ITEM_TYPE,
                qid,
                title=str(payload.get("question") or "Applied Math question")[:200],
                payload=blob,
            )
            blob_save_ms_by_app[app_name] = round((time.perf_counter() - t_app) * 1000, 1)
            store_results.append({"app": app_name, **(result if isinstance(result, dict) else {})})
    except Exception as exc:
        log.warning("remember_saved_item failed for analytical context: %s", exc)
        return {
            "blob_updated": False,
            "question_id": qid,
            "blob_updated_at": saved_at,
            "blob_payload_hash": payload_hash,
            "blob_store_error": str(exc),
            "blob_payload_available_players_count_after_save": blob_diag.get("available_players_count"),
            "blob_payload_current_pick_after_save": blob_diag.get("current_pick"),
        }
    return {
        "blob_updated": True,
        "question_id": qid,
        "blob_updated_at": saved_at,
        "blob_payload_hash": payload_hash,
        "blob_payload_available_players_count_after_save": blob_diag.get("available_players_count"),
        "blob_payload_draft_snapshot_available_players_count_after_save": blob_diag.get(
            "draft_snapshot_available_players_count"
        ),
        "blob_payload_best_available_count_after_save": blob_diag.get("best_available_count"),
        "blob_payload_current_pick_after_save": blob_diag.get("current_pick"),
        "blob_payload_draft_round_after_save": blob_diag.get("draft_round"),
        "blob_store_apps": store_apps,
        "blob_store_results": store_results,
        "blob_save_ms_by_app": blob_save_ms_by_app,
    }


def _blob_candidate_score(payload: dict[str, Any], updated_at: str) -> tuple[str, int]:
    """Sort key: prefer newest store time, then richest pool."""
    ctx = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    diag = payload.get("blob_diagnostics") if isinstance(payload.get("blob_diagnostics"), dict) else {}
    avail = diag.get("available_players_count")
    if avail is None:
        avail = len(ctx.get("available_players") or snap.get("available_players") or [])
    ts = str(updated_at or payload.get("saved_at") or payload.get("blob_store_updated_at") or "")
    return (ts, int(avail or 0))


def _select_best_blob_payload(candidates: list[tuple[str, str, dict[str, Any]]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    best_ts, best_app, best_payload = max(
        candidates,
        key=lambda item: _blob_candidate_score(item[2], item[0]),
    )
    out = copy.deepcopy(best_payload)
    out["blob_store_updated_at"] = best_ts or out.get("saved_at")
    out["blob_store_app"] = best_app
    out["blob_load_source"] = "saved_items"
    if len(candidates) > 1:
        out["blob_load_candidates"] = [
            {
                "app": app,
                "updated_at": ts,
                "payload_hash": (payload or {}).get("payload_hash"),
                "available_players_count": _blob_candidate_score(payload, ts)[1],
            }
            for ts, app, payload in candidates
        ]
    return out


def load_analytical_question_context(question_id: str) -> dict[str, Any]:
    """Load full context blob by question_id from saved items or resume subtitle."""
    return load_analytical_question_payload(question_id).get("context") or {}


def load_analytical_question_payload(question_id: str) -> dict[str, Any]:
    """Load full question blob (context + source_state) by question_id."""
    qid = str(question_id or "").strip()
    if not qid:
        return {}
    resume_key = f"ai:question:{qid}"
    search_apps = ["applied_intelligence", "baseball", "investment", "nba", "music"]
    load_error = ""
    try:
        from suite_account import load_saved_items

        candidates: list[tuple[str, str, dict[str, Any]]] = []
        for app_name in search_apps:
            rows = load_saved_items(app=app_name, item_type=_CONTEXT_ITEM_TYPE, limit=80)
            for row in rows:
                if str(row.get("item_key") or "") != qid:
                    continue
                payload = row.get("payload")
                if isinstance(payload, dict):
                    candidates.append((str(row.get("updated_at") or ""), app_name, payload))
        picked = _select_best_blob_payload(candidates)
        if picked:
            return picked
    except Exception as exc:
        log.warning("load_saved_items failed for question context: %s", exc)
        load_error = str(exc)
    try:
        from suite_storage_supabase import load_active_resume_items

        for row in load_active_resume_items(limit=40):
            if str(row.get("app") or "") != "applied_intelligence":
                continue
            if str(row.get("item_key") or "") != resume_key:
                continue
            ctx = _parse_context_from_resume_subtitle(str(row.get("subtitle") or ""))
            if ctx:
                return {
                    "context": ctx,
                    "question_id": qid,
                    "blob_load_source": "resume_subtitle",
                    "payload_hash": _context_payload_hash(ctx),
                }
    except Exception:
        pass
    return {"blob_load_error": load_error or "no_blob_context_for_question_id", "question_id": qid}


def build_send_identity_diagnostics(session_state: dict[str, Any]) -> dict[str, Any]:
    """Hard identity block for Baseball Dev Mode after AMI send."""
    try:
        from suite_deploy_marker import GIT_COMMIT_SHORT, SUITE_BUILD_LABEL
    except ImportError:
        SUITE_BUILD_LABEL, GIT_COMMIT_SHORT = "unknown", "unknown"
    last_send = session_state.get("_ami_last_send") if isinstance(session_state.get("_ami_last_send"), dict) else {}
    send_diag = (
        session_state.get("_ami_last_send_diagnostics")
        if isinstance(session_state.get("_ami_last_send_diagnostics"), dict)
        else {}
    )
    identity: dict[str, Any] = {
        "deploy_build": SUITE_BUILD_LABEL,
        "deploy_commit": GIT_COMMIT_SHORT,
        "question_id": last_send.get("question_id") or send_diag.get("question_id"),
        "blob_updated": last_send.get("blob_updated", send_diag.get("blob_updated")),
        "blob_updated_at": last_send.get("blob_updated_at") or send_diag.get("blob_updated_at"),
        "blob_payload_hash": last_send.get("blob_payload_hash") or send_diag.get("blob_payload_hash"),
        "blob_payload_available_players_count_after_save": send_diag.get(
            "blob_payload_available_players_count_after_save"
        ),
        "blob_payload_current_pick_after_save": send_diag.get("blob_payload_current_pick_after_save"),
        "blob_store_apps": send_diag.get("blob_store_apps"),
        "cache_build_action": send_diag.get("cache_build_action"),
        "skip_reason": send_diag.get("skip_reason"),
    }
    return identity


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
    if isinstance(m.get("context"), dict):
        ctx = copy.deepcopy(m["context"])
    elif m.get("context_json"):
        try:
            parsed = json.loads(str(m["context_json"]))
            if isinstance(parsed, dict):
                ctx = parsed
        except json.JSONDecodeError:
            pass
    if not ctx and qid:
        ctx = load_analytical_question_context(qid)
    source_state: dict[str, Any] = {}
    if qid:
        source_state = load_analytical_question_source_state(qid)
    if not ctx:
        raw_ctx = _qp("suite_ai_context")
        if raw_ctx:
            try:
                parsed = json.loads(raw_ctx)
                if isinstance(parsed, dict):
                    ctx = parsed
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


def _format_context_value(key: str, val: Any) -> str:
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


def analytical_question_continue_copy(payload: dict[str, Any]) -> tuple[str, str, str]:
    """Return (title, subtitle, button_label) for Command Center Continue cards."""
    ctx = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    app = normalize_source_app_id(str(payload.get("source_app") or ""), ctx)
    question = str(payload.get("question") or "").strip()
    title = source_question_card_title(app, ctx)
    if app == "music":
        return (title, question, "Continue with Music Coach →")
    return (title, question, ANALYTICAL_QUESTION_BUTTON_LABEL)


def analytical_question_storage_subtitle(payload: dict[str, Any], *, include_context_json: bool = True) -> str:
    """Resume-item subtitle — question text only when blob is saved by question_id."""
    question = str(payload.get("question") or "").strip()
    qid = str(payload.get("question_id") or "").strip()
    if qid and not include_context_json:
        return question
    ctx = dict(payload.get("context") or {})
    ctx_json = json.dumps(ctx, ensure_ascii=False) if ctx else ""
    if ctx_json:
        return f"{question}\n__ctx_json__:{ctx_json[:_CTX_JSON_SUBTITLE_LIMIT]}"
    return question


def metrics_for_activity_record(payload: dict[str, Any]) -> dict[str, Any]:
    """Lean Command Center activity metrics — full solver context lives in saved blob."""
    ctx = dict(payload.get("context") or {})
    diag = ctx.get("send_pipeline_diagnostics") if isinstance(ctx.get("send_pipeline_diagnostics"), dict) else {}
    avail = ctx.get("available_players")
    return {
        "question": payload.get("question"),
        "question_id": payload.get("question_id"),
        "resume_key": payload.get("resume_key"),
        "page": "Solve a Problem",
        "source_app": payload.get("source_app"),
        "source_page": payload.get("source_page"),
        "context_summary": payload.get("context_summary"),
        "quant_area": payload.get("quant_area"),
        "dedupe_fingerprint": payload.get("question_id"),
        "cache_build_action": diag.get("cache_build_action"),
        "current_pick": ctx.get("current_pick"),
        "available_players_count": len(avail) if isinstance(avail, list) else None,
    }


def metrics_for_applied_math_resume(payload: dict[str, Any]) -> dict[str, Any]:
    """Metrics bundle for deep links into Applied Intelligence."""
    ctx = dict(payload.get("context") or {})
    ctx_lines = format_context_lines(ctx)
    return {
        "question": payload.get("question"),
        "question_id": payload.get("question_id"),
        "page": "Solve a Problem",
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


def _flush_pending_blob_save(session_state: dict[str, Any] | None) -> None:
    """Run deferred question-context blob save from a prior send."""
    if not session_state:
        return
    pending = session_state.pop("_ami_pending_blob_save", None)
    if not isinstance(pending, dict):
        return
    payload = pending.get("payload")
    store_apps = pending.get("store_apps")
    if isinstance(payload, dict):
        _store_question_context_blob(
            payload,
            store_apps=store_apps if isinstance(store_apps, list) else None,
        )


def _flush_pending_resume_upsert(session_state: dict[str, Any] | None) -> None:
    """Run deferred Applied Intelligence resume upsert from a prior send (non-blocking path)."""
    if not session_state:
        return
    pending = session_state.pop("_ami_pending_resume_upsert", None)
    if not isinstance(pending, dict):
        return
    payload = pending.get("payload")
    action_url = str(pending.get("action_url") or "")
    if isinstance(payload, dict) and action_url:
        _upsert_applied_intelligence_resume(payload, action_url=action_url, include_context_json=False)


def _upsert_applied_intelligence_resume(
    payload: dict[str, Any],
    *,
    action_url: str,
    include_context_json: bool = True,
) -> None:
    title, _, _ = analytical_question_continue_copy(payload)
    subtitle = analytical_question_storage_subtitle(payload, include_context_json=include_context_json)
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
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    if snap:
        parts = ["Fantasy draft"]
        if snap.get("draft_round") and snap.get("current_pick"):
            parts.append(f"R{snap['draft_round']} pick {snap['current_pick']}")
        recs = snap.get("recommended_players") or []
        if isinstance(recs, list) and recs:
            names = [str(r.get("player") or r) for r in recs[:3] if r]
            if names:
                parts.append(f"top: {', '.join(names)}")
        return " · ".join(parts)
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
    defer_blob_save: bool = False,
) -> dict[str, Any]:
    """Log event on source app and upsert Applied Intelligence resume item."""
    timing: dict[str, Any] = {}
    t_total = time.perf_counter()

    t0 = time.perf_counter()
    payload = build_question_payload(
        source_app=source_app,
        source_page=source_page,
        question=question,
        context=context,
        context_summary=context_summary,
        quant_area=quant_area,
        source_state=source_state,
    )
    timing["build_payload_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    t1 = time.perf_counter()
    action_url = build_applied_math_resume_url(payload)
    timing["action_url_ms"] = round((time.perf_counter() - t1) * 1000, 1)

    duplicate = _recent_duplicate_send(session_state, payload["question_id"])
    card_title, card_subtitle, _ = analytical_question_continue_copy(payload)
    blob_meta: dict[str, Any] = {}
    activity_created = False
    continue_item_created = False
    if duplicate:
        t_blob = time.perf_counter()
        blob_meta = _store_question_context_blob(payload, store_apps=["applied_intelligence"])
        timing["blob_save_ms"] = round((time.perf_counter() - t_blob) * 1000, 1)
        timing["duplicate_send"] = True
    else:
        metrics = metrics_for_activity_record(payload)
        metrics["source_app"] = normalize_source_app_id(
            str(payload.get("source_app") or ""),
            dict(payload.get("context") or {}),
        )
        metrics["continue_action_url"] = action_url
        metrics["target_app"] = "applied_intelligence"
        if metrics["source_app"] == "music":
            summary = f"Asked Music Coach: {payload['question'][:80]}"
        else:
            summary = f"Asked Applied Math: {payload['question'][:80]}"
        t_rec = time.perf_counter()
        try:
            from suite_activity_client import last_record_trace, record_activity

            record_activity(
                payload["source_app"],
                "analytical_question",
                page=payload["source_page"],
                metrics=metrics,
                summary=summary,
                resume_key=str(payload.get("resume_key") or ""),
                resume_title=card_title,
                resume_subtitle=card_subtitle,
                action_url=action_url,
            )
            activity_created = True
        except Exception as exc:
            log.warning("record_activity failed for analytical_question: %s", exc)
        timing["record_activity_ms"] = round((time.perf_counter() - t_rec) * 1000, 1)
        rec_trace = last_record_trace()
        for key in (
            "payload_prepare_ms",
            "activity_api_ms",
            "append_event_ms",
            "activity_storage_ms",
            "saved_item_link_ms",
            "command_center_index_ms",
            "record_activity_total_ms",
        ):
            if key in rec_trace:
                timing[key] = rec_trace[key]

        t_blob = time.perf_counter()
        if defer_blob_save and session_state is not None:
            session_state["_ami_pending_blob_save"] = {
                "payload": payload,
                "store_apps": ["applied_intelligence"],
            }
            blob_meta = {"blob_updated": False, "blob_save_deferred": True}
            timing["blob_save_deferred"] = True
            timing["blob_save_ms"] = 0.0
            session_state["_ami_pending_resume_upsert"] = {
                "payload": payload,
                "action_url": action_url,
            }
            continue_item_created = True
            timing["resume_upsert_ms"] = 0.0
        else:
            blob_meta = _store_question_context_blob(payload, store_apps=["applied_intelligence"])
            timing["blob_save_ms"] = round((time.perf_counter() - t_blob) * 1000, 1)
        if isinstance(blob_meta.get("blob_save_ms_by_app"), dict):
            timing["blob_save_ms_by_app"] = blob_meta["blob_save_ms_by_app"]

        elif blob_meta.get("blob_updated"):
            if session_state is not None:
                session_state["_ami_pending_resume_upsert"] = {
                    "payload": payload,
                    "action_url": action_url,
                }
                continue_item_created = True
                timing["resume_upsert_ms"] = 0.0
                timing["resume_upsert_deferred"] = True
            else:
                t_resume = time.perf_counter()
                _upsert_applied_intelligence_resume(payload, action_url=action_url, include_context_json=False)
                continue_item_created = True
                timing["resume_upsert_ms"] = round((time.perf_counter() - t_resume) * 1000, 1)
    timing["send_total_ms"] = round((time.perf_counter() - t_total) * 1000, 1)
    if timing:
        numeric = {k: v for k, v in timing.items() if isinstance(v, (int, float)) and k != "send_total_ms"}
        if numeric:
            timing["slowest_step"] = max(numeric, key=lambda k: numeric[k])
            timing["slowest_step_ms"] = numeric[timing["slowest_step"]]

    if session_state is not None:
        ctx = dict(payload.get("context") or {})
        send_diag = dict(ctx.get("send_pipeline_diagnostics") or {})
        send_diag.update(blob_meta)
        send_diag.update(timing)
        build_timing = session_state.get("_ami_last_send_build_timing")
        if isinstance(build_timing, dict):
            send_diag.update(build_timing)
        numeric = {
            k: v
            for k, v in send_diag.items()
            if isinstance(v, (int, float)) and k not in ("send_total_ms",)
        }
        if numeric:
            send_diag["slowest_step"] = max(numeric, key=lambda k: numeric[k])
            send_diag["slowest_step_ms"] = numeric[send_diag["slowest_step"]]
        session_state["_ami_last_send"] = {
            "question_id": payload["question_id"],
            "question": payload["question"],
            "source_app": payload["source_app"],
            "submitted_at": utc_now_iso(),
            "duplicate": duplicate,
            **blob_meta,
        }
        submit_diag = {
            "source_page": payload.get("source_page"),
            "question_id": payload.get("question_id"),
            "activity_created": activity_created,
            "continue_item_created": continue_item_created,
            "duplicate_detected": duplicate,
            "insight_card_created": bool(session_state.get("_ami_last_instant_insight_ok")),
            "command_center_write_status": "skipped_duplicate" if duplicate else ("ok" if activity_created else "failed"),
        }
        ctx_diag = dict(payload.get("context") or {})
        if ctx_diag.get("trend_send_diagnostics"):
            submit_diag.update(dict(ctx_diag["trend_send_diagnostics"]))
        team_diag = ctx_diag.get("_draft_team_diagnostics")
        if isinstance(team_diag, dict):
            submit_diag.update(team_diag)
        if ctx_diag.get("send_pipeline_diagnostics"):
            submit_diag.update(
                {
                    k: v
                    for k, v in dict(ctx_diag["send_pipeline_diagnostics"]).items()
                    if k.startswith(("requested_team", "resolved_team", "roster_", "trend_", "source_page", "routing_"))
                }
            )
        session_state["_ami_last_submit_diagnostics"] = submit_diag
        send_diag.update(submit_diag)
        session_state["_ami_last_send_diagnostics"] = send_diag
    return {
        **payload,
        "action_url": action_url,
        "continue_title": card_title,
        "continue_subtitle": card_subtitle,
        "duplicate": duplicate,
        "submitted_at": utc_now_iso(),
        "send_timing": timing,
    }


def build_submit_context(
    source_app: str,
    source_page: str,
    session_state: dict[str, Any],
    *,
    context_extra_builder: Callable[[], dict[str, Any] | None] | None = None,
    context_extra: dict[str, Any] | None = None,
    question: str = "",
) -> dict[str, Any]:
    """Fresh context at Send time — page hooks may run after sidebar render."""
    timing: dict[str, Any] = {}
    t0 = time.perf_counter()
    ctx, _ = build_context_from_session(source_app, source_page, session_state)
    ctx["source_page"] = str(source_page or "").strip()
    timing["build_context_from_session_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    low_page = str(source_page or "").lower()
    draft_cached = False
    if str(source_app or "").strip().lower() == "baseball" and "draft" in low_page:
        try:
            from draft_ami_helpers import draft_ami_cache_has_pool

            draft_cached = draft_ami_cache_has_pool(session_state)
        except ImportError:
            draft_cached = False

    if not draft_cached:
        extra: dict[str, Any] | None = None
        t_extra = time.perf_counter()
        if context_extra_builder is not None:
            try:
                extra = context_extra_builder()
            except Exception:
                log.exception("AMI context builder failed for %s (%s)", source_app, source_page)
        elif context_extra:
            extra = context_extra
        if extra:
            ctx = merge_analytical_context(ctx, extra)
        timing["context_extra_builder_ms"] = round((time.perf_counter() - t_extra) * 1000, 1)
    else:
        timing["context_extra_builder_ms"] = 0.0
        timing["cache_build_action"] = "already_present"

    if str(source_app or "").strip().lower() == "baseball" and str(question or "").strip():
        try:
            from applied_math_context import (
                attach_draft_team_to_context,
                attach_question_player_to_context,
                augment_ami_available_pool_at_send,
                ensure_draft_assistant_ami_cache_at_send,
                finalize_draft_context_for_send,
            )

            attach_question_player_to_context(ctx, str(question).strip(), session_state)
            if "draft" in low_page:
                if draft_cached:
                    timing["cache_build_ms"] = 0.0
                    timing["cache_build_action"] = timing.get("cache_build_action") or "already_present"
                else:
                    t_cache = time.perf_counter()
                    cache_trace = ensure_draft_assistant_ami_cache_at_send(session_state, source_page=source_page)
                    timing["cache_build_ms"] = round((time.perf_counter() - t_cache) * 1000, 1)
                    timing["cache_build_action"] = cache_trace.get("cache_action")
                augment_ami_available_pool_at_send(ctx, str(question).strip(), session_state)
                t_fin = time.perf_counter()
                finalize_draft_context_for_send(ctx, session_state)
                timing["finalize_context_ms"] = round((time.perf_counter() - t_fin) * 1000, 1)
            attach_draft_team_to_context(ctx, str(question).strip(), session_state)
            if "draft" in low_page:
                from applied_math_context import build_draft_send_pipeline_diagnostics

                diag = build_draft_send_pipeline_diagnostics(ctx, session_state)
                ctx["send_pipeline_diagnostics"] = diag
            else:
                try:
                    from baseball_ami_pages import promote_page_ami_context_at_send

                    page_diag = promote_page_ami_context_at_send(
                        ctx, session_state, source_page=source_page, question=str(question).strip()
                    )
                    if page_diag:
                        ctx.setdefault("send_pipeline_diagnostics", {})
                        if isinstance(ctx.get("send_pipeline_diagnostics"), dict):
                            ctx["send_pipeline_diagnostics"].update(page_diag)
                except ImportError:
                    pass
        except Exception:
            log.exception("attach_question_player_to_context failed for %s (%s)", source_app, source_page)
    session_state["_ami_last_send_build_timing"] = timing
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
    _flush_pending_resume_upsert(ss)
    _flush_pending_blob_save(ss)
    page_suffix = _safe_widget_suffix(source_page)
    send_gen = int(ss.get(f"_ami_send_gen_{source_app}_{page_suffix}") or 0)
    question_key = f"ami_question_{source_app}_{page_suffix}_{send_gen}"
    submit_key = f"ami_submit_{source_app}_{page_suffix}"

    is_music = str(source_app or "").strip().lower() == "music"
    is_baseball = str(source_app or "").strip().lower() == "baseball"
    if is_music:
        st.sidebar.markdown("### Ask the Music Coach")
        st.sidebar.caption(
            "Get help with practice, theory, navigation, backing tracks, karaoke, or this app."
        )
    elif is_baseball:
        st.sidebar.markdown("### Get Baseball Insight")
        st.sidebar.caption(
            "Ask a fantasy baseball question about what you are viewing on this page."
        )
    else:
        st.sidebar.markdown("### Analyze with Applied Math")
        st.sidebar.caption("Ask a math question about what you are viewing.")

    last = ss.get("_ami_last_send")
    if (
        isinstance(last, dict)
        and last.get("source_app") == source_app
        and _recent_duplicate_send(ss, str(last.get("question_id") or ""))
    ):
        sent_msg = (
            "Question sent to Command Center. Open Command Center to continue with the Music Coach."
            if is_music
            else (
                "Baseball Insight is ready on this page."
                if is_baseball
                else "Question sent to Command Center. Open Command Center to continue in Applied Intelligence."
            )
        )
        st.sidebar.success(sent_msg)

    if question_key not in ss:
        ss[question_key] = str(default_question or ss.get("_ami_last_typed_question") or "").strip()

    form_key = f"ami_form_{source_app}_{page_suffix}_{send_gen}"
    with st.sidebar.form(key=form_key, clear_on_submit=False):
        question = st.text_area(
            "Question",
            placeholder=(
                music_coach_question_placeholder(source_page)
                if is_music
                else "e.g. Is this trend meaningful statistically?"
            ),
            height=88,
            key=question_key,
            label_visibility="visible",
        )

        submit_label = (
            "Get Baseball Insight"
            if is_baseball
            else ("Ask the Music Coach" if is_music else "Send to Command Center")
        )
        submitted = st.form_submit_button(
            submit_label,
            use_container_width=True,
            type="primary",
        )

    if submitted:
        q = str(ss.get(question_key) or question or "").strip()
        if not q:
            st.sidebar.warning("Enter a question first.")
        else:
            ss["_ami_last_typed_question"] = q
            t_send = time.perf_counter()
            submit_ctx = build_submit_context(
                source_app,
                source_page,
                ss,
                context_extra_builder=context_extra_builder,
                context_extra=context,
                question=q,
            )
            build_timing = dict(ss.get("_ami_last_send_build_timing") or {})
            build_timing["build_submit_context_total_ms"] = round((time.perf_counter() - t_send) * 1000, 1)
            ss["_ami_last_send_build_timing"] = build_timing
            submit_source_state: dict[str, Any] | None = None
            skip_source_state = False
            if is_baseball and "draft" in str(source_page or "").lower():
                try:
                    from draft_ami_helpers import draft_ami_cache_has_pool

                    skip_source_state = draft_ami_cache_has_pool(ss)
                except ImportError:
                    skip_source_state = False
            if source_state_builder is not None and not skip_source_state:
                try:
                    submit_source_state = source_state_builder()
                except Exception:
                    log.exception("AMI source_state builder failed for %s (%s)", source_app, source_page)
            elif skip_source_state:
                build_timing = dict(ss.get("_ami_last_send_build_timing") or {})
                build_timing["source_state_builder_skipped"] = "draft_cache_present"
                ss["_ami_last_send_build_timing"] = build_timing
            elif skip_source_state:
                build_timing = dict(ss.get("_ami_last_send_build_timing") or {})
                build_timing["source_state_builder_skipped"] = "draft_cache_present"
                ss["_ami_last_send_build_timing"] = build_timing

            instant_solved = False
            if is_baseball:
                t_inst = time.perf_counter()
                try:
                    from applied_math_return_insight import build_return_insight_payload, stage_pending_insight
                    from draft_ami_instant_solver import solve_instant_baseball_insight

                    pre_payload = build_question_payload(
                        source_app=source_app,
                        source_page=source_page,
                        question=q,
                        context=submit_ctx,
                        context_summary=context_summary,
                        source_state=submit_source_state,
                    )
                    action_url_pre = build_applied_math_resume_url(pre_payload)
                    solved_pair = solve_instant_baseball_insight(q, submit_ctx)
                    if solved_pair:
                        route, solved = solved_pair
                        insight = build_return_insight_payload(
                            question=q,
                            source_app=source_app,
                            source_page=source_page,
                            question_id=str(pre_payload.get("question_id") or ""),
                            route=route,
                            result=solved,
                            full_analysis_url=action_url_pre,
                            context=submit_ctx,
                            resume_key=str(pre_payload.get("resume_key") or ""),
                        )
                        stage_pending_insight(ss, insight)
                        try:
                            from applied_math_return_insight import (
                                SESSION_PERSIST_INSIGHT_DIRTY,
                                store_applied_math_insight,
                            )

                            insight_data = (
                                insight.to_dict() if hasattr(insight, "to_dict") else dict(insight)
                            )
                            store_applied_math_insight(
                                insight_data,
                                return_context=submit_ctx,
                                source_state=submit_source_state,
                                st=ss,
                            )
                            ss[SESSION_PERSIST_INSIGHT_DIRTY] = True
                        except Exception:
                            log.exception("instant insight cloud persist failed")
                        instant_solved = True
                except Exception:
                    log.exception("instant Baseball Insight failed for %s (%s)", source_app, source_page)
                build_timing = dict(ss.get("_ami_last_send_build_timing") or {})
                build_timing["instant_insight_ms"] = round((time.perf_counter() - t_inst) * 1000, 1)
                build_timing["instant_insight_ok"] = instant_solved
                ss["_ami_last_send_build_timing"] = build_timing
            ss["_ami_last_instant_insight_ok"] = instant_solved

            result = submit_analytical_question(
                source_app=source_app,
                source_page=source_page,
                question=q,
                context=submit_ctx,
                context_summary=context_summary,
                source_state=submit_source_state,
                session_state=ss,
                defer_blob_save=is_baseball and instant_solved,
            )
            if is_baseball and instant_solved:
                _flush_pending_blob_save(ss)
                _flush_pending_resume_upsert(ss)
            ss["_last_analytical_question"] = result
            ss[f"_ami_send_gen_{source_app}_{page_suffix}"] = send_gen + 1
            dup_msg = (
                "That question was already sent recently. Open Command Center to continue with the Music Coach."
                if is_music
                else (
                    "That question was already sent recently. Open Command Center to continue with Baseball Insight."
                    if is_baseball
                    else "That question was already sent recently. Open Command Center to continue in Applied Intelligence."
                )
            )
            ok_msg = (
                "Question sent to Command Center. Open Command Center to continue with the Music Coach."
                if is_music
                else (
                    "Baseball Insight is ready on this page — use Open full analysis for the deep dive."
                    if is_baseball
                    else "Question sent to Command Center. Open Command Center to continue in Applied Intelligence."
                )
            )
            if result.get("duplicate"):
                st.sidebar.info(dup_msg)
            else:
                st.sidebar.success(ok_msg)
                if is_baseball and instant_solved:
                    try:
                        st.rerun()
                    except Exception:
                        pass
                if on_after_send is not None:
                    try:
                        on_after_send()
                    except Exception:
                        log.exception("on_after_send hook failed for %s (%s)", source_app, source_page)

    if developer_mode:
        st.sidebar.caption(f"🛠 {AMI_SIDEBAR_DEPLOY_LABEL} · {AMI_SIDEBAR_DEPLOY_VERSION}")
        try:
            from suite_analytical_question import build_send_identity_diagnostics

            identity = build_send_identity_diagnostics(ss)
            with st.sidebar.expander("AMI blob identity (last send)", expanded=True):
                for key, val in identity.items():
                    if val is not None and val != "" and val != []:
                        st.text(f"{key}: {val}")
        except Exception:
            pass
        submit_diag = ss.get("_ami_last_submit_diagnostics")
        if isinstance(submit_diag, dict) and submit_diag:
            with st.sidebar.expander("AMI submit diagnostics (last send)", expanded=True):
                for key, val in submit_diag.items():
                    if val is not None and val != "" and val != []:
                        st.text(f"{key}: {val}")
        last_diag = ss.get("_ami_last_send_diagnostics")
        if isinstance(last_diag, dict) and last_diag:
            with st.sidebar.expander("AMI send pipeline (last send)", expanded=False):
                timing_keys = (
                    "send_total_ms",
                    "slowest_step",
                    "slowest_step_ms",
                    "build_submit_context_total_ms",
                    "build_context_from_session_ms",
                    "context_extra_builder_ms",
                    "cache_build_ms",
                    "cache_build_action",
                    "finalize_context_ms",
                    "build_payload_ms",
                    "action_url_ms",
                    "blob_save_ms",
                    "blob_save_ms_by_app",
                    "record_activity_ms",
                    "payload_prepare_ms",
                    "activity_api_ms",
                    "append_event_ms",
                    "activity_storage_ms",
                    "saved_item_link_ms",
                    "command_center_index_ms",
                    "record_activity_total_ms",
                    "resume_upsert_ms",
                )
                for key in timing_keys:
                    if key in last_diag and last_diag[key] is not None:
                        st.text(f"{key}: {last_diag[key]}")
                for key, val in last_diag.items():
                    if key in timing_keys:
                        continue
                    st.text(f"{key}: {val}")
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
            room = session_state.get("live_draft_room") or session_state.get("draft_room_state") or {}
            if "live draft" in low_page and isinstance(room, dict):
                idx = int(room.get("current_pick_index") or 0)
                cfg = room.get("config") if isinstance(room.get("config"), dict) else {}
                num_teams = int(
                    cfg.get("num_teams")
                    or room.get("num_teams")
                    or session_state.get("draft_num_teams")
                    or session_state.get("room_team_count")
                    or 12
                )
                if idx >= 0 and num_teams > 0:
                    ctx["current_pick"] = idx + 1
                    ctx["draft_round"] = (idx // num_teams) + 1
                your_team = str(cfg.get("your_team") or session_state.get("room_your_team") or "").strip()
                if your_team and isinstance(room.get("rosters"), dict):
                    roster = room["rosters"].get(your_team) or []
                    ctx["roster"] = [
                        str(p.get("fullName") or p.get("Player") or p)
                        for p in roster[:12]
                        if isinstance(p, dict)
                    ]
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
            ctx.pop("player_a", None)
            ctx.pop("player_b", None)
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
                ctx["workflow"] = "Multi-player trend analysis"
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
