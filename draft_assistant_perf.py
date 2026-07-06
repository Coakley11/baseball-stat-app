"""Draft Assistant Simulator performance tracing (Developer Mode only)."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

DRAFT_ASSISTANT_PERF_ACTIONS_KEY = "_draft_assistant_perf_actions"
DRAFT_ASSISTANT_PERF_MAX = 32

# Canonical phase names for baseline profiling and future UI instrumentation.
PHASE_DA_PAGE_PREP = "draft_assistant_page_prep"
PHASE_DA_SHARED_CONTEXT = "draft_assistant_shared_context"
PHASE_DA_PROJECTION_POOL = "projection_pool"
PHASE_DA_BOARD_HYDRATE = "draft_assistant_board_hydrate"
PHASE_DA_SETTINGS_ONCHANGE = "draft_assistant_settings_onchange"
PHASE_DA_CANONICAL_SETTINGS = "draft_assistant_canonical_settings"
PHASE_DA_PAGE_STATE_SAVE = "draft_assistant_page_state_save"
PHASE_DA_FORCE_SAVE = "draft_assistant_force_save"
PHASE_DA_BUILD_DISK_STATE = "draft_assistant_build_disk_state"
PHASE_DA_CLOUD_AUTOSAVE = "draft_assistant_cloud_autosave"
PHASE_DA_SCORING = "draft_assistant_scoring"
PHASE_DA_ROSTER_FIT = "roster_fit_scoring"
PHASE_DA_CATEGORY_ANALYSIS = "draft_assistant_category_analysis"
PHASE_DA_WHY_TEXT = "draft_assistant_why_text"
PHASE_DA_TABLE_PREP = "draft_assistant_table_prep"
PHASE_DA_RECOMMENDATIONS = "draft_assistant_recommendations"
PHASE_DA_ROSTER_CHANGE = "draft_assistant_roster_change"
PHASE_DA_NAV_RETURN = "draft_assistant_nav_return"

_DA_PHASE_PREFIX = "draft_assistant_"


def _dev_enabled(session: dict[str, Any]) -> bool:
    try:
        from page_perf_phases import dev_perf_enabled

        return dev_perf_enabled(session)
    except ImportError:
        return False


def record_draft_assistant_action(
    session: dict[str, Any],
    action: str,
    elapsed_sec: float,
    *,
    phase: str = "",
    cache: str | None = None,
    detail: str = "",
) -> None:
    if not _dev_enabled(session):
        return
    label = str(action or phase or "action").strip()
    if not label:
        return
    phase_name = str(phase or label).strip()
    try:
        from page_perf_phases import record_perf_phase

        record_perf_phase(session, phase_name, elapsed_sec)
    except ImportError:
        pass
    rows = session.get(DRAFT_ASSISTANT_PERF_ACTIONS_KEY)
    if not isinstance(rows, list):
        rows = []
    rows.append(
        {
            "action": label,
            "phase": phase_name,
            "elapsed_ms": round(float(elapsed_sec) * 1000.0, 2),
            "cache": str(cache) if cache else "",
            "detail": str(detail or "")[:120],
            "at": round(time.time(), 3),
        }
    )
    session[DRAFT_ASSISTANT_PERF_ACTIONS_KEY] = rows[-DRAFT_ASSISTANT_PERF_MAX:]


@contextmanager
def draft_assistant_perf_action(
    session: dict[str, Any],
    action: str,
    *,
    phase: str = "",
    cache: str | None = None,
) -> Iterator[None]:
    if not _dev_enabled(session):
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - t0
        record_draft_assistant_action(
            session,
            action,
            elapsed,
            phase=phase or action,
            cache=cache,
        )


def record_draft_assistant_cache_action(
    session: dict[str, Any],
    action: str,
    *,
    phase: str,
    hit: bool,
    elapsed_sec: float = 0.0,
) -> None:
    cache_label = "hit" if hit else "miss"
    try:
        from page_perf_phases import record_cache_event

        record_cache_event(session, phase, hit=hit)
    except ImportError:
        pass
    record_draft_assistant_action(
        session,
        action,
        elapsed_sec,
        phase=phase,
        cache=cache_label,
    )


def recent_draft_assistant_actions(session: dict[str, Any], *, limit: int = 24) -> list[dict[str, Any]]:
    rows = session.get(DRAFT_ASSISTANT_PERF_ACTIONS_KEY)
    if not isinstance(rows, list):
        return []
    return list(rows[-max(1, int(limit)) :])


def summarize_draft_assistant_phases(session: dict[str, Any], *, limit: int = 16) -> list[tuple[str, float]]:
    """Top slow Draft Assistant phases from the shared perf namespace (seconds)."""
    ns = session.get("_page_perf_ns")
    if not isinstance(ns, dict):
        return []
    timings = dict(ns.get("timings") or {})
    extra = {
        PHASE_DA_PROJECTION_POOL,
        PHASE_DA_ROSTER_FIT,
        "roster_tracker",
        "category_outlook",
    }
    ranked = [
        (name, float(sec))
        for name, sec in timings.items()
        if name.startswith(_DA_PHASE_PREFIX) or name in extra
    ]
    ranked.sort(key=lambda kv: kv[1], reverse=True)
    return ranked[: max(1, int(limit))]


def draft_assistant_phase_total_ms(session: dict[str, Any]) -> float:
    ns = session.get("_page_perf_ns")
    if not isinstance(ns, dict):
        return 0.0
    timings = dict(ns.get("timings") or {})
    return sum(
        float(sec) * 1000.0
        for name, sec in timings.items()
        if name.startswith(_DA_PHASE_PREFIX) or name in (PHASE_DA_PROJECTION_POOL, PHASE_DA_ROSTER_FIT)
    )
