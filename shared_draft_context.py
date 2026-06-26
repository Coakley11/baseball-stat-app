"""Shared draft settings (lookback, format, projection style) while a draft is active."""

from __future__ import annotations

from typing import Any

GLOBAL_WINDOW_KEY = "room_window"
GLOBAL_PROJECTION_STYLE_KEY = "fantasy_draft_projection_style"

WINDOW_ALIASES: dict[str, str] = {
    "draft_window": GLOBAL_WINDOW_KEY,
    "live_draft_proj_window": GLOBAL_WINDOW_KEY,
    "draft_lab_window": GLOBAL_WINDOW_KEY,
    "fantasy_market_window": GLOBAL_WINDOW_KEY,
}

PROJECTION_STYLE_ALIASES: dict[str, str] = {
    "live_draft_proj_style": GLOBAL_PROJECTION_STYLE_KEY,
    "draft_lab_projection_style": GLOBAL_PROJECTION_STYLE_KEY,
}

_ALL_ALIASES: dict[str, str] = {**WINDOW_ALIASES, **PROJECTION_STYLE_ALIASES}

DRAFT_SYNC_PAGES: frozenset[str] = frozenset(
    {
        "Live Draft Room",
        "Draft Assistant Simulator",
        "Draft Room Simulator",
        "Draft Simulation Test Mode",
        "Fantasy Sleepers & Busts",
        "Fantasy Lineup Assistant",
        "Fantasy Standings Tracker",
    }
)

RESEARCH_PAGES: frozenset[str] = frozenset(
    {
        "Historical Explorer",
        "Career Totals",
        "Leaderboards",
        "Comparison Tool",
        "Trend Value",
        "Valuation",
        "Scatterplots",
        "Hall of Fame Predictor",
        "Hall of Fame Explorer",
        "ML Predictions",
    }
)

_SHARED_CONTEXT_DIAG_KEY = "_shared_draft_context_diag"
_LAST_RESUME_KEY = "_suite_last_consumed_resume_key"


def shared_draft_context_snapshot_excluded_keys() -> frozenset[str]:
    return frozenset({GLOBAL_WINDOW_KEY, GLOBAL_PROJECTION_STYLE_KEY, *_ALL_ALIASES.keys()})


def has_active_draft_context(session: dict[str, Any]) -> bool:
    """True when live or simulator draft should drive shared settings."""
    try:
        from draft_room_state import get_active_draft_status, table_pick_count, DRAFT_ROOM_TABLE_KEY

        status = get_active_draft_status(session)
        if status.get("active"):
            return True
        if int(status.get("pick_count") or 0) > 0:
            return True
        if table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY)) > 0:
            return True
    except ImportError:
        pass
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, has_active_live_draft
        from draft_room_state import live_draft_handoff_pick_count

        if has_active_live_draft(session):
            return True
        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if isinstance(room, dict):
            if str(room.get("status") or "") in ("in_progress", "paused", "complete"):
                return True
            if live_draft_handoff_pick_count(room) > 0:
                return True
    except ImportError:
        room = session.get("live_draft_room")
        if isinstance(room, dict) and str(room.get("status") or "") in (
            "in_progress",
            "paused",
            "complete",
        ):
            return True
    return False


def _mirror_aliases(session: dict[str, Any]) -> None:
    window = session.get(GLOBAL_WINDOW_KEY)
    style = session.get(GLOBAL_PROJECTION_STYLE_KEY)
    for alias, canonical in _ALL_ALIASES.items():
        val = window if canonical == GLOBAL_WINDOW_KEY else style
        if val is not None:
            session[alias] = val
    session["_shared_draft_context_last_propagated"] = {
        alias: session.get(alias) for alias in _ALL_ALIASES
    }


def write_shared_draft_context(
    session: dict[str, Any],
    *,
    lookback: int | None = None,
    projection_style: str | None = None,
    source_page: str = "",
    reason: str = "",
) -> None:
    if lookback is not None:
        session[GLOBAL_WINDOW_KEY] = int(lookback)
    if projection_style is not None:
        session[GLOBAL_PROJECTION_STYLE_KEY] = str(projection_style).strip()
    _mirror_aliases(session)
    session["_shared_draft_context_source_page"] = str(source_page or "").strip() or None
    session["_shared_draft_context_last_update_reason"] = reason or None
    session["_shared_draft_context_inherited"] = False
    _record_diag(session, step=f"write:{reason or 'unspecified'}")


def prepare_shared_draft_context(
    session: dict[str, Any],
    *,
    active_page: str = "",
    force_mirror: bool = False,
) -> None:
    """Mirror canonical lookback + projection style into draft page aliases when a draft is active."""
    if not has_active_draft_context(session):
        _record_diag(session, step="inactive")
        return
    window = session.get(GLOBAL_WINDOW_KEY)
    style = session.get(GLOBAL_PROJECTION_STYLE_KEY)
    if window is None:
        for alias in WINDOW_ALIASES:
            if session.get(alias) is not None:
                session[GLOBAL_WINDOW_KEY] = int(session[alias])
                break
    if style is None:
        for alias in PROJECTION_STYLE_ALIASES:
            if session.get(alias) is not None:
                session[GLOBAL_PROJECTION_STYLE_KEY] = str(session[alias])
                break
    window = session.get(GLOBAL_WINDOW_KEY)
    style = session.get(GLOBAL_PROJECTION_STYLE_KEY)
    last = session.get("_shared_draft_context_last_propagated") or {}
    for alias, canonical in _ALL_ALIASES.items():
        canonical_val = window if canonical == GLOBAL_WINDOW_KEY else style
        if canonical_val is None:
            continue
        if alias not in session:
            session[alias] = canonical_val
            session["_shared_draft_context_inherited"] = True
        elif session[alias] != canonical_val:
            if force_mirror or (isinstance(last, dict) and last.get(alias) == session[alias]):
                session[alias] = canonical_val
                session["_shared_draft_context_inherited"] = True
    _mirror_aliases(session)
    try:
        from global_fantasy_settings_state import prepare_global_fantasy_settings

        prepare_global_fantasy_settings(session, force_mirror=force_mirror)
    except ImportError:
        pass
    _record_diag(session, step=f"prepare:{active_page or 'global'}")


def on_alias_lookback_changed(session: dict[str, Any], alias_key: str, *, source_page: str = "") -> None:
    if not has_active_draft_context(session):
        return
    val = session.get(alias_key)
    if val is not None:
        write_shared_draft_context(
            session,
            lookback=int(val),
            source_page=source_page or alias_key,
            reason=f"lookback:{alias_key}",
        )


def on_alias_projection_style_changed(session: dict[str, Any], alias_key: str, *, source_page: str = "") -> None:
    if not has_active_draft_context(session):
        return
    val = session.get(alias_key)
    if val is not None:
        write_shared_draft_context(
            session,
            projection_style=str(val),
            source_page=source_page or alias_key,
            reason=f"projection_style:{alias_key}",
        )


def shared_draft_context_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "shared_draft_context_exists": has_active_draft_context(session),
        "source_page": session.get("_shared_draft_context_source_page"),
        "lookback_window": session.get(GLOBAL_WINDOW_KEY),
        "fantasy_format": session.get("room_format"),
        "projection_style": session.get(GLOBAL_PROJECTION_STYLE_KEY),
        "last_update_page": session.get("_shared_draft_context_source_page"),
        "last_update_reason": session.get("_shared_draft_context_last_update_reason"),
        "inherited_from_shared_context": bool(session.get("_shared_draft_context_inherited")),
        "window_aliases": {a: session.get(a) for a in WINDOW_ALIASES},
        "projection_aliases": {a: session.get(a) for a in PROJECTION_STYLE_ALIASES},
    }


def _record_diag(session: dict[str, Any], *, step: str) -> None:
    session[_SHARED_CONTEXT_DIAG_KEY] = {
        **shared_draft_context_diagnostics(session),
        "step": step,
    }


def mark_resume_key_consumed(session: dict[str, Any], resume_key: str) -> None:
    session[_LAST_RESUME_KEY] = str(resume_key or "").strip()


def is_fresh_resume_request(session: dict[str, Any], resume_key: str) -> bool:
    key = str(resume_key or "").strip()
    if not key:
        return False
    return key != str(session.get(_LAST_RESUME_KEY) or "").strip()


def render_research_draft_context_banner(st: Any, session: dict[str, Any], active_page: str) -> None:
    """Optional banner on research pages when a draft context exists."""
    if active_page in DRAFT_SYNC_PAGES or active_page not in RESEARCH_PAGES:
        return
    if not has_active_draft_context(session):
        return

    def _apply() -> None:
        prepare_shared_draft_context(session, active_page=active_page, force_mirror=True)
        session["_shared_draft_context_inherited"] = True

    with st.container(border=True):
        st.markdown("**Active Draft Context Available**")
        st.caption(
            f"Lookback {session.get(GLOBAL_WINDOW_KEY, '—')} yr · "
            f"{session.get('room_format', '—')} · "
            f"{session.get(GLOBAL_PROJECTION_STYLE_KEY, '—')}"
        )
        st.button(
            "Apply Draft Settings",
            key=f"apply_draft_settings_{active_page.replace(' ', '_')}",
            on_click=_apply,
        )
