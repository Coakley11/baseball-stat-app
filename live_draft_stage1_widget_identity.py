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


def read_actual_registered_widget_id(st: Any | None, user_key: str) -> tuple[str, str]:
    """Return (widget_id, source) from Streamlit runtime widget states only."""
    if not user_key:
        return "", "missing_user_key"
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx:
            matches: list[str] = []
            for ws in ctx.session_state.get_widget_states():
                wid = str(getattr(ws, "id", "") or "")
                if wid.endswith(f"-{user_key}") or f"-{user_key}" in wid:
                    matches.append(wid)
            if matches:
                return matches[-1], "streamlit_session_widget_states"
    except Exception:
        pass
    return "", "widget_state_unavailable"


def resolve_registered_component_widget_id(st: Any | None, user_key: str) -> str:
    """Legacy helper: prefer actual runtime id, else predicted (for non-authoritative use)."""
    actual, _ = read_actual_registered_widget_id(st, user_key)
    if actual:
        return actual
    predicted = predict_solo_countdown_component_element_id(user_key)
    if predicted and not predicted.startswith("$$"):
        return f"$$ID-{predicted}" if not predicted.startswith("$$ID-") else predicted
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
    after_mount: bool = False,
) -> dict[str, Any]:
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        live = {}
    rid = str(live.get("draft_room_id") or live.get("draft_id") or "").strip().upper()
    pick = live.get("current_pick_index")
    predicted_raw = predict_solo_countdown_component_element_id(user_key)
    predicted = predicted_raw
    if predicted_raw and not predicted_raw.startswith("$$"):
        predicted = f"$$ID-{predicted_raw}" if not predicted_raw.startswith("$$ID-") else predicted_raw
    actual, actual_source = read_actual_registered_widget_id(st, user_key)
    if actual_source == "streamlit_session_widget_states":
        authority = "actual_registered_id"
    elif predicted:
        authority = "predicted_id" if after_mount else "predicted_id_pre_mount"
    else:
        authority = "missing"
    # Deprecated ledger alias: actual runtime id only — never copy predicted_element_id here.
    legacy_generated = str(actual or "")[:200]
    script_seq = int(session.get("_solo_stage1_script_run_seq") or 0)
    try:
        from solo_countdown_component import _COMPONENT, get_component_frontend_dir

        component_path = str(get_component_frontend_dir())
        component_url = str(getattr(_COMPONENT, "url", "") or "")
    except Exception:
        component_path = ""
        component_url = ""
    return {
        "actual_registered_widget_id": str(actual or "")[:200],
        "actual_registered_id_source": actual_source,
        "predicted_element_id": str(predicted or "")[:200],
        "registered_widget_id_authority": authority,
        "generated_internal_widget_id": str(legacy_generated or "")[:200],
        "user_widget_key": str(user_key or "")[:120],
        "component_name": str(component_name or "")[:80],
        "component_frontend_path": component_path[:200],
        "component_url": component_url[:200],
        "page_script_hash": _active_script_hash(),
        "fragment_id": _fragment_id(),
        "streamlit_session_id_safe": _safe_streamlit_session_id(),
        "streamlit_session_id_full_prefix": _full_streamlit_session_id()[:8],
        "declaration_script_run_seq": script_seq,
        "declaration_ts": time.time(),
        "after_mount": after_mount,
        "active_page": str(active_page or session.get("active_page") or "")[:80],
        "room_id": rid,
        "pick_index": pick,
        "expected_token": str(expected_token or "")[:400],
        "widget_active_in_run": bool(actual or legacy_generated),
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
