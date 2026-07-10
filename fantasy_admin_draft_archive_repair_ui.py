"""Cloud-only one-shot admin repair trigger (Streamlit query param)."""

from __future__ import annotations

import json
from typing import Any

from fantasy_admin_draft_archive_repair import (
    DEFAULT_REPAIR_LEAGUE_ID,
    DEFAULT_REPAIR_WORKSPACES,
    run_league_draft_archive_repair,
)

_SESSION_RAN_KEY = "_suite_admin_draft_archive_repair_ran"
_SESSION_TRACE_KEY = "_suite_admin_draft_archive_repair_trace"


def _query_repair_token(st: Any) -> str:
    try:
        raw = st.query_params.get("admin_draft_archive_repair", "")
        if isinstance(raw, list):
            return str(raw[0] if raw else "").strip()
        return str(raw or "").strip()
    except Exception:
        return ""


def _secrets_repair_token(st: Any) -> str:
    try:
        block = st.secrets.get("suite_activity")
        if block is None:
            return ""
        return str(block.get("admin_draft_archive_repair_token") or "").strip()
    except Exception:
        return ""


def _authorized_repair_token(st: Any) -> str:
    secret_token = _secrets_repair_token(st)
    if secret_token:
        return secret_token
    return DEFAULT_REPAIR_LEAGUE_ID


def _parse_repair_request(st: Any) -> tuple[str, bool, bool] | None:
    """Return (league_id, dry_run, force) when query requests repair; else None."""
    token = _query_repair_token(st)
    if not token:
        return None
    expected = _authorized_repair_token(st)
    force = token.endswith(":force") or token.endswith(":dry:force")
    base = token
    if force:
        base = base.replace(":force", "")
    dry = base.endswith(":dry")
    if dry:
        base = base[:-4]
    if base != expected and token != expected and token.replace(":dry", "") != expected:
        return None
    league_id = DEFAULT_REPAIR_LEAGUE_ID if base == expected else base
    return league_id, dry, force


def maybe_run_cloud_admin_draft_archive_repair(st: Any) -> dict[str, Any] | None:
    """
    Run admin repair when URL includes ?admin_draft_archive_repair=<token>[:dry][:force].

    Token defaults to DEFAULT_REPAIR_LEAGUE_ID; override via
    [suite_activity].admin_draft_archive_repair_token in Streamlit secrets.
    Only executes when cloud storage is configured (Streamlit Cloud prod).
    """
    try:
        from suite_storage_config import cloud_storage_enabled
    except ImportError:
        return None
    if not cloud_storage_enabled():
        return None

    parsed = _parse_repair_request(st)
    if not parsed:
        return None

    league_id, dry_run, force = parsed
    ss = st.session_state
    if ss.get(_SESSION_RAN_KEY) and not force:
        cached = ss.get(_SESSION_TRACE_KEY)
        return cached if isinstance(cached, dict) else None

    trace = run_league_draft_archive_repair(
        league_id=league_id,
        workspaces=DEFAULT_REPAIR_WORKSPACES,
        dry_run=dry_run,
        write_disk=True,
    )
    ss[_SESSION_RAN_KEY] = True
    ss[_SESSION_TRACE_KEY] = trace
    return trace


def render_cloud_admin_draft_archive_repair_banner(st: Any) -> None:
    """Show repair trace when query-param repair ran this session."""
    trace = st.session_state.get(_SESSION_TRACE_KEY)
    if not isinstance(trace, dict):
        return
    ok = bool(trace.get("ok"))
    title = "Admin draft archive repair (dry-run)" if trace.get("dry_run") else "Admin draft archive repair"
    if ok:
        st.success(f"{title} — OK")
    else:
        st.error(f"{title} — FAILED")
    with st.expander("Repair trace", expanded=True):
        st.code(json.dumps(trace, indent=2, default=str), language="json")
