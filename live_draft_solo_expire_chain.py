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
    if stage == "commit_confirmed":
        session[SOLO_EXPIRE_COMMIT_COUNT_KEY] = int(session.get(SOLO_EXPIRE_COMMIT_COUNT_KEY) or 0) + 1
    return row


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


def render_solo_expire_chain_probe(st: Any, session: dict[str, Any], room: dict[str, Any] | None) -> None:
    """Hidden DOM probe for production soak (no ld_accept required)."""
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
    st.markdown(
        f'<div id="solo-expire-chain" '
        f'data-owner="{summary.get("owner") or ""}" '
        f'data-commits="{summary.get("commits") or 0}" '
        f'data-last="{summary.get("last_stage") or ""}" '
        f'data-chain="{chain_s}" '
        f'data-log="{payload.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )
