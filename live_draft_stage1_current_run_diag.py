"""Lightweight current app-generation DOM probe (solo_component_diag; not historical ledger)."""

from __future__ import annotations

import time
from typing import Any

CURRENT_RUN_PROBE_ID = "solo-stage1-current-run-diag"
CURRENT_RUN_IMPL_REV = "stage1_current_run_diag_v1"


def stage1_current_run_diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        return bool(stage1_production_ledger_enabled(st, session))
    except ImportError:
        return False


def _streamlit_session_id_for_probe() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def _deployment_sha(session: dict[str, Any]) -> str:
    sha = str(session.get("_solo_stage1_deployment_sha") or "").strip()
    if sha:
        return sha[:7]
    try:
        from suite_deploy_marker import GIT_COMMIT_SHORT

        return str(GIT_COMMIT_SHORT or "")[:7]
    except Exception:
        return ""


def _active_page_label(session: dict[str, Any]) -> str:
    for key in ("_active_page", "active_page", "_suite_active_page"):
        val = str(session.get(key) or "").strip()
        if val:
            return val[:80]
    return "Live Draft Room"


def _fragment_run_hint(session: dict[str, Any]) -> str:
    hint = str(session.get("_solo_stage1_fragment_run_hint") or "").strip()
    if hint:
        return hint[:48]
    if session.get("_solo_stage1_in_fragment_run"):
        return "fragment_run"
    return "full_run"


def _room_id(session: dict[str, Any]) -> str:
    try:
        from live_draft_stage1_production_ledger import _room_fields

        return str(_room_fields(session, None).get("room_id") or "").strip().upper()[:32]
    except ImportError:
        live = session.get("live_draft_room")
        if isinstance(live, dict):
            return str(live.get("draft_room_id") or live.get("draft_id") or "").strip().upper()[:32]
        return ""


def render_stage1_current_run_diag_probe(
    st: Any,
    session: dict[str, Any],
    *,
    probe_checkpoint: str = "early_script",
) -> None:
    """Emit current script run / session / room — re-rendered each probe call (not append-only ledger)."""
    if not stage1_current_run_diag_enabled(st, session):
        return
    try:
        from live_draft_stage1_production_ledger import ensure_stage1_run_id

        run_id = ensure_stage1_run_id(session)
    except ImportError:
        run_id = str(session.get("_solo_stage1_run_id") or "")[:16]
    script_run_seq = int(session.get("_solo_stage1_script_run_seq") or 0)
    probe_ts = time.time()
    checkpoint = str(probe_checkpoint or "early_script")[:64]
    streamlit_session_id = _streamlit_session_id_for_probe()
    room_id = _room_id(session)
    deployment_sha = _deployment_sha(session)
    active_page = _active_page_label(session)
    fragment_hint = _fragment_run_hint(session)
    st.markdown(
        f'<div id="{CURRENT_RUN_PROBE_ID}" '
        f'data-script-run-seq="{script_run_seq}" '
        f'data-run-seq="{script_run_seq}" '
        f'data-run-id="{run_id}" '
        f'data-streamlit-session-id="{streamlit_session_id}" '
        f'data-room-id="{room_id}" '
        f'data-probe-ts="{probe_ts}" '
        f'data-deployment-sha="{deployment_sha}" '
        f'data-active-page="{active_page.replace(chr(34), chr(39))}" '
        f'data-fragment-run-hint="{fragment_hint}" '
        f'data-probe-checkpoint="{checkpoint}" '
        f'data-impl-rev="{CURRENT_RUN_IMPL_REV}"></div>',
        unsafe_allow_html=True,
    )
