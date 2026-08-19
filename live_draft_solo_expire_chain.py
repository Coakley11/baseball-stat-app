"""Production Solo expire call-chain instrumentation (one authoritative owner)."""

from __future__ import annotations

import json
import time
from collections.abc import MutableMapping
from typing import Any


def is_session_mapping(session: Any) -> bool:
    """True for dict and Streamlit SessionStateProxy (MutableMapping, not dict)."""
    return isinstance(session, MutableMapping)

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
    if stage == "pick_committed":
        try:
            from live_draft_solo_delivery_diag import note_pick_committed_if_diag

            note_pick_committed_if_diag(session, source=str(source or ""))
        except ImportError:
            pass
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


def format_solo_deploy_marker_html(
    sha: str,
    build: str,
    *,
    carrier_phase: str = "",
    preflight_attached: bool | None = None,
) -> str:
    """Canonical #solo-deploy-build element. SHA poll reads data-sha only.

    Optional data-carrier-phase / data-preflight-attached are appended AFTER
    data-sha so poll_exact_cloud_sha and querySelector('#solo-deploy-build')
    remain compatible. Two-arg calls emit the historical exact HTML.
    """
    html = f'<div id="solo-deploy-build" data-build="{build}" data-sha="{sha}"'
    phase = str(carrier_phase or "").strip()
    if phase:
        html += f' data-carrier-phase="{phase.replace(chr(34), "")}"'
    if preflight_attached is True:
        html += ' data-preflight-attached="1"'
    elif preflight_attached is False:
        html += ' data-preflight-attached="0"'
    html += "></div>"
    return html


def format_solo_deploy_carrier_html(
    sha: str,
    build: str,
    preflight_div: str = "",
    *,
    carrier_phase: str = "",
    preflight_attached: bool | None = None,
) -> str:
    """One srcdoc/markdown payload: proven deploy marker plus optional preflight sibling."""
    carrier = format_solo_deploy_marker_html(
        sha,
        build,
        carrier_phase=carrier_phase,
        preflight_attached=preflight_attached,
    )
    extra = str(preflight_div or "")
    if extra:
        return carrier + extra
    return carrier


def render_solo_deploy_probe(
    st: Any,
    session: dict[str, Any] | None = None,
    *,
    carrier_phase: str = "",
) -> None:
    """Always-on hidden deploy marker for production soak deploy polling.

    When session is a mapping (dict or Streamlit SessionStateProxy), the same
    components.html document also carries #stage1-queue-gate-state-preflight so
    Context A can observe preflight in the production-proven deploy iframe.
    Deploy id/data-sha/comment are unchanged. Readiness false still attaches.
    """
    from suite_deploy_marker import format_build_label, resolve_git_commit_short

    build = format_build_label()
    sha = resolve_git_commit_short()
    preflight_div = ""
    phase = str(carrier_phase or "").strip()
    if not phase:
        phase = "steady" if is_session_mapping(session) else "build_only"
    if is_session_mapping(session):
        try:
            from live_draft_stage1_parent_boundary import capture_stage1_diagnostic_intents

            capture_stage1_diagnostic_intents(st, session)
        except ImportError:
            pass
        try:
            from live_draft_queue_state_snapshot_diag import (
                PREFLIGHT_PROBE_ID,
                format_queue_gate_preflight_dom_attrs,
                observe_queue_gate_preflight_state,
            )

            session["_stage1_ldr_entry_reached"] = True
            obs = observe_queue_gate_preflight_state(st, session)
            obs["ldr_entry_reached"] = True
            attrs = format_queue_gate_preflight_dom_attrs(obs)
            preflight_div = f'<div id="{PREFLIGHT_PROBE_ID}" {attrs}>&nbsp;</div>'
        except ImportError:
            preflight_div = ""
    carrier = format_solo_deploy_carrier_html(
        sha,
        build,
        preflight_div,
        carrier_phase=phase,
        preflight_attached=bool(preflight_div),
    )
    st.markdown(
        f"<!-- solo-deploy-build sha={sha} build={build} -->\n{carrier}",
        unsafe_allow_html=True,
    )
    try:
        import streamlit.components.v1 as components

        components.html(carrier, height=0)
    except ImportError:
        pass
    if session is not None:
        try:
            from solo_cloud_deploy_identity import render_visible_deploy_diag_caption

            render_visible_deploy_diag_caption(st, session, sha=sha, build=build)
        except ImportError:
            pass


def render_solo_expire_chain_probe(st: Any, session: dict[str, Any], room: dict[str, Any] | None) -> None:
    """Hidden DOM probes for production soak (no ld_accept required).

    Do not emit another #solo-deploy-build. LDR already renders early+steady
    session-backed carriers; a session-less call here created a build-only
    srcdoc with a duplicate id.
    """
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
    try:
        from live_draft_stage1_expire_audit import render_stage1_expire_audit_probe

        render_stage1_expire_audit_probe(st, session)
    except ImportError:
        pass
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
