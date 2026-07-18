"""Deferred persistence for Live Draft setup — lightweight widget edits."""

from __future__ import annotations

import time
from typing import Any

LIVE_DRAFT_SETUP_DIRTY_KEY = "_live_draft_setup_dirty"
LIVE_DRAFT_SETUP_DIRTY_TS_KEY = "_live_draft_setup_dirty_ts"
LIVE_DRAFT_SETUP_AUTOSAVE_SEC = 0.8


def is_live_draft_pre_pick_setup(session: dict[str, Any], room: dict[str, Any] | None = None) -> bool:
    """True before a live draft room is actively picking (pure setup or shared lobby)."""
    if room is None:
        room = session.get("live_draft_room")
    if not isinstance(room, dict) or not room.get("draft_room_id"):
        return True
    status = str(room.get("status") or "").strip()
    board_len = len(room.get("draft_board") or [])
    return status in ("", "not_started") and board_len == 0


def should_skip_draft_room_prep_for_live_setup(session: dict[str, Any]) -> bool:
    """Skip simulator canonical board hydrate/sync during pure live-draft setup reruns."""
    if str(session.get("active_page") or "") != "Live Draft Room":
        return False
    return is_live_draft_pre_pick_setup(session)


def should_skip_live_draft_state_prep(session: dict[str, Any]) -> bool:
    """Skip live_draft_state hydrate when no runtime room exists yet."""
    if str(session.get("active_page") or "") != "Live Draft Room":
        return False
    return is_live_draft_pre_pick_setup(session)


def should_skip_live_draft_recommendations(session: dict[str, Any], room: dict[str, Any] | None = None) -> bool:
    """Do not score recommendations during setup / pre-pick lobby."""
    return is_live_draft_pre_pick_setup(session, room=room)


def mark_live_draft_setup_dirty(session: dict[str, Any]) -> None:
    session[LIVE_DRAFT_SETUP_DIRTY_KEY] = True
    session[LIVE_DRAFT_SETUP_DIRTY_TS_KEY] = time.time()


def clear_live_draft_setup_dirty(session: dict[str, Any]) -> None:
    session.pop(LIVE_DRAFT_SETUP_DIRTY_KEY, None)
    session.pop(LIVE_DRAFT_SETUP_DIRTY_TS_KEY, None)


def is_live_draft_setup_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(LIVE_DRAFT_SETUP_DIRTY_KEY))


def on_live_draft_setup_widget_changed(
    session: dict[str, Any],
    *,
    source_page: str = "Live Draft Room",
    lookback_key: str = "live_draft_proj_window",
    style_key: str = "live_draft_proj_style",
    format_key: str = "live_draft_scoring",
) -> None:
    """Lightweight setup edit — canonical settings + dirty flag; autosave follows shortly."""
    # Ignore widget on_change fired while we are seeding session from persistence.
    if session.get("_live_draft_setup_seeding"):
        return
    try:
        from live_draft_perf import PHASE_SETUP_CANONICAL_SETTINGS, PHASE_SETUP_SETTINGS_ONCHANGE, live_draft_perf_action

        with live_draft_perf_action(session, "settings_onchange", phase=PHASE_SETUP_SETTINGS_ONCHANGE):
            with live_draft_perf_action(session, "canonical_settings", phase=PHASE_SETUP_CANONICAL_SETTINGS):
                _apply_canonical_setup_settings(
                    session,
                    source_page=source_page,
                    lookback_key=lookback_key,
                    style_key=style_key,
                    format_key=format_key,
                )
    except ImportError:
        _apply_canonical_setup_settings(
            session,
            source_page=source_page,
            lookback_key=lookback_key,
            style_key=style_key,
            format_key=format_key,
        )
    mark_live_draft_setup_dirty(session)


def _apply_canonical_setup_settings(
    session: dict[str, Any],
    *,
    source_page: str,
    lookback_key: str,
    style_key: str,
    format_key: str,
) -> None:
    try:
        from shared_draft_context import on_draft_settings_changed

        on_draft_settings_changed(
            session,
            source_page=source_page,
            lookback_key=lookback_key,
            style_key=style_key,
            format_key=format_key,
        )
    except ImportError:
        pass


def flush_live_draft_setup_persist(
    st: Any,
    session: dict[str, Any],
    *,
    reason: str,
    save_page: bool = True,
) -> bool:
    """Persist deferred setup edits to page_filter_state + disk/cloud + preference record."""
    if not is_live_draft_setup_dirty(session) and reason != "live_draft_setup_force":
        return False
    try:
        from live_draft_perf import (
            PHASE_SETUP_FORCE_SAVE,
            PHASE_SETUP_PAGE_STATE_SAVE,
            live_draft_perf_action,
        )

        if save_page:
            with live_draft_perf_action(session, "page_state_save", phase=PHASE_SETUP_PAGE_STATE_SAVE):
                _save_live_draft_page_state(st, session)
        with live_draft_perf_action(session, "force_save", phase=PHASE_SETUP_FORCE_SAVE):
            _force_save_setup(st, session, reason=reason)
    except ImportError:
        if save_page:
            _save_live_draft_page_state(st, session)
        _force_save_setup(st, session, reason=reason)
    try:
        from user_page_preferences import persist_live_draft_setup_preferences

        persist_live_draft_setup_preferences(session, st=st, force_disk=True)
    except ImportError:
        pass
    clear_live_draft_setup_dirty(session)
    return True


def maybe_flush_deferred_live_draft_setup_autosave(st: Any, session: dict[str, Any]) -> bool:
    """Debounced background flush while user keeps editing setup."""
    if not is_live_draft_setup_dirty(session):
        return False
    ts = float(session.get(LIVE_DRAFT_SETUP_DIRTY_TS_KEY) or 0.0)
    if ts <= 0 or (time.time() - ts) < LIVE_DRAFT_SETUP_AUTOSAVE_SEC:
        return False
    return flush_live_draft_setup_persist(st, session, reason="live_draft_setup_debounced_autosave")


def _save_live_draft_page_state(st: Any, session: dict[str, Any]) -> None:
    try:
        import page_state as pg_state

        store = session.setdefault("page_filter_state", {})
        pg_state.save_page_state(session, "Live Draft Room", store)
    except Exception:
        pass


def _force_save_setup(st: Any, session: dict[str, Any], *, reason: str) -> None:
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason=reason)
    except ImportError:
        pass
