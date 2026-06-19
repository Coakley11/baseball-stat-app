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
AMI_INSIGHT_STORE_VERSION = "insight-store-v10"
SESSION_PENDING_KEY = "_ami_pending_insight"
SESSION_RETURN_PAGE_KEY = "_ami_return_page"
SESSION_RETURN_CONTEXT_KEY = "_ami_return_context"
INSIGHT_DISMISSAL_ITEM_TYPE = "applied_math_insight_dismissal"
SESSION_DISMISSED_KEY = "_ami_dismissed_insight_ids"
SESSION_DISMISSED_AT_KEY = "_ami_dismissed_insight_at"
SESSION_PERSIST_INSIGHT_DIRTY = "_suite_persist_insight_dirty"
SESSION_INSIGHT_SOURCE_TAB_KEY = "insight_source_tab"
SESSION_SOURCE_INVESTMENT_TAB_KEY = "source_investment_tab"
INVESTMENT_INSIGHT_PANEL_TITLE = "Applied Investment Insight"

_INVESTMENT_TAB_CANONICAL: dict[str, str] = {
    "portfolio health": "Portfolio Health",
    "⑤ portfolio health": "Portfolio Health",
    "portfolio analytics": "Portfolio Analytics",
    "④ analyze portfolio": "Portfolio Analytics",
    "analyze portfolio": "Portfolio Analytics",
    "efficient frontier": "Efficient Frontier",
    "⑩ frontier (optional)": "Efficient Frontier",
    "frontier (optional)": "Efficient Frontier",
}

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


def _normalize_investment_tab(page: str) -> str:
    """Canonical Investment tab label for insight page scoping."""
    p = _normalize_insight_page(page)
    if not p:
        return ""
    key = p.lower().strip()
    if key in _INVESTMENT_TAB_CANONICAL:
        return _INVESTMENT_TAB_CANONICAL[key]
    import re

    stripped = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩\d]+\s*", "", p).strip()
    alias = _INVESTMENT_TAB_CANONICAL.get(stripped.lower())
    if alias:
        return alias
    for label in _INVESTMENT_TAB_CANONICAL.values():
        if label.lower() == stripped.lower() or label.lower() == key:
            return label
    return p


def _investment_tabs_match(current_page: str, insight_page: str) -> bool:
    cur = _normalize_investment_tab(current_page)
    src = _normalize_investment_tab(insight_page)
    if not cur or not src:
        return False
    return cur == src or cur.lower() == src.lower()


def _resolve_insight_source_page(insight: dict[str, Any]) -> str:
    """Canonical originating Investment/source page for a pending insight."""
    raw = str(insight.get("source_page") or "").strip()
    page = _normalize_investment_tab(raw) if raw else _normalize_insight_page(raw)
    if page:
        return page
    for container_key in ("source_state", "return_context"):
        container = insight.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("source_page", "page"):
            candidate = str(container.get(key) or "").strip()
            if candidate:
                normalized = _normalize_investment_tab(candidate)
                if normalized:
                    return normalized
        page_params = container.get("page_params")
        if isinstance(page_params, dict):
            candidate = str(page_params.get("page") or page_params.get("tab") or "").strip()
            if candidate:
                normalized = _normalize_investment_tab(candidate)
                if normalized:
                    return normalized
        ent = container.get("entity_params")
        if isinstance(ent, dict):
            candidate = str(ent.get("tab") or ent.get("page") or "").strip()
            if candidate:
                normalized = _normalize_investment_tab(candidate)
                if normalized:
                    return normalized
    return ""


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
    return _query_param(st, "suite_ami_insight")


def _pending_insight_id(st: Any) -> str:
    pending = st.session_state.get(SESSION_PENDING_KEY)
    if isinstance(pending, dict):
        return str(pending.get("insight_id") or "").strip()
    return ""


def _clear_stale_return_insight_cache(st: Any, query_iid: str) -> dict[str, Any]:
    """Drop session pending insight when URL ``suite_ami_insight`` id differs."""
    ss = st.session_state
    query_iid = str(query_iid or "").strip()
    pending_before = _pending_insight_id(st) or None
    stale_ignored = bool(query_iid and pending_before and pending_before != query_iid)
    if stale_ignored:
        ss.pop(SESSION_PENDING_KEY, None)
        ss.pop(SESSION_RETURN_CONTEXT_KEY, None)
        prev_hydrated = str(ss.get("_ami_hydrated_insight_id") or "").strip()
        if prev_hydrated and prev_hydrated != query_iid:
            ss.pop("_ami_hydrated_insight_id", None)
    return {
        "pending_insight_id_before_return": pending_before,
        "pending_insight_id_after_query_override": _pending_insight_id(st) or None,
        "query_insight_id_used_for_load": query_iid or None,
        "stale_pending_insight_ignored": stale_ignored,
        "loaded_insight_id": None,
    }


def _load_return_insight_for_query(
    st: Any,
    app_key: str,
    query_iid: str,
    *,
    question_id_qp: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load return insight using URL query id only (never a mismatched pending cache)."""
    key = str(app_key or "").strip().lower()
    query_iid = str(query_iid or "").strip()
    trace = _clear_stale_return_insight_cache(st, query_iid)
    if not query_iid:
        return {}, trace

    loaded = load_applied_math_insight(query_iid, source_app=key)
    if loaded:
        insight = dict(loaded)
    else:
        insight = {
            "insight_id": query_iid,
            "conclusion": "Applied Investment Insight loaded.",
            "question": "",
            "source_app": key,
        }
    insight["insight_id"] = query_iid
    insight = _enrich_insight_from_question_blob(insight, question_id_qp=question_id_qp)
    trace["loaded_insight_id"] = query_iid
    trace["pending_insight_id_after_query_override"] = query_iid
    return insight, trace


def _source_state_has_restore_payload(state: Any) -> bool:
    """True when a source_state dict can restore page/holdings (not empty shell)."""
    if not isinstance(state, dict) or not state:
        return False
    if not str(state.get("source_app") or "").strip():
        return False
    ent = state.get("entity_params")
    if isinstance(ent, dict) and ent:
        return True
    wp = state.get("widget_params")
    if isinstance(wp, dict) and wp:
        return True
    if state.get("source_page") or state.get("page_params"):
        return True
    return False


def _ami_insight_store_trace(
    *,
    insight_id: str,
    question_id: str,
    source_state: dict[str, Any],
    return_context_exists: bool,
    blob_written_success: bool,
    return_link_insight_id: str = "",
    store_exception: str = "",
    payload_keys: list[str] | None = None,
) -> dict[str, Any]:
    ent = source_state.get("entity_params") if isinstance(source_state, dict) else {}
    return {
        "store_called": True,
        "store_function_name_used": "store_applied_math_insight",
        "store_module_file_used": __file__,
        "store_version": AMI_INSIGHT_STORE_VERSION,
        "store_insight_id": insight_id or None,
        "store_question_id": question_id or None,
        "store_source_state_exists": _source_state_has_restore_payload(source_state),
        "store_source_state_keys": (
            sorted(str(k) for k in source_state.keys()) if isinstance(source_state, dict) and source_state else None
        ),
        "store_source_state_has_holdings_df": bool(isinstance(ent, dict) and ent.get("holdings_df")),
        "store_source_state_holdings_fingerprint": (
            str(ent.get("holdings_fingerprint") or "").strip() or None if isinstance(ent, dict) else None
        ),
        "store_return_context_exists": return_context_exists,
        "store_blob_written_success": blob_written_success,
        "store_payload_keys": sorted(str(k) for k in (payload_keys or [])) or None,
        "store_payload_has_source_state": _source_state_has_restore_payload(source_state),
        "store_payload_has_question_id": bool(str(question_id or "").strip()),
        "store_payload_has_ami_store_trace": True,
        "store_exception": str(store_exception or "").strip() or None,
        "return_link_insight_id": str(return_link_insight_id or insight_id or "").strip() or None,
    }


def _flatten_insight_store_diag_on_blob(blob: dict[str, Any], trace: dict[str, Any]) -> None:
    blob["_ami_store_trace"] = dict(trace)
    blob["store_version"] = AMI_INSIGHT_STORE_VERSION
    for key, value in trace.items():
        if key.startswith("store_") or key == "return_link_insight_id":
            blob[key] = value


def _insight_blob_restore_score(payload: dict[str, Any]) -> int:
    """Rank stored insight payloads — prefer blobs with usable source_state."""
    if not isinstance(payload, dict) or not payload:
        return -1
    score = 0
    if str(payload.get("insight_id") or "").strip():
        score += 1
    if str(payload.get("question_id") or "").strip():
        score += 1
    for key in ("source_state", "return_context"):
        if _source_state_has_restore_payload(payload.get(key)):
            score += 4
            break
    if isinstance(payload.get("_ami_store_trace"), dict) and payload.get("_ami_store_trace"):
        score += 2
    if str(payload.get("store_version") or "") == AMI_INSIGHT_STORE_VERSION:
        score += 3
    if payload.get("store_blob_written_success") is True:
        score += 1
    return score


def _enrich_insight_from_question_blob(
    insight: dict[str, Any],
    *,
    question_id_qp: str = "",
) -> dict[str, Any]:
    """Merge question-send source_state into insight when blob lacks restore payload."""
    data = dict(insight or {})
    if _source_state_has_restore_payload(data.get("source_state")):
        return data
    qid = str(data.get("question_id") or question_id_qp or "").strip()
    if not qid:
        return data
    try:
        from suite_analytical_question import load_analytical_question_source_state

        loaded = load_analytical_question_source_state(qid)
        if _source_state_has_restore_payload(loaded):
            data["source_state"] = dict(loaded)
            data["return_context"] = dict(loaded)
            data.setdefault("question_id", qid)
    except Exception:
        pass
    return data


def diagnose_ami_return_source_state_resolution(
    st: Any,
    app_key: str,
    insight: dict[str, Any],
    *,
    question_id_qp: str = "",
    load_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect insight/question blobs for AMI return source_state (Test E debug)."""
    query_iid = str(insight_return_query_id(st) or "").strip()
    insight = dict(insight or {})
    if query_iid and str(insight.get("insight_id") or "").strip() != query_iid:
        insight, load_trace = _load_return_insight_for_query(
            st,
            app_key,
            query_iid,
            question_id_qp=question_id_qp,
        )
    iid = query_iid or str(insight.get("insight_id") or "").strip()
    qid = str(
        insight.get("question_id")
        or question_id_qp
        or _query_param(st, "suite_ai_question_id")
        or ""
    ).strip()
    raw_ss = insight.get("source_state")
    raw_rc = insight.get("return_context")
    ent = raw_ss.get("entity_params") if isinstance(raw_ss, dict) else {}
    diag: dict[str, Any] = {
        "return_insight_id": iid or None,
        "return_question_id": qid or None,
        "insight_blob_has_source_state": isinstance(raw_ss, dict) and bool(raw_ss),
        "insight_blob_source_state_keys": sorted(str(k) for k in raw_ss.keys()) if isinstance(raw_ss, dict) else None,
        "insight_blob_has_return_context": isinstance(raw_rc, dict) and bool(raw_rc),
        "insight_blob_has_question_id": bool(str(insight.get("question_id") or "").strip()),
        "insight_blob_source_app": str(insight.get("source_app") or "").strip() or None,
        "insight_blob_has_holdings_df": bool(isinstance(ent, dict) and ent.get("holdings_df")),
        "insight_blob_holdings_fingerprint": (
            str(ent.get("holdings_fingerprint") or "").strip() or None if isinstance(ent, dict) else None
        ),
        "question_blob_loaded": False,
        "question_blob_has_source_state": False,
        "question_blob_source_state_keys": None,
        "question_blob_has_holdings_df": False,
        "question_blob_holdings_fingerprint": None,
        "resolved_source_state_source": "none",
    }
    if load_trace:
        diag.update(load_trace)
    store_trace = insight.get("_ami_store_trace")
    if isinstance(store_trace, dict) and store_trace:
        diag.update(store_trace)
    for key, val in insight.items():
        if (str(key).startswith("store_") or key in ("return_link_insight_id", "store_version")) and val is not None:
            diag.setdefault(key, val)
    question_ss: dict[str, Any] = {}
    if qid:
        try:
            from suite_analytical_question import load_analytical_question_source_state

            question_ss = load_analytical_question_source_state(qid)
            diag["question_blob_loaded"] = bool(question_ss)
            diag["question_blob_has_source_state"] = _source_state_has_restore_payload(question_ss)
            if isinstance(question_ss, dict) and question_ss:
                diag["question_blob_source_state_keys"] = sorted(str(k) for k in question_ss.keys())
                qent = question_ss.get("entity_params")
                if isinstance(qent, dict):
                    diag["question_blob_has_holdings_df"] = bool(qent.get("holdings_df"))
                    diag["question_blob_holdings_fingerprint"] = (
                        str(qent.get("holdings_fingerprint") or "").strip() or None
                    )
        except Exception:
            pass

    resolved_source = "none"
    resolved: dict[str, Any] = {}
    for candidate, label in (
        (raw_ss, "insight_blob"),
        (raw_rc, "insight_blob"),
    ):
        if isinstance(candidate, dict) and _source_state_has_restore_payload(candidate):
            resolved = dict(candidate)
            resolved_source = label
            break
    if not resolved and _source_state_has_restore_payload(question_ss):
        resolved = dict(question_ss)
        resolved_source = "question_blob"
    if not resolved:
        session_ctx = st.session_state.get(SESSION_RETURN_CONTEXT_KEY)
        if _source_state_has_restore_payload(session_ctx):
            resolved = dict(session_ctx)
            resolved_source = "session"
    diag["resolved_source_state_source"] = resolved_source
    diag["resolved_source_state_has_restore_payload"] = _source_state_has_restore_payload(resolved)
    return diag


def investment_ami_return_allows_restore_skip(st: Any) -> bool:
    """Defer cloud restore only when AMI return has usable source_state to apply."""
    ss = st.session_state
    if ss.get("_ami_return_allow_cloud_restore"):
        return False
    if ss.get("_ami_return_source_applied"):
        return True
    ctx = ss.get(SESSION_RETURN_CONTEXT_KEY)
    if _source_state_has_restore_payload(ctx):
        return True
    if not insight_return_query_id(st) and not _query_param(st, "suite_ai_question_id"):
        return False
    pending = ss.get(SESSION_PENDING_KEY)
    if isinstance(pending, dict) and pending:
        resolved = _resolve_return_source_state(
            st,
            "investment",
            pending,
            question_id_qp=_query_param(st, "suite_ai_question_id"),
        )
        return _source_state_has_restore_payload(resolved)
    return False


def _active_ami_return_query_param_keys(st: Any) -> list[str]:
    """AMI return query params present on the current URL."""
    names = ("suite_ami_insight", "suite_page", "suite_holdings_fp", "suite_ai_question_id")
    return [name for name in names if _query_param(st, name)]


def _ami_return_url_active(st: Any) -> bool:
    """True when the current URL carries a live AMI insight return param."""
    return bool(insight_return_query_id(st))


def clear_ami_return_deferred_flags(st: Any, app_key: str) -> list[str]:
    """Drop deferred AMI tab/holdings restore flags (safe after return consumed or on normal reboot)."""
    ss = st.session_state
    cleared: list[str] = []
    for flag in (
        SESSION_RETURN_CONTEXT_KEY,
        SESSION_RETURN_PAGE_KEY,
        "_skip_page_restore_for",
        "_suite_holdings_fp",
        "_ami_hydrated_insight_id",
        "_navigate_to_page",
        "_suite_page_overwrite_source",
        "_suite_holdings_fp_mismatch",
        "_suite_holdings_fp_confirmed",
    ):
        if flag in ss:
            ss.pop(flag, None)
            cleared.append(flag)
    if str(app_key or "").strip().lower() == "investment" and not _ami_return_url_active(st):
        for flag in (SESSION_PENDING_KEY,):
            if flag in ss:
                ss.pop(flag, None)
                cleared.append(flag)
    return cleared


def reconcile_stale_page_navigation(st: Any, app_key: str) -> list[str]:
    """Clear stale AMI deferred-restore flags when not in a live AMI return URL."""
    if _ami_return_url_active(st):
        return []
    return clear_ami_return_deferred_flags(st, app_key)


def mark_ami_return_resume_consumed(st: Any, app_key: str) -> None:
    """Record that AMI return hydration/restore finished so startup may use cloud restore."""
    key = str(app_key or "").strip().lower()
    if key == "math":
        key = "applied_intelligence"
    try:
        from suite_cloud_state import _ami_resume_consumed_flag

        st.session_state[_ami_resume_consumed_flag(key)] = True
    except ImportError:
        st.session_state[f"_ami_resume_consumed_{key}"] = True


def ami_return_navigation_active(st: Any, app_key: str) -> bool:
    """True only when ``suite_ami_insight`` is on the URL (live AMI return), not stale session flags."""
    key = str(app_key or "").strip().lower()
    if key == "math":
        key = "applied_intelligence"
    if not insight_return_query_id(st):
        return False
    return key == "investment" or bool(st.session_state.get(SESSION_RETURN_CONTEXT_KEY))


def _session_holdings_fingerprint(session_state: Any) -> str:
    try:
        import pandas as pd

        from components.beginner_navigation import _holdings_fingerprint

        df = session_state.get("holdings_df")
        if isinstance(df, pd.DataFrame) and not df.empty:
            return str(_holdings_fingerprint(df)).strip()
    except Exception:
        pass
    return ""


def ami_resume_consumed(st: Any, app_key: str) -> bool:
    try:
        from suite_cloud_state import ami_return_resume_consumed

        return ami_return_resume_consumed(st, app_key)
    except Exception:
        key = str(app_key or "").strip().lower()
        return bool(st.session_state.get(f"_ami_resume_consumed_{key}"))


def _sync_investment_insight_tab_keys(
    st: Any,
    app_key: str,
    *,
    insight: dict[str, Any] | None = None,
) -> None:
    if str(app_key or "").strip().lower() != "investment":
        return
    ss = st.session_state
    pending = insight if isinstance(insight, dict) else ss.get(SESSION_PENDING_KEY)
    source_tab = ""
    if isinstance(pending, dict):
        source_tab = _resolve_insight_source_page(pending)
    if not source_tab:
        source_tab = str(ss.get(SESSION_RETURN_PAGE_KEY) or "").strip()
    current = str(ss.get("investment_active_tab") or "").strip()
    if source_tab:
        ss[SESSION_INSIGHT_SOURCE_TAB_KEY] = source_tab
        ss[SESSION_SOURCE_INVESTMENT_TAB_KEY] = source_tab
    ss["current_investment_tab"] = current


def insight_page_scope_decision(
    source_app: str,
    current_page: str,
    insight: dict[str, Any],
) -> dict[str, Any]:
    """Strict page scope decision with skip reason (Investment uses tab equality)."""
    app = str(source_app or insight.get("source_app") or "").strip().lower()
    cur_raw = str(current_page or "").strip()
    insight_page = _resolve_insight_source_page(insight)
    if app == "investment":
        cur = _normalize_investment_tab(cur_raw)
        eligible = INSIGHT_ELIGIBLE_PAGES.get("investment", frozenset())
        cur_eligible = cur in eligible or any(
            _normalize_investment_tab(x) == cur for x in eligible
        )
        should_render = False
        skip_reason = ""
        if not cur_eligible:
            skip_reason = f"current_page_not_eligible ({cur_raw!r})"
        elif not insight_page:
            skip_reason = "missing_insight_source_tab"
        elif _investment_tabs_match(cur_raw, insight_page):
            should_render = True
        else:
            skip_reason = "source_tab_mismatch"
        return {
            "source_page_raw": str(insight.get("source_page") or "").strip() or None,
            "source_page_normalized": insight_page or None,
            "current_page_raw": cur_raw or None,
            "current_page_normalized": cur or None,
            "insight_source_tab": insight_page or None,
            "current_investment_tab": cur_raw or None,
            "should_render_insight_on_page": should_render,
            "render_skip_reason": skip_reason or None,
        }

    cur = _normalize_insight_page(current_page)
    eligible = INSIGHT_ELIGIBLE_PAGES.get(app, frozenset())
    if cur not in eligible and not any(_normalize_insight_page(x) == cur for x in eligible):
        return {
            "should_render_insight_on_page": False,
            "render_skip_reason": f"current_page_not_eligible ({cur!r})",
        }
    insight_page_norm = _normalize_insight_page(insight_page)
    if not insight_page_norm:
        return {
            "should_render_insight_on_page": False,
            "render_skip_reason": "missing_normalized_source_page",
        }
    if insight_page_norm == cur:
        return {"should_render_insight_on_page": True, "render_skip_reason": None}
    if "draft" in insight_page_norm.lower() and "draft" in cur.lower():
        return {"should_render_insight_on_page": True, "render_skip_reason": None}
    return {
        "should_render_insight_on_page": False,
        "render_skip_reason": f"normalized_page_mismatch (insight={insight_page_norm!r}, current={cur!r})",
    }


def should_render_insight_on_page(source_app: str, current_page: str, insight: dict[str, Any]) -> bool:
    """True when pending insight belongs on this page only (strict for Investment)."""
    return bool(
        insight_page_scope_decision(source_app, current_page, insight).get(
            "should_render_insight_on_page"
        )
    )


def _insight_panel_title(source_app: str, insight: dict[str, Any] | None = None) -> str:
    app = str(source_app or (insight or {}).get("source_app") or "").strip().lower()
    if app == "investment":
        return INVESTMENT_INSIGHT_PANEL_TITLE
    return "Applied Math Insight"


def _insight_from_persisted_full_session(app_key: str) -> dict[str, Any]:
    """Load pending insight embedded in Investment ``full_session`` (disk or cloud)."""
    app = str(app_key or "").strip().lower()
    if not app:
        return {}
    try:
        from suite_cloud_state import load_cloud_full_session
        from suite_user_persistence import load_user_state

        cloud_state, _cloud_ts = load_cloud_full_session(app)
        disk_state, _disk_warn = load_user_state(app)
        for state in (cloud_state, disk_state):
            if not isinstance(state, dict):
                continue
            pending = state.get(SESSION_PENDING_KEY)
            if isinstance(pending, dict) and (pending.get("conclusion") or pending.get("question")):
                out = dict(pending)
                out.setdefault("source_app", app)
                if not out.get("insight_id"):
                    out["insight_id"] = str(pending.get("insight_id") or "").strip()
                out["_hydrate_source_hint"] = "full_session_blob"
                return out
    except Exception as exc:
        log.warning("_insight_from_persisted_full_session failed: %s", exc)
    return {}


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

        store_keys = (app, "applied_intelligence")
        if app == "investment":
            store_keys = ("investment", "applied_intelligence")
        for app_key in store_keys:
            rows = load_saved_items(app=app_key, item_type=INSIGHT_ITEM_TYPE, limit=30)
            for row in rows:
                iid = str(row.get("item_key") or "").strip()
                if not iid or iid in excluded:
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                payload_app = str(payload.get("source_app") or "").strip().lower()
                if app == "investment" and payload_app and payload_app != "investment":
                    continue
                if payload_app and payload_app != app and app_key != app:
                    continue
                if payload.get("conclusion") or payload.get("question"):
                    out = dict(payload)
                    out.setdefault("insight_id", iid)
                    out.setdefault("source_app", app)
                    return out
    except Exception as exc:
        log.warning("load_latest_applied_math_insight_for_app failed: %s", exc)
    return _insight_from_persisted_full_session(app)


def _get_dismissed_insight_ids(st: Any) -> set[str]:
    raw = st.session_state.get(SESSION_DISMISSED_KEY)
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(x).strip() for x in raw if str(x).strip()}


def _insight_is_dismissed(st: Any, insight_id: str) -> bool:
    iid = str(insight_id or "").strip()
    return bool(iid and iid in _get_dismissed_insight_ids(st))


def load_dismissed_insight_ids_from_cloud(source_app: str) -> dict[str, str]:
    """Cross-device dismissals: {insight_id: dismissed_at_iso}."""
    app = str(source_app or "").strip().lower()
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
    key = str(app_key or "").strip().lower()
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
    app = str(app_key or "").strip().lower()
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
            title=f"Dismissed insight {iid[:8]}",
            payload=payload,
        )
        remember_saved_item(
            "applied_intelligence",
            INSIGHT_DISMISSAL_ITEM_TYPE,
            iid,
            title=f"Dismissed insight {iid[:8]}",
            payload=payload,
        )
    except Exception as exc:
        log.warning("persist_insight_dismissal_to_cloud failed: %s", exc)



def _pending_insight_valid(st: Any) -> dict[str, Any]:
    pending = st.session_state.get(SESSION_PENDING_KEY)
    if not isinstance(pending, dict):
        return {}
    iid = str(pending.get("insight_id") or "").strip()
    if iid and _insight_is_dismissed(st, iid):
        return {}
    if pending.get("conclusion") or pending.get("question"):
        return pending
    return {}


def insight_exists_in_cloud(source_app: str) -> bool:
    return bool(load_latest_applied_math_insight_for_app(source_app))


def hydrate_applied_math_insight_for_session(st: Any, app_key: str) -> bool:
    """
    Load pending insight from URL, session, or cloud (cross-device phone refresh).

    Display-only — does not change Tests A–E persistence paths.
    """
    key = str(app_key or "").strip().lower()
    ss = st.session_state
    ss["_ami_insight_hydrate_attempted"] = True

    if ss.get("_ami_force_insight_render") or ss.get("_ami_submit_render_insight_this_run"):
        pending = _pending_insight_valid(st)
        if pending:
            ss["_ami_insight_return_preserve"] = True
            ss.pop("_ami_force_insight_render", None)
            ss["_ami_insight_hydrate_success"] = True
            ss["_ami_insight_hydrate_source"] = "submit_staged"
            if key == "investment":
                _sync_investment_insight_tab_keys(st, key, insight=pending)
            return True

    sync_dismissed_insights_from_cloud(st, key)

    url_iid = insight_return_query_id(st)
    if url_iid and _insight_is_dismissed(st, url_iid):
        url_iid = ""
    if url_iid:
        _clear_stale_return_insight_cache(st, url_iid)
        prev = str(ss.get("_ami_hydrated_insight_id") or "").strip()
        pending = _pending_insight_valid(st)
        pending_id = _pending_insight_id(st)
        if prev != url_iid or pending_id != url_iid or not pending:
            apply_ami_insight_from_query(st, key)
        pending = _pending_insight_valid(st)
        if pending:
            ss["_ami_insight_hydrate_success"] = True
            ss["_ami_insight_hydrate_source"] = "url"
            _sync_investment_insight_tab_keys(st, key, insight=pending)
            return True

    pending = _pending_insight_valid(st)
    if pending:
        ss["_ami_insight_hydrate_success"] = True
        ss["_ami_insight_hydrate_source"] = "session"
        _sync_investment_insight_tab_keys(st, key, insight=pending)
        return True

    dismissed = _get_dismissed_insight_ids(st)
    latest = load_latest_applied_math_insight_for_app(key, exclude_ids=dismissed)
    if latest:
        ss[SESSION_PENDING_KEY] = latest
        source_page = _resolve_insight_source_page(latest)
        if source_page:
            ss[SESSION_RETURN_PAGE_KEY] = source_page
        _sync_investment_insight_tab_keys(st, key, insight=latest)
        ss["_ami_insight_hydrate_success"] = True
        hydrate_src = str(latest.get("_hydrate_source_hint") or "cloud_saved_items")
        ss["_ami_insight_hydrate_source"] = hydrate_src
        ss["_ami_hydrated_insight_id"] = str(latest.get("insight_id") or "").strip()
        if key == "investment" and hydrate_src == "cloud_saved_items":
            try:
                from investment_persistent_state import notify_pending_insight_change

                notify_pending_insight_change(st, source="insight_hydrate")
            except Exception:
                pass
        return True

    ss["_ami_insight_hydrate_success"] = False
    ss["_ami_insight_hydrate_source"] = "none"
    return False


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
    analyst_sections: dict[str, Any] = field(default_factory=dict)

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
        sections = getattr(result, "analyst_sections", None)
        if isinstance(sections, dict) and sections:
            key_numbers["analyst_sections"] = dict(sections)

    if route is not None:
        if not model_name:
            model_name = str(getattr(route, "model_name", "") or getattr(route, "problem_type", "") or "").strip()
        if not method:
            method = str(getattr(route, "model_rationale", "") or method).strip()
        pt = str(getattr(route, "problem_type", "") or "").strip()
        if pt:
            key_numbers["problem_type"] = pt

    iid = _insight_id(qid, conclusion or q)
    analyst_sections: dict[str, Any] = {}
    if isinstance(key_numbers.get("analyst_sections"), dict):
        analyst_sections = dict(key_numbers.pop("analyst_sections"))
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
        analyst_sections=analyst_sections,
    )


def build_submit_fallback_insight(
    *,
    question: str,
    source_app: str,
    source_page: str = "",
    question_id: str = "",
    full_analysis_url: str = "",
    resume_key: str = "",
    reason: str = "",
) -> AppliedMathInsight:
    """Stage an immediate insight card when local solver is unavailable."""
    q = str(question or "").strip()
    app = str(source_app or "").strip().lower()
    page = str(source_page or "").strip()
    qid = str(question_id or "").strip()
    why = (
        "Local solver is unavailable on this server — your question was saved and "
        "the full Applied Math analysis opens via **Open full analysis**."
    )
    if reason and reason not in ("ok", "solver_ok", "solver_unavailable", "ami_repo_not_found"):
        why += f" ({reason})"
    elif reason == "ami_repo_not_found":
        why = (
            "Instant solver is not bundled on this deploy — your question was sent to "
            "Command Center. Use **Open full analysis** for the complete answer."
        )
    conclusion = (
        "Question received — open **full analysis** for your Investment Insight answer."
        if app == "investment"
        else "Question received — open full analysis for details."
    )
    iid = _insight_id(qid or hashlib.sha256(q.encode()).hexdigest()[:12], conclusion)
    return AppliedMathInsight(
        insight_id=iid,
        question_id=qid,
        question=q,
        source_app=app,
        source_page=page,
        conclusion=conclusion,
        method="Investment Insight",
        model_name="Applied Math (full analysis)",
        math_summary=why,
        assumptions=[],
        confidence="medium",
        confidence_pct=None,
        key_numbers={"routing_reason": reason or "fallback_insight"},
        full_analysis_url=str(full_analysis_url or "").strip(),
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
            pa = ent.get("player_a_label") or wp.get("sig_player_a_clean")
            pb = ent.get("player_b_label") or wp.get("sig_player_b_clean")
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
    if not isinstance(source_state, dict) or not _source_state_has_restore_payload(source_state):
        return
    ss = st.session_state
    ss[SESSION_RETURN_CONTEXT_KEY] = dict(source_state)
    page = str(
        source_state.get("source_page")
        or source_state.get("page_params", {}).get("page")
        or ""
    ).strip()
    app = str(app_key or source_state.get("source_app") or "").strip().lower()
    if page:
        ss[SESSION_RETURN_PAGE_KEY] = page
        if app == "investment":
            if _source_state_has_restore_payload(source_state) and insight_return_query_id(st):
                ss["_skip_page_restore_for"] = page
            else:
                ss.pop("_skip_page_restore_for", None)
        elif insight_return_query_id(st):
            ss["_skip_page_restore_for"] = page
    try:
        if app == "baseball":
            from applied_math_context import apply_source_state_to_session

            apply_source_state_to_session(ss, source_state)
        elif app == "nba":
            from applied_math_context import apply_source_state_to_session

            apply_source_state_to_session(ss, source_state)
        elif app == "investment":
            from applied_math_context import (
                apply_source_state_to_session,
                investment_source_state_has_portfolio_payload,
            )

            fp_before = _session_holdings_fingerprint(ss)
            has_portfolio = investment_source_state_has_portfolio_payload(source_state)
            apply_source_state_to_session(ss, source_state)
            fp_after = _session_holdings_fingerprint(ss)
            apply_success = has_portfolio
            if not has_portfolio:
                ss["_ami_return_partial_source_state"] = True
                ss["_ami_return_allow_cloud_restore"] = True
                ss["apply_source_state_skip_reason"] = "source_state_missing_portfolio_payload"
            else:
                ss.pop("_ami_return_partial_source_state", None)
                ss.pop("apply_source_state_skip_reason", None)
            ss["_ami_return_source_applied"] = True
            try:
                from investment_persistence_trace import record_ami_apply_trace

                record_ami_apply_trace(
                    st,
                    source_state=source_state,
                    success=apply_success,
                    holdings_fp_before=fp_before,
                    holdings_fp_after=fp_after,
                )
            except Exception:
                pass
    except Exception as exc:
        if app == "investment":
            try:
                from investment_persistence_trace import record_ami_apply_trace

                record_ami_apply_trace(
                    st,
                    source_state=source_state,
                    success=False,
                    error=str(exc),
                    holdings_fp_before=_session_holdings_fingerprint(ss),
                    holdings_fp_after=_session_holdings_fingerprint(ss),
                )
            except Exception:
                pass
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


def _question_id_from_insight_or_session(st: Any, data: dict[str, Any]) -> str:
    qid = str(data.get("question_id") or "").strip()
    if qid:
        return qid
    try:
        return str(st.session_state.get("_suite_ai_question_id") or "").strip()
    except Exception:
        return ""


def resolve_ami_return_source_state_for_store(
    st: Any,
    insight_data: dict[str, Any],
    *,
    source_state: dict[str, Any] | None = None,
    return_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Resolve page-restore source_state for insight store + return URL.

    Question-send snapshot (``load_analytical_question_source_state``) is authoritative
    over partial session/context when present.
    """
    data = dict(insight_data or {})
    app = str(data.get("source_app") or "").strip().lower()
    ss: dict[str, Any] = dict(source_state) if _source_state_has_restore_payload(source_state) else {}

    try:
        session_ss = dict(st.session_state.get("_suite_ai_source_state") or {})
    except Exception:
        session_ss = {}
    if _source_state_has_restore_payload(session_ss) and not _source_state_has_restore_payload(ss):
        ss = session_ss

    for blob_key in ("source_state", "return_context"):
        blob_ss = data.get(blob_key)
        if _source_state_has_restore_payload(blob_ss):
            ss = dict(blob_ss)
            break

    qid = _question_id_from_insight_or_session(st, data)
    if qid:
        try:
            from suite_analytical_question import load_analytical_question_source_state

            loaded = load_analytical_question_source_state(qid)
            if _source_state_has_restore_payload(loaded):
                ss = dict(loaded)
        except Exception:
            pass

    rc = dict(return_context) if isinstance(return_context, dict) else {}
    if not _source_state_has_restore_payload(ss) and app == "investment" and rc:
        page = str(data.get("source_page") or rc.get("page") or "").strip()
        hfp = str(rc.get("holdings_fingerprint") or "").strip()
        ent: dict[str, Any] = {}
        if hfp:
            ent["holdings_fingerprint"] = hfp
        if page or ent:
            ss = {
                "source_app": app,
                "source_page": page,
                "entity_params": ent,
                "widget_params": {},
                "page_params": {"page": page, "tab": page},
            }

    if ss:
        ss.setdefault("source_app", app or ss.get("source_app") or "investment")
        page = str(data.get("source_page") or ss.get("source_page") or "").strip()
        if page:
            ss.setdefault("source_page", page)
            pp = ss.get("page_params")
            if not isinstance(pp, dict):
                pp = {}
                ss["page_params"] = pp
            pp.setdefault("page", page)
            pp.setdefault("tab", page)
    if app == "investment" and ss:
        try:
            from suite_analytical_question import ensure_investment_source_state_portfolio_payload

            session_ss: dict[str, Any] = {}
            try:
                session_ss = dict(st.session_state.get("_suite_ai_source_state") or {})
            except Exception:
                session_ss = {}
            ss = ensure_investment_source_state_portfolio_payload(ss, session_state=session_ss)
        except Exception:
            pass
    return ss


def store_applied_math_insight(
    insight: AppliedMathInsight | dict[str, Any],
    *,
    return_context: dict[str, Any] | None = None,
    source_state: dict[str, Any] | None = None,
    st: Any | None = None,
) -> str:
    """Persist insight for retrieval on source app return."""
    data = insight.to_dict() if isinstance(insight, AppliedMathInsight) else dict(insight)
    iid = str(data.get("insight_id") or "").strip()
    if not iid:
        return ""
    blob = dict(data)
    ss = dict(source_state) if isinstance(source_state, dict) else {}
    if st is not None and not _source_state_has_restore_payload(ss):
        ss = resolve_ami_return_source_state_for_store(
            st,
            data,
            source_state=ss,
            return_context=return_context,
        )
    elif not _source_state_has_restore_payload(ss):
        for key in ("source_state", "return_context"):
            candidate = data.get(key)
            if _source_state_has_restore_payload(candidate):
                ss = dict(candidate)
                break
    qid = str(
        data.get("question_id")
        or blob.get("question_id")
        or (st is not None and _question_id_from_insight_or_session(st, data))
        or ""
    ).strip()
    if qid and not _source_state_has_restore_payload(ss):
        try:
            from suite_analytical_question import load_analytical_question_source_state

            loaded = load_analytical_question_source_state(qid)
            if _source_state_has_restore_payload(loaded):
                ss = dict(loaded)
        except Exception:
            pass
    if _source_state_has_restore_payload(ss):
        blob["source_state"] = ss
        blob["return_context"] = ss
    if qid:
        blob["question_id"] = qid
    store_exc = ""
    store_trace = _ami_insight_store_trace(
        insight_id=iid,
        question_id=qid,
        source_state=ss if isinstance(ss, dict) else {},
        return_context_exists=_source_state_has_restore_payload(ss),
        blob_written_success=False,
        payload_keys=sorted(str(k) for k in blob.keys()),
    )
    _flatten_insight_store_diag_on_blob(blob, store_trace)
    written_ok = False
    try:
        from suite_account import remember_saved_item

        for store_app in (
            str(data.get("source_app") or "applied_intelligence"),
            "applied_intelligence",
            "investment",
        ):
            default_title = "Applied Math insight"
            if str(data.get("source_app") or "").strip().lower() == "investment":
                default_title = "Applied Investment Insight"
            remember_saved_item(
                store_app,
                INSIGHT_ITEM_TYPE,
                iid,
                title=str(data.get("conclusion") or default_title)[:120],
                payload=blob,
            )
        written_ok = True
    except Exception as exc:
        store_exc = str(exc)
        log.warning("remember_saved_item insight failed: %s", exc)
    store_trace["store_blob_written_success"] = written_ok
    store_trace["store_exception"] = store_exc or None
    store_trace["store_payload_has_source_state"] = _source_state_has_restore_payload(blob.get("source_state"))
    store_trace["store_payload_has_question_id"] = bool(str(blob.get("question_id") or "").strip())
    _flatten_insight_store_diag_on_blob(blob, store_trace)
    if written_ok:
        try:
            from suite_account import remember_saved_item

            for store_app in (
                str(data.get("source_app") or "applied_intelligence"),
                "applied_intelligence",
                "investment",
            ):
                default_title = "Applied Investment Insight"
                if str(data.get("source_app") or "").strip().lower() != "investment":
                    default_title = "Applied Math insight"
                remember_saved_item(
                    store_app,
                    INSIGHT_ITEM_TYPE,
                    iid,
                    title=str(data.get("conclusion") or default_title)[:120],
                    payload=blob,
                )
        except Exception as exc:
            log.warning("remember_saved_item insight re-write failed: %s", exc)
    if st is not None:
        st.session_state["_ami_insight_store_trace"] = dict(store_trace)
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
    """Load stored insight by id, preferring blobs that include usable source_state."""
    iid = str(insight_id or "").strip()
    if not iid:
        return {}
    app = str(source_app or "").strip()
    best: dict[str, Any] = {}
    best_score = -1
    seen_apps: set[str] = set()
    try:
        from suite_account import load_saved_items

        for app_key in ([app] if app else []) + [
            "applied_intelligence",
            "investment",
            "baseball",
            "nba",
        ]:
            if app_key in seen_apps:
                continue
            seen_apps.add(app_key)
            rows = load_saved_items(app=app_key, item_type=INSIGHT_ITEM_TYPE, limit=80)
            for row in rows:
                if str(row.get("item_key") or "") != iid:
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                score = _insight_blob_restore_score(payload)
                if score > best_score:
                    best = dict(payload)
                    best_score = score
    except Exception as exc:
        log.warning("load_applied_math_insight failed: %s", exc)
    return best


def load_applied_math_insight_for_question(question_id: str, *, source_app: str = "") -> dict[str, Any]:
    """Load the stored insight tied to a question_id (instant / canonical answer)."""
    qid = str(question_id or "").strip()
    if not qid:
        return {}
    app_filter = str(source_app or "").strip().lower()
    search_apps: list[str] = []
    if app_filter:
        search_apps.append(app_filter)
    for app_key in ("investment", "applied_intelligence"):
        if app_key not in search_apps:
            search_apps.append(app_key)
    best: dict[str, Any] = {}
    best_score = -1
    try:
        from suite_account import load_saved_items

        for app_key in search_apps:
            rows = load_saved_items(app=app_key, item_type=INSIGHT_ITEM_TYPE, limit=100)
            for row in rows:
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                if str(payload.get("question_id") or "") != qid:
                    continue
                score = _insight_blob_restore_score(payload)
                if payload.get("canonical_instant"):
                    score += 10
                if score > best_score:
                    best = dict(payload)
                    best_score = score
    except Exception as exc:
        log.warning("load_applied_math_insight_for_question failed: %s", exc)
    return best



def _resolve_return_source_state(
    st: Any,
    app_key: str,
    insight: dict[str, Any],
    *,
    question_id_qp: str = "",
) -> dict[str, Any]:
    """Best-effort source_state from insight blob, return_context, or question send snapshot."""
    insight = insight if isinstance(insight, dict) else {}
    raw_ss = insight.get("source_state")
    raw_rc = insight.get("return_context")
    for candidate in (raw_ss, raw_rc):
        if isinstance(candidate, dict) and _source_state_has_restore_payload(candidate):
            return dict(candidate)

    qid = str(insight.get("question_id") or question_id_qp or _query_param(st, "suite_ai_question_id") or "").strip()
    if qid:
        try:
            from suite_analytical_question import load_analytical_question_source_state

            loaded = load_analytical_question_source_state(qid)
            if _source_state_has_restore_payload(loaded):
                return dict(loaded)
        except Exception:
            pass

    for candidate in (raw_ss, raw_rc):
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
    return {}


def _record_investment_ami_return_diagnostics(
    st: Any,
    *,
    insight: dict[str, Any] | None = None,
    source_state: dict[str, Any] | None = None,
    applied: bool = False,
    skip_reason: str = "",
    storage_diag: dict[str, Any] | None = None,
) -> None:
    """Session + trace diagnostics for Test E AMI return apply path."""
    ss = st.session_state
    iid = insight_return_query_id(st)
    insight = insight if isinstance(insight, dict) else {}
    source_state = source_state if isinstance(source_state, dict) else {}
    storage_diag = dict(storage_diag or {})
    ss["suite_ami_insight_query_value"] = iid or None
    ss["source_state_exists_on_return"] = _source_state_has_restore_payload(source_state)
    ss["source_state_app"] = str(source_state.get("source_app") or insight.get("source_app") or "").strip() or None
    ss["source_state_keys_on_return"] = sorted(str(k) for k in source_state.keys()) if source_state else None
    for key, value in storage_diag.items():
        ss[key] = value
    if skip_reason:
        ss["apply_source_state_skip_reason"] = skip_reason
    elif applied:
        ss.pop("apply_source_state_skip_reason", None)
    try:
        from investment_persistence_trace import record_investment_ami_return_diagnostics

        record_investment_ami_return_diagnostics(
            st,
            insight=insight,
            source_state=source_state,
            applied=applied,
            skip_reason=skip_reason or None,
            storage_diag=storage_diag,
        )
    except Exception:
        pass


def hydrate_investment_ami_return_state(st: Any, app_key: str = "investment") -> bool:
    """
    Load AMI insight on return URL and apply investment source_state when available.

    When source_state is missing, clears deferred-tab flags so cloud restore can run.
    """
    key = str(app_key or "").strip().lower()
    if key != "investment":
        return False
    iid = insight_return_query_id(st)
    qid_qp = _query_param(st, "suite_ai_question_id")
    if not iid and not qid_qp:
        return False

    ss = st.session_state
    ss["_ami_insight_hydrate_attempted"] = True
    already_applied = bool(ss.get("_ami_return_source_applied"))

    insight: dict[str, Any] = {}
    load_trace: dict[str, Any] = {}
    if iid:
        insight, load_trace = _load_return_insight_for_query(
            st,
            key,
            iid,
            question_id_qp=qid_qp,
        )

    if insight:
        ss[SESSION_PENDING_KEY] = insight
        ss[SESSION_RETURN_PAGE_KEY] = (
            _query_param(st, "suite_page")
            or _resolve_insight_source_page(insight)
            or insight.get("source_page")
            or ""
        )
        ss["_ami_hydrated_insight_id"] = iid or str(insight.get("insight_id") or "")

    storage_diag = diagnose_ami_return_source_state_resolution(
        st,
        key,
        insight,
        question_id_qp=qid_qp,
        load_trace=load_trace,
    )
    source_state = _resolve_return_source_state(st, key, insight, question_id_qp=qid_qp)
    _record_investment_ami_return_diagnostics(
        st,
        insight=insight,
        source_state=source_state,
        storage_diag=storage_diag,
    )

    if already_applied and _source_state_has_restore_payload(ss.get(SESSION_RETURN_CONTEXT_KEY)):
        ss["_ami_insight_hydrate_success"] = True
        ss["_ami_insight_hydrate_source"] = "session"
        return True

    if _source_state_has_restore_payload(source_state):
        from applied_math_context import investment_source_state_has_portfolio_payload

        apply_return_source_state(st, key, source_state)
        ss["_ami_return_source_applied"] = True
        ss["_ami_insight_hydrate_success"] = True
        ss["_ami_insight_hydrate_source"] = "url"
        has_portfolio = investment_source_state_has_portfolio_payload(source_state)
        _record_investment_ami_return_diagnostics(
            st,
            insight=insight,
            source_state=source_state,
            applied=has_portfolio,
            skip_reason=None if has_portfolio else "source_state_missing_portfolio_payload",
        )
        try:
            from investment_persistence_trace import record_ami_return_hydrate_trace

            record_ami_return_hydrate_trace(st, source_state=source_state, insight_id=iid)
        except Exception:
            pass
        _sync_investment_insight_tab_keys(st, key, insight=insight)
        if has_portfolio:
            try:
                from investment_persistent_state import notify_pending_insight_change

                notify_pending_insight_change(st, source="insight_hydrate")
            except Exception:
                pass
        else:
            ss["_ami_defer_insight_autosave"] = True
        return True

    skip_reason = "no_usable_source_state_on_return"
    ss["apply_source_state_skip_reason"] = skip_reason
    ss["_ami_return_allow_cloud_restore"] = True
    ss["_ami_insight_hydrate_success"] = bool(insight)
    ss["_ami_insight_hydrate_source"] = "url_partial" if insight else "none"
    clear_ami_return_deferred_flags(st, key)
    ss.pop("_skip_page_restore_for", None)
    ss.pop("_suite_page_overwrite_source", None)
    _record_investment_ami_return_diagnostics(
        st,
        insight=insight,
        source_state=source_state,
        applied=False,
        skip_reason=skip_reason,
    )
    return False


def commit_ami_return_page_restore(st: Any, app_key: str) -> bool:
    """
    After page navigation is committed, re-apply source_state once so widgets
    pick up pending_compare_players / trend labels before render.
    """
    flag = f"_ami_page_restore_committed_{app_key}"
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
    load_trace: dict[str, Any] = {}
    insight, load_trace = _load_return_insight_for_query(
        st,
        app_key,
        iid,
        question_id_qp=_qp("suite_ai_question_id"),
    )
    st.session_state[SESSION_PENDING_KEY] = insight

    storage_diag = diagnose_ami_return_source_state_resolution(
        st,
        app_key,
        insight,
        question_id_qp=_qp("suite_ai_question_id"),
        load_trace=load_trace,
    )
    source_state = st.session_state.get(SESSION_RETURN_CONTEXT_KEY)
    if not _source_state_has_restore_payload(source_state):
        source_state = _resolve_return_source_state(
            st,
            app_key,
            insight,
            question_id_qp=_qp("suite_ai_question_id"),
        )
    if isinstance(source_state, dict) and _source_state_has_restore_payload(source_state):
        st.session_state[SESSION_RETURN_CONTEXT_KEY] = dict(source_state)
        apply_return_source_state(st, app_key, source_state)
        st.session_state[flag] = True
        mark_ami_return_resume_consumed(st, app_key)
        clear_ami_return_deferred_flags(st, app_key)
        _record_investment_ami_return_diagnostics(
            st,
            insight=insight,
            source_state=source_state,
            applied=True,
            storage_diag=storage_diag,
        )
        return True
    _record_investment_ami_return_diagnostics(
        st,
        insight=insight if isinstance(insight, dict) else {},
        source_state=source_state if isinstance(source_state, dict) else {},
        applied=False,
        skip_reason="commit_ami_return_no_usable_source_state",
        storage_diag=storage_diag,
    )
    return False


def stage_pending_insight(st: Any, insight: AppliedMathInsight | dict[str, Any], *, return_context: dict[str, Any] | None = None) -> None:
    """Write insight into Streamlit session for AMI return button."""
    data = insight.to_dict() if isinstance(insight, AppliedMathInsight) else dict(insight)
    st.session_state[SESSION_PENDING_KEY] = data
    source_page = _resolve_insight_source_page(data) or str(data.get("source_page") or "").strip()
    st.session_state[SESSION_RETURN_PAGE_KEY] = source_page
    if return_context:
        st.session_state[SESSION_RETURN_CONTEXT_KEY] = dict(return_context)
    app = str(data.get("source_app") or "").strip().lower()
    if app == "investment":
        _sync_investment_insight_tab_keys(st, app, insight=data)


def apply_ami_insight_from_query(st: Any, app_key: str) -> bool:
    """On source app load: hydrate pending insight from ?suite_ami_insight= (cloud-backed)."""
    key = str(app_key or "").strip().lower()
    if key == "investment":
        return hydrate_investment_ami_return_state(st, key)

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

    _clear_stale_return_insight_cache(st, iid)
    prev = str(st.session_state.get("_ami_hydrated_insight_id") or "").strip()
    pending_id = _pending_insight_id(st)
    if prev == iid and pending_id == iid and isinstance(st.session_state.get(SESSION_PENDING_KEY), dict):
        return False

    insight = load_applied_math_insight(iid, source_app=app_key)
    if not insight:
        placeholder = (
            "Applied Investment Insight loaded."
            if str(app_key or "").strip().lower() == "investment"
            else "Applied Math insight loaded."
        )
        insight = {"insight_id": iid, "conclusion": placeholder, "question": "", "source_app": app_key}

    st.session_state[SESSION_PENDING_KEY] = insight
    st.session_state[SESSION_RETURN_PAGE_KEY] = (
        _query_param(st, "suite_page") or _resolve_insight_source_page(insight) or insight.get("source_page") or ""
    )

    source_state = _resolve_return_source_state(
        st,
        app_key,
        insight if isinstance(insight, dict) else {},
        question_id_qp=_qp("suite_ai_question_id"),
    )

    if isinstance(source_state, dict) and source_state:
        st.session_state[SESSION_RETURN_CONTEXT_KEY] = dict(source_state)
        apply_return_source_state(st, app_key, source_state)
        if str(app_key or "").strip().lower() == "investment":
            try:
                from investment_persistence_trace import record_ami_return_hydrate_trace

                record_ami_return_hydrate_trace(st, source_state=source_state, insight_id=iid)
            except Exception:
                pass
    elif st.session_state.get(SESSION_RETURN_PAGE_KEY):
        page = st.session_state[SESSION_RETURN_PAGE_KEY]
        st.session_state["_navigate_to_page"] = page
        if insight_return_query_id(st):
            st.session_state["_skip_page_restore_for"] = page

    st.session_state["_ami_hydrated_insight_id"] = iid
    if str(app_key or "").strip().lower() == "investment":
        _sync_investment_insight_tab_keys(st, app_key, insight=insight if isinstance(insight, dict) else {})
        try:
            from investment_persistent_state import notify_pending_insight_change

            notify_pending_insight_change(st, source="insight_hydrate")
        except Exception:
            pass
    return True


def dismiss_applied_math_insight(st: Any, *, app_key: str = "") -> None:
    """Dismiss insight locally and persist dismissal for cross-device sync."""
    pending = st.session_state.get(SESSION_PENDING_KEY)
    iid = ""
    if isinstance(pending, dict):
        iid = str(pending.get("insight_id") or "").strip()
    source_app = str(
        app_key
        or (pending.get("source_app") if isinstance(pending, dict) else "")
        or st.session_state.get("_suite_persist_app_id")
        or "investment"
    ).strip().lower()
    dismissed_at = datetime.now(timezone.utc).isoformat()
    if iid:
        dismissed = _get_dismissed_insight_ids(st)
        dismissed.add(iid)
        st.session_state[SESSION_DISMISSED_KEY] = sorted(dismissed)
        meta = dict(st.session_state.get(SESSION_DISMISSED_AT_KEY) or {})
        if not isinstance(meta, dict):
            meta = {}
        meta[iid] = dismissed_at
        st.session_state[SESSION_DISMISSED_AT_KEY] = meta
    clear_pending_insight(st)
    st.session_state.pop("_ami_hydrated_insight_id", None)
    st.session_state.pop("_ami_insight_active_id", None)
    st.session_state.pop("_ami_force_insight_render", None)
    if iid:
        persist_insight_dismissal_to_cloud(source_app, iid, dismissed_at=dismissed_at)
    st.session_state[SESSION_PERSIST_INSIGHT_DIRTY] = True
    try:
        from investment_persistent_state import autosave_investment_state

        autosave_investment_state(st, trigger="insight_dismiss")
    except Exception:
        pass



def clear_pending_insight(st: Any) -> None:
    st.session_state.pop(SESSION_PENDING_KEY, None)
    st.session_state.pop(SESSION_RETURN_PAGE_KEY, None)
    st.session_state.pop(SESSION_RETURN_CONTEXT_KEY, None)


def render_applied_math_insight_panel(
    st: Any,
    *,
    source_app: str = "",
    insight: dict[str, Any] | None = None,
) -> bool:
    """Display-only insight card on source app pages. Returns True if rendered."""
    data = insight if isinstance(insight, dict) else st.session_state.get(SESSION_PENDING_KEY)
    if not isinstance(data, dict) or not data.get("conclusion"):
        return False
    app = str(source_app or data.get("source_app") or "").strip().lower()

    with st.container(border=True):
        st.markdown(f"#### {_insight_panel_title(app, data)}")
        q = str(data.get("question") or "").strip()
        if q:
            st.markdown(f"**Question:** *{q}*")
        if str(source_app or data.get("source_app") or "").strip().lower() == "investment":
            try:
                from investment_ami_sliders import render_ami_assumption_controls

                if render_ami_assumption_controls(st, data):
                    st.rerun()
            except ImportError:
                pass
        sections = data.get("analyst_sections")
        if not isinstance(sections, dict) or not sections:
            kn = data.get("key_numbers")
            if isinstance(kn, dict) and isinstance(kn.get("analyst_sections"), dict):
                sections = kn.get("analyst_sections")
        if isinstance(sections, dict) and sections:
            from investment_ami_answer_format import render_investment_page_insight_markdown

            exp = str(data.get("experience_mode") or "").lower()
            body = render_investment_page_insight_markdown(
                sections,
                beginner="beginner" in exp,
                include_summary=True,
            )
            if body:
                st.markdown(body)
            else:
                st.markdown(f"**Conclusion:** {data.get('conclusion')}")
        else:
            st.markdown(f"**Conclusion:** {data.get('conclusion')}")
        show_details = str(source_app or data.get("source_app") or "").strip().lower() != "investment"
        method = str(data.get("method") or data.get("model_name") or "").strip()
        if show_details and method:
            st.markdown(f"**Math used:** {method}")
        assumptions = data.get("assumptions") or []
        if show_details and assumptions:
            st.markdown("**Assumptions:**")
            for a in assumptions[:4]:
                st.markdown(f"- {a}")
        conf = data.get("confidence")
        if conf:
            extra = f" ({data.get('confidence_pct')}%)" if data.get("confidence_pct") else ""
            st.caption(f"Confidence: **{conf}**{extra}")
        elif not show_details and isinstance(sections, dict) and sections:
            st.caption("Open full analysis in Applied Intelligence for detailed reasoning and scenarios.")
        url = str(data.get("full_analysis_url") or "").strip()
        c1, c2 = st.columns(2)
        with c1:
            if url:
                st.link_button("Open full analysis →", url, use_container_width=True)
        with c2:
            insight_id = str(data.get("insight_id") or "pending")[:12]
            if st.button("Dismiss insight", key=f"ami_insight_dismiss_{insight_id}", use_container_width=True):
                dismiss_applied_math_insight(st, app_key=app)
                st.rerun()
    return True


def render_suite_applied_math_insight_for_page(
    st: Any,
    *,
    source_app: str,
    source_page: str,
) -> bool:
    """Render insight card when pending insight matches this page (source apps)."""
    app = str(source_app or "").strip().lower()
    if app == "investment":
        hydrate_applied_math_insight_for_session(st, app)

    insight = st.session_state.get(SESSION_PENDING_KEY)
    pending_exists = isinstance(insight, dict) and bool(insight.get("conclusion") or insight.get("question"))
    cloud_exists = insight_exists_in_cloud(app) if app == "investment" else False
    scope = (
        insight_page_scope_decision(app, source_page, insight)
        if isinstance(insight, dict) and pending_exists
        else {"should_render_insight_on_page": False, "render_skip_reason": "no_pending_insight"}
    )
    should_render = bool(scope.get("should_render_insight_on_page"))
    skip_reason = str(scope.get("render_skip_reason") or "")

    if app == "investment":
        _sync_investment_insight_tab_keys(st, app, insight=insight if isinstance(insight, dict) else None)
        try:
            from investment_persistence_trace import record_insight_card_trace

            record_insight_card_trace(
                st,
                insight_exists_cloud=cloud_exists,
                pending_insight_exists=pending_exists,
                insight_card_rendered=should_render,
                insight_render_skipped_reason=skip_reason or None,
                insight_source_tab=scope.get("insight_source_tab")
                or st.session_state.get(SESSION_INSIGHT_SOURCE_TAB_KEY),
                current_investment_tab=str(st.session_state.get("investment_active_tab") or source_page),
                source_investment_tab=st.session_state.get(SESSION_SOURCE_INVESTMENT_TAB_KEY),
                insight_hydrate_attempted=bool(st.session_state.get("_ami_insight_hydrate_attempted")),
                insight_hydrate_success=bool(st.session_state.get("_ami_insight_hydrate_success")),
                insight_hydrate_source=st.session_state.get("_ami_insight_hydrate_source"),
            )
        except Exception:
            pass

    if not pending_exists:
        st.session_state["_ami_insight_render_success"] = False
        st.session_state["_ami_insight_render_skipped_reason"] = "no_pending_insight"
        return False
    if not should_render:
        submit_page = _normalize_investment_tab(
            str(st.session_state.get("_ami_last_submit_source_page") or "")
        ) if app == "investment" else _normalize_insight_page(
            str(st.session_state.get("_ami_last_submit_source_page") or "")
        )
        cur_page = _normalize_investment_tab(source_page) if app == "investment" else _normalize_insight_page(source_page)
        force_render = bool(
            st.session_state.get("_ami_force_insight_render")
            or st.session_state.get("_ami_submit_render_insight_this_run")
            or (
                submit_page
                and cur_page
                and submit_page == cur_page
                and isinstance(insight, dict)
                and insight.get("conclusion")
            )
        )
        if force_render and isinstance(insight, dict) and insight.get("conclusion"):
            should_render = True
            skip_reason = ""
        else:
            st.session_state["_ami_insight_render_skipped_reason"] = skip_reason or "page_scope_blocked"
            st.session_state["_ami_insight_render_success"] = False
            return False
    rendered = render_applied_math_insight_panel(st, source_app=app, insight=insight)
    st.session_state["_ami_insight_render_success"] = bool(rendered)
    if rendered and app == "investment":
        st.session_state["_ami_insight_card_rendered"] = True
        try:
            from suite_cloud_state import _ami_resume_consumed_flag

            st.session_state[_ami_resume_consumed_flag(app)] = True
        except Exception:
            pass
    return rendered


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

    ss = resolve_ami_return_source_state_for_store(
        st,
        data,
        source_state=source_state if isinstance(source_state, dict) else None,
        return_context=return_context,
    )

    blob_data = dict(data)
    page = str(data.get("source_page") or ss.get("source_page") or "").strip()
    if page:
        blob_data["source_page"] = page
        if ss and not ss.get("source_page"):
            ss["source_page"] = page
    qid = str(blob_data.get("question_id") or _question_id_from_insight_or_session(st, blob_data) or "").strip()
    if qid:
        blob_data["question_id"] = qid

    rk = str(resume_key or build_return_resume_key(blob_data, source_state=ss) or "").strip()
    store_applied_math_insight(blob_data, return_context=ss or None, source_state=ss or None, st=st)
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
