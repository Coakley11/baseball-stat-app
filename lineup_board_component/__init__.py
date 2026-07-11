"""Bidirectional Streamlit component for Fantasy Lineup circular board."""

from __future__ import annotations

import os
from typing import Any

import streamlit.components.v1 as components

_PARENT = os.path.dirname(os.path.abspath(__file__))
_component = components.declare_component(
    "fantasy_lineup_board",
    path=os.path.join(_PARENT, "frontend"),
)


def lineup_board_component(payload: dict[str, Any], *, key: str | None = None) -> Any:
    """Render lineup board; returns last drop event dict or None."""
    return _component(payload=payload, key=key, default=None)
