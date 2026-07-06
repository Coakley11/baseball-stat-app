"""Deferred persistence for Draft Assistant settings — lightweight widget edits."""

from __future__ import annotations

import time
from typing import Any

DRAFT_ASSISTANT_DIRTY_KEY = "_draft_assistant_settings_dirty"
DRAFT_ASSISTANT_DIRTY_TS_KEY = "_draft_assistant_settings_dirty_ts"
DRAFT_ASSISTANT_AUTOSAVE_SEC = 3.0


def mark_draft_assistant_settings_dirty(session: dict[str, Any]) -> None:
    session[DRAFT_ASSISTANT_DIRTY_KEY] = True
    session[DRAFT_ASSISTANT_DIRTY_TS_KEY] = time.time()


def clear_draft_assistant_settings_dirty(session: dict[str, Any]) -> None:
    session.pop(DRAFT_ASSISTANT_DIRTY_KEY, None)
    session.pop(DRAFT_ASSISTANT_DIRTY_TS_KEY, None)


def is_draft_assistant_settings_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(DRAFT_ASSISTANT_DIRTY_KEY))


def on_draft_assistant_settings_changed(session: dict[str, Any]) -> None:
    """Lightweight settings edit — canonical settings + dirty flag only (no cloud/disk save)."""
    try:
        from draft_assistant_perf import (
            PHASE_DA_CANONICAL_SETTINGS,
            PHASE_DA_SETTINGS_ONCHANGE,
            draft_assistant_perf_action,
        )

        with draft_assistant_perf_action(session, "settings_onchange", phase=PHASE_DA_SETTINGS_ONCHANGE):
            with draft_assistant_perf_action(session, "canonical_settings", phase=PHASE_DA_CANONICAL_SETTINGS):
                _apply_canonical_draft_assistant_settings(session)
    except ImportError:
        _apply_canonical_draft_assistant_settings(session)
    try:
        from live_draft_ui_cache import invalidate_draft_assistant_ui_caches

        invalidate_draft_assistant_ui_caches(session)
    except ImportError:
        pass
    mark_draft_assistant_settings_dirty(session)


def _apply_canonical_draft_assistant_settings(session: dict[str, Any]) -> None:
    try:
        from shared_draft_context import on_draft_settings_changed

        on_draft_settings_changed(
            session,
            source_page="Draft Assistant Simulator",
            lookback_key="draft_window",
            style_key="fantasy_draft_projection_style",
            format_key="draft_format",
            ml_blend_key="draft_use_ml_blend",
            ml_weight_key="draft_ml_blend_weight",
            ml_min_games_key="draft_ml_min_games_signal",
        )
    except ImportError:
        pass


def flush_draft_assistant_settings_persist(
    st: Any,
    session: dict[str, Any],
    *,
    reason: str,
    save_page: bool = True,
) -> bool:
    """Persist deferred Draft Assistant edits to page_filter_state + disk/cloud."""
    if not is_draft_assistant_settings_dirty(session) and reason != "draft_assistant_settings_force":
        return False
    try:
        from draft_assistant_perf import (
            PHASE_DA_FORCE_SAVE,
            PHASE_DA_PAGE_STATE_SAVE,
            draft_assistant_perf_action,
        )

        if save_page:
            with draft_assistant_perf_action(session, "page_state_save", phase=PHASE_DA_PAGE_STATE_SAVE):
                _save_draft_assistant_page_state(session)
        with draft_assistant_perf_action(session, "force_save", phase=PHASE_DA_FORCE_SAVE):
            _force_save_draft_assistant(st, session, reason=reason)
    except ImportError:
        if save_page:
            _save_draft_assistant_page_state(session)
        _force_save_draft_assistant(st, session, reason=reason)
    clear_draft_assistant_settings_dirty(session)
    return True


def maybe_flush_deferred_draft_assistant_autosave(st: Any, session: dict[str, Any]) -> bool:
    """Debounced background flush while user keeps editing Draft Assistant settings."""
    if not is_draft_assistant_settings_dirty(session):
        return False
    ts = float(session.get(DRAFT_ASSISTANT_DIRTY_TS_KEY) or 0.0)
    if ts <= 0 or (time.time() - ts) < DRAFT_ASSISTANT_AUTOSAVE_SEC:
        return False
    return flush_draft_assistant_settings_persist(
        st, session, reason="draft_assistant_debounced_autosave"
    )


def _save_draft_assistant_page_state(session: dict[str, Any]) -> None:
    try:
        import page_state as pg_state

        store = session.setdefault("page_filter_state", {})
        pg_state.save_page_state(session, "Draft Assistant Simulator", store)
    except Exception:
        pass


def _force_save_draft_assistant(st: Any, session: dict[str, Any], *, reason: str) -> None:
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason=reason)
    except ImportError:
        pass
