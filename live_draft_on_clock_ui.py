"""Live-updating On-the-Clock banner — shares countdown with live_draft_timer_ui."""

from __future__ import annotations

from typing import Any

from live_draft_timer_logic import live_draft_current_slot, live_draft_display_seconds
from live_draft_timer_ui import _resolve_live_room


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
) -> None:
    team = slot.get("Team", "—")
    rnd = slot.get("Round", "—")
    pick_no = slot.get("Pick", "—")
    next_txt = f'<div class="ld-next-pick">Your next pick: #{next_pick}</div>' if next_pick else ""
    accent = _team_accent(str(team))
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
                <span class="live-draft-timer">{int(remaining)}s</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_live_on_clock_banner(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    slot: dict[str, Any],
    *,
    next_pick: int | None = None,
) -> None:
    """Render blue On-the-Clock banner with the same live countdown as the top timer."""
    if not isinstance(slot, dict):
        return
    live_room = _resolve_live_room(session, room)
    slot_view = dict(slot)
    next_pick_view = next_pick

    use_fragment = True
    try:
        from live_draft_safe_mode import is_draft_truly_complete, timer_should_run

        if is_draft_truly_complete(live_room) or not timer_should_run(session, live_room):
            use_fragment = False
    except ImportError:
        pass

    if not use_fragment:
        _render_on_clock_banner_html(
            st,
            slot_view,
            live_draft_display_seconds(live_room),
            next_pick=next_pick_view,
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
        )
        return

    @fragment(run_every=1)
    def _banner_tick() -> None:
        tick_room = _resolve_live_room(session, room)
        tick_slot = live_draft_current_slot(tick_room) or slot_view
        remaining = live_draft_display_seconds(tick_room)
        _render_on_clock_banner_html(st, tick_slot, remaining, next_pick=next_pick_view)

    _banner_tick()
