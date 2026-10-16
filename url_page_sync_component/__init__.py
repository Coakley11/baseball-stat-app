"""Hidden component behind url_page_sync: reports Back/Forward, replaces ?active_page= when asked."""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_FRONTEND_DIR = (Path(__file__).resolve().parent / "frontend").resolve()
_COMPONENT = components.declare_component("url_page_sync", path=str(_FRONTEND_DIR))


def mount_url_page_sync(page: str, *, mode: str, key: str) -> None:
    """Render the (zero-height) sync frame. Its value — a popstate event — is read from session_state[key]."""
    _COMPONENT(page=page, mode=mode, key=key, default=None)
