"""Deferred heavy Live Draft paint — fragment-only load without full-page rerun."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

DEFER_HEAVY_LOADING_KEY = "_live_draft_defer_heavy_loading"
HEAVY_PAINT_DONE_KEY = "_live_draft_heavy_paint_done"
HEAVY_FRAGMENT_MOUNT_KEY = "_live_draft_heavy_fragment_mount_log"


def note_heavy_fragment_mount(session: dict[str, Any], *, phase: str = "render") -> None:
    log = list(session.get(HEAVY_FRAGMENT_MOUNT_KEY) or [])
    log.append(
        {
            "ts": time.time(),
            "phase": str(phase),
            "run_seq": int(session.get("_live_draft_cloud_diag_run_seq") or 0),
        }
    )
    session[HEAVY_FRAGMENT_MOUNT_KEY] = log[-120:]


def heavy_fragment_mount_count(session: dict[str, Any]) -> int:
    return len(list(session.get(HEAVY_FRAGMENT_MOUNT_KEY) or []))


def render_deferred_heavy_paint_fragment(
    st: Any,
    session: dict[str, Any],
    paint_body: Callable[[], None],
) -> None:
    """Paint recommendations/decision panels once the stable shell is visible.

    First Solo start: defer flag skips heavy work and uses a 1 Hz fragment tick to
    paint heavy content without ``st.rerun()`` (avoids duplicate control-center widgets).
    """
    try:
        from live_draft_fast_solo_start import (
            clear_defer_heavy_first_paint,
            note_start_stage,
            should_defer_heavy_first_paint,
        )
    except ImportError:
        paint_body()
        return

    if session.get(HEAVY_PAINT_DONE_KEY):
        return

    defer = should_defer_heavy_first_paint(session)
    loading = bool(session.get(DEFER_HEAVY_LOADING_KEY))
    if not defer and not loading:
        paint_body()
        session[HEAVY_PAINT_DONE_KEY] = True
        try:
            note_start_stage(session, "heavy_content_rendered", via="full_page")
        except ImportError:
            pass
        return

    fragment = getattr(st, "fragment", None)
    if fragment is None:
        if defer:
            st.caption(
                "Draft is live — controls and timer are ready. "
                "Loading recommendations and decision tools…"
            )
            note_start_stage(session, "first_page_rendered", deferred_heavy=True)
            clear_defer_heavy_first_paint(session)
            session[DEFER_HEAVY_LOADING_KEY] = True
            return
        paint_body()
        session[HEAVY_PAINT_DONE_KEY] = True
        return

    @fragment(run_every=1)
    def _heavy_paint_fragment() -> None:
        if session.get(HEAVY_PAINT_DONE_KEY):
            return
        note_heavy_fragment_mount(session, phase="tick")
        try:
            from live_draft_cloud_diagnostics import note_fragment_owner

            note_fragment_owner(session, "heavy_paint_fragment", delta=0)
        except ImportError:
            pass
        if should_defer_heavy_first_paint(session):
            st.caption(
                "Draft is live — controls and timer are ready. "
                "Loading recommendations and decision tools…"
            )
            note_start_stage(session, "first_page_rendered", deferred_heavy=True)
            clear_defer_heavy_first_paint(session)
            session[DEFER_HEAVY_LOADING_KEY] = True
            return
        session.pop(DEFER_HEAVY_LOADING_KEY, None)
        paint_body()
        session[HEAVY_PAINT_DONE_KEY] = True
        note_start_stage(session, "heavy_content_rendered", via="fragment")

    note_heavy_fragment_mount(session, phase="mount")
    _heavy_paint_fragment()
