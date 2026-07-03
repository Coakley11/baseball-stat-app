"""Lightweight page timing — developer mode only."""
from __future__ import annotations

import time
from typing import Any

_PERF_KEY = "_page_perf_trace"
_PERF_MAX = 24


def _dev_mode(session: dict[str, Any]) -> bool:
    try:
        from suite_workspace import developer_ui_visible_from_session

        return developer_ui_visible_from_session(session)
    except ImportError:
        return False


def perf_mark(session: dict[str, Any], label: str, elapsed_ms: float) -> None:
    if not _dev_mode(session):
        return
    entry = {"label": str(label), "ms": round(float(elapsed_ms), 1)}
    trace = session.get(_PERF_KEY)
    if not isinstance(trace, list):
        trace = []
    trace.append(entry)
    session[_PERF_KEY] = trace[-_PERF_MAX:]


def perf_timer(session: dict[str, Any], label: str) -> float:
    if not _dev_mode(session):
        return 0.0
    return time.perf_counter()


def perf_end(session: dict[str, Any], label: str, start: float) -> None:
    if not _dev_mode(session) or start <= 0:
        return
    perf_mark(session, label, (time.perf_counter() - start) * 1000.0)


def perf_page_start(session: dict[str, Any], page: str) -> float:
    """Mark page render start — dev mode only."""
    return perf_timer(session, f"page_render:{page}")


def perf_page_end(session: dict[str, Any], page: str, start: float) -> None:
    perf_end(session, f"page_render:{page}", start)
