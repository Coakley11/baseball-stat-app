"""Live-updating On-the-Clock banner — shares countdown with live_draft_timer_ui."""

from __future__ import annotations

import time
from typing import Any

from live_draft_timer_logic import live_draft_current_slot, live_draft_display_seconds, live_draft_timer_deadline
from live_draft_timer_ui import _resolve_live_room, record_timer_diagnostics


def _team_accent(team: str) -> str:
    import hashlib

    digest = hashlib.md5(str(team or "team").encode("utf-8")).hexdigest()
    return f"#{digest[:6]}"


def _emit_banner_html(
    st: Any,
    html: str,
    *,
    height: int = 210,
    deadline: float | None = None,
    timer_id: str = "",
) -> None:
    """Render banner + countdown in one iframe (Control Center pattern).

    A separate script iframe cannot update the timer node via parent.document —
    that left the blue card stuck on ``--`` while Draft Control Center counted down.
    """
    try:
        import streamlit.components.v1 as components

        countdown_script = ""
        if deadline is not None and timer_id:
            countdown_script = f"""
            <script>
            (function() {{
              const deadline = {float(deadline)};
              const el = document.getElementById("{timer_id}");
              if (!el) return;
              function tick() {{
                const rem = Math.max(0, Math.ceil(deadline - Date.now() / 1000));
                el.textContent = String(rem);
                if (rem > 0) window.setTimeout(tick, 250);
              }}
              tick();
            }})();
            </script>
            """
        components.html(
            f"""
            <style>
              .live-draft-on-clock {{
                font-family: system-ui, -apple-system, Segoe UI, sans-serif;
                background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #1d4ed8 100%);
                color: #f8fafc;
                border-radius: 12px;
                padding: 16px 18px;
                margin: 0 0 8px 0;
                box-shadow: 0 8px 24px rgba(15, 23, 42, 0.35);
              }}
              .live-draft-on-clock .ld-title {{
                font-size: 12px;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                opacity: 0.85;
                margin-bottom: 4px;
              }}
              .live-draft-on-clock .ld-team-name {{
                font-size: 28px;
                font-weight: 800;
                line-height: 1.1;
                margin-bottom: 10px;
              }}
              .live-draft-on-clock .ld-pick-pills {{ display: flex; gap: 8px; flex-wrap: wrap; }}
              .live-draft-on-clock .ld-pill {{
                background: rgba(248, 250, 252, 0.14);
                border: 1px solid rgba(248, 250, 252, 0.22);
                border-radius: 999px;
                padding: 4px 10px;
                font-size: 13px;
                font-weight: 600;
              }}
              .live-draft-on-clock .ld-next-pick {{
                margin-top: 10px;
                font-size: 13px;
                opacity: 0.92;
              }}
              .live-draft-on-clock .ld-meta {{
                margin-top: 14px;
                display: flex;
                align-items: baseline;
                gap: 10px;
              }}
              .live-draft-on-clock .ld-clock-label {{
                font-size: 12px;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                opacity: 0.8;
              }}
              .live-draft-on-clock .live-draft-timer {{
                font-size: 36px;
                font-weight: 900;
                font-variant-numeric: tabular-nums;
                line-height: 1;
              }}
              .live-draft-on-clock.ld-on-clock-flash {{
                animation: ldFlash 0.9s ease-in-out 2;
              }}
              @keyframes ldFlash {{
                0%, 100% {{ filter: brightness(1); }}
                50% {{ filter: brightness(1.18); }}
              }}
            </style>
            {html}
            {countdown_script}
            """,
            height=height,
        )
        return
    except Exception:
        pass
    try:
        st.html(html)
        return
    except Exception:
        pass
    st.markdown(html, unsafe_allow_html=True)


def _render_on_clock_banner_html(
    st: Any,
    slot: dict[str, Any],
    remaining: int,
    *,
    next_pick: int | None = None,
    pick_index: int = 0,
    deadline: float | None = None,
    flash: bool = False,
) -> None:
    team = slot.get("Team", "—")
    rnd = slot.get("Round", "—")
    pick_no = slot.get("Pick", "—")
    next_txt = f'<div class="ld-next-pick">Your next pick: #{next_pick}</div>' if next_pick else ""
    accent = _team_accent(str(team))
    timer_id = f"ld-banner-timer-{pick_index}"
    # Seed with current remaining so the card never shows a stuck "--".
    seed = max(0, int(remaining))
    timer_html = (
        f'<span id="{timer_id}" class="live-draft-timer">{seed}</span>'
        if deadline is not None
        else f'<span class="live-draft-timer">{seed}</span>'
    )
    flash_class = " ld-on-clock-flash" if flash else ""
    html = f"""
        <div class="live-draft-on-clock{flash_class}" style="border-left: 8px solid {accent};">
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
        """
    _emit_banner_html(
        st,
        html,
        height=220 if next_pick else 190,
        deadline=float(deadline) if deadline is not None else None,
        timer_id=timer_id if deadline is not None else "",
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
    try:
        from live_draft_ux import on_clock_should_flash

        clock_flash = on_clock_should_flash(session, pick_idx)
    except ImportError:
        clock_flash = False

    if str(live_room.get("status") or "") == "paused":
        remaining = live_draft_display_seconds(live_room)
        _render_on_clock_banner_html(
            st, slot_view, remaining, next_pick=next_pick_view, pick_index=pick_idx, deadline=None, flash=clock_flash
        )
        st.caption("Draft paused — timer stopped")
        return

    try:
        from live_draft_pick_timer import display_seconds_with_freeze, frozen_deadline, is_pick_submitting

        if is_pick_submitting(session):
            remaining = display_seconds_with_freeze(session, live_room)
            deadline = frozen_deadline(session, live_room)
            _render_on_clock_banner_html(
                st, slot_view, remaining, next_pick=next_pick_view, pick_index=pick_idx, deadline=deadline, flash=clock_flash
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
            flash=clock_flash,
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
            flash=clock_flash,
        )
        return

    @fragment(run_every=1)
    def _banner_tick() -> None:
        try:
            from live_draft_rerun_scope import mark_live_draft_timer_tick

            mark_live_draft_timer_tick(session)
        except ImportError:
            pass
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
            flash=False,
        )

    _banner_tick()
