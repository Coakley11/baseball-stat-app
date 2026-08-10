"""Control Center pause-sibling callsite diagnostics (no sibling module import)."""

from __future__ import annotations

import json
import time
from typing import Any

CALLSITE_DOM_ID = "solo-stage1-pause-sibling-callsite"
CALLSITE_IMPL_REV = "stage1_pause_sibling_callsite_v1"


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def _full_app_run_seq(session: dict[str, Any]) -> int:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _thread_fragment_id_safe() -> str:
    try:
        from live_draft_stage1_fragment_identity_runtime import snapshot_fragment_identity

        snap = snapshot_fragment_identity(phase="SIBLING_CALLSITE", widget_user_key="")
        return str(snap.get("thread_state_fragment_id") or "")[:64]
    except Exception:
        return ""


def _solo_query_evidence(st: Any | None, session: dict[str, Any]) -> dict[str, Any]:
    raw = ""
    qp_flag = False
    session_latched = bool(session.get("_solo_component_diag_enabled"))
    try:
        from live_draft_solo_component_diagnostics import SOLO_DIAG_ENABLED_KEY, _qp_flag, _qp_get

        raw = _qp_get(st, "solo_component_diag") if st is not None else ""
        qp_flag = bool(st is not None and _qp_flag(st, "solo_component_diag"))
        session_latched = bool(session.get(SOLO_DIAG_ENABLED_KEY) or session_latched)
    except ImportError:
        try:
            from live_draft_cloud_diagnostics import _qp_flag, _qp_get

            raw = _qp_get(st, "solo_component_diag") if st is not None else ""
            qp_flag = bool(st is not None and _qp_flag(st, "solo_component_diag"))
        except ImportError:
            pass
    return {
        "solo_component_diag_raw": str(raw)[:32],
        "solo_component_diag_qp_flag": qp_flag,
        "session_solo_component_diag_enabled": session_latched,
    }


def emit_sibling_callsite_marker(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    room_status: str = "",
    import_attempted: bool = False,
    import_ok: bool | None = None,
    import_error: str = "",
) -> None:
    """SIBLING_CALLSITE_ENTRY — emitted before sibling module import."""
    room_id = str(room.get("draft_room_id") or room.get("room_id") or "").strip()
    q = _solo_query_evidence(st, session)
    payload: dict[str, Any] = {
        "event": "SIBLING_CALLSITE_ENTRY",
        "ts": time.time(),
        "room_id": room_id,
        "room_status": str(room_status or room.get("status") or "")[:32],
        "streamlit_session_id": _streamlit_session_id(),
        "thread_fragment_id": _thread_fragment_id_safe(),
        "full_app_run_seq": _full_app_run_seq(session),
        "import_attempted": bool(import_attempted),
        "import_ok": import_ok,
        "import_error": str(import_error or "")[:240],
        **q,
    }
    safe = lambda s: str(s or "").replace('"', "'")[:160]
    blob = json.dumps(payload, default=str)[:8000].replace('"', "'")
    st.markdown(
        f'<div id="{CALLSITE_DOM_ID}" '
        f'data-event="SIBLING_CALLSITE_ENTRY" '
        f'data-import-attempted="{1 if import_attempted else 0}" '
        f'data-import-ok="{"" if import_ok is None else (1 if import_ok else 0)}" '
        f'data-room-id="{safe(room_id)}" '
        f'data-streamlit-session-id="{safe(_streamlit_session_id())}" '
        f'data-impl-rev="{CALLSITE_IMPL_REV}" '
        f'data-json="{blob}"></div>',
        unsafe_allow_html=True,
    )
