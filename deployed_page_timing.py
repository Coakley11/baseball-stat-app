"""Helpers for measuring deployed Streamlit page interactivity milestones.

Production timing should be read from session after real navigation, not from
local helper-only profiling scripts.
"""

from __future__ import annotations

from typing import Any

from page_render_timing import (
    finish_page_render,
    last_page_timings,
    mark_navigation_start,
    record_milestone,
)


INTERACTIVE_MILESTONES = (
    "page_heading_visible",
    "active_league_team_visible",
    "main_content_interactive",
    "full_optional_complete",
)

WARM_TARGETS_MS = {
    "Saved Draft Library": 2000.0,
    "Fantasy Lineup Assistant": 2000.0,
    "Fantasy Standings Tracker": 2000.0,
    "Waiver Wire / Add-Drop Center": 2000.0,
    "Draft Assistant Simulator": 2000.0,
    "Live Draft Room": 3000.0,
}


def mark_page_heading_visible(session: dict[str, Any], page: str) -> None:
    record_milestone(session, page, "page_heading_visible")


def mark_active_league_visible(session: dict[str, Any], page: str) -> None:
    record_milestone(session, page, "active_league_team_visible")


def mark_main_content_interactive(session: dict[str, Any], page: str) -> None:
    record_milestone(session, page, "main_content_interactive")


def mark_full_optional_complete(session: dict[str, Any], page: str) -> None:
    record_milestone(session, page, "full_optional_complete")


def summarize_deployed_page_timing(session: dict[str, Any], page: str) -> dict[str, Any]:
    row = last_page_timings(session, page)
    milestones = dict(row.get("milestones") or {})
    interactive_ms = milestones.get("main_content_interactive")
    if interactive_ms is None:
        interactive_ms = row.get("total_wall_ms")
    target = WARM_TARGETS_MS.get(str(page or ""))
    top_phases: list[dict[str, Any]] = []
    try:
        from page_perf_phases import top_slow_phases

        top_phases = [{"phase": name, "sec": sec} for name, sec in top_slow_phases(session, limit=8)]
    except ImportError:
        phases = dict(row.get("phases") or {})
        ranked = sorted(phases.items(), key=lambda kv: float(kv[1] or 0), reverse=True)[:8]
        top_phases = [{"phase": name, "ms": ms} for name, ms in ranked]
    warm = bool(session.get("_baseball_warm_startup_skipped"))
    return {
        "page": page,
        "navigation_start": row.get("navigation_start"),
        "total_wall_ms": row.get("total_wall_ms"),
        "milestones_ms": {k: milestones.get(k) for k in INTERACTIVE_MILESTONES},
        "main_content_interactive_ms": interactive_ms,
        "warm_startup_skipped": warm,
        "page_change_save_skipped": str(session.get("_suite_page_change_save_skipped") or ""),
        "largest_timing_phases": top_phases,
        "warm_target_ms": target,
        "within_warm_target": (
            None
            if interactive_ms is None or target is None
            else float(interactive_ms) <= float(target)
        ),
    }


__all__ = [
    "INTERACTIVE_MILESTONES",
    "WARM_TARGETS_MS",
    "finish_page_render",
    "mark_navigation_start",
    "mark_page_heading_visible",
    "mark_active_league_visible",
    "mark_main_content_interactive",
    "mark_full_optional_complete",
    "summarize_deployed_page_timing",
]
