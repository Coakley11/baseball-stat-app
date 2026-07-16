"""Return-to-Command-Center sidebar link for Daniel AI Suite apps."""

from __future__ import annotations

from typing import Any

# Mirror app_urls.py when this module is copied into sibling repos.
_HOMEPAGE_DEV_URL = "https://daniel-ai-command-center-ion4vh2cvo7bgdnkuktrb3.streamlit.app"
_HOMEPAGE_PRODUCTION_URL = "https://daniel-ai-command-center-dexxnd7bf8jalxzqbyq55i.streamlit.app"


def command_center_url(*, workspace_id: str = "") -> str:
    """Public Command Center homepage URL with active workspace profile."""
    try:
        from app_urls import HOMEPAGE_DEV_URL, HOMEPAGE_PRODUCTION_URL
    except ImportError:
        dev, prod = _HOMEPAGE_DEV_URL, _HOMEPAGE_PRODUCTION_URL
    else:
        dev = (HOMEPAGE_DEV_URL or "").strip()
        prod = (HOMEPAGE_PRODUCTION_URL or "").strip()
    base = (dev or prod or _HOMEPAGE_DEV_URL).rstrip("/")
    try:
        from suite_workspace import append_suite_workspace_param, resolve_workspace_id

        ws = str(workspace_id or "").strip() or resolve_workspace_id()
        return append_suite_workspace_param(base, workspace_id=ws)
    except ImportError:
        return base


def render_command_center_sidebar_link(
    st: Any,
    *,
    label: str = "← Command Center",
    show_divider: bool = True,
) -> None:
    """Top-of-sidebar link back to the suite homepage."""
    try:
        from suite_workspace import get_active_workspace_id

        url = command_center_url(workspace_id=get_active_workspace_id(st))
    except Exception:
        url = command_center_url()
    if not url:
        return
    st.sidebar.link_button(label, url, use_container_width=True)
    if show_divider:
        st.sidebar.divider()
