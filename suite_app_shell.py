"""
Consistent account + workspace sidebar shell for all Daniel AI Suite apps.

Synced to sibling repos via ``scripts/sync_suite_cloud_modules.py``.
Call near the top of each app's sidebar (after ``set_page_config`` / workspace init).
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "apply_suite_auth_gate",
    "render_suite_sidebar_account_shell",
    "render_suite_namespace_notices",
)


def apply_suite_auth_gate(st: Any) -> None:
    """Block app body when Real Accounts are enabled and user is not signed in."""
    try:
        from suite_auth import render_auth_gate

        render_auth_gate(st)
    except ImportError:
        pass


def render_suite_namespace_notices(st: Any) -> None:
    """Compact sidebar warnings when workspace URL/state may be inconsistent."""
    try:
        from suite_account_settings import detect_workspace_namespace_issues
    except ImportError:
        return
    for issue in detect_workspace_namespace_issues(st=st):
        severity = str(issue.get("severity") or "warning").strip()
        title = str(issue.get("title") or "Workspace notice").strip()
        detail = str(issue.get("detail") or "").strip()
        text = f"**{title}** — {detail}" if detail else f"**{title}**"
        if severity == "error":
            st.sidebar.error(text)
        elif severity == "info":
            st.sidebar.info(text)
        else:
            st.sidebar.warning(text)


def render_suite_sidebar_account_shell(
    st: Any,
    *,
    show_command_center_link: bool = True,
    show_account_panel: bool = True,
    account_panel_expanded: bool = False,
    command_center_divider: bool = True,
    top_divider: bool = False,
) -> None:
    """Render workspace badge, optional account panel, and Command Center link."""
    try:
        from suite_workspace import init_suite_workspace

        init_suite_workspace(st)
    except ImportError:
        pass

    if top_divider:
        st.sidebar.divider()

    render_suite_namespace_notices(st)

    try:
        from suite_account_settings import (
            render_account_settings_panel,
            render_global_workspace_badge,
        )

        render_global_workspace_badge(st)
        if show_account_panel:
            render_account_settings_panel(
                st,
                expanded=account_panel_expanded,
                show_title=True,
            )
    except ImportError:
        st.sidebar.caption("Account settings module unavailable on this deploy.")

    if show_command_center_link:
        try:
            from suite_command_center_link import render_command_center_sidebar_link

            render_command_center_sidebar_link(
                st,
                show_divider=command_center_divider,
            )
        except ImportError:
            pass
    elif command_center_divider:
        st.sidebar.divider()

    try:
        from suite_egress_trace import render_egress_sidebar_panel

        render_egress_sidebar_panel(st)
    except ImportError:
        pass
