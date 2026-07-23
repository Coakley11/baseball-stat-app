"""Production Solo expire call-chain instrumentation (one authoritative owner)."""

from __future__ import annotations

import json
import time
from typing import Any

SOLO_EXPIRE_CHAIN_KEY = "_solo_expire_chain_log"
SOLO_EXPIRE_OWNER_KEY = "_solo_expire_owner"
SOLO_EXPIRE_COMMIT_COUNT_KEY = "_solo_expire_chain_commits"
MAX_CHAIN = 120


def solo_expire_owner(session: dict[str, Any]) -> str:
    """Single server expiration owner: wake on Cloud, fragment locally."""
    cached = str(session.get(SOLO_EXPIRE_OWNER_KEY) or "").strip()
    if cached in ("wake", "fragment"):
        return cached
    try:
        from live_draft_cloud_diagnostics import streamlit_cloud_runtime

        owner = "wake" if streamlit_cloud_runtime() else "fragment"
    except ImportError:
        owner = "fragment"
    session[SOLO_EXPIRE_OWNER_KEY] = owner
    return owner


def note_solo_expire_chain(
    session: dict[str, Any],
    stage: str,
    *,
    source: str = "",
    **fields: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ts": time.time(),
        "stage": str(stage),
        "source": str(source or ""),
        **fields,
    }
    log = list(session.get(SOLO_EXPIRE_CHAIN_KEY) or [])
    log.append(row)
    session[SOLO_EXPIRE_CHAIN_KEY] = log[-MAX_CHAIN:]
    if stage in ("commit_confirmed", "pick_committed"):
        session[SOLO_EXPIRE_COMMIT_COUNT_KEY] = int(session.get(SOLO_EXPIRE_COMMIT_COUNT_KEY) or 0) + 1
    return row


EXPECTED_CHAIN_STAGES = (
    "browser_deadline_crossed",
    "component_value_sent",
    "component_value_received",
    "wake_received",
    "expire_entered",
    "deadline_confirmed_expired",
    "autopick_attempted",
    "pick_committed",
    "canonical_state_updated",
    "new_deadline_installed",
    "page_repaint_completed",
)


def first_missing_chain_stage(stages: list[str]) -> str:
    seen = set(stages)
    for stage in EXPECTED_CHAIN_STAGES:
        if stage not in seen:
            return stage
    return ""


def solo_expire_chain_summary(session: dict[str, Any]) -> dict[str, Any]:
    log = list(session.get(SOLO_EXPIRE_CHAIN_KEY) or [])
    stages = [str(r.get("stage") or "") for r in log if isinstance(r, dict)]
    return {
        "owner": solo_expire_owner(session),
        "commits": int(session.get(SOLO_EXPIRE_COMMIT_COUNT_KEY) or 0),
        "last_stage": stages[-1] if stages else "",
        "stages_tail": stages[-24:],
        "rows": len(log),
        "log_tail": log[-12:],
    }


def render_solo_deploy_probe(st: Any) -> None:
    """Always-on hidden deploy marker for production soak deploy polling."""
    try:
        from suite_deploy_marker import format_build_label, resolve_git_commit_short
    except ImportError:
        return
    build = format_build_label()
    sha = resolve_git_commit_short()
    st.markdown(
        f"<!-- solo-deploy-build sha={sha} build={build} -->\n"
        f'<div id="solo-deploy-build" data-build="{build}" data-sha="{sha}"></div>',
        unsafe_allow_html=True,
    )
    try:
        import streamlit.components.v1 as components

        components.html(
            f'<div id="solo-deploy-build" data-build="{build}" data-sha="{sha}"></div>',
            height=0,
        )
    except ImportError:
        pass


def render_solo_expire_chain_probe(st: Any, session: dict[str, Any], room: dict[str, Any] | None) -> None:
    """Hidden DOM probes for production soak (no ld_accept required)."""
    render_solo_deploy_probe(st)
    try:
        from live_draft_solo_component_diagnostics import render_solo_component_mount_probe

        render_solo_component_mount_probe(st, session, room)
    except ImportError:
        pass
    try:
        from live_draft_solo_timer import is_solo_live_draft
    except ImportError:
        return
    if not isinstance(room, dict) or not is_solo_live_draft(session, room):
        return
    if str(room.get("status") or "") not in ("in_progress", "paused"):
        return
    summary = solo_expire_chain_summary(session)
    chain_s = "|".join(summary.get("stages_tail") or [])
    payload = json.dumps(summary.get("log_tail") or [], default=str)[:4000]
    comp_diag = session.get("_solo_component_diag") or {}
    comp_return = str(comp_diag.get("returned_token") or "")
    comp_raw = str(comp_diag.get("raw_type") or "")
    st.markdown(
        f'<div id="solo-expire-chain" '
        f'data-owner="{summary.get("owner") or ""}" '
        f'data-commits="{summary.get("commits") or 0}" '
        f'data-last="{summary.get("last_stage") or ""}" '
        f'data-chain="{chain_s}" '
        f'data-log="{payload.replace(chr(34), chr(39))}" '
        f'data-component-return="{comp_return.replace(chr(34), chr(39))}" '
        f'data-component-raw="{comp_raw.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )
