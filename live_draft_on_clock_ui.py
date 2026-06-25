"""Live-updating On-the-Clock banner — shares countdown with live_draft_timer_ui."""

from __future__ import annotations

import time
from typing import Any

from live_draft_timer_logic import live_draft_current_slot, live_draft_display_seconds, live_draft_timer_deadline
from live_draft_timer_ui import _mount_js_countdown, _resolve_live_room, record_timer_diagnostics


def _team_accent(team: str) -> str:
    import hashlib

    digest = hashlib.md5(str(team or "team").encode("utf-8")).hexdigest()
    return f"#{digest[:6]}"


def _render_on_clock_banner_html(
    st: Any,
    slot: dict[str, Any],
    remaining: int,
    *,
    next_pick: int | None = None,
    pick_index: int = 0,
    deadline: float | None = None,
) -> None:
    team = slot.get("Team", "—")
    rnd = slot.get("Round", "—")
    pick_no = slot.get("Pick", "—")
    next_txt = f'<div class="ld-next-pick">Your next pick: #{next_pick}</div>' if next_pick else ""
    accent = _team_accent(str(team))
    timer_id = f"ld-banner-timer-{pick_index}"
    timer_html = (
        f'<span id="{timer_id}" class="live-draft-timer">--</span>'
        if deadline is not None
        else f'<span class="live-draft-timer">{int(remaining)}s</span>'
    )
    st.markdown(
        f"""
        <div class="live-draft-on-clock" style="border-left: 8px solid {accent};">
            <div class="ld-title">On the clock</div>
            <div class="ld-team-name">{team}</div>
            <div class="ld-pick-pills">
                <span class="ld-pill">Round {rnd}</span>
                <span class="ld-pill">Pick {pick_no}</span>
            </div>
            {next_txt}
            <div class="ld-meta">
                <span class="ld-clock-label">Time remaining</span>
                {timer_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if deadline is not None:
        _mount_js_countdown(
            st,
            float(deadline),
            pick_index=pick_index,
            element_id=timer_id,
            height=0,
            source="on_clock_banner",
        )


def render_live_on_clock_banner(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    slot: dict[str, Any],
    *,
    next_pick: int | None = None,
) -> None:
    """Render blue On-the-Clock banner with client-side 1 Hz countdown."""
    if not isinstance(slot, dict):
        return
    live_room = _resolve_live_room(session, room)
    slot_view = dict(slot)
    next_pick_view = next_pick
    pick_idx = int(live_room.get("current_pick_index") or 0)

    if str(live_room.get("status") or "") == "paused":
        remaining = live_draft_display_seconds(live_room)
        _render_on_clock_banner_html(st, slot_view, remaining, next_pick=next_pick_view, pick_index=pick_idx, deadline=None)
        st.caption("Draft paused — timer stopped")
        return

    try:
        from live_draft_pick_timer import display_seconds_with_freeze, frozen_deadline, is_pick_submitting

        if is_pick_submitting(session):
            remaining = display_seconds_with_freeze(session, live_room)
            deadline = frozen_deadline(session, live_room)
            _render_on_clock_banner_html(
                st, slot_view, remaining, next_pick=next_pick_view, pick_index=pick_idx, deadline=deadline
            )
            st.caption("Submitting pick…")
            return
    except ImportError:
        pass

    deadline = live_draft_timer_deadline(live_room)
    record_timer_diagnostics(
        session,
        live_room,
        source="on_clock_banner_render",
    )
    if session.get("_live_draft_timer_diag"):
        diag = dict(session["_live_draft_timer_diag"])
        diag["timer_component_mounted"] = deadline is not None
        diag["timer_component_last_render"] = time.time()
        session["_live_draft_timer_diag"] = diag

    use_fragment = False
    try:
        from live_draft_safe_mode import is_draft_truly_complete, timer_should_run

        use_fragment = timer_should_run(session, live_room) and not is_draft_truly_complete(live_room)
    except ImportError:
        use_fragment = live_room.get("status") == "in_progress"

    if not use_fragment or deadline is None:
        _render_on_clock_banner_html(
            st,
            slot_view,
            live_draft_display_seconds(live_room),
            next_pick=next_pick_view,
            pick_index=pick_idx,
            deadline=deadline,
        )
        return

    try:
        fragment = st.fragment
    except AttributeError:
        _render_on_clock_banner_html(
            st,
            slot_view,
            live_draft_display_seconds(live_room),
            next_pick=next_pick_view,
            pick_index=pick_idx,
            deadline=deadline,
        )
        return

    @fragment(run_every=1)
    def _banner_tick() -> None:
        tick_room = _resolve_live_room(session, room)
        tick_slot = live_draft_current_slot(tick_room) or slot_view
        tick_deadline = live_draft_timer_deadline(tick_room)
        tick_idx = int(tick_room.get("current_pick_index") or pick_idx)
        record_timer_diagnostics(session, tick_room, source="on_clock_banner_tick")
        if session.get("_live_draft_timer_diag"):
            diag = dict(session["_live_draft_timer_diag"])
            diag["timer_component_mounted"] = tick_deadline is not None
            diag["timer_component_last_render"] = time.time()
            session["_live_draft_timer_diag"] = diag
        _render_on_clock_banner_html(
            st,
            tick_slot,
            live_draft_display_seconds(tick_room),
            next_pick=next_pick_view,
            pick_index=tick_idx,
            deadline=tick_deadline,
        )

    _banner_tick()
