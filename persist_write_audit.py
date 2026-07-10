"""Durable audit log for workspace persistence writes and blocks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_AUDIT_SESSION_KEY = "_suite_persist_write_audit_tail"
_AUDIT_MAX_SESSION_ENTRIES = 40


def _utc_now_iso() -> str:
    try:
        from activity_time import utc_now_iso

        return utc_now_iso()
    except ImportError:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _audit_file_path(session: dict[str, Any]) -> Path | None:
    try:
        from suite_workspace import get_active_workspace_id, workspace_dir

        st_stub = type("_St", (), {"session_state": session})()
        ws = str(get_active_workspace_id(st=st_stub))
        return workspace_dir(ws) / "persist_write_audit.jsonl"
    except Exception:
        return None


def _workflow_counts(state: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(state, dict):
        return {"draft_archive_count": 0, "league_context_count": 0}
    try:
        from workflow_persist_guard import count_draft_archives, count_league_contexts

        return {
            "draft_archive_count": count_draft_archives(state.get("draft_archive_teams")),
            "league_context_count": count_league_contexts(state.get("fantasy_league_context_state")),
        }
    except ImportError:
        return {"draft_archive_count": 0, "league_context_count": 0}


def _live_cloud_counts(st: Any | None, app_id: str) -> dict[str, int]:
    if st is None:
        return {"draft_archive_count": 0, "league_context_count": 0}
    try:
        from workflow_persist_guard import probe_cloud_workflow_for_workspace, read_live_cloud_draft_probe
        from suite_workspace import get_active_workspace_id

        probe = read_live_cloud_draft_probe(st, app_id)
        draft_count = int(probe.get("draft_archive_count") or 0)
        context_count = 0
        if draft_count <= 0:
            ws = str(get_active_workspace_id(st=st))
            ws_probe = probe_cloud_workflow_for_workspace(ws)
            draft_count = int(ws_probe.get("draft_archive_count") or 0)
            context_count = int(ws_probe.get("league_context_count") or 0)
        return {
            "draft_archive_count": draft_count,
            "league_context_count": context_count,
        }
    except Exception:
        return {"draft_archive_count": 0, "league_context_count": 0}


def record_persist_write_audit(
    st: Any,
    app_id: str,
    *,
    source_function: str,
    save_reason: str = "",
    outgoing_state: dict[str, Any] | None = None,
    blocked: bool = False,
    block_reason: str = "",
    wrote_disk: bool = False,
    wrote_cloud: bool = False,
) -> dict[str, Any]:
    """Append one persistence audit row to workspace disk and session tail."""
    session = st.session_state
    outgoing = _workflow_counts(outgoing_state)
    live_cloud = _live_cloud_counts(st, app_id)
    hydration_complete = bool(
        session.get("_suite_startup_canonical_sync_complete")
        or session.get("_suite_workflow_hydrated_this_run")
        or session.get("_suite_post_auth_workflow_hydrate", {}).get("hydrated")
    )
    gate = session.get("_suite_startup_read_only_gate")
    entry = {
        "at": _utc_now_iso(),
        "app_id": app_id,
        "source_function": str(source_function or "").strip(),
        "save_reason": str(save_reason or "").strip(),
        "blocked": bool(blocked),
        "block_reason": str(block_reason or "").strip(),
        "wrote_disk": bool(wrote_disk),
        "wrote_cloud": bool(wrote_cloud),
        "outgoing_draft_count": int(outgoing.get("draft_archive_count") or 0),
        "outgoing_context_count": int(outgoing.get("league_context_count") or 0),
        "live_cloud_draft_count": int(live_cloud.get("draft_archive_count") or 0),
        "live_cloud_context_count": int(live_cloud.get("league_context_count") or 0),
        "hydration_complete": hydration_complete,
        "startup_gate_active": bool(isinstance(gate, dict) and gate.get("active")),
        "workspace_id": str(
            session.get("_suite_owned_workspace_id") or session.get("_suite_active_workspace_id") or ""
        ).strip(),
    }
    tail = session.get(_AUDIT_SESSION_KEY)
    if not isinstance(tail, list):
        tail = []
    tail.append(entry)
    session[_AUDIT_SESSION_KEY] = tail[-_AUDIT_MAX_SESSION_ENTRIES:]

    path = _audit_file_path(session)
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
        except OSError:
            pass
    return entry


def get_persist_write_audit_tail(session: dict[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
    tail = session.get(_AUDIT_SESSION_KEY)
    if not isinstance(tail, list):
        return []
    rows = [dict(x) for x in tail if isinstance(x, dict)]
    return rows[-max(1, int(limit)) :]
