"""Full-page render wall-clock timing — lightweight always-on, verbose in Developer Mode."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

_NAV_START_KEY = "_page_render_nav_start"
_TIMINGS_KEY = "_page_render_timings"
_LAST_PAGE_KEY = "_page_render_last_page"


def mark_navigation_start(session: dict[str, Any], page: str) -> None:
    session[_NAV_START_KEY] = time.perf_counter()
    session[_LAST_PAGE_KEY] = str(page or "")
    timings = session.get(_TIMINGS_KEY)
    if not isinstance(timings, dict):
        timings = {}
    timings[str(page or "")] = {
        "navigation_start": session[_NAV_START_KEY],
        "phases": {},
        "milestones": {},
    }
    session[_TIMINGS_KEY] = timings


def record_milestone(session: dict[str, Any], page: str, label: str) -> None:
    page = str(page or "")
    label = str(label or "").strip()
    if not page or not label:
        return
    timings = session.get(_TIMINGS_KEY)
    if not isinstance(timings, dict):
        return
    row = timings.get(page)
    if not isinstance(row, dict):
        return
    milestones = dict(row.get("milestones") or {})
    t0 = float(row.get("navigation_start") or time.perf_counter())
    milestones[label] = round((time.perf_counter() - t0) * 1000.0, 2)
    row["milestones"] = milestones
    timings[page] = row
    session[_TIMINGS_KEY] = timings


def record_render_phase(session: dict[str, Any], page: str, phase: str, elapsed_sec: float) -> None:
    page = str(page or "")
    phase = str(phase or "").strip()
    if not page or not phase:
        return
    verbose = False
    try:
        from page_perf_phases import dev_perf_enabled

        verbose = dev_perf_enabled(session)
    except ImportError:
        pass
    timings = session.get(_TIMINGS_KEY)
    if not isinstance(timings, dict):
        return
    row = timings.get(page)
    if not isinstance(row, dict):
        return
    phases = dict(row.get("phases") or {})
    prev = float(phases.get(phase) or 0.0)
    phases[phase] = round(prev + float(elapsed_sec) * 1000.0, 2)
    row["phases"] = phases
    if verbose:
        row["verbose"] = True
    timings[page] = row
    session[_TIMINGS_KEY] = timings


@contextmanager
def render_phase(session: dict[str, Any], page: str, phase: str) -> Iterator[None]:
    t0 = time.perf_counter()
    try:
        yield
    finally:
        record_render_phase(session, page, phase, time.perf_counter() - t0)


def finish_page_render(session: dict[str, Any], page: str) -> dict[str, Any]:
    page = str(page or "")
    timings = session.get(_TIMINGS_KEY)
    if not isinstance(timings, dict):
        return {}
    row = timings.get(page)
    if not isinstance(row, dict):
        return {}
    nav = float(row.get("navigation_start") or time.perf_counter())
    total_ms = round((time.perf_counter() - nav) * 1000.0, 2)
    row["total_wall_ms"] = total_ms
    timings[page] = row
    session[_TIMINGS_KEY] = timings
    try:
        from page_perf_phases import dev_perf_enabled

        if dev_perf_enabled(session):
            session["_page_render_last_summary"] = dict(row)
    except ImportError:
        pass
    if total_ms > 2000.0:
        session["_page_render_slow_last"] = {"page": page, "total_wall_ms": total_ms}
    return dict(row)


def last_page_timings(session: dict[str, Any], page: str) -> dict[str, Any]:
    timings = session.get(_TIMINGS_KEY)
    if not isinstance(timings, dict):
        return {}
    row = timings.get(str(page or ""))
    return dict(row) if isinstance(row, dict) else {}
