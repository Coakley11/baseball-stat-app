"""Daniel-only (or ?nav_trace=1) page-resolution assignment tracer.

Logs every meaningful nav key write with previous/new/function/reason so we can
see why Historical Explorer still wins after a Live Draft sidebar click.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

NAV_TRACE_LOG_KEY = "_nav_page_assignment_log"
NAV_TRACE_RUN_ID_KEY = "_nav_page_trace_run_id"
NAV_TRACE_ENABLED_KEY = "_nav_page_trace_enabled"
NAV_TRACE_MAX_ENTRIES = 250

_TRACE_KEYS = (
    "active_page",
    "main_sidebar_page",
    "_navigate_to_page",
    "_skip_page_restore_for",
    "_suite_nav_consumed_target",
    "_suite_user_owned_page",
    "_suite_last_persisted_page",
    "_suite_cloud_target_page",
    "_pending_active_page",
    "_suite_page_overwrite_source",
    "active_page_source",
    "_suite_page_user_nav",
)


def _ws_id(session: dict[str, Any]) -> str:
    for key in (
        "_suite_active_workspace_id",
        "suite_workspace_id",
        "_suite_owned_workspace_id",
    ):
        raw = str(session.get(key) or "").strip().lower()
        if raw:
            return raw
    return ""


def _identity_blob(session: dict[str, Any]) -> str:
    parts = [
        _ws_id(session),
        str(session.get("_suite_auth_user_id") or "").strip().lower(),
        str(session.get("_suite_auth_username") or "").strip().lower(),
        str(session.get("_suite_auth_email") or "").strip().lower(),
        str(session.get("_suite_auth_display_name") or "").strip().lower(),
        str(session.get("suite_auth_username") or "").strip().lower(),
    ]
    return " ".join(p for p in parts if p)


def is_nav_page_trace_enabled(session: dict[str, Any] | None, st: Any | None = None) -> bool:
    """True for Daniel workspace/account, forced session flag, or ?nav_trace=1."""
    if not isinstance(session, dict):
        return False
    if session.get(NAV_TRACE_ENABLED_KEY) or session.get("_nav_page_trace_force"):
        return True
    if st is not None:
        try:
            raw = st.query_params.get("nav_trace")
            if isinstance(raw, (list, tuple)):
                raw = raw[0] if raw else ""
            if str(raw or "").strip() in {"1", "true", "yes", "daniel"}:
                session[NAV_TRACE_ENABLED_KEY] = True
                return True
        except Exception:
            pass
    blob = _identity_blob(session)
    ws = _ws_id(session)
    if ws in {"daniel", "user_daniel", "user:daniel"}:
        return True
    if "daniel" in blob:
        return True
    return False


def begin_nav_trace_run(session: dict[str, Any], *, st: Any | None = None, phase: str = "run_start") -> None:
    if not is_nav_page_trace_enabled(session, st):
        return
    run_id = f"{int(time.time() * 1000)}"
    session[NAV_TRACE_RUN_ID_KEY] = run_id
    log = session.setdefault(NAV_TRACE_LOG_KEY, [])
    if not isinstance(log, list):
        log = []
        session[NAV_TRACE_LOG_KEY] = log
    # Keep prior runs briefly, but start a clear marker for this script run.
    entry = {
        "t": time.time(),
        "run_id": run_id,
        "kind": "run_marker",
        "function": "begin_nav_trace_run",
        "reason": phase,
        "workspace_id": _ws_id(session),
        "identity": _identity_blob(session),
        "snapshot": snapshot_nav_keys(session),
    }
    log.append(entry)
    _trim(session)
    _append_disk(session, entry)


def snapshot_nav_keys(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _TRACE_KEYS:
        out[key] = session.get(key)
    pending = session.get("_pending_page_transfer")
    if isinstance(pending, dict):
        out["_pending_page_transfer.target"] = pending.get("target")
        out["_pending_page_transfer.source"] = pending.get("source")
    else:
        out["_pending_page_transfer"] = pending
    pending_resume = session.get("_suite_pending_resume_query")
    if isinstance(pending_resume, dict):
        out["pending_resume.suite_page"] = pending_resume.get("suite_page")
        out["pending_resume.suite_resume"] = pending_resume.get("suite_resume")
    else:
        out["_suite_pending_resume_query"] = pending_resume
    out["_suite_pending_draft_lab_resume"] = session.get("_suite_pending_draft_lab_resume")
    out["_suite_pending_hof_case_resume"] = session.get("_suite_pending_hof_case_resume")
    out["_page_state_last_active"] = session.get("_page_state_last_active")
    return out


def log_nav_event(
    session: dict[str, Any],
    *,
    function: str,
    reason: str,
    key: str = "",
    previous: Any = None,
    new: Any = None,
    extra: dict[str, Any] | None = None,
    st: Any | None = None,
) -> None:
    if not is_nav_page_trace_enabled(session, st):
        return
    entry: dict[str, Any] = {
        "t": time.time(),
        "run_id": session.get(NAV_TRACE_RUN_ID_KEY),
        "kind": "assign" if key else "event",
        "function": str(function or ""),
        "reason": str(reason or ""),
        "key": str(key or ""),
        "previous": previous,
        "new": new,
        "workspace_id": _ws_id(session),
    }
    if extra:
        entry["extra"] = extra
    log = session.setdefault(NAV_TRACE_LOG_KEY, [])
    if not isinstance(log, list):
        log = []
        session[NAV_TRACE_LOG_KEY] = log
    log.append(entry)
    _trim(session)
    _append_disk(session, entry)


def assign_nav_key(
    session: dict[str, Any],
    key: str,
    new_value: Any,
    *,
    function: str,
    reason: str,
    st: Any | None = None,
) -> Any:
    """Assign a nav key and log previous → new when tracing is enabled."""
    prev = session.get(key)
    if new_value is None:
        session.pop(key, None)
        actual = None
    else:
        session[key] = new_value
        actual = new_value
    if is_nav_page_trace_enabled(session, st) and prev != actual:
        log_nav_event(
            session,
            function=function,
            reason=reason,
            key=key,
            previous=prev,
            new=actual,
            st=st,
        )
    return actual


def note_nav_snapshot(
    session: dict[str, Any],
    *,
    function: str,
    reason: str,
    st: Any | None = None,
    **extra: Any,
) -> None:
    if not is_nav_page_trace_enabled(session, st):
        return
    payload = {"snapshot": snapshot_nav_keys(session)}
    if extra:
        payload.update(extra)
    log_nav_event(
        session,
        function=function,
        reason=reason,
        extra=payload,
        st=st,
    )


def resolve_body_page(
    session: dict[str, Any],
    *,
    radio_selected: Any = None,
    normalize_page_key=None,
    function: str = "resolve_body_page",
    st: Any | None = None,
) -> str:
    """
    Final arbiter used immediately before page-body `if active_page == ...` blocks.

    When sidebar/owned page disagrees with active_page, prefer sidebar and log why.
    """
    def _norm(value: Any) -> str:
        if normalize_page_key is not None:
            try:
                return str(normalize_page_key(value) or "").strip()
            except Exception:
                pass
        return str(value or "").strip()

    radio = _norm(radio_selected)
    active = _norm(session.get("active_page"))
    sidebar = _norm(session.get("main_sidebar_page"))
    owned = _norm(session.get("_suite_user_owned_page"))
    skip = _norm(session.get("_skip_page_restore_for"))
    navigate = _norm(session.get("_navigate_to_page"))
    overwrite = str(session.get("_suite_page_overwrite_source") or "")
    user_nav = bool(session.get("_suite_page_user_nav"))

    winner = active or sidebar or radio or "Historical Explorer"
    reason = "active_page"

    # Explicit navigation schedule still pending.
    if navigate and navigate != winner:
        winner = navigate
        reason = "pending _navigate_to_page"

    # Sidebar click / ownership must beat a stale active_page (Daniel ghost render).
    intent = owned or (sidebar if user_nav or owned else "")
    if intent and sidebar and intent == sidebar and active and active != sidebar:
        winner = sidebar
        reason = "sidebar/owned disagree with active_page — prefer sidebar"
        assign_nav_key(
            session,
            "active_page",
            winner,
            function=function,
            reason=reason,
            st=st,
        )
    elif radio and sidebar and radio == sidebar and active and active != sidebar:
        winner = sidebar
        reason = "radio+sidebar disagree with active_page — prefer sidebar"
        assign_nav_key(
            session,
            "active_page",
            winner,
            function=function,
            reason=reason,
            st=st,
        )
    elif radio and active and radio != active and radio == sidebar:
        winner = radio
        reason = "radio selected page overrides stale active_page"
        assign_nav_key(
            session,
            "active_page",
            winner,
            function=function,
            reason=reason,
            st=st,
        )
    else:
        if winner != active:
            assign_nav_key(
                session,
                "active_page",
                winner,
                function=function,
                reason=reason,
                st=st,
            )

    log_nav_event(
        session,
        function=function,
        reason=f"body_page_winner:{reason}",
        key="body_active_page",
        previous=active,
        new=winner,
        extra={
            "radio_selected": radio,
            "sidebar": sidebar,
            "owned": owned,
            "skip": skip,
            "navigate": navigate,
            "overwrite_source": overwrite,
            "user_nav": user_nav,
            "snapshot": snapshot_nav_keys(session),
        },
        st=st,
    )
    return winner


def format_nav_trace_text(session: dict[str, Any], *, limit: int = 80) -> str:
    log = session.get(NAV_TRACE_LOG_KEY) or []
    if not isinstance(log, list) or not log:
        return "(no nav assignment log entries)"
    rows = log[-limit:]
    lines: list[str] = []
    for i, entry in enumerate(rows, 1):
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        fn = entry.get("function")
        reason = entry.get("reason")
        if kind == "assign" or entry.get("key"):
            lines.append(
                f"{i:02d}. {fn} | {entry.get('key')}: {entry.get('previous')!r} → {entry.get('new')!r} | {reason}"
            )
        else:
            lines.append(f"{i:02d}. {fn} | {reason}")
            extra = entry.get("extra") if isinstance(entry.get("extra"), dict) else {}
            snap = extra.get("snapshot") if isinstance(extra, dict) else None
            if isinstance(snap, dict):
                lines.append(
                    "    snap: "
                    + ", ".join(
                        f"{k}={snap.get(k)!r}"
                        for k in (
                            "active_page",
                            "main_sidebar_page",
                            "_navigate_to_page",
                            "_skip_page_restore_for",
                            "_suite_page_overwrite_source",
                            "_suite_user_owned_page",
                        )
                        if k in snap
                    )
                )
    return "\n".join(lines)


def render_nav_assignment_trace(st: Any, session: dict[str, Any] | None = None) -> None:
    ss = session if isinstance(session, dict) else st.session_state
    if not is_nav_page_trace_enabled(ss, st):
        return
    try:
        from portfolio_polish import allow_developer_diagnostic_ui

        if not allow_developer_diagnostic_ui(st):
            return
    except ImportError:
        return
    text = format_nav_trace_text(ss)
    with st.sidebar.expander("Daniel nav assignment trace", expanded=False):
        st.caption(
            "Live page-resolution log (Daniel / ?nav_trace=1). "
            "Shows every assignment that can force Historical Explorer."
        )
        st.code(text, language="text")
        winner = None
        for entry in reversed(ss.get(NAV_TRACE_LOG_KEY) or []):
            if isinstance(entry, dict) and str(entry.get("key") or "") == "body_active_page":
                winner = entry
                break
        if isinstance(winner, dict):
            st.markdown(
                f"**Body winner:** `{winner.get('new')}` — {winner.get('reason')}"
            )


def _trim(session: dict[str, Any]) -> None:
    log = session.get(NAV_TRACE_LOG_KEY)
    if isinstance(log, list) and len(log) > NAV_TRACE_MAX_ENTRIES:
        session[NAV_TRACE_LOG_KEY] = log[-NAV_TRACE_MAX_ENTRIES:]


def _append_disk(session: dict[str, Any], entry: dict[str, Any]) -> None:
    try:
        from suite_user_persistence import DATA_DIR

        ws = _ws_id(session) or "unknown"
        path = Path(DATA_DIR) / "workspaces" / ws / "nav_page_assignment_trace.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass
