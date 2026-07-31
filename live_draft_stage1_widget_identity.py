"""Stage 1 widget identity snapshots for declaration / acceptance diagnostics."""

from __future__ import annotations

import time
from typing import Any

STAGE1_DECLARATION_REGISTRY_KEY = "_solo_stage1_declaration_registry_by_key"


def _safe_streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and getattr(ctx, "session_id", None):
            sid = str(ctx.session_id)
            if len(sid) > 16:
                return sid[:8] + "…" + sid[-4:]
            return sid
    except Exception:
        pass
    return ""


def _full_streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and getattr(ctx, "session_id", None):
            return str(ctx.session_id)
    except Exception:
        pass
    return ""


def _active_script_hash() -> str:
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import ThreadState

        return str(ThreadState.get().active_script_hash or "")[:64]
    except Exception:
        pass
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx:
            return str(getattr(ctx, "page_script_hash", "") or "")[:64]
    except Exception:
        pass
    return ""


def _fragment_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and getattr(ctx, "current_fragment_id", None):
            return str(ctx.current_fragment_id or "")[:80]
    except Exception:
        pass
    return ""


def predict_solo_countdown_component_element_id(user_key: str) -> str:
    """Predict Streamlit element id for solo_countdown_wake (stable user key; name/url only)."""
    if not user_key:
        return ""
    try:
        from streamlit.elements.lib.utils import _compute_element_id
        from solo_countdown_component import _COMPONENT

        name = str(getattr(_COMPONENT, "name", "") or "solo_countdown_wake")
        url = str(getattr(_COMPONENT, "url", "") or "")
        active_hash = _active_script_hash()
        kwargs: dict[str, Any] = {"name": name, "url": url}
        if active_hash:
            kwargs["active_script_hash"] = active_hash
        return _compute_element_id("component_instance", user_key, **kwargs)
    except Exception:
        return ""


def resolve_registered_component_widget_id(st: Any | None, user_key: str) -> str:
    """Best-effort widget id after registration (proto ids use $$ID- prefix)."""
    if not user_key:
        return ""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx:
            for ws in ctx.session_state.get_widget_states():
                wid = str(getattr(ws, "id", "") or "")
                if wid.endswith(f"-{user_key}") or f"-{user_key}" in wid:
                    return wid
    except Exception:
        pass
    predicted = predict_solo_countdown_component_element_id(user_key)
    if predicted and not predicted.startswith("$$"):
        return f"$$ID-{predicted}" if predicted.startswith("ID-") else predicted
    return predicted


def stage1_widget_identity_snapshot(
    st: Any | None,
    session: dict[str, Any],
    *,
    user_key: str,
    component_name: str = "solo_countdown_wake",
    room: dict[str, Any] | None = None,
    expected_token: str = "",
    active_page: str = "",
) -> dict[str, Any]:
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        live = {}
    rid = str(live.get("draft_room_id") or live.get("draft_id") or "").strip().upper()
    pick = live.get("current_pick_index")
    internal_id = resolve_registered_component_widget_id(st, user_key)
    if not internal_id:
        internal_id = predict_solo_countdown_component_element_id(user_key)
    script_seq = int(session.get("_solo_stage1_script_run_seq") or 0)
    return {
        "generated_internal_widget_id": str(internal_id or "")[:200],
        "user_widget_key": str(user_key or "")[:120],
        "component_name": str(component_name or "")[:80],
        "page_script_hash": _active_script_hash(),
        "fragment_id": _fragment_id(),
        "streamlit_session_id_safe": _safe_streamlit_session_id(),
        "streamlit_session_id_full_prefix": _full_streamlit_session_id()[:8],
        "declaration_script_run_seq": script_seq,
        "declaration_ts": time.time(),
        "active_page": str(active_page or session.get("active_page") or "")[:80],
        "room_id": rid,
        "pick_index": pick,
        "expected_token": str(expected_token or "")[:400],
        "widget_active_in_run": bool(internal_id),
    }


def record_declaration_registry_entry(session: dict[str, Any], identity: dict[str, Any]) -> None:
    """Append declaration identity for duplicate-key / supersede analysis."""
    by_key = dict(session.get(STAGE1_DECLARATION_REGISTRY_KEY) or {})
    ukey = str(identity.get("user_widget_key") or "")
    if not ukey:
        return
    rows = list(by_key.get(ukey) or [])
    rows.append(dict(identity))
    by_key[ukey] = rows[-30:]
    session[STAGE1_DECLARATION_REGISTRY_KEY] = by_key


def latest_declaration_identity(session: dict[str, Any], user_key: str) -> dict[str, Any]:
    by_key = session.get(STAGE1_DECLARATION_REGISTRY_KEY) or {}
    rows = list(by_key.get(user_key) or []) if isinstance(by_key, dict) else []
    return dict(rows[-1]) if rows else {}


def declaration_supersede_after_ts(
    session: dict[str, Any],
    user_key: str,
    *,
    after_ts: float,
) -> list[dict[str, Any]]:
    by_key = session.get(STAGE1_DECLARATION_REGISTRY_KEY) or {}
    rows = list(by_key.get(user_key) or []) if isinstance(by_key, dict) else []
    return [r for r in rows if isinstance(r, dict) and float(r.get("declaration_ts") or 0) > after_ts]
