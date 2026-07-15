"""Trace Fantasy / Draft workflow initialization that can abort page render.

Enabled for Daniel workspace (same gate as nav_page_trace) or ?wf_trace=1.
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any, Callable

WF_TRACE_LOG_KEY = "_fantasy_wf_assignment_log"
WF_TRACE_ENABLED_KEY = "_fantasy_wf_trace_enabled"
WF_TRACE_MAX = 300
WF_PAGE_ENTER_KEY = "_fantasy_wf_page_entered"
WF_SUPPRESS_PREFS_RERUN_KEY = "_fantasy_wf_suppress_prefs_app_rerun"

FANTASY_WF_PAGES = frozenset(
    {
        "Live Draft Room",
        "Draft Room Simulator",
        "Draft Assistant Simulator",
        "Draft Lab / Simulation",
        "Saved Draft Library",
        "Fantasy Standings Tracker",
        "Fantasy Lineup Assistant",
        "Waiver Wire / Add-Drop Center",
        "Fantasy Sleepers & Busts",
    }
)


def _ws_id(session: dict[str, Any]) -> str:
    for key in ("_suite_active_workspace_id", "suite_workspace_id", "_suite_owned_workspace_id"):
        raw = str(session.get(key) or "").strip().lower()
        if raw:
            return raw
    return ""


def is_wf_trace_enabled(session: dict[str, Any] | None, st: Any | None = None) -> bool:
    if not isinstance(session, dict):
        return False
    if session.get(WF_TRACE_ENABLED_KEY) or session.get("_fantasy_wf_trace_force"):
        return True
    try:
        from nav_page_trace import is_nav_page_trace_enabled

        if is_nav_page_trace_enabled(session, st):
            return True
    except ImportError:
        pass
    if st is not None:
        try:
            raw = st.query_params.get("wf_trace")
            if isinstance(raw, (list, tuple)):
                raw = raw[0] if raw else ""
            if str(raw or "").strip() in {"1", "true", "yes"}:
                session[WF_TRACE_ENABLED_KEY] = True
                return True
        except Exception:
            pass
    ws = _ws_id(session)
    if ws in {"daniel", "user_daniel", "user:daniel"}:
        return True
    blob = " ".join(
        str(session.get(k) or "").lower()
        for k in (
            "_suite_auth_user_id",
            "_suite_auth_username",
            "_suite_auth_email",
            "_suite_auth_display_name",
        )
    )
    return "daniel" in blob


def log_wf(
    session: dict[str, Any],
    *,
    function: str,
    reason: str,
    page: str = "",
    previous: Any = None,
    new: Any = None,
    key: str = "",
    extra: dict[str, Any] | None = None,
    st: Any | None = None,
) -> None:
    if not is_wf_trace_enabled(session, st):
        return
    entry: dict[str, Any] = {
        "t": time.time(),
        "kind": "wf",
        "function": str(function or ""),
        "reason": str(reason or ""),
        "page": str(page or session.get("active_page") or ""),
        "key": str(key or ""),
        "previous": previous,
        "new": new,
        "workspace_id": _ws_id(session),
    }
    if extra:
        entry["extra"] = extra
    log = session.setdefault(WF_TRACE_LOG_KEY, [])
    if not isinstance(log, list):
        log = []
        session[WF_TRACE_LOG_KEY] = log
    log.append(entry)
    if len(log) > WF_TRACE_MAX:
        session[WF_TRACE_LOG_KEY] = log[-WF_TRACE_MAX:]
    try:
        from suite_user_persistence import DATA_DIR

        path = Path(DATA_DIR) / "workspaces" / (_ws_id(session) or "unknown") / "fantasy_workflow_trace.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


def mark_fantasy_page_enter(session: dict[str, Any], page: str, *, st: Any | None = None) -> None:
    page = str(page or "").strip()
    if page not in FANTASY_WF_PAGES:
        return
    prev = str(session.get(WF_PAGE_ENTER_KEY) or "").strip()
    session[WF_PAGE_ENTER_KEY] = page
    # Suppress prefs full-app rerun while the new fantasy page paints.
    session[WF_SUPPRESS_PREFS_RERUN_KEY] = True
    session["_fantasy_wf_page_enter_at"] = time.time()
    log_wf(
        session,
        function="mark_fantasy_page_enter",
        reason="page_entered",
        page=page,
        key="page",
        previous=prev,
        new=page,
        st=st,
    )


def prefs_app_rerun_allowed(session: dict[str, Any]) -> tuple[bool, str]:
    """Gate for account_fantasy_preferences full-app st.rerun()."""
    if session.get(WF_SUPPRESS_PREFS_RERUN_KEY):
        return False, "suppressed_for_fantasy_page_enter"
    if session.get("_suite_page_user_nav"):
        return False, "suppressed_for_user_nav"
    now = time.time()
    enter_at = float(session.get("_fantasy_wf_page_enter_at") or 0.0)
    if enter_at and (now - enter_at) < 8.0:
        return False, "suppressed_within_8s_of_page_enter"
    last = float(session.get("_account_fantasy_prefs_last_app_rerun_at") or 0.0)
    if last and (now - last) < 20.0:
        return False, "cooldown_20s"
    return True, "allowed"


def note_prefs_app_rerun(session: dict[str, Any], *, reason: str, st: Any | None = None) -> None:
    session["_account_fantasy_prefs_last_app_rerun_at"] = time.time()
    log_wf(
        session,
        function="account_fantasy_preferences._tick",
        reason=f"st.rerun(scope=app):{reason}",
        key="rerun",
        previous=False,
        new=True,
        st=st,
    )


def note_rerun(
    session: dict[str, Any],
    *,
    function: str,
    reason: str,
    page: str = "",
    st: Any | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    log_wf(
        session,
        function=function,
        reason=f"rerun:{reason}",
        page=page,
        key="rerun",
        previous=False,
        new=True,
        extra=extra,
        st=st,
    )


def note_stop(
    session: dict[str, Any],
    *,
    function: str,
    reason: str,
    page: str = "",
    st: Any | None = None,
) -> None:
    log_wf(
        session,
        function=function,
        reason=f"st.stop:{reason}",
        page=page,
        key="stop",
        previous=False,
        new=True,
        st=st,
    )


def note_suppressed_exception(
    session: dict[str, Any],
    *,
    function: str,
    exc: BaseException,
    page: str = "",
    st: Any | None = None,
) -> None:
    log_wf(
        session,
        function=function,
        reason=f"suppressed_exception:{type(exc).__name__}:{exc}",
        page=page,
        key="exception",
        extra={"traceback": traceback.format_exc()[-1500:]},
        st=st,
    )


def traced_call(
    session: dict[str, Any],
    *,
    function: str,
    reason: str,
    page: str = "",
    st: Any | None = None,
    fn: Callable[[], Any],
) -> Any:
    log_wf(session, function=function, reason=f"begin:{reason}", page=page, st=st)
    try:
        out = fn()
        log_wf(
            session,
            function=function,
            reason=f"end:{reason}",
            page=page,
            extra={"result_type": type(out).__name__},
            st=st,
        )
        return out
    except Exception as exc:
        note_suppressed_exception(session, function=function, exc=exc, page=page, st=st)
        raise


def format_wf_trace_text(session: dict[str, Any], *, limit: int = 100) -> str:
    log = session.get(WF_TRACE_LOG_KEY) or []
    if not isinstance(log, list) or not log:
        return "(no fantasy workflow trace entries)"
    lines: list[str] = []
    for i, entry in enumerate(log[-limit:], 1):
        if not isinstance(entry, dict):
            continue
        page = entry.get("page") or ""
        key = entry.get("key") or ""
        prev = entry.get("previous")
        new = entry.get("new")
        if key:
            lines.append(
                f"{i:02d}. [{page}] {entry.get('function')} | {key}: {prev!r} → {new!r} | {entry.get('reason')}"
            )
        else:
            lines.append(f"{i:02d}. [{page}] {entry.get('function')} | {entry.get('reason')}")
    return "\n".join(lines)


def render_fantasy_workflow_trace(st: Any, session: dict[str, Any] | None = None) -> None:
    ss = session if isinstance(session, dict) else st.session_state
    if not is_wf_trace_enabled(ss, st):
        return
    try:
        from portfolio_polish import allow_developer_diagnostic_ui

        if not allow_developer_diagnostic_ui(st):
            return
    except ImportError:
        return
    if str(ss.get("active_page") or "") not in FANTASY_WF_PAGES and not ss.get(WF_TRACE_LOG_KEY):
        return
    with st.sidebar.expander("Fantasy workflow init trace", expanded=False):
        st.caption(
            "Logs fantasy/draft page enter, restores, and any rerun/stop that can abort render."
        )
        st.code(format_wf_trace_text(ss), language="text")
        # Highlight last exit/rerun
        for entry in reversed(ss.get(WF_TRACE_LOG_KEY) or []):
            if not isinstance(entry, dict):
                continue
            reason = str(entry.get("reason") or "")
            if reason.startswith("rerun:") or reason.startswith("st.stop:") or "exited" in reason:
                st.markdown(f"**Last abort/exit:** `{entry.get('function')}` — {reason}")
                break
