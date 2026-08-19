"""Diagnostic-only dual-queue state snapshots (session + canonical).

Exposes independently, on the NORMAL UNLATCHED Live Draft Stage-1 path:

  session["draft_queue"]
  session["draft_state"]["queue"]

Requires:
  solo_component_diag=1
  AND solo_stage1_parent_boundary=1

Does NOT require stage1_francisco_callback_only.

Observability only — no queue mutation, sync, dirty, or persist side effects
on the baseline path. Post-mutation snapshot is recorded AFTER the existing
product add/sync/canonical-write sequence completes.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

IMPL_REV = "stage1_queue_state_snapshot_diag_v1"
PROBE_ID = "stage1-queue-state-snapshot"
PREFLIGHT_PROBE_ID = "stage1-queue-gate-state-preflight"
PREFLIGHT_IMPL_REV = "stage1_queue_gate_preflight_v4"
SESSION_LEDGER_KEY = "_stage1_queue_state_snapshot_ledger"
SESSION_LAST_KEY = "_stage1_queue_state_snapshot_last"
SESSION_BASELINE_KEY = "_stage1_queue_state_snapshot_baseline"
SESSION_POST_KEY = "_stage1_queue_state_snapshot_post"
SESSION_GATE_OBS_KEY = "_stage1_queue_snapshot_gate_obs"
SOLO_QP_NAME = "solo_component_diag"
PARENT_QP_NAME = "solo_stage1_parent_boundary"
MAX_LEDGER = 32

PHASE_BASELINE = "QUEUE_STATE_BASELINE"
PHASE_POST_ADDED = "QUEUE_STATE_POST_MUTATION_ADDED"
PHASE_POST_NO_ADD = "QUEUE_STATE_POST_NO_ADD"

FRANCISCO_NAME = "Francisco Lindor"

_LOCK = threading.Lock()


def _qp_flag(st: Any, name: str) -> bool:
    try:
        from live_draft_cloud_diagnostics import _qp_flag as _flag

        return bool(_flag(st, name))
    except Exception:
        return False


def _refresh_queue_state_diag_latches(st: Any | None, session: dict[str, Any]) -> None:
    """Latch parent_boundary when solo is on and parent QP was seen this session.

    Sibling Stage-1 card probes (fragment exec / render-trace) enable on solo alone.
    Dual-queue snapshots require BOTH flags. Remember parent QP even when solo is
    still off, then convert to the session latch once solo is on — including
    fragment_interactive_live reruns where query params may already be gone.

    Observe-only: does not install hooks, mutate queues, or emit canaries.
    """
    if not isinstance(session, dict):
        return
    try:
        from live_draft_stage1_parent_boundary import remember_parent_boundary_request

        remember_parent_boundary_request(st, session)
    except ImportError:
        if st is not None and _qp_flag(st, "solo_stage1_parent_boundary"):
            session["_solo_stage1_parent_boundary_requested"] = True
    solo_on = bool(session.get("_solo_component_diag_enabled"))
    if not solo_on and st is not None:
        try:
            from live_draft_solo_component_diagnostics import solo_component_diag_enabled

            solo_on = bool(solo_component_diag_enabled(st, session))
        except ImportError:
            solo_on = _qp_flag(st, "solo_component_diag")
        if solo_on:
            session["_solo_component_diag_enabled"] = True
    if not solo_on:
        return
    if session.get("_solo_stage1_parent_boundary_probe"):
        return
    parent_on = bool(session.get("_solo_stage1_parent_boundary_requested"))
    if not parent_on:
        try:
            from live_draft_stage1_parent_boundary import stage1_parent_boundary_probe_enabled

            parent_on = bool(stage1_parent_boundary_probe_enabled(st, session))
        except ImportError:
            parent_on = _qp_flag(st, "solo_stage1_parent_boundary")
    if not parent_on:
        parent_on = _qp_flag(st, "solo_stage1_parent_boundary")
    if parent_on:
        session["_solo_stage1_parent_boundary_probe"] = True
        session["_solo_stage1_parent_boundary_requested"] = True

def queue_state_snapshot_diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    """solo_component_diag AND solo_stage1_parent_boundary. No Francisco latch."""
    if not isinstance(session, dict):
        return False
    _refresh_queue_state_diag_latches(st, session)
    # Session latches set by existing bootstraps (work in callbacks where st may be absent).
    solo_on = bool(session.get("_solo_component_diag_enabled"))
    parent_on = bool(session.get("_solo_stage1_parent_boundary_probe"))
    if st is not None:
        try:
            from live_draft_solo_component_diagnostics import solo_component_diag_enabled

            solo_on = solo_on or bool(solo_component_diag_enabled(st, session))
        except ImportError:
            solo_on = solo_on or _qp_flag(st, "solo_component_diag")
        try:
            from live_draft_stage1_parent_boundary import stage1_parent_boundary_probe_enabled

            parent_on = parent_on or bool(stage1_parent_boundary_probe_enabled(st, session))
        except ImportError:
            parent_on = parent_on or (
                solo_on and _qp_flag(st, "solo_stage1_parent_boundary")
            )
        # Direct QP fallback: keep contract (both flags) even if helper import/order fails.
        if not parent_on and solo_on and _qp_flag(st, "solo_stage1_parent_boundary"):
            parent_on = True
            session["_solo_stage1_parent_boundary_probe"] = True
    return bool(solo_on and parent_on)


def _truthy_flag(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _query_params_raw(st: Any | None, name: str) -> tuple[bool, str]:
    """Read st.query_params only — no st.context.url fallback."""
    if st is None:
        return False, ""
    try:
        qp = getattr(st, "query_params", None)
        if qp is None:
            return False, ""
        present = False
        val: Any = None
        try:
            present = name in qp
        except Exception:
            present = False
        try:
            val = qp.get(name)
        except Exception:
            val = None
        if val is None and not present:
            return False, ""
        if isinstance(val, list):
            text = str(val[0] or "").strip()
        elif isinstance(val, (str, int, float, bool)):
            text = str(val).strip()
        else:
            text = ""
        return True, text
    except Exception:
        return False, ""


def _context_url_raw(st: Any | None, name: str) -> tuple[bool, str]:
    if st is None:
        return False, ""
    try:
        from live_draft_cloud_diagnostics import _qp_from_context_url

        text = str(_qp_from_context_url(st, name) or "").strip()
        return bool(text), text
    except Exception:
        return False, ""


def _paint_via(session: dict[str, Any]) -> str:
    last = session.get("_solo_stage1_last_recommendation_paint")
    if isinstance(last, dict):
        via = str(last.get("via") or "").strip()
        if via:
            return via[:48]
    hint = str(session.get("_solo_stage1_fragment_run_hint") or "").strip()
    return hint[:48]


def classify_queue_snapshot_early_return_reason(
    *,
    renderer_call_reached: bool,
    gate_enabled: bool,
    solo_enabled: bool,
    parent_requested: bool,
    parent_probe: bool,
    parent_qp_present: bool,
    parent_url_present: bool,
) -> str:
    """Deterministic first-failing predicate from actual gate inputs."""
    if not renderer_call_reached:
        return "renderer_not_called"
    if gate_enabled:
        return "enabled"
    if not solo_enabled:
        return "solo_disabled"
    if parent_requested and not parent_probe:
        return "parent_probe_false"
    if not parent_requested and not parent_probe:
        if not parent_qp_present and not parent_url_present:
            return "parent_requested_false"
        if not parent_qp_present:
            return "parent_live_flag_not_seen"
        if not parent_url_present:
            return "parent_url_flag_not_seen"
        return "parent_requested_false"
    if not parent_probe:
        return "parent_probe_false"
    return "dual_gate_false"


def observe_queue_snapshot_gate_state(
    st: Any | None,
    session: dict[str, Any],
    *,
    renderer_call_reached: bool = False,
) -> dict[str, Any]:
    """Read-only live queue-probe gate inputs. Does not emit the snapshot DOM.

    Does not include queue contents, tokens, cookies, email, or credentials.
    """
    if not isinstance(session, dict):
        session = {}
    solo_qp_present, solo_qp_value = _query_params_raw(st, SOLO_QP_NAME)
    parent_qp_present, parent_qp_value = _query_params_raw(st, PARENT_QP_NAME)
    solo_url_present, solo_url_value = _context_url_raw(st, SOLO_QP_NAME)
    parent_url_present, parent_url_value = _context_url_raw(st, PARENT_QP_NAME)
    gate_enabled = bool(queue_state_snapshot_diag_enabled(st, session))
    solo_enabled = bool(session.get("_solo_component_diag_enabled"))
    parent_requested = bool(session.get("_solo_stage1_parent_boundary_requested"))
    parent_probe = bool(session.get("_solo_stage1_parent_boundary_probe"))
    reason = classify_queue_snapshot_early_return_reason(
        renderer_call_reached=bool(renderer_call_reached),
        gate_enabled=gate_enabled,
        solo_enabled=solo_enabled,
        parent_requested=parent_requested,
        parent_probe=parent_probe,
        parent_qp_present=parent_qp_present and _truthy_flag(parent_qp_value),
        parent_url_present=parent_url_present and _truthy_flag(parent_url_value),
    )
    obs: dict[str, Any] = {
        "streamlit_session_id": _streamlit_session_id(session),
        "room_id": _room_id(session),
        "paint_via": _paint_via(session),
        "solo_qp_present": bool(solo_qp_present),
        "solo_qp_value": solo_qp_value[:16],
        "solo_qp_flag": _truthy_flag(solo_qp_value),
        "solo_url_present": bool(solo_url_present),
        "solo_url_value": solo_url_value[:16],
        "solo_url_flag": _truthy_flag(solo_url_value),
        "solo_enabled": solo_enabled,
        "parent_qp_present": bool(parent_qp_present),
        "parent_qp_value": parent_qp_value[:16],
        "parent_qp_flag": _truthy_flag(parent_qp_value),
        "parent_url_present": bool(parent_url_present),
        "parent_url_value": parent_url_value[:16],
        "parent_url_flag": _truthy_flag(parent_url_value),
        "parent_requested": parent_requested,
        "parent_probe": parent_probe,
        "queue_state_snapshot_diag_enabled": gate_enabled,
        "queue_snapshot_renderer_call_reached": bool(renderer_call_reached),
        "queue_snapshot_renderer_would_render": bool(gate_enabled and renderer_call_reached),
        "queue_snapshot_early_return_reason": reason,
    }
    session[SESSION_GATE_OBS_KEY] = dict(obs)
    return obs


def format_queue_gate_dom_attrs(obs: dict[str, Any] | None) -> str:
    """data-* attributes for #rec-card-queue-render-trace. No queue contents."""
    row = dict(obs or {})
    safe = lambda s: str(s or "").replace('"', "'")[:120]
    flag = lambda k: "1" if row.get(k) else "0"
    compact = {
        "sid": row.get("streamlit_session_id") or "",
        "room_id": row.get("room_id") or "",
        "paint_via": row.get("paint_via") or "",
        "solo_qp_present": bool(row.get("solo_qp_present")),
        "solo_qp_flag": bool(row.get("solo_qp_flag")),
        "solo_url_present": bool(row.get("solo_url_present")),
        "solo_url_flag": bool(row.get("solo_url_flag")),
        "solo_enabled": bool(row.get("solo_enabled")),
        "parent_qp_present": bool(row.get("parent_qp_present")),
        "parent_qp_flag": bool(row.get("parent_qp_flag")),
        "parent_url_present": bool(row.get("parent_url_present")),
        "parent_url_flag": bool(row.get("parent_url_flag")),
        "parent_requested": bool(row.get("parent_requested")),
        "parent_probe": bool(row.get("parent_probe")),
        "queue_gate": bool(row.get("queue_state_snapshot_diag_enabled")),
        "renderer_call_reached": bool(row.get("queue_snapshot_renderer_call_reached")),
        "would_render": bool(row.get("queue_snapshot_renderer_would_render")),
        "early_return_reason": row.get("queue_snapshot_early_return_reason") or "",
    }
    gate_json = json.dumps(compact, default=str).replace('"', "'")[:2000]
    return (
        f'data-sid="{safe(row.get("streamlit_session_id"))}" '
        f'data-paint-via="{safe(row.get("paint_via"))}" '
        f'data-solo-qp="{safe(row.get("solo_qp_value"))}" '
        f'data-solo-qp-present="{flag("solo_qp_present")}" '
        f'data-solo-qp-flag="{flag("solo_qp_flag")}" '
        f'data-solo-url-present="{flag("solo_url_present")}" '
        f'data-solo-url-flag="{flag("solo_url_flag")}" '
        f'data-solo-enabled="{flag("solo_enabled")}" '
        f'data-parent-qp="{safe(row.get("parent_qp_value"))}" '
        f'data-parent-qp-present="{flag("parent_qp_present")}" '
        f'data-parent-qp-flag="{flag("parent_qp_flag")}" '
        f'data-parent-url="{safe(row.get("parent_url_value"))}" '
        f'data-parent-url-present="{flag("parent_url_present")}" '
        f'data-parent-url-flag="{flag("parent_url_flag")}" '
        f'data-parent-requested="{flag("parent_requested")}" '
        f'data-parent-probe="{flag("parent_probe")}" '
        f'data-queue-gate="{flag("queue_state_snapshot_diag_enabled")}" '
        f'data-queue-renderer-reached="{flag("queue_snapshot_renderer_call_reached")}" '
        f'data-queue-would-render="{flag("queue_snapshot_renderer_would_render")}" '
        f'data-queue-early-return-reason="{safe(row.get("queue_snapshot_early_return_reason"))}" '
        f'data-queue-gate-json="{gate_json}"'
    )


def queue_gate_preflight_diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    """Pre-draft probe enable: solo diagnostic OR parent intent. Not behind dual gate."""
    if not isinstance(session, dict):
        return False
    try:
        from live_draft_stage1_parent_boundary import remember_parent_boundary_request

        remember_parent_boundary_request(st, session)
    except ImportError:
        if st is not None and _qp_flag(st, "solo_stage1_parent_boundary"):
            session["_solo_stage1_parent_boundary_requested"] = True
    solo = bool(session.get("_solo_component_diag_enabled"))
    if not solo and st is not None:
        try:
            from live_draft_solo_component_diagnostics import solo_component_diag_enabled

            solo = bool(solo_component_diag_enabled(st, session))
        except ImportError:
            solo = _qp_flag(st, "solo_component_diag")
        if solo:
            session["_solo_component_diag_enabled"] = True
    parent_requested = bool(session.get("_solo_stage1_parent_boundary_requested"))
    if not parent_requested and st is not None:
        parent_requested = _qp_flag(st, "solo_stage1_parent_boundary")
        if parent_requested:
            session["_solo_stage1_parent_boundary_requested"] = True
    return bool(solo or parent_requested)


def observe_queue_gate_preflight_state(st: Any | None, session: dict[str, Any]) -> dict[str, Any]:
    """Read-only pre-draft gate inputs. renderer_call_reached stays false by contract."""
    if not isinstance(session, dict):
        session = {}
    obs = observe_queue_snapshot_gate_state(st, session, renderer_call_reached=False)
    solo = bool(obs.get("solo_enabled"))
    parent_requested = bool(obs.get("parent_requested"))
    parent_probe = bool(obs.get("parent_probe"))
    dual = bool(obs.get("queue_state_snapshot_diag_enabled"))
    obs["preflight_solo_ready"] = solo
    obs["preflight_parent_requested"] = parent_requested
    obs["preflight_parent_probe"] = parent_probe
    obs["preflight_dual_gate"] = dual
    obs["preflight_ready"] = bool(solo and parent_requested and parent_probe and dual)
    obs["capture_stage1_diagnostic_intents_reached"] = bool(
        session.get("_stage1_diagnostic_intents_captured") or solo or parent_requested
    )
    obs["ldr_entry_reached"] = bool(session.get("_stage1_ldr_entry_reached"))
    obs["suite_sid"] = _suite_sid_diagnostic(st, session)
    # Explicitly not post-draft renderer execution.
    obs["queue_snapshot_renderer_call_reached"] = False
    obs["queue_snapshot_renderer_would_render"] = False
    return obs


def _suite_sid_diagnostic(st: Any | None, session: dict[str, Any]) -> str:
    for key in ("_capture_suite_sid", "suite_sid", "_solo_stage1_suite_sid"):
        val = str(session.get(key) or "").strip()
        if val:
            return val[:64]
    present, val = _query_params_raw(st, "suite_sid")
    if present:
        return str(val or "").strip()[:64]
    url_present, url_val = _context_url_raw(st, "suite_sid")
    if url_present:
        return str(url_val or "").strip()[:64]
    return ""


def format_queue_gate_preflight_dom_attrs(obs: dict[str, Any] | None) -> str:
    row = dict(obs or {})
    safe = lambda s: str(s or "").replace('"', "'")[:120]
    flag = lambda k: "1" if row.get(k) else "0"
    compact = {
        "sid": row.get("streamlit_session_id") or "",
        "suite_sid": row.get("suite_sid") or "",
        "solo_qp_present": bool(row.get("solo_qp_present")),
        "solo_qp_flag": bool(row.get("solo_qp_flag")),
        "solo_url_present": bool(row.get("solo_url_present")),
        "solo_url_flag": bool(row.get("solo_url_flag")),
        "preflight_solo_ready": bool(row.get("preflight_solo_ready")),
        "parent_qp_present": bool(row.get("parent_qp_present")),
        "parent_qp_flag": bool(row.get("parent_qp_flag")),
        "parent_url_present": bool(row.get("parent_url_present")),
        "parent_url_flag": bool(row.get("parent_url_flag")),
        "preflight_parent_requested": bool(row.get("preflight_parent_requested")),
        "preflight_parent_probe": bool(row.get("preflight_parent_probe")),
        "preflight_dual_gate": bool(row.get("preflight_dual_gate")),
        "preflight_ready": bool(row.get("preflight_ready")),
        "intents_reached": bool(row.get("capture_stage1_diagnostic_intents_reached")),
        "ldr_entry_reached": bool(row.get("ldr_entry_reached")),
    }
    preflight_json = json.dumps(compact, default=str).replace('"', "'")[:2000]
    return (
        f'data-sid="{safe(row.get("streamlit_session_id"))}" '
        f'data-suite-sid="{safe(row.get("suite_sid"))}" '
        f'data-solo-qp="{safe(row.get("solo_qp_value"))}" '
        f'data-solo-qp-present="{flag("solo_qp_present")}" '
        f'data-solo-qp-flag="{flag("solo_qp_flag")}" '
        f'data-solo-url-present="{flag("solo_url_present")}" '
        f'data-solo-url-flag="{flag("solo_url_flag")}" '
        f'data-solo-enabled="{flag("solo_enabled")}" '
        f'data-preflight-solo-ready="{flag("preflight_solo_ready")}" '
        f'data-parent-qp="{safe(row.get("parent_qp_value"))}" '
        f'data-parent-qp-present="{flag("parent_qp_present")}" '
        f'data-parent-qp-flag="{flag("parent_qp_flag")}" '
        f'data-parent-url="{safe(row.get("parent_url_value"))}" '
        f'data-parent-url-present="{flag("parent_url_present")}" '
        f'data-parent-url-flag="{flag("parent_url_flag")}" '
        f'data-preflight-parent-requested="{flag("preflight_parent_requested")}" '
        f'data-preflight-parent-probe="{flag("preflight_parent_probe")}" '
        f'data-preflight-dual-gate="{flag("preflight_dual_gate")}" '
        f'data-preflight-ready="{flag("preflight_ready")}" '
        f'data-intents-reached="{flag("capture_stage1_diagnostic_intents_reached")}" '
        f'data-ldr-entry-reached="{flag("ldr_entry_reached")}" '
        f'data-impl-rev="{safe(PREFLIGHT_IMPL_REV)}" '
        f'data-preflight-json="{preflight_json}"'
    )


def render_queue_gate_state_preflight_probe(st: Any, session: dict[str, Any]) -> None:
    """Preflight telemetry is piggybacked on the proven #solo-deploy-build carrier.

    Do not emit a separate components.html iframe. Always-on even when readiness
    is false — the deploy renderer reports the values rather than hiding them.
    """
    if not isinstance(session, dict):
        return
    session["_stage1_ldr_entry_reached"] = True
    from live_draft_solo_expire_chain import render_solo_deploy_probe

    render_solo_deploy_probe(st, session, carrier_phase="steady")


def evaluate_context_a_preflight_reservation(gate: dict[str, Any] | None) -> dict[str, Any]:
    """Auth-only Context A reservation. Does not require rec-card renderer execution."""
    row = dict(gate or {})
    checks = {
        "probe_found": row.get("probe_found") is True,
        "parse_valid": row.get("parse_invalid") is not True,
        "preflight_solo_ready": row.get("preflight_solo_ready") is True or row.get("solo_enabled") is True,
        "preflight_parent_requested": (
            row.get("preflight_parent_requested") is True or row.get("parent_requested") is True
        ),
        "preflight_parent_probe": (
            row.get("preflight_parent_probe") is True or row.get("parent_probe") is True
        ),
        "preflight_dual_gate": (
            row.get("preflight_dual_gate") is True
            or row.get("queue_gate") is True
            or row.get("queue_state_snapshot_diag_enabled") is True
        ),
        "preflight_ready": row.get("preflight_ready") is True,
        "authoritative_steady_found": row.get("authoritative_steady_found") is True,
        "same_carrier_document": row.get("same_carrier_document") is True,
    }
    failing = [k for k, ok in checks.items() if not ok]
    return {
        "ok": not failing,
        "checks": checks,
        "failing": failing,
        "probe_found": row.get("probe_found") is True,
        "probe_absent": row.get("probe_absent") is True,
        "classification": (
            "CONTEXT_A_PREFLIGHT_RESERVATION_OK"
            if not failing
            else "FRANCISCO_QUEUE_MUTATION_LIVE_AUTHENTICATED_QUEUE_GATE_NOT_READY"
        ),
    }


def _streamlit_session_id(session: dict[str, Any] | None = None) -> str:
    if isinstance(session, dict):
        for key in (
            "_streamlit_session_id",
            "streamlit_session_id",
            "_solo_stage1_streamlit_session_id",
        ):
            val = str(session.get(key) or "").strip()
            if val:
                return val[:64]
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def _diagnostic_run_id(session: dict[str, Any]) -> str:
    return str(
        session.get("_solo_stage1_run_id")
        or session.get("diagnostic_run_id")
        or session.get("application_diagnostic_run_id")
        or ""
    )[:64]


def _room_id(session: dict[str, Any]) -> str:
    try:
        from live_draft_stage1_production_ledger import _room_fields

        return str(_room_fields(session, None).get("room_id") or "").strip().upper()[:32]
    except Exception:
        live = session.get("live_draft_room")
        if isinstance(live, dict):
            return str(live.get("draft_room_id") or live.get("draft_id") or "").strip().upper()[:32]
        return ""


def _pick_index(session: dict[str, Any]) -> Any:
    live = session.get("live_draft_room")
    if isinstance(live, dict):
        for key in ("current_pick_index", "pick_index", "current_pick"):
            if live.get(key) is not None:
                try:
                    return int(live.get(key))
                except (TypeError, ValueError):
                    return live.get(key)
    return session.get("_solo_stage1_current_pick_index")


def _full_app_run_seq(session: dict[str, Any]) -> Any:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return session.get("_solo_stage1_script_run_seq")


def _recommendation_fragment_run_seq(session: dict[str, Any]) -> Any:
    try:
        return int(session.get("_solo_stage1_recommendation_fragment_run_seq") or 0)
    except (TypeError, ValueError):
        return session.get("_solo_stage1_recommendation_fragment_run_seq")


def _persist_dirty(session: dict[str, Any]) -> Any:
    try:
        from live_draft_queue_persist import DRAFT_QUEUE_PERSIST_DIRTY_KEY, is_draft_queue_persist_dirty

        if DRAFT_QUEUE_PERSIST_DIRTY_KEY in session:
            return bool(session.get(DRAFT_QUEUE_PERSIST_DIRTY_KEY))
        return bool(is_draft_queue_persist_dirty(session))
    except Exception:
        return session.get("_draft_queue_persist_dirty")


def read_session_queue(session: dict[str, Any]) -> list[str]:
    """Authoritative session draft_queue — copied list."""
    try:
        from draft_state import DRAFT_QUEUE_KEY

        raw = session.get(DRAFT_QUEUE_KEY)
    except ImportError:
        raw = session.get("draft_queue")
    return [str(x).strip() for x in (raw or []) if str(x).strip()]


def read_canonical_queue(session: dict[str, Any]) -> list[str]:
    """Authoritative draft_state.queue — independent of session draft_queue / UI / mirrors."""
    try:
        from draft_state import canonical_draft_workflow

        canon = canonical_draft_workflow(session)
        if isinstance(canon, dict):
            return [str(x).strip() for x in (canon.get("queue") or []) if str(x).strip()]
    except ImportError:
        pass
    ds = session.get("draft_state") if isinstance(session.get("draft_state"), dict) else {}
    return [str(x).strip() for x in (ds.get("queue") or []) if str(x).strip()]


def francisco_count(queue: list[Any] | None) -> int:
    target = FRANCISCO_NAME.lower()
    return sum(1 for x in list(queue or []) if str(x).strip().lower() == target)


def build_queue_state_snapshot(
    session: dict[str, Any],
    *,
    phase: str,
    added: bool | None = None,
    mutation_helper_entered: bool | None = None,
    player_name: str = "",
    event_id: str = "",
) -> dict[str, Any]:
    """Build a copied dual-queue snapshot. Read-only — does not mutate session queues."""
    sess_q = read_session_queue(session)
    canon_q = read_canonical_queue(session)
    # Explicit copies (already new lists from readers; re-copy for safety).
    sess_q = list(sess_q)
    canon_q = list(canon_q)
    return {
        "impl_rev": IMPL_REV,
        "phase": str(phase or "")[:64],
        "ts": time.time(),
        "streamlit_session_id": _streamlit_session_id(session),
        "diagnostic_run_id": _diagnostic_run_id(session),
        "room_id": _room_id(session),
        "current_pick_index": _pick_index(session),
        "full_app_run_seq": _full_app_run_seq(session),
        "recommendation_fragment_run_seq": _recommendation_fragment_run_seq(session),
        "session_queue": sess_q,
        "canonical_queue": canon_q,
        "session_queue_length": len(sess_q),
        "canonical_queue_length": len(canon_q),
        "queues_equal": sess_q == canon_q,
        "francisco_count_session": francisco_count(sess_q),
        "francisco_count_canonical": francisco_count(canon_q),
        "persist_dirty": _persist_dirty(session),
        "added": added,
        "mutation_helper_entered": mutation_helper_entered,
        "player_name": str(player_name or "").strip()[:80],
        "event_id": str(event_id or "").strip()[:64],
        "latch_required": False,
        "francisco_callback_only_required": False,
        "authoritative_membership": True,
        "ui_not_authority": True,
    }


def _append_ledger(session: dict[str, Any], snap: dict[str, Any]) -> None:
    book = session.get(SESSION_LEDGER_KEY)
    if not isinstance(book, list):
        book = []
    book = list(book) + [dict(snap)]
    session[SESSION_LEDGER_KEY] = book[-MAX_LEDGER:]
    session[SESSION_LAST_KEY] = dict(snap)
    phase = str(snap.get("phase") or "")
    if phase == PHASE_BASELINE:
        session[SESSION_BASELINE_KEY] = dict(snap)
    elif phase == PHASE_POST_ADDED:
        session[SESSION_POST_KEY] = dict(snap)
    elif phase == PHASE_POST_NO_ADD:
        # Retain as last no-add observation; do not overwrite successful post.
        session["_stage1_queue_state_snapshot_post_no_add"] = dict(snap)


def snapshot_static_root() -> Path:
    module_root = Path(__file__).resolve().parent
    candidates = (
        module_root / "static" / "queue_state",
        Path("/mount/src/baseball-stat-app/static/queue_state"),
        Path.cwd() / "static" / "queue_state",
    )
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue
    fallback = module_root / "static" / "queue_state"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _persist_sid_snapshot(snap: dict[str, Any]) -> str:
    """Durable SID-keyed JSON (diagnostic-only; mirrors OOB atomic-write pattern)."""
    sid = str(snap.get("streamlit_session_id") or "").strip()
    if not sid:
        return ""
    safe = sid.replace("/", "_")[:64]
    path = snapshot_static_root() / f"{safe}.json"
    payload = {
        "impl_rev": IMPL_REV,
        "streamlit_session_id": sid,
        "updated_ts": time.time(),
        "latest": dict(snap),
        "baseline": None,
        "post_mutation_added": None,
    }
    # Merge prior file if present.
    try:
        if path.is_file():
            prior = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prior, dict):
                payload["baseline"] = prior.get("baseline")
                payload["post_mutation_added"] = prior.get("post_mutation_added")
    except Exception:
        pass
    phase = str(snap.get("phase") or "")
    if phase == PHASE_BASELINE:
        payload["baseline"] = dict(snap)
    elif phase == PHASE_POST_ADDED:
        payload["post_mutation_added"] = dict(snap)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
        os.replace(tmp, path)
    return str(path)


def record_queue_state_baseline_snapshot(
    st: Any | None,
    session: dict[str, Any],
) -> dict[str, Any] | None:
    """Read-only baseline. No sync, dirty, persist, or queue mutation."""
    if not queue_state_snapshot_diag_enabled(st, session):
        return None
    snap = build_queue_state_snapshot(session, phase=PHASE_BASELINE)
    _append_ledger(session, snap)
    try:
        _persist_sid_snapshot(snap)
    except Exception:
        pass
    return dict(snap)


def record_queue_state_post_mutation_snapshot(
    session: dict[str, Any],
    *,
    added: bool,
    mutation_helper_entered: bool,
    player_name: str = "",
    event_id: str = "",
    st: Any | None = None,
) -> dict[str, Any] | None:
    """Post-path snapshot AFTER product add/sync/canonical write.

    Successful new membership → PHASE_POST_ADDED.
    No-add / duplicate → PHASE_POST_NO_ADD (not labeled successful mutation).
    """
    if not queue_state_snapshot_diag_enabled(st, session):
        return None
    phase = PHASE_POST_ADDED if bool(added) else PHASE_POST_NO_ADD
    snap = build_queue_state_snapshot(
        session,
        phase=phase,
        added=bool(added),
        mutation_helper_entered=bool(mutation_helper_entered),
        player_name=player_name,
        event_id=event_id,
    )
    _append_ledger(session, snap)
    try:
        _persist_sid_snapshot(snap)
    except Exception:
        pass
    return dict(snap)


def latest_baseline_for_sid(
    session: dict[str, Any] | None,
    *,
    streamlit_session_id: str,
    room_id: str = "",
) -> dict[str, Any] | None:
    """Select latest baseline correlating to production SID (fail closed on mismatch)."""
    sid = str(streamlit_session_id or "").strip()
    if not sid:
        return None
    candidates: list[dict[str, Any]] = []
    if isinstance(session, dict):
        book = session.get(SESSION_LEDGER_KEY)
        if isinstance(book, list):
            for row in book:
                if isinstance(row, dict) and str(row.get("phase") or "") == PHASE_BASELINE:
                    candidates.append(dict(row))
        base = session.get(SESSION_BASELINE_KEY)
        if isinstance(base, dict):
            candidates.append(dict(base))
    # Also try durable file.
    try:
        path = snapshot_static_root() / f"{sid.replace('/', '_')[:64]}.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            b = payload.get("baseline") if isinstance(payload, dict) else None
            if isinstance(b, dict):
                candidates.append(dict(b))
    except Exception:
        pass
    matched = [
        c
        for c in candidates
        if str(c.get("streamlit_session_id") or "").strip() == sid
    ]
    if room_id:
        room = str(room_id or "").strip().upper()
        matched = [
            c
            for c in matched
            if str(c.get("room_id") or "").strip().upper() == room
        ]
    if not matched:
        return None
    matched.sort(key=lambda r: float(r.get("ts") or 0))
    return dict(matched[-1])


def latest_post_added_for_sid(
    session: dict[str, Any] | None,
    *,
    streamlit_session_id: str,
    room_id: str = "",
    after_ts: float | None = None,
) -> dict[str, Any] | None:
    sid = str(streamlit_session_id or "").strip()
    if not sid:
        return None
    candidates: list[dict[str, Any]] = []
    if isinstance(session, dict):
        book = session.get(SESSION_LEDGER_KEY)
        if isinstance(book, list):
            for row in book:
                if isinstance(row, dict) and str(row.get("phase") or "") == PHASE_POST_ADDED:
                    candidates.append(dict(row))
        post = session.get(SESSION_POST_KEY)
        if isinstance(post, dict) and str(post.get("phase") or "") == PHASE_POST_ADDED:
            candidates.append(dict(post))
    try:
        path = snapshot_static_root() / f"{sid.replace('/', '_')[:64]}.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            p = payload.get("post_mutation_added") if isinstance(payload, dict) else None
            if isinstance(p, dict):
                candidates.append(dict(p))
    except Exception:
        pass
    matched = [
        c
        for c in candidates
        if str(c.get("streamlit_session_id") or "").strip() == sid
    ]
    if room_id:
        room = str(room_id or "").strip().upper()
        matched = [
            c
            for c in matched
            if str(c.get("room_id") or "").strip().upper() == room
        ]
    if after_ts is not None:
        matched = [c for c in matched if float(c.get("ts") or 0) > float(after_ts)]
    if not matched:
        return None
    matched.sort(key=lambda r: float(r.get("ts") or 0))
    return dict(matched[-1])


def _emit_queue_state_probe_dom(st: Any, html: str) -> None:
    """Markdown (app document) + components.html (Playwright page.frames), matching deploy marker."""
    st.markdown(html, unsafe_allow_html=True)
    html_fn = getattr(st, "html", None)
    if callable(html_fn):
        try:
            html_fn(html, height=0)
            return
        except Exception:
            pass
    try:
        import streamlit.components.v1 as components

        components.html(html, height=0)
    except Exception:
        pass


def render_queue_state_snapshot_probe(st: Any, session: dict[str, Any]) -> None:
    """Hidden DOM probe for Playwright scrape (diag-gated)."""
    # Always stamp live gate-state first so the solo-only rec-card sibling can
    # expose why this renderer returned. Does not emit this probe when gated off.
    obs = observe_queue_snapshot_gate_state(st, session, renderer_call_reached=True)
    if not obs.get("queue_state_snapshot_diag_enabled"):
        return
    # Refresh baseline on render so pre-click evidence stays current.
    # Empty queues [] are valid and MUST still emit (never treat as missing).
    record_queue_state_baseline_snapshot(st, session)
    baseline = dict(session.get(SESSION_BASELINE_KEY) or {})
    post = dict(session.get(SESSION_POST_KEY) or {})
    last = dict(session.get(SESSION_LAST_KEY) or {})
    # Prefer last/baseline even when queues are empty lists.
    payload = {
        "impl_rev": IMPL_REV,
        "baseline": baseline,
        "post_mutation_added": post if str(post.get("phase") or "") == PHASE_POST_ADDED else {},
        "last": last,
    }
    raw = json.dumps(payload, default=str)[:12000]
    safe = lambda s: str(s or "").replace('"', "'")[:120]
    # queues_equal: use explicit True check so False and missing stay 0; empty==empty is True.
    queues_equal_attr = "1" if baseline.get("queues_equal") is True else "0"
    html = (
        f'<div id="{PROBE_ID}" '
        f'data-impl-rev="{safe(IMPL_REV)}" '
        f'data-sid="{safe(baseline.get("streamlit_session_id") or last.get("streamlit_session_id"))}" '
        f'data-run-id="{safe(baseline.get("diagnostic_run_id") or last.get("diagnostic_run_id"))}" '
        f'data-room-id="{safe(baseline.get("room_id") or last.get("room_id"))}" '
        f'data-phase="{safe(baseline.get("phase") or PHASE_BASELINE)}" '
        f'data-baseline-ts="{safe(baseline.get("ts"))}" '
        f'data-post-ts="{safe(post.get("ts"))}" '
        f'data-queues-equal="{queues_equal_attr}" '
        f'data-session-len="{int(baseline.get("session_queue_length") or 0)}" '
        f'data-canonical-len="{int(baseline.get("canonical_queue_length") or 0)}" '
        f'data-json="{raw.replace(chr(34), chr(39))}"></div>'
    )
    _emit_queue_state_probe_dom(st, html)


_QUEUE_PROBE_EVAL_JS = f"""() => {{
  const el = document.querySelector('#{PROBE_ID}');
  if (!el) return {{ probe_found: false, probe_absent: true }};
  return {{
    probe_found: true,
    probe_absent: false,
    sid: el.getAttribute('data-sid') || '',
    run_id: el.getAttribute('data-run-id') || '',
    room_id: el.getAttribute('data-room-id') || '',
    phase: el.getAttribute('data-phase') || '',
    baseline_ts: el.getAttribute('data-baseline-ts') || '',
    post_ts: el.getAttribute('data-post-ts') || '',
    session_len: el.getAttribute('data-session-len') || '',
    canonical_len: el.getAttribute('data-canonical-len') || '',
    json: el.getAttribute('data-json') || '',
  }};
}}"""

_QUEUE_PROBE_CONTENTDOCUMENT_FALLBACK_JS = f"""() => {{
  const docs = [document];
  for (const f of document.querySelectorAll('iframe')) {{
    try {{ if (f.contentDocument) docs.push(f.contentDocument); }} catch (e) {{}}
  }}
  for (const doc of docs) {{
    const el = doc.querySelector('#{PROBE_ID}');
    if (!el) continue;
    return {{
      probe_found: true,
      probe_absent: false,
      sid: el.getAttribute('data-sid') || '',
      run_id: el.getAttribute('data-run-id') || '',
      room_id: el.getAttribute('data-room-id') || '',
      phase: el.getAttribute('data-phase') || '',
      baseline_ts: el.getAttribute('data-baseline-ts') || '',
      post_ts: el.getAttribute('data-post-ts') || '',
      session_len: el.getAttribute('data-session-len') || '',
      canonical_len: el.getAttribute('data-canonical-len') || '',
      json: el.getAttribute('data-json') || '',
      source: 'contentDocument_fallback',
    }};
  }}
  return {{ probe_found: false, probe_absent: true, source: 'contentDocument_fallback' }};
}}"""


def _decode_queue_probe_eval(raw: Any, *, frame_index: int | None = None, frame_url: str = "") -> dict[str, Any]:
    """Decode one frame evaluate result. probe_found means the selector existed.

    SID/room/phase filtering is NOT applied here — a present element is reported
    even when JSON parse fails, so absence vs parse-invalid stay distinct.
    """
    if not isinstance(raw, dict):
        return {
            "probe_found": False,
            "probe_absent": True,
            "parse_invalid": False,
            "selector": f"#{PROBE_ID}",
            "frame_index": frame_index,
            "frame_url": frame_url,
        }
    out = dict(raw)
    out["selector"] = f"#{PROBE_ID}"
    if frame_index is not None:
        out["frame_index"] = frame_index
    if frame_url:
        out["frame_url"] = frame_url
    found = out.get("probe_found") is True or bool(out.get("json") or out.get("sid"))
    out["probe_found"] = bool(found)
    out["probe_absent"] = not bool(found)
    out["parse_invalid"] = False
    payload = out.get("json")
    if isinstance(payload, str) and payload.strip():
        try:
            out["payload"] = json.loads(payload.replace("'", '"'))
        except Exception:
            out["parse_invalid"] = True
            out["payload_raw"] = payload[:4000]
    elif found and not str(out.get("sid") or "").strip() and not str(out.get("phase") or "").strip():
        out["parse_invalid"] = True
    return out


def scrape_queue_state_snapshot_from_page(page: Any) -> dict[str, Any]:
    """Playwright helper — prefer page.frames (same contract as scrape_deploy).

    probe_found=true means #stage1-queue-state-snapshot existed in a searched
    document. It does NOT mean SID/room/phase were accepted.
    """
    last_absent: dict[str, Any] = {
        "probe_found": False,
        "probe_absent": True,
        "parse_invalid": False,
        "selector": f"#{PROBE_ID}",
        "frame_strategy": "page.frames",
    }
    frames = list(getattr(page, "frames", []) or [])
    for idx, frame in enumerate(frames):
        try:
            raw = frame.evaluate(_QUEUE_PROBE_EVAL_JS)
        except Exception:
            continue
        parsed = _decode_queue_probe_eval(
            raw,
            frame_index=idx,
            frame_url=str(getattr(frame, "url", "") or ""),
        )
        parsed["frame_strategy"] = "page.frames"
        if parsed.get("probe_found") is True:
            return parsed
        last_absent = parsed
    try:
        raw = page.evaluate(_QUEUE_PROBE_CONTENTDOCUMENT_FALLBACK_JS)
    except Exception as exc:
        last_absent = dict(last_absent)
        last_absent["error"] = str(exc)[:200]
        last_absent["frame_strategy"] = last_absent.get("frame_strategy") or "contentDocument_fallback"
        return last_absent
    parsed = _decode_queue_probe_eval(raw)
    parsed["frame_strategy"] = "contentDocument_fallback" if frames else "top_page_evaluate"
    if parsed.get("probe_found") is True:
        return parsed
    if frames:
        last_absent["contentDocument_fallback_absent"] = True
        return last_absent
    return parsed


def wait_and_scrape_queue_state_snapshot_from_page(
    page: Any,
    *,
    timeout_s: float = 20.0,
    poll_s: float = 0.5,
) -> dict[str, Any]:
    """Poll until #stage1-queue-state-snapshot is present, then scrape.

    Empty baseline queues are valid; only absence of the probe element retries.
    A present element with invalid JSON stops the wait (parse_invalid=true).
    """
    deadline = time.time() + max(0.5, float(timeout_s))
    last: dict[str, Any] = {"probe_found": False, "probe_absent": True, "selector": f"#{PROBE_ID}"}
    attempts = 0
    started = time.time()
    while time.time() < deadline:
        attempts += 1
        last = scrape_queue_state_snapshot_from_page(page)
        last["attempts"] = attempts
        last["elapsed_s"] = max(0.0, time.time() - started)
        if last.get("probe_found") is True or last.get("parse_invalid") is True:
            last["waited_for_probe"] = True
            return last
        try:
            page.wait_for_timeout(int(max(0.05, float(poll_s)) * 1000))
        except Exception:
            time.sleep(max(0.05, float(poll_s)))
    last = scrape_queue_state_snapshot_from_page(page)
    last["waited_for_probe"] = True
    last["probe_wait_timeout"] = True
    last["attempts"] = attempts + 1
    last["elapsed_s"] = max(0.0, time.time() - started)
    last["selector"] = f"#{PROBE_ID}"
    return last


_PREFLIGHT_EVAL_JS = f"""() => {{
  const el = document.querySelector('#{PREFLIGHT_PROBE_ID}');
  if (!el) return {{ probe_found: false, probe_absent: true, selector: '#{PREFLIGHT_PROBE_ID}' }};
  const flag = (name) => {{
    const v = (el.getAttribute(name) || '').trim().toLowerCase();
    return v === '1' || v === 'true' || v === 'yes' || v === 'on';
  }};
  return {{
    probe_found: true,
    probe_absent: false,
    selector: '#{PREFLIGHT_PROBE_ID}',
    sid: el.getAttribute('data-sid') || '',
    suite_sid: el.getAttribute('data-suite-sid') || '',
    solo_qp: el.getAttribute('data-solo-qp') || '',
    solo_qp_present: flag('data-solo-qp-present'),
    solo_qp_flag: flag('data-solo-qp-flag'),
    solo_url_present: flag('data-solo-url-present'),
    solo_url_flag: flag('data-solo-url-flag'),
    solo_enabled: flag('data-solo-enabled'),
    preflight_solo_ready: flag('data-preflight-solo-ready'),
    parent_qp: el.getAttribute('data-parent-qp') || '',
    parent_qp_present: flag('data-parent-qp-present'),
    parent_qp_flag: flag('data-parent-qp-flag'),
    parent_url_present: flag('data-parent-url-present'),
    parent_url_flag: flag('data-parent-url-flag'),
    preflight_parent_requested: flag('data-preflight-parent-requested'),
    preflight_parent_probe: flag('data-preflight-parent-probe'),
    preflight_dual_gate: flag('data-preflight-dual-gate'),
    preflight_ready: flag('data-preflight-ready'),
    intents_reached: flag('data-intents-reached'),
    ldr_entry_reached: flag('data-ldr-entry-reached'),
    impl_rev: el.getAttribute('data-impl-rev') || '',
    preflight_json: el.getAttribute('data-preflight-json') || '',
  }};
}}"""

_PREFLIGHT_CONTENTDOCUMENT_FALLBACK_JS = f"""() => {{
  const docs = [document];
  for (const f of document.querySelectorAll('iframe')) {{
    try {{ if (f.contentDocument) docs.push(f.contentDocument); }} catch (e) {{}}
  }}
  const flag = (name, el) => {{
    const v = (el.getAttribute(name) || '').trim().toLowerCase();
    return v === '1' || v === 'true' || v === 'yes' || v === 'on';
  }};
  for (const doc of docs) {{
    const el = doc.querySelector('#{PREFLIGHT_PROBE_ID}');
    if (!el) continue;
    return {{
      probe_found: true,
      probe_absent: false,
      selector: '#{PREFLIGHT_PROBE_ID}',
      sid: el.getAttribute('data-sid') || '',
      suite_sid: el.getAttribute('data-suite-sid') || '',
      solo_qp: el.getAttribute('data-solo-qp') || '',
      solo_qp_present: flag('data-solo-qp-present', el),
      solo_qp_flag: flag('data-solo-qp-flag', el),
      solo_url_present: flag('data-solo-url-present', el),
      solo_url_flag: flag('data-solo-url-flag', el),
      solo_enabled: flag('data-solo-enabled', el),
      preflight_solo_ready: flag('data-preflight-solo-ready', el),
      parent_qp: el.getAttribute('data-parent-qp') || '',
      parent_qp_flag: flag('data-parent-qp-flag', el),
      parent_qp_present: flag('data-parent-qp-present', el),
      parent_url_present: flag('data-parent-url-present', el),
      parent_url_flag: flag('data-parent-url-flag', el),
      preflight_parent_requested: flag('data-preflight-parent-requested', el),
      preflight_parent_probe: flag('data-preflight-parent-probe', el),
      preflight_dual_gate: flag('data-preflight-dual-gate', el),
      preflight_ready: flag('data-preflight-ready', el),
      intents_reached: flag('data-intents-reached', el),
      ldr_entry_reached: flag('data-ldr-entry-reached', el),
      impl_rev: el.getAttribute('data-impl-rev') || '',
      preflight_json: el.getAttribute('data-preflight-json') || '',
    }};
  }}
  return {{ probe_found: false, probe_absent: true, selector: '#{PREFLIGHT_PROBE_ID}' }};
}}"""


def _decode_preflight_eval(
    raw: Any,
    *,
    frame_index: int | None = None,
    frame_url: str = "",
    frame_strategy: str = "",
) -> dict[str, Any]:
    out: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    out["selector"] = str(out.get("selector") or f"#{PREFLIGHT_PROBE_ID}")
    if frame_index is not None:
        out["frame_index"] = frame_index
    if frame_url:
        out["frame_url"] = frame_url
    if frame_strategy:
        out["frame_strategy"] = frame_strategy
    found = out.get("probe_found") is True
    out["probe_found"] = bool(found)
    out["probe_absent"] = not bool(found)
    out["parse_invalid"] = False
    if not found:
        return out
    raw_json = out.get("preflight_json")
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            out["preflight_payload"] = json.loads(raw_json.replace("'", '"'))
        except Exception as exc:
            out["parse_invalid"] = True
            out["parse_error"] = str(exc)[:200]
            return out
    has_ready_key = "preflight_ready" in out or "preflight_solo_ready" in out
    if not has_ready_key and not str(out.get("impl_rev") or "").strip():
        out["parse_invalid"] = True
        out["parse_error"] = "present_without_preflight_fields"
    return out


def scrape_queue_gate_preflight_from_page(page: Any) -> dict[str, Any]:
    last_absent: dict[str, Any] = {
        "probe_found": False,
        "probe_absent": True,
        "parse_invalid": False,
        "selector": f"#{PREFLIGHT_PROBE_ID}",
        "frame_strategy": "page.frames",
        "frames_searched": 0,
    }
    frames = list(getattr(page, "frames", []) or [])
    last_absent["frames_searched"] = len(frames)
    last_invalid: dict[str, Any] | None = None
    for idx, frame in enumerate(frames):
        try:
            raw = frame.evaluate(_PREFLIGHT_EVAL_JS)
        except Exception:
            continue
        parsed = _decode_preflight_eval(
            raw,
            frame_index=idx,
            frame_url=str(getattr(frame, "url", "") or ""),
            frame_strategy="page.frames",
        )
        if parsed.get("probe_found") is True and parsed.get("parse_invalid") is not True:
            return parsed
        if parsed.get("probe_found") is True and parsed.get("parse_invalid") is True:
            last_invalid = parsed
            continue
        last_absent = parsed
        last_absent["frames_searched"] = len(frames)
    try:
        raw = page.evaluate(_PREFLIGHT_CONTENTDOCUMENT_FALLBACK_JS)
    except Exception as exc:
        if last_invalid is not None:
            return last_invalid
        last_absent = dict(last_absent)
        last_absent["error"] = str(exc)[:200]
        return last_absent
    parsed = _decode_preflight_eval(
        raw,
        frame_strategy="contentDocument_fallback" if frames else "top_page_evaluate",
    )
    if parsed.get("probe_found") is True and parsed.get("parse_invalid") is not True:
        return parsed
    if parsed.get("probe_found") is True and parsed.get("parse_invalid") is True:
        return parsed
    if last_invalid is not None:
        return last_invalid
    if frames:
        last_absent["contentDocument_fallback_absent"] = True
        return last_absent
    return parsed


def wait_and_scrape_queue_gate_preflight_from_page(
    page: Any,
    *,
    timeout_s: float = 20.0,
    poll_s: float = 0.5,
) -> dict[str, Any]:
    deadline = time.time() + max(0.5, float(timeout_s))
    last: dict[str, Any] = {
        "probe_found": False,
        "probe_absent": True,
        "parse_invalid": False,
        "selector": f"#{PREFLIGHT_PROBE_ID}",
        "frame_strategy": "page.frames",
    }
    attempts = 0
    started = time.time()
    while time.time() < deadline:
        attempts += 1
        last = scrape_queue_gate_preflight_from_page(page)
        last["attempts"] = attempts
        last["elapsed_s"] = max(0.0, time.time() - started)
        last["waited_for_probe"] = True
        last["probe_wait_timeout"] = False
        if last.get("probe_found") is True and last.get("parse_invalid") is not True:
            return last
        try:
            page.wait_for_timeout(int(max(0.05, float(poll_s)) * 1000))
        except Exception:
            time.sleep(max(0.05, float(poll_s)))
    last = scrape_queue_gate_preflight_from_page(page)
    last["attempts"] = attempts + 1
    last["elapsed_s"] = max(0.0, time.time() - started)
    last["waited_for_probe"] = True
    last["probe_wait_timeout"] = True
    return last


AUTHORITATIVE_CARRIER_PHASE = "steady"

_SAME_CARRIER_EVAL_JS = f"""() => {{
  const deploy = document.querySelector('#solo-deploy-build');
  if (!deploy) {{
    return {{
      deploy_found: false,
      probe_found: false,
      probe_absent: true,
      selector: '#{PREFLIGHT_PROBE_ID}',
    }};
  }}
  const flag = (el, name) => {{
    const v = (el.getAttribute(name) || '').trim().toLowerCase();
    return v === '1' || v === 'true' || v === 'yes' || v === 'on';
  }};
  const pre = document.querySelector('#{PREFLIGHT_PROBE_ID}');
  const out = {{
    deploy_found: true,
    data_sha: (deploy.getAttribute('data-sha') || '').toLowerCase(),
    data_build: deploy.getAttribute('data-build') || '',
    carrier_phase: deploy.getAttribute('data-carrier-phase') || '',
    preflight_attached_attr: deploy.getAttribute('data-preflight-attached') || '',
    probe_found: !!pre,
    probe_absent: !pre,
    selector: '#{PREFLIGHT_PROBE_ID}',
  }};
  if (!pre) return out;
  out.sid = pre.getAttribute('data-sid') || '';
  out.suite_sid = pre.getAttribute('data-suite-sid') || '';
  out.solo_qp = pre.getAttribute('data-solo-qp') || '';
  out.solo_qp_present = flag(pre, 'data-solo-qp-present');
  out.solo_qp_flag = flag(pre, 'data-solo-qp-flag');
  out.solo_url_present = flag(pre, 'data-solo-url-present');
  out.solo_url_flag = flag(pre, 'data-solo-url-flag');
  out.solo_enabled = flag(pre, 'data-solo-enabled');
  out.preflight_solo_ready = flag(pre, 'data-preflight-solo-ready');
  out.parent_qp = pre.getAttribute('data-parent-qp') || '';
  out.parent_qp_present = flag(pre, 'data-parent-qp-present');
  out.parent_qp_flag = flag(pre, 'data-parent-qp-flag');
  out.parent_url_present = flag(pre, 'data-parent-url-present');
  out.parent_url_flag = flag(pre, 'data-parent-url-flag');
  out.preflight_parent_requested = flag(pre, 'data-preflight-parent-requested');
  out.preflight_parent_probe = flag(pre, 'data-preflight-parent-probe');
  out.preflight_dual_gate = flag(pre, 'data-preflight-dual-gate');
  out.preflight_ready = flag(pre, 'data-preflight-ready');
  out.intents_reached = flag(pre, 'data-intents-reached');
  out.ldr_entry_reached = flag(pre, 'data-ldr-entry-reached');
  out.impl_rev = pre.getAttribute('data-impl-rev') || '';
  out.preflight_json = pre.getAttribute('data-preflight-json') || '';
  return out;
}}"""


def _decode_same_carrier_eval(
    raw: Any,
    *,
    frame_index: int | None = None,
    frame_url: str = "",
    frame_strategy: str = "",
) -> dict[str, Any]:
    out: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    out["deploy_found"] = out.get("deploy_found") is True
    if frame_index is not None:
        out["frame_index"] = frame_index
    if frame_url:
        out["frame_url"] = frame_url
    if frame_strategy:
        out["frame_strategy"] = frame_strategy
    decoded = _decode_preflight_eval(
        out,
        frame_index=out.get("frame_index"),
        frame_url=str(out.get("frame_url") or ""),
        frame_strategy=str(out.get("frame_strategy") or ""),
    )
    decoded["deploy_found"] = out.get("deploy_found") is True
    decoded["data_sha"] = str(out.get("data_sha") or "")[:7]
    decoded["data_build"] = str(out.get("data_build") or "")
    decoded["carrier_phase"] = str(out.get("carrier_phase") or "")
    decoded["preflight_attached_attr"] = str(out.get("preflight_attached_attr") or "")
    return decoded


def select_authoritative_deploy_preflight_carrier(candidates: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Choose the STEADY #solo-deploy-build document; never mix frames."""
    rows = [dict(c) for c in (candidates or []) if isinstance(c, dict)]
    deploy_rows = [c for c in rows if c.get("deploy_found") is True]
    base: dict[str, Any] = {
        "candidates": [
            {
                "frame_index": c.get("frame_index"),
                "frame_url": c.get("frame_url"),
                "carrier_phase": c.get("carrier_phase"),
                "data_sha": c.get("data_sha"),
                "deploy_found": c.get("deploy_found"),
                "probe_found": c.get("probe_found"),
                "preflight_attached_attr": c.get("preflight_attached_attr"),
            }
            for c in deploy_rows
        ],
        "candidate_count": len(deploy_rows),
        "selector": f"#{PREFLIGHT_PROBE_ID}",
        "deploy_selector": "#solo-deploy-build",
        "same_carrier_document": False,
        "authoritative_steady_found": False,
        "probe_found": False,
        "probe_absent": True,
        "parse_invalid": False,
    }
    if not deploy_rows:
        base["outcome"] = "DEPLOY_ABSENT"
        return base
    steady = [c for c in deploy_rows if str(c.get("carrier_phase") or "") == AUTHORITATIVE_CARRIER_PHASE]
    if not steady:
        last = dict(deploy_rows[-1])
        last.update(base)
        last["outcome"] = "STEADY_NOT_OBSERVED"
        last["authoritative_steady_found"] = False
        last["same_carrier_document"] = False
        last["probe_found"] = bool(deploy_rows[-1].get("probe_found"))
        last["probe_absent"] = not last["probe_found"]
        last["frame_index"] = deploy_rows[-1].get("frame_index")
        last["frame_url"] = deploy_rows[-1].get("frame_url")
        last["data_sha"] = deploy_rows[-1].get("data_sha")
        last["data_build"] = deploy_rows[-1].get("data_build")
        last["carrier_phase"] = deploy_rows[-1].get("carrier_phase")
        last["deploy_found"] = True
        last["candidate_count"] = len(deploy_rows)
        last["candidates"] = base["candidates"]
        return last
    with_pf = [c for c in steady if c.get("probe_found") is True]
    selected = dict(with_pf[-1] if with_pf else steady[-1])
    selected["candidates"] = base["candidates"]
    selected["candidate_count"] = len(deploy_rows)
    selected["deploy_selector"] = "#solo-deploy-build"
    selected["authoritative_steady_found"] = True
    selected["same_carrier_document"] = selected.get("probe_found") is True
    if selected.get("probe_found") is True and selected.get("parse_invalid") is True:
        selected["outcome"] = "STEADY_PARSE_INVALID"
    elif selected.get("probe_found") is True:
        selected["outcome"] = "STEADY_CARRIER_FOUND"
    else:
        selected["outcome"] = "STEADY_PREFLIGHT_MISSING"
        selected["same_carrier_document"] = False
    return selected


def scrape_same_carrier_deploy_preflight_from_page(page: Any) -> dict[str, Any]:
    """One evaluate per frame: deploy marker AND preflight sibling in that document."""
    frames = list(getattr(page, "frames", []) or [])
    candidates: list[dict[str, Any]] = []
    for idx, frame in enumerate(frames):
        try:
            raw = frame.evaluate(_SAME_CARRIER_EVAL_JS)
        except Exception:
            continue
        parsed = _decode_same_carrier_eval(
            raw,
            frame_index=idx,
            frame_url=str(getattr(frame, "url", "") or ""),
            frame_strategy="page.frames",
        )
        candidates.append(parsed)
    if not candidates:
        try:
            raw = page.evaluate(_SAME_CARRIER_EVAL_JS)
        except Exception as exc:
            row = select_authoritative_deploy_preflight_carrier([])
            row["error"] = str(exc)[:200]
            row["frame_strategy"] = "top_page_evaluate"
            return row
        parsed = _decode_same_carrier_eval(raw, frame_strategy="top_page_evaluate")
        candidates.append(parsed)
    selected = select_authoritative_deploy_preflight_carrier(candidates)
    selected["frames_searched"] = len(frames)
    selected["frame_strategy"] = str(selected.get("frame_strategy") or "page.frames")
    return selected


def wait_and_scrape_same_carrier_deploy_preflight_from_page(
    page: Any,
    *,
    timeout_s: float = 20.0,
    poll_s: float = 0.5,
) -> dict[str, Any]:
    """Wait for the STEADY carrier. Early/build-only is not failure until timeout."""
    deadline = time.time() + max(0.5, float(timeout_s))
    started = time.time()
    attempts = 0
    last: dict[str, Any] = {
        "probe_found": False,
        "probe_absent": True,
        "outcome": "DEPLOY_ABSENT",
        "selector": f"#{PREFLIGHT_PROBE_ID}",
    }
    terminal_ok = {"STEADY_CARRIER_FOUND", "STEADY_PARSE_INVALID"}
    while time.time() < deadline:
        attempts += 1
        last = scrape_same_carrier_deploy_preflight_from_page(page)
        last["attempts"] = attempts
        last["elapsed_s"] = max(0.0, time.time() - started)
        last["waited_for_probe"] = True
        last["probe_wait_timeout"] = False
        if str(last.get("outcome") or "") in terminal_ok:
            return last
        try:
            page.wait_for_timeout(int(max(0.05, float(poll_s)) * 1000))
        except Exception:
            time.sleep(max(0.05, float(poll_s)))
    last = scrape_same_carrier_deploy_preflight_from_page(page)
    last["attempts"] = attempts + 1
    last["elapsed_s"] = max(0.0, time.time() - started)
    last["waited_for_probe"] = True
    last["probe_wait_timeout"] = True
    return last

