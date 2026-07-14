"""Live Draft Room render-pipeline tracer (Daniel / ?ldr_trace=1)."""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any

LDR_TRACE_LOG_KEY = "_live_draft_render_trace_log"
LDR_TRACE_ENABLED_KEY = "_live_draft_render_trace_enabled"
LDR_TRACE_LAST_SECTION_KEY = "_live_draft_render_last_section"
LDR_TRACE_MAX = 400


def is_ldr_trace_enabled(session: dict[str, Any] | None, st: Any | None = None) -> bool:
    if not isinstance(session, dict):
        return False
    if session.get(LDR_TRACE_ENABLED_KEY) or session.get("_live_draft_render_trace_force"):
        return True
    try:
        from fantasy_workflow_trace import is_wf_trace_enabled

        if is_wf_trace_enabled(session, st):
            return True
    except ImportError:
        pass
    if st is not None:
        try:
            raw = st.query_params.get("ldr_trace")
            if isinstance(raw, (list, tuple)):
                raw = raw[0] if raw else ""
            if str(raw or "").strip() in {"1", "true", "yes"}:
                session[LDR_TRACE_ENABLED_KEY] = True
                return True
        except Exception:
            pass
    return False


def _append(session: dict[str, Any], entry: dict[str, Any]) -> None:
    log = session.setdefault(LDR_TRACE_LOG_KEY, [])
    if not isinstance(log, list):
        log = []
        session[LDR_TRACE_LOG_KEY] = log
    log.append(entry)
    if len(log) > LDR_TRACE_MAX:
        session[LDR_TRACE_LOG_KEY] = log[-LDR_TRACE_MAX:]
    try:
        from suite_user_persistence import DATA_DIR

        ws = str(session.get("_suite_active_workspace_id") or "unknown").strip() or "unknown"
        path = Path(DATA_DIR) / "workspaces" / ws / "live_draft_render_trace.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


def ldr_trace(
    session: dict[str, Any],
    *,
    section: str,
    reason: str = "",
    kind: str = "section",
    st: Any | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    if not is_ldr_trace_enabled(session, st):
        return
    entry = {
        "t": time.time(),
        "kind": kind,
        "section": str(section or ""),
        "reason": str(reason or ""),
        "active_page": str(session.get("active_page") or ""),
    }
    if extra:
        entry["extra"] = extra
    if kind in {"section", "section_end", "fragment", "empty", "container"}:
        session[LDR_TRACE_LAST_SECTION_KEY] = str(section or "")
    _append(session, entry)


def ldr_section(session: dict[str, Any], name: str, *, st: Any | None = None, **extra: Any) -> None:
    ldr_trace(session, section=name, reason="enter", kind="section", st=st, extra=extra or None)


def ldr_section_done(session: dict[str, Any], name: str, *, st: Any | None = None, **extra: Any) -> None:
    ldr_trace(session, section=name, reason="complete", kind="section_end", st=st, extra=extra or None)


def ldr_early_return(session: dict[str, Any], name: str, *, reason: str, st: Any | None = None) -> None:
    ldr_trace(session, section=name, reason=f"early_return:{reason}", kind="early_return", st=st)


def ldr_rerun(session: dict[str, Any], name: str, *, reason: str, st: Any | None = None) -> None:
    ldr_trace(session, section=name, reason=f"rerun:{reason}", kind="rerun", st=st)


def ldr_stop(session: dict[str, Any], name: str, *, reason: str, st: Any | None = None) -> None:
    ldr_trace(session, section=name, reason=f"st.stop:{reason}", kind="stop", st=st)


def ldr_exception(session: dict[str, Any], name: str, exc: BaseException, *, st: Any | None = None) -> None:
    ldr_trace(
        session,
        section=name,
        reason=f"exception:{type(exc).__name__}:{exc}",
        kind="exception",
        st=st,
        extra={"traceback": traceback.format_exc()[-1500:]},
    )


def format_ldr_trace_text(session: dict[str, Any], *, limit: int = 120) -> str:
    log = session.get(LDR_TRACE_LOG_KEY) or []
    if not isinstance(log, list) or not log:
        return "(no Live Draft render trace entries)"
    lines = []
    for i, entry in enumerate(log[-limit:], 1):
        if not isinstance(entry, dict):
            continue
        lines.append(
            f"{i:02d}. [{entry.get('kind')}] {entry.get('section')} | {entry.get('reason')}"
        )
    last = session.get(LDR_TRACE_LAST_SECTION_KEY) or ""
    if last:
        lines.append(f"\nLAST SUCCESSFUL SECTION: {last}")
    return "\n".join(lines)


def render_live_draft_render_trace(st: Any, session: dict[str, Any] | None = None) -> None:
    ss = session if isinstance(session, dict) else st.session_state
    if not is_ldr_trace_enabled(ss, st):
        return
    with st.sidebar.expander("Live Draft render trace", expanded=True):
        st.caption("Section-by-section LDR pipeline — find the last section before paint stalls.")
        st.code(format_ldr_trace_text(ss), language="text")
        last = ss.get(LDR_TRACE_LAST_SECTION_KEY)
        if last:
            st.markdown(f"**Last successful section:** `{last}`")
