"""Live Draft Room action-level performance tracing (Developer Mode only)."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

LIVE_DRAFT_PERF_ACTIONS_KEY = "_live_draft_perf_actions"
LIVE_DRAFT_PERF_MAX = 32

# Canonical phase names shown in Page performance panel.
PHASE_DRAFT_PICK = "live_draft_pick"
PHASE_PICK_COMMIT = "live_draft_pick_commit"
PHASE_QUEUE_ADD = "live_draft_queue_add"
PHASE_QUEUE_REMOVE = "live_draft_queue_remove"
PHASE_QUEUE_REORDER = "live_draft_queue_reorder"
PHASE_RECOMMENDATIONS = "live_draft_recommendations"
PHASE_SCORE_AVAILABLE = "live_draft_score_available"
PHASE_AVAILABLE_POOL = "live_draft_available_pool"
PHASE_DECISION_CONTEXT = "live_draft_decision_context"
PHASE_ROSTER_TRACKER = "roster_tracker"
PHASE_CATEGORY_OUTLOOK = "category_outlook"
PHASE_POSITION_SCARCITY = "position_scarcity"
PHASE_PERSIST = "live_draft_persist"
PHASE_PREPARE_STATE = "live_draft_prepare_state"
PHASE_BOARD_TABLE = "live_draft_board_table"
PHASE_POST_DRAFT_SAVE = "live_draft_post_draft_save"
PHASE_REC_SECTION = "live_draft_rec_section"
PHASE_ROSTER_SECTION = "live_draft_roster_section"
PHASE_SECTION_NAV = "live_draft_section_nav"
PHASE_TIMER_PROCESS = "live_draft_timer_process"
PHASE_CHAT_LOAD = "live_draft_chat_load"
PHASE_DRAFT_STATE_LOAD = "live_draft_state_load"
PHASE_PAGE_TOTAL = "live_draft_page_total"

# Pick-commit sub-phases (slice 2 — profile before optimize).
PHASE_PICK_COMMIT_DIAG = "live_draft_pick_commit_diag"
PHASE_PICK_SYNC_REVISION = "live_draft_pick_sync_revision"
PHASE_PICK_VERDICT_PREP = "live_draft_pick_verdict_prep"
PHASE_PICK_MAKE_PICK = "live_draft_pick_make_pick"
PHASE_PICK_BOARD_MUTATION = "live_draft_pick_board_mutation"
PHASE_PICK_ROSTER_MUTATION = "live_draft_pick_roster_mutation"
PHASE_PICK_PICK_ENRICH = "live_draft_pick_enrich"
PHASE_PICK_CACHE_INVALIDATE = "live_draft_pick_cache_invalidate"
PHASE_PICK_PERSIST = "live_draft_pick_persist"
PHASE_PICK_SHARED_COMMIT = "live_draft_pick_shared_commit"
PHASE_PICK_DEFER_FLAGS = "live_draft_pick_defer_flags"
PHASE_PICK_ROOM_SERIALIZE = "live_draft_pick_room_serialize"
PHASE_PICK_CANONICAL_PATCH = "live_draft_pick_canonical_patch"
PHASE_PICK_CANONICAL_FULL = "live_draft_pick_canonical_full"
PHASE_PICK_PAGE_FILTER_SYNC = "live_draft_pick_page_filter_sync"
PHASE_PICK_RECONCILE = "live_draft_pick_reconcile"
PHASE_PICK_ACTIVITY = "live_draft_pick_activity"
PHASE_PICK_CLOUD_HOOK = "live_draft_pick_cloud_hook"

_PICK_COMMIT_PHASE_PREFIX = "live_draft_pick_"

# Live Draft setup/configuration path (pre-room and lobby).
PHASE_SETUP_PAGE_PREP = "live_draft_setup_page_prep"
PHASE_SETUP_RENDER = "live_draft_setup_render"
PHASE_SETUP_SHARED_CONTEXT = "live_draft_setup_shared_context"
PHASE_SETUP_GLOBAL_FANTASY = "live_draft_setup_global_fantasy"
PHASE_SETUP_SETTINGS_ONCHANGE = "live_draft_setup_settings_onchange"
PHASE_SETUP_CANONICAL_SETTINGS = "live_draft_setup_canonical_settings"
PHASE_SETUP_PAGE_STATE_SAVE = "live_draft_setup_page_state_save"
PHASE_SETUP_FORCE_SAVE = "live_draft_setup_force_save"
PHASE_SETUP_BUILD_DISK_STATE = "live_draft_setup_build_disk_state"
PHASE_SETUP_CLOUD_AUTOSAVE = "live_draft_setup_cloud_autosave"
PHASE_SETUP_PREPARE_DRAFT_ROOM = "live_draft_setup_prepare_draft_room"
PHASE_SETUP_PREPARE_LIVE_STATE = "live_draft_setup_prepare_live_state"
PHASE_SETUP_SYNC_DRAFT_ROOM_SAVE = "live_draft_setup_sync_draft_room_save"
PHASE_SETUP_START_POOL_BUILD = "live_draft_setup_start_pool_build"
PHASE_SETUP_ROOM_CREATE = "live_draft_setup_room_create"
PHASE_SETUP_LOBBY_RECOMMENDATIONS = "live_draft_setup_lobby_recommendations"
PHASE_SETUP_JOIN_LOOKUP = "live_draft_setup_join_lookup"

_SETUP_PHASE_PREFIX = "live_draft_setup_"


def _dev_enabled(session: dict[str, Any]) -> bool:
    try:
        from page_perf_phases import dev_perf_enabled

        return dev_perf_enabled(session)
    except ImportError:
        return False


def record_live_draft_action(
    session: dict[str, Any],
    action: str,
    elapsed_sec: float,
    *,
    phase: str = "",
    cache: str | None = None,
    detail: str = "",
) -> None:
    """Append one timed action to the Live Draft action log."""
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
    rows = session.get(LIVE_DRAFT_PERF_ACTIONS_KEY)
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
    session[LIVE_DRAFT_PERF_ACTIONS_KEY] = rows[-LIVE_DRAFT_PERF_MAX:]


@contextmanager
def live_draft_perf_action(
    session: dict[str, Any],
    action: str,
    *,
    phase: str = "",
    cache: str | None = None,
) -> Iterator[None]:
    """Time a Live Draft hot-path action and record phase + action log."""
    if not _dev_enabled(session):
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - t0
        record_live_draft_action(
            session,
            action,
            elapsed,
            phase=phase or action,
            cache=cache,
        )


def record_cache_action(
    session: dict[str, Any],
    action: str,
    *,
    phase: str,
    hit: bool,
    elapsed_sec: float = 0.0,
) -> None:
    """Record cache hit/miss alongside optional elapsed time for a sub-step."""
    cache_label = "hit" if hit else "miss"
    try:
        from page_perf_phases import record_cache_event

        record_cache_event(session, phase, hit=hit)
    except ImportError:
        pass
    record_live_draft_action(
        session,
        action,
        elapsed_sec,
        phase=phase,
        cache=cache_label,
    )


def recent_live_draft_actions(session: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    rows = session.get(LIVE_DRAFT_PERF_ACTIONS_KEY)
    if not isinstance(rows, list):
        return []
    return list(rows[-max(1, int(limit)) :])


def render_live_draft_perf_section(st: Any, session: dict[str, Any]) -> None:
    """Developer Mode sidebar — recent Live Draft actions with cache hints."""
    if not _dev_enabled(session):
        return
    # Compact timing strip requested for Live Draft Room profiling.
    buckets = [
        ("page", session.get("_live_draft_page_total_ms")),
        ("timer", session.get("_live_draft_timer_process_ms")),
        ("recs", session.get("_live_draft_rec_engine_ms")),
        ("state", session.get("_live_draft_state_load_ms")),
        ("persist", session.get("_live_draft_persist_ms")),
        ("chat", session.get("_live_draft_chat_load_ms")),
    ]
    present = [(k, v) for k, v in buckets if v is not None]
    if present:
        st.markdown("**Live Draft — timing (ms)**")
        st.caption(" · ".join(f"{k}={int(v)}" for k, v in present))
    rows = recent_live_draft_actions(session, limit=12)
    if not rows:
        return
    st.markdown("**Live Draft — recent actions**")
    for row in reversed(rows):
        action = str(row.get("action") or row.get("phase") or "—")
        ms = float(row.get("elapsed_ms") or 0.0)
        bits = [f"{action}: {ms:.1f}ms"]
        cache = str(row.get("cache") or "").strip()
        if cache:
            bits.append(f"cache {cache}")
        detail = str(row.get("detail") or "").strip()
        if detail:
            bits.append(detail)
        st.text(" · ".join(bits))


def summarize_pick_commit_phases(session: dict[str, Any], *, limit: int = 24) -> list[tuple[str, float]]:
    """Pick-commit sub-phases from the shared perf namespace (ms, descending)."""
    ns = session.get("_page_perf_ns")
    if not isinstance(ns, dict):
        return []
    timings = dict(ns.get("timings") or {})
    ranked = [
        (name, float(sec) * 1000.0)
        for name, sec in timings.items()
        if name.startswith(_PICK_COMMIT_PHASE_PREFIX) and name != PHASE_PICK_COMMIT
    ]
    ranked.sort(key=lambda kv: kv[1], reverse=True)
    return ranked[: max(1, int(limit))]


def pick_commit_phase_total_ms(session: dict[str, Any]) -> float:
    ns = session.get("_page_perf_ns")
    if not isinstance(ns, dict):
        return 0.0
    timings = dict(ns.get("timings") or {})
    return sum(float(sec) * 1000.0 for name, sec in timings.items() if name.startswith(_PICK_COMMIT_PHASE_PREFIX))


def summarize_setup_phases(session: dict[str, Any], *, limit: int = 24) -> list[tuple[str, float]]:
    """Setup/configuration sub-phases from the shared perf namespace (ms, descending)."""
    ns = session.get("_page_perf_ns")
    if not isinstance(ns, dict):
        return []
    timings = dict(ns.get("timings") or {})
    ranked = [
        (name, float(sec) * 1000.0)
        for name, sec in timings.items()
        if name.startswith(_SETUP_PHASE_PREFIX)
    ]
    ranked.sort(key=lambda kv: kv[1], reverse=True)
    return ranked[: max(1, int(limit))]


def setup_phase_total_ms(session: dict[str, Any]) -> float:
    ns = session.get("_page_perf_ns")
    if not isinstance(ns, dict):
        return 0.0
    timings = dict(ns.get("timings") or {})
    return sum(float(sec) * 1000.0 for name, sec in timings.items() if name.startswith(_SETUP_PHASE_PREFIX))


def summarize_live_draft_phases(session: dict[str, Any], *, limit: int = 10) -> list[tuple[str, float]]:
    """Top slow Live Draft phases from the shared perf namespace."""
    ns = session.get("_page_perf_ns")
    if not isinstance(ns, dict):
        return []
    timings = dict(ns.get("timings") or {})
    live_prefixes = (
        "live_draft_",
        "roster_tracker",
        "category_outlook",
        "position_scarcity",
    )
    ranked = [
        (name, float(sec))
        for name, sec in timings.items()
        if any(name.startswith(p) or name == p for p in live_prefixes)
    ]
    ranked.sort(key=lambda kv: kv[1], reverse=True)
    return ranked[: max(1, int(limit))]
