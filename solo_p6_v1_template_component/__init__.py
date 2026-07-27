"""Minimal Streamlit V1 template — setComponentReady + RENDER_EVENT + setComponentValue."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

_FRONTEND = (Path(__file__).resolve().parent / "frontend").resolve()
_TEMPLATE = components.declare_component("solo_p6_v1_template_wake", path=str(_FRONTEND))


def mount_p6_v1_template_once(
    expire_token: str,
    *,
    key: str,
    on_change: Any | None = None,
) -> Any:
    token = str(expire_token or "").strip()
    return _TEMPLATE(
        expire_token=token,
        key=key,
        default=None,
        on_change=on_change,
    )
