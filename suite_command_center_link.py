"""Return-to-Command-Center sidebar link for Daniel AI Suite apps."""

from __future__ import annotations

from typing import Any

# Mirror app_urls.py when this module is copied into sibling repos.
_HOMEPAGE_DEV_URL = "https://daniel-ai-command-center-ion4vh2cvo7bgdnkuktrb3.streamlit.app"
_HOMEPAGE_PRODUCTION_URL = "https://daniel-ai-command-center-dexxnd7bf8jalxzqbyq55i.streamlit.app"


def command_center_url() -> str:
    """Public Command Center homepage URL (dev deploy preferred)."""
    try:
        from app_urls import HOMEPAGE_DEV_URL, HOMEPAGE_PRODUCTION_URL
    except ImportError:
        dev, prod = _HOMEPAGE_DEV_URL, _HOMEPAGE_PRODUCTION_URL
    else:
        dev = (HOMEPAGE_DEV_URL or "").strip()
        prod = (HOMEPAGE_PRODUCTION_URL or "").strip()
    base = dev or prod or _HOMEPAGE_DEV_URL
    return base.rstrip("/")


def render_command_center_sidebar_link(st: Any, *, label: str = "← Command Center") -> None:
    """Top-of-sidebar link back to the suite homepage."""
    url = command_center_url()
    if not url:
        return
    st.sidebar.link_button(label, url, use_container_width=True)
    st.sidebar.divider()
