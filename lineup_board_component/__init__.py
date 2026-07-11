"""Bidirectional Streamlit component for Fantasy Lineup circular board."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

_FRONTEND_DIR = (Path(__file__).resolve().parent / "frontend").resolve()
_COMPONENT_NAME = "fantasy_lineup_board"

_component = components.declare_component(
    _COMPONENT_NAME,
    path=str(_FRONTEND_DIR),
)


def get_component_frontend_dir() -> Path:
    """Absolute path to the packaged static frontend directory."""
    return _FRONTEND_DIR


def component_frontend_ready() -> bool:
    """True when index.html exists at the declared component path."""
    return (_FRONTEND_DIR / "index.html").is_file()


def lineup_board_component(payload: dict[str, Any], *, key: str | None = None) -> Any:
    """Render lineup board; returns last drop event dict or None."""
    if not component_frontend_ready():
        raise FileNotFoundError(f"Lineup board frontend missing: {_FRONTEND_DIR / 'index.html'}")
    return _component(payload=payload, key=key, default=None)
