"""Temporary join-flow tracing for Live Draft Room multiplayer (dev / acceptance)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

JOIN_TRACE_KEY = "_draft_join_trace"
JOIN_TRACE_MAX = 40


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def trace_join_step(session: dict[str, Any], step: str, **fields: Any) -> None:
    """Append a join-flow event to session trace and application log."""
    entry: dict[str, Any] = {"ts": _utc_now_iso(), "step": str(step)}
    for key, value in fields.items():
        if value is not None:
            entry[key] = value
    trace = session.get(JOIN_TRACE_KEY)
    if not isinstance(trace, list):
        trace = []
    trace.append(entry)
    session[JOIN_TRACE_KEY] = trace[-JOIN_TRACE_MAX:]
    try:
        detail = " ".join(f"{k}={v!r}" for k, v in fields.items() if v is not None)
        log.info("draft_join_trace step=%s %s", step, detail)
    except Exception:
        log.info("draft_join_trace step=%s", step)


def join_trace_visible(session: dict[str, Any]) -> bool:
    """Match Developer Mode checkbox gating (eligible workspace + checkbox on)."""
    try:
        from suite_workspace import developer_ui_visible_from_session

        return developer_ui_visible_from_session(session)
    except ImportError:
        return bool(session.get("app_developer_mode"))
    except Exception:
        return bool(session.get("app_developer_mode"))


def get_shared_room_auth_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Snapshot of what multiplayer join checks for authentication."""
    diag: dict[str, Any] = {
        "shared_room_requires_auth": False,
        "auth_ui_enabled": False,
        "authenticated": False,
        "auth_session_flag": False,
        "auth_user_id": "",
        "auth_email": "",
        "join_would_pass": False,
        "join_block_reason": "",
        "backend": "unknown",
        "suite_storage_user_id": "",
        "suite_external_user_id": "",
        "participant_id": "",
    }
    try:
        from draft_room_membership import (
            auth_user_id,
            ensure_authenticated_for_shared_room,
            is_auth_session,
            shared_room_requires_auth,
        )
        from draft_room_shared_state import shared_room_backend_name

        diag["shared_room_requires_auth"] = bool(shared_room_requires_auth())
        diag["backend"] = shared_room_backend_name()
        diag["auth_user_id"] = auth_user_id(session)
        diag["authenticated"] = bool(is_auth_session(session) and diag["auth_user_id"])
        ok, msg = ensure_authenticated_for_shared_room(session)
        diag["join_would_pass"] = bool(ok)
        diag["join_block_reason"] = "" if ok else str(msg)
    except ImportError:
        diag["join_block_reason"] = "draft_room_membership unavailable"
    try:
        from suite_auth import (
            AUTH_SESSION_KEY,
            AUTH_USER_EMAIL_KEY,
            AUTH_USER_ID_KEY,
            is_auth_enabled,
            is_authenticated,
        )

        diag["auth_ui_enabled"] = bool(is_auth_enabled())
        diag["auth_session_flag"] = bool(session.get(AUTH_SESSION_KEY))
        diag["auth_email"] = str(session.get(AUTH_USER_EMAIL_KEY) or "").strip()
        if not diag["auth_user_id"]:
            diag["auth_user_id"] = str(session.get(AUTH_USER_ID_KEY) or "").strip()
        if diag["auth_ui_enabled"]:
            diag["authenticated"] = bool(
                diag["auth_session_flag"] and bool(str(diag["auth_user_id"] or "").strip())
            )
    except ImportError:
        pass
    try:
        from suite_user import get_account_user_id, get_external_user_id

        diag["suite_storage_user_id"] = str(get_account_user_id() or "")
        diag["suite_external_user_id"] = str(get_external_user_id() or "")
    except ImportError:
        pass
    try:
        from draft_room_participant_state import resolve_participant_id

        diag["participant_id"] = resolve_participant_id(session)
    except ImportError:
        pass
    return diag


def render_shared_room_auth_diagnostics(st: Any, session: dict[str, Any]) -> None:
    """Dev-only: show why join may treat the user as logged out."""
    if not join_trace_visible(session):
        return
    diag = get_shared_room_auth_diagnostics(session)
    with st.expander("Shared room auth (dev)", expanded=not diag.get("join_would_pass")):
        st.caption(
            "Multiplayer join requires **Supabase Real Accounts** session keys "
            "(`_suite_auth_session` + `_suite_auth_user_id`), not workspace profile or secrets identity alone."
        )
        rows = [
            ("shared_room_requires_auth", str(diag.get("shared_room_requires_auth"))),
            ("auth_ui_enabled (Real Accounts)", str(diag.get("auth_ui_enabled"))),
            ("authenticated (join check)", str(diag.get("authenticated"))),
            ("auth_session_flag", str(diag.get("auth_session_flag"))),
            ("auth_user_id", diag.get("auth_user_id") or "—"),
            ("auth_email", diag.get("auth_email") or "—"),
            ("backend", diag.get("backend") or "—"),
            ("join_would_pass", str(diag.get("join_would_pass"))),
            ("join_block_reason", diag.get("join_block_reason") or "—"),
            ("suite_storage_user_id", diag.get("suite_storage_user_id") or "—"),
            ("suite_external_user_id", diag.get("suite_external_user_id") or "—"),
            ("participant_id", diag.get("participant_id") or "—"),
        ]
        for label, value in rows:
            st.text(f"{label}: {value}")
        if diag.get("shared_room_requires_auth") and not diag.get("join_would_pass"):
            st.info(
                "Use **Account Settings → Sign-in & password** (Command Center apps) or enable "
                "Real Accounts here, then sign in with email/password on this device."
            )


def render_join_attempt_diagnostics(st: Any, session: dict[str, Any]) -> None:
    """Developer Mode: last join attempt fields (lookup, claim, workspace isolation)."""
    if not join_trace_visible(session):
        return
    diag = session.get("_draft_room_join_attempt_diag")
    load = session.get("_draft_room_join_load_diag")
    if not isinstance(diag, dict) and not isinstance(load, dict):
        return
    diag = dict(diag or {})
    load = dict(load or {})
    with st.expander("Join attempt diagnostics (Developer Mode)", expanded=True):
        rows = [
            ("entered / normalized code", diag.get("normalized_code") or load.get("room_code_queried") or "—"),
            ("lookup backend", diag.get("lookup_backend") or load.get("backend") or "—"),
            ("lookup fallback used", str(diag.get("lookup_fallback_used", load.get("lookup_fallback_used")))),
            ("matched room ID", diag.get("matched_room_id") or "—"),
            ("room owner", diag.get("room_owner") or "—"),
            ("room status", diag.get("room_status") or "—"),
            ("auth user ID", diag.get("auth_user_id") or "—"),
            ("owned workspace (before)", diag.get("owned_workspace_before") or "—"),
            ("owned workspace (after)", diag.get("owned_workspace_after") or "—"),
            ("workspace unchanged", str(diag.get("workspace_unchanged"))),
            ("selected team", diag.get("selected_team") or "—"),
            ("invitation required", str(diag.get("invitation_required", False))),
            ("claim / join result", diag.get("claim_result") or ("ok" if diag.get("participant_write_ok") else "—")),
            ("participant write ok", str(diag.get("participant_write_ok"))),
            ("presence write ok", str(diag.get("presence_write_ok"))),
            ("room revision", str(diag.get("room_revision") if diag.get("room_revision") is not None else "—")),
            ("navigation target", diag.get("navigation_target") or "—"),
            ("load found", str(load.get("found"))),
            ("load reason", load.get("reason") or "—"),
        ]
        for label, value in rows:
            st.text(f"{label}: {value}")


def render_join_trace_panel(st: Any, session: dict[str, Any]) -> None:
    if not join_trace_visible(session):
        return
    trace = session.get(JOIN_TRACE_KEY)
    if not isinstance(trace, list) or not trace:
        return
    with st.expander("Join flow trace (dev)", expanded=False):
        for row in reversed(trace[-20:]):
            if not isinstance(row, dict):
                continue
            parts = [str(row.get("ts") or "")[:19], str(row.get("step") or "")]
            extras = {k: v for k, v in row.items() if k not in ("ts", "step")}
            if extras:
                parts.append(str(extras))
            st.caption(" · ".join(p for p in parts if p))
