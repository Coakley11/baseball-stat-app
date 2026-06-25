"""
Activity namespace diagnostics for Baseball (mirrors Command Center helpers).
"""

from __future__ import annotations

from typing import Any

from suite_activity_namespace import activity_namespace_diagnostics


def build_workspace_activity_namespace_diagnostics(st: Any | None = None) -> dict[str, Any]:
    """Namespace fields used for activity writes — compare to Command Center read panel."""
    return activity_namespace_diagnostics(st=st)
