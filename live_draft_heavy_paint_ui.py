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
    *,
    paint_interactive: Callable[[], None] | None = None,
) -> None:
    """Defer expensive recommendation paint; keep interactive widgets on a live render path.

    ``paint_body`` runs once for heavy compute + initial paint. After ``HEAVY_PAINT_DONE_KEY``,
    ``paint_interactive`` runs on the owning ScriptRun (not under ``run_every``) so ``st.button``
    widgets stay registered for callbacks without timer remount races (F4 + CASE_II fix).
    """
    def _reemit_rec_queue_render_trace() -> None:
        try:
            from live_draft_rec_queue_click_trace import reemit_rec_queue_render_trace_diagnostics

            reemit_rec_queue_render_trace_diagnostics(st, session)
        except ImportError:
            pass

    def _reemit_fragment_diagnostics() -> None:
        _reemit_rec_queue_render_trace()
        try:
            from live_draft_rec_fragment_exec_diag import reemit_fragment_callback_ledger_probe

            reemit_fragment_callback_ledger_probe(st, session)
        except ImportError:
            pass
        try:
            from live_draft_queue_state_snapshot_diag import render_queue_state_snapshot_probe

            render_queue_state_snapshot_probe(st, session)
        except ImportError:
            pass

    def _invoke_paint_body(*, via: str) -> None:
        try:
            from live_draft_rec_fragment_exec_diag import enter_recommendation_paint_invocation

            enter_recommendation_paint_invocation(session, st, via=via)
        except ImportError:
            pass
        paint_body()

    def _invoke_paint_interactive(*, via: str) -> None:
        if paint_interactive is None:
            return
        try:
            from live_draft_rec_fragment_exec_diag import enter_recommendation_paint_invocation

            enter_recommendation_paint_invocation(session, st, via=via)
        except ImportError:
            pass
        paint_interactive()

    try:
        from live_draft_fast_solo_start import (
            clear_defer_heavy_first_paint,
            note_start_stage,
            should_defer_heavy_first_paint,
        )
    except ImportError:
        _invoke_paint_body(via="full_page_no_fast_start")
        return

    fragment = getattr(st, "fragment", None)

    def _heavy_paint_fragment() -> None:
        if session.get(HEAVY_PAINT_DONE_KEY):
            # Do not re-register Add-to-Queue under run_every — ScriptRun owns them
            # after HEAVY_PAINT_DONE_KEY (see outer branch below). Diagnostics only.
            _reemit_fragment_diagnostics()
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
        _invoke_paint_body(via="fragment")
        session[HEAVY_PAINT_DONE_KEY] = True
        note_start_stage(session, "heavy_content_rendered", via="fragment")
        # paint_body must not register Add-to-Queue under this run_every fragment
        # (production 47712472: heavy_paint_done=0 at click, transport without callback).
        # Force a full-app ScriptRun so the outer DONE branch owns interactive widgets.
        session["_live_draft_rec_queue_interactive_owner"] = "pending_script_run_handoff"
        try:
            st.rerun(scope="app")
        except TypeError:
            st.rerun()
        return

    if session.get(HEAVY_PAINT_DONE_KEY):
        # After first heavy paint, Add-to-Queue must register on the owning ScriptRun.
        # Keeping these buttons under fragment(run_every=1) remounts them every second:
        # the browser can still emit the widget key (WS transport) while Streamlit never
        # dispatches on_click — FRAGMENT_MATRIX_CASE_II / production c50733b1 / 47712472.
        # Timer refresh stays in dedicated timer/heartbeat fragments, not this surface.
        #
        # Claim ownership BEFORE paint_interactive so registration diagnostics cannot
        # stamp pending_script_run_handoff (production f166ce6c: full_page path with
        # pending owner label because finalization previously ran after registration).
        note_heavy_fragment_mount(session, phase="interactive_script_run")
        session["_live_draft_rec_queue_interactive_owner"] = "script_run_no_run_every"
        _invoke_paint_interactive(via="full_page_interactive_live")
        _reemit_fragment_diagnostics()
        return

    defer = should_defer_heavy_first_paint(session)
    loading = bool(session.get(DEFER_HEAVY_LOADING_KEY))

    if not defer and not loading:
        _invoke_paint_body(via="full_page")
        session[HEAVY_PAINT_DONE_KEY] = True
        session["_live_draft_rec_queue_interactive_owner"] = "script_run_no_run_every"
        try:
            note_start_stage(session, "heavy_content_rendered", via="full_page")
        except ImportError:
            pass
        # Ensure interactive path is the dedicated ScriptRun registrar (not only paint_body).
        _invoke_paint_interactive(via="full_page_interactive_live")
        _reemit_fragment_diagnostics()
        return

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
        _invoke_paint_body(via="full_page_no_fragment_api")
        session[HEAVY_PAINT_DONE_KEY] = True
        session["_live_draft_rec_queue_interactive_owner"] = "script_run_no_run_every"
        _invoke_paint_interactive(via="full_page_interactive_live")
        return

    note_heavy_fragment_mount(session, phase="mount")
    fragment(run_every=1)(_heavy_paint_fragment)()
