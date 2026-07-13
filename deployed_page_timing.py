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
    return {
        "page": page,
        "total_wall_ms": row.get("total_wall_ms"),
        "milestones_ms": {k: milestones.get(k) for k in INTERACTIVE_MILESTONES},
        "warm_startup_skipped": bool(session.get("_baseball_warm_startup_skipped")),
    }


__all__ = [
    "INTERACTIVE_MILESTONES",
    "finish_page_render",
    "mark_navigation_start",
    "mark_page_heading_visible",
    "mark_active_league_visible",
    "mark_main_content_interactive",
    "mark_full_optional_complete",
    "summarize_deployed_page_timing",
]
