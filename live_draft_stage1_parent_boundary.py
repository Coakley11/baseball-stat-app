"""Query-param gate for Stage 1A parent-boundary probe (diagnostic; no delivery owner)."""

from __future__ import annotations

from typing import Any

SESSION_FLAG = "_solo_stage1_parent_boundary_probe"


def stage1_parent_boundary_probe_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    if session.get(SESSION_FLAG):
        return True
    if st is None:
        return False
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        if not solo_component_diag_enabled(st, session):
            return False
    except ImportError:
        return False
    try:
        from live_draft_cloud_diagnostics import _qp_flag

        return bool(_qp_flag(st, "solo_stage1_parent_boundary"))
    except ImportError:
        return False


def bootstrap_stage1_parent_boundary_probe(st: Any | None, session: dict[str, Any]) -> None:
    if stage1_parent_boundary_probe_enabled(st, session):
        session[SESSION_FLAG] = True
