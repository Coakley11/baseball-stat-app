"""Query-param gate for Stage 1A parent-boundary probe (diagnostic; no delivery owner)."""

from __future__ import annotations

from typing import Any

SESSION_FLAG = "_solo_stage1_parent_boundary_probe"
REQUESTED_FLAG = "_solo_stage1_parent_boundary_requested"


def remember_parent_boundary_request(st: Any | None, session: dict[str, Any]) -> None:
    """Persist parent-boundary QP intent even when solo is not yet latched.

    Dual-queue snapshots AND solo with parent_boundary. If the parent QP is
    visible on a run where solo is still off, remember it so a later solo-only
    fragment/auth rerun can latch the session flag after the QP disappears.
    """
    if not isinstance(session, dict) or st is None:
        return
    try:
        from live_draft_cloud_diagnostics import _qp_flag

        if bool(_qp_flag(st, "solo_stage1_parent_boundary")):
            session[REQUESTED_FLAG] = True
    except ImportError:
        return


def _solo_on(st: Any | None, session: dict[str, Any]) -> bool:
    if session.get("_solo_component_diag_enabled"):
        return True
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return bool(solo_component_diag_enabled(st, session))
    except ImportError:
        return False


def stage1_parent_boundary_probe_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    if session.get(SESSION_FLAG):
        return True
    remember_parent_boundary_request(st, session)
    if st is None:
        return bool(session.get(REQUESTED_FLAG) and session.get("_solo_component_diag_enabled"))
    if not _solo_on(st, session):
        return False
    if session.get(REQUESTED_FLAG):
        return True
    try:
        from live_draft_cloud_diagnostics import _qp_flag

        if bool(_qp_flag(st, "solo_stage1_parent_boundary")):
            session[REQUESTED_FLAG] = True
            return True
    except ImportError:
        return False
    return False


def bootstrap_stage1_parent_boundary_probe(st: Any | None, session: dict[str, Any]) -> None:
    remember_parent_boundary_request(st, session)
    if stage1_parent_boundary_probe_enabled(st, session):
        session[SESSION_FLAG] = True


def capture_stage1_diagnostic_intents(st: Any | None, session: dict[str, Any]) -> None:
    """Latch solo + parent-boundary intents from the initial URL before QP loss.

    Shared bootstrap for ``solo_component_diag`` and ``solo_stage1_parent_boundary``.
    Reads ``st.query_params`` and ``st.context.url``. Does not clear query params,
    mutate queues, change picks, or arm/clear Francisco gates.
    """
    if not isinstance(session, dict):
        return
    session["_stage1_diagnostic_intents_captured"] = True
    remember_parent_boundary_request(st, session)
    try:
        from live_draft_cloud_diagnostics import _qp_flag

        if st is not None and bool(_qp_flag(st, "solo_component_diag")):
            session["_solo_component_diag_enabled"] = True
    except ImportError:
        pass
    if stage1_parent_boundary_probe_enabled(st, session):
        session[SESSION_FLAG] = True
