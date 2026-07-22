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
              function noteClientStage(stage) {{
                try {{
                  const win = window.top || window.parent || window;
                  const doc = win.document;
                  let node = doc.getElementById("solo-expire-client");
                  if (!node) {{
                    node = doc.createElement("div");
                    node.id = "solo-expire-client";
                    node.style.display = "none";
                    doc.body.appendChild(node);
                  }}
                  const chain = String(node.getAttribute("data-chain") || "");
                  node.setAttribute("data-last", stage);
                  node.setAttribute("data-chain", chain ? chain + "|" + stage : stage);
                }} catch (e) {{}}
              }}
              function triggerWakeUrl() {{
                try {{
                  const win = window.top || window.parent || window;
                  noteClientStage("url_wake_triggered");
                  const url = new URL(win.location.href);
                  url.searchParams.set("solo_wake", String(Date.now()));
                  win.location.assign(url.toString());
                  return true;
                }} catch (e) {{}}
                return false;
              }}
              function clickSoloWake() {{
                try {{
                  const doc = (window.top || window.parent || window).document;
                  for (const b of doc.querySelectorAll('button')) {{
                    const title = (b.getAttribute('title') || b.getAttribute('aria-label') || '').toLowerCase();
                    const text = (b.innerText || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    if (title.includes('solo-timer-wake') || text === 'solo-timer-wake') {{
                      b.click();
                      return;
                    }}
                  }}
                }} catch (e) {{}}
              }}
              function wakeAtZero() {{
                noteClientStage("browser_deadline_crossed");
                if (!triggerWakeUrl()) clickSoloWake();
              }}
              function tick() {{
                const rem = Math.max(0, Math.ceil(deadline - Date.now() / 1000));
                if (el) el.textContent = String(rem);
                if (rem <= 0) {{
                  wakeAtZero();
                  window.setTimeout(wakeAtZero, 200);
                  window.setTimeout(wakeAtZero, 800);
                  return;
                }}
                window.setTimeout(tick, 250);
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


def _emit_primary_auto_picking_status(st: Any, session: dict[str, Any]) -> None:
    """Single authoritative Auto-picking label for the On-the-Clock area."""
    count = int(session.get("visible_auto_picking_status_count") or 0) + 1
    session["visible_auto_picking_status_count"] = count
    session["_live_draft_timer_autopick_ui"] = True
    st.caption("Auto-picking…")
    if bool(session.get("developer_mode") or session.get("_developer_mode")) and count != 1:
        st.caption(f"Dev assert: visible_auto_picking_status_count == {count} (expected 1)")


def render_live_on_clock_banner(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    slot: dict[str, Any],
    *,
    next_pick: int | None = None,
) -> None:
    """Render blue On-the-Clock banner with client-side 1 Hz countdown."""
    # Reset per full-page paint; fragment ticks may increment once more.
    session["visible_auto_picking_status_count"] = 0
    try:
        from app_page_generation import fragment_allowed

        if not fragment_allowed(session, expected_page="Live Draft Room"):
            return
    except ImportError:
        pass
    if not isinstance(slot, dict):
        return
    try:
        from live_draft_ux_latency import mark_ux_milestone
    except ImportError:
        mark_ux_milestone = None  # type: ignore[assignment]
    if mark_ux_milestone:
        mark_ux_milestone(session, "on_clock_paint_start", rebuild="on_clock", st=st)

    live_room = _resolve_live_room(session, room)
    try:
        from live_draft_canonical_snapshot import get_live_draft_paint_snapshot, render_canonical_diag_line

        canon = get_live_draft_paint_snapshot(session)
        if isinstance(slot, dict) and canon.get("team_on_clock"):
            slot = dict(slot)
            slot["Team"] = canon["team_on_clock"]
            if canon.get("current_pick") is not None:
                slot["Pick"] = canon["current_pick"]
            if canon.get("round") is not None:
                slot["Round"] = canon["round"]
        pick_idx = int(
            canon.get("current_pick_index")
            if canon.get("current_pick_index") is not None
            else live_room.get("current_pick_index") or 0
        )
        render_canonical_diag_line(st, session, label="On the Clock")
    except ImportError:
        pick_idx = int(live_room.get("current_pick_index") or 0)
    slot_view = dict(slot) if isinstance(slot, dict) else {}
    next_pick_view = next_pick
    try:
        from live_draft_ux import on_clock_should_flash

        clock_flash = on_clock_should_flash(session, pick_idx)
    except ImportError:
        clock_flash = False

    def _mark_on_clock_done() -> None:
        if mark_ux_milestone:
            mark_ux_milestone(session, "on_clock_paint_done", rebuild="on_clock", st=st)

    if str(live_room.get("status") or "") == "paused":
        remaining = live_draft_display_seconds(live_room)
        _render_on_clock_banner_html(
            st, slot_view, remaining, next_pick=next_pick_view, pick_index=pick_idx, deadline=None, flash=clock_flash
        )
        st.caption("Draft paused — timer stopped")
        _mark_on_clock_done()
        return

    try:
        from live_draft_solo_timer import is_solo_live_draft, record_visible_timer_count

        if is_solo_live_draft(session, live_room):
            # Sole primary countdown for Solo Draft Room.
            record_visible_timer_count(session, 1)
        else:
            # Shared: On-the-Clock is the sole visible countdown.
            record_visible_timer_count(session, 1)
    except ImportError:
        pass

    try:
        from live_draft_pick_timer import display_seconds_with_freeze, frozen_deadline, is_pick_submitting

        if is_pick_submitting(session):
            remaining = display_seconds_with_freeze(session, live_room)
            deadline = frozen_deadline(session, live_room)
            _render_on_clock_banner_html(
                st, slot_view, remaining, next_pick=next_pick_view, pick_index=pick_idx, deadline=deadline, flash=clock_flash
            )
            st.caption("Submitting pick…")
            _mark_on_clock_done()
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

    remaining_now = live_draft_display_seconds(live_room)

    _solo_draft = False
    try:
        from live_draft_solo_timer import (
            get_solo_display_snapshot,
            install_solo_display_snapshot,
            is_solo_live_draft,
        )

        _solo_draft = bool(is_solo_live_draft(session, live_room))
    except ImportError:
        _solo_draft = False

    # Solo: paint banner once with JS deadline countdown. A 1 Hz fragment that remounts
    # components.html every tick caused ghost/stale timers on Streamlit Cloud.
    if _solo_draft and use_fragment and deadline is not None:
        try:
            from live_draft_solo_heartbeat import solo_banner_uses_static_paint, shared_banner_should_repaint

            if solo_banner_uses_static_paint(session):
                install_solo_display_snapshot(session, live_room)
                snap = get_solo_display_snapshot(session, live_room)
                remaining_now = int(snap.get("remaining_seconds") or remaining_now)
                if snap.get("timer_deadline") is not None:
                    deadline = float(snap["timer_deadline"])
                if not shared_banner_should_repaint(
                    session,
                    pick_index=int(snap.get("pick_index") or pick_idx),
                    deadline=deadline,
                ):
                    _mark_on_clock_done()
                    return
                try:
                    from live_draft_cloud_diagnostics import render_surface_stamp

                    render_surface_stamp(
                        st,
                        session,
                        component="on_clock_banner",
                        render_owner="page_static_js",
                        room=live_room,
                        extra={"remaining": remaining_now},
                    )
                except ImportError:
                    pass
                _render_on_clock_banner_html(
                    st,
                    slot_view,
                    remaining_now,
                    next_pick=next_pick_view,
                    pick_index=pick_idx,
                    deadline=deadline,
                    flash=clock_flash,
                )
                if (
                    int(remaining_now or 0) <= 0
                    and str(live_room.get("status") or "") == "in_progress"
                ):
                    _emit_primary_auto_picking_status(st, session)
                _mark_on_clock_done()
                return
        except ImportError:
            pass

    if not use_fragment or deadline is None:
        _render_on_clock_banner_html(
            st,
            slot_view,
            remaining_now,
            next_pick=next_pick_view,
            pick_index=pick_idx,
            deadline=deadline,
            flash=clock_flash,
        )
        if (
            int(remaining_now or 0) <= 0
            and str(live_room.get("status") or "") == "in_progress"
        ):
            _emit_primary_auto_picking_status(st, session)
        _mark_on_clock_done()
        return

    try:
        fragment = st.fragment
    except AttributeError:
        _render_on_clock_banner_html(
            st,
            slot_view,
            remaining_now,
            next_pick=next_pick_view,
            pick_index=pick_idx,
            deadline=deadline,
            flash=clock_flash,
        )
        if (
            int(remaining_now or 0) <= 0
            and str(live_room.get("status") or "") == "in_progress"
        ):
            _emit_primary_auto_picking_status(st, session)
        _mark_on_clock_done()
        return

    @fragment(run_every=1)
    def _banner_tick() -> None:
        try:
            from live_draft_rerun_scope import mark_live_draft_timer_tick

            mark_live_draft_timer_tick(session)
        except ImportError:
            pass
        # Keep banner on the same authoritative deadline as Draft Control Center.
        try:
            from live_draft_timer_ui import _sync_room_on_timer_tick

            tick_room, _changed = _sync_room_on_timer_tick(session, room)
        except Exception:
            tick_room = _resolve_live_room(session, room)
        try:
            from live_draft_canonical_snapshot import get_live_draft_paint_snapshot

            paint = get_live_draft_paint_snapshot(session)
            tick_idx = int(paint.get("current_pick_index") or pick_idx)
            tick_deadline = paint.get("timer_deadline")
            if paint.get("timer_remaining") is not None:
                remaining = int(paint.get("timer_remaining") or 0)
            else:
                remaining = live_draft_display_seconds(tick_room)
            on_clock = str(paint.get("team_on_clock") or "").strip()
            tick_slot = dict(slot_view)
            if on_clock:
                tick_slot["Team"] = on_clock
            if paint.get("current_pick") is not None:
                tick_slot["Pick"] = paint.get("current_pick")
            if paint.get("round") is not None:
                tick_slot["Round"] = paint.get("round")
        except ImportError:
            try:
                from shared_live_draft_snapshot import build_shared_live_draft_snapshot
                from live_draft_canonical_snapshot import (
                    align_room_pick_index,
                    install_canonical_live_draft_snapshot,
                )

                snap = build_shared_live_draft_snapshot(session, room=tick_room)
                align_room_pick_index(tick_room)
                install_canonical_live_draft_snapshot(session, tick_room, state_source="shared_fallback_sync")
                session["_live_draft_shared_fallback_paint"] = dict(snap)
                tick_idx = int(snap.get("current_pick_index") or pick_idx)
                tick_deadline = snap.get("turn_deadline")
                remaining = snap.get("seconds_remaining")
                if remaining is None:
                    remaining = live_draft_display_seconds(tick_room)
                on_clock = str(snap.get("on_clock_team") or "").strip()
                tick_slot = dict(slot_view)
                if on_clock:
                    tick_slot["Team"] = on_clock
                if snap.get("current_pick") is not None:
                    tick_slot["Pick"] = snap.get("current_pick")
            except ImportError:
                tick_slot = live_draft_current_slot(tick_room) or slot_view
                tick_deadline = live_draft_timer_deadline(tick_room)
                tick_idx = int(tick_room.get("current_pick_index") or pick_idx)
                remaining = live_draft_display_seconds(tick_room)
        # When at zero: Solo fragment/banner installs next pick+full timer in-place.
        # Shared rooms still poll; page/timer-authority owns multiparty CAS.
        try:
            from live_draft_timer_logic import live_draft_timer_expired_for_pick

            if live_draft_timer_expired_for_pick(tick_room):
                try:
                    from live_draft_solo_timer import (
                        expire_current_pick_and_advance,
                        is_solo_live_draft,
                        note_solo_fragment_owned_expire,
                    )

                    if is_solo_live_draft(session, tick_room):
                        note_solo_fragment_owned_expire(session)
                        result = expire_current_pick_and_advance(
                            tick_room, session=session, request_full_rerun=False
                        )
                        tick_room = _resolve_live_room(session, tick_room)
                        if result.display is not None:
                            tick_idx = int(result.display.pick_index)
                            tick_deadline = result.display.timer_deadline
                            remaining = int(result.display.remaining_seconds)
                            tick_slot = dict(tick_slot)
                            tick_slot["Team"] = result.display.team or tick_slot.get("Team")
                            tick_slot["Pick"] = result.display.pick_number
                        else:
                            tick_slot = live_draft_current_slot(tick_room) or tick_slot
                            tick_deadline = live_draft_timer_deadline(tick_room)
                            tick_idx = int(tick_room.get("current_pick_index") or tick_idx)
                            remaining = live_draft_display_seconds(tick_room)
                        session["_live_draft_solo_board_stale"] = True
                        if result.ok and (result.advanced or result.complete):
                            try:
                                from live_draft_canonical_snapshot import (
                                    align_room_pick_index,
                                    begin_live_draft_paint,
                                    invalidate_live_draft_paint,
                                    note_action_timing,
                                )

                                invalidate_live_draft_paint(session)
                                tick_room = _resolve_live_room(session, tick_room)
                                align_room_pick_index(tick_room)
                                begin_live_draft_paint(session, tick_room, state_source="solo_expire_fragment")
                                note_action_timing(
                                    session,
                                    "solo_expire_fragment",
                                    zero_to_commit_ms=result.zero_to_commit_ms,
                                    team_after=result.team_on_clock,
                                )
                            except ImportError:
                                pass
                            try:
                                from live_draft_safe_mode import request_live_draft_rerun

                                request_live_draft_rerun(st, session, "solo_expire", room=tick_room)
                            except Exception:
                                st.rerun()
                    else:
                        # Shared: poll fragment owns room sync. Banner never force-loads
                        # the full shared_room_json on a schedule.
                        if not session.get("_live_draft_poll_fragment_active"):
                            try:
                                from draft_room_context import (
                                    poll_shared_draft_room,
                                    reset_shared_draft_sync_gate,
                                )

                                reset_shared_draft_sync_gate(session)
                                changed = bool(poll_shared_draft_room(session, force=False))
                                session["_live_draft_on_clock_zero_diag"] = {
                                    "force_poll": False,
                                    "poll_changed": changed,
                                    "ts": time.time(),
                                }
                            except Exception as exc:
                                session["_live_draft_on_clock_zero_diag"] = {
                                    "poll_error": f"{type(exc).__name__}: {exc}"[:160],
                                }
                        tick_room = _resolve_live_room(session, tick_room)
                        try:
                            from shared_live_draft_snapshot import build_shared_live_draft_snapshot
                            from live_draft_canonical_snapshot import (
                                align_room_pick_index,
                                install_canonical_live_draft_snapshot,
                            )

                            snap = build_shared_live_draft_snapshot(session, room=tick_room)
                            align_room_pick_index(tick_room)
                            install_canonical_live_draft_snapshot(
                                session, tick_room, state_source="shared_fallback_poll"
                            )
                            session["_live_draft_shared_fallback_paint"] = dict(snap)
                            tick_idx = int(snap.get("current_pick_index") or tick_idx)
                            tick_deadline = snap.get("turn_deadline")
                            remaining = snap.get("seconds_remaining")
                            if remaining is None:
                                remaining = live_draft_display_seconds(tick_room)
                            on_clock = str(snap.get("on_clock_team") or "").strip()
                            if on_clock:
                                tick_slot = dict(tick_slot)
                                tick_slot["Team"] = on_clock
                            if snap.get("current_pick") is not None:
                                tick_slot = dict(tick_slot)
                                tick_slot["Pick"] = snap.get("current_pick")
                        except ImportError:
                            remaining = live_draft_display_seconds(tick_room)
                            tick_deadline = live_draft_timer_deadline(tick_room)
                except ImportError:
                    remaining = live_draft_display_seconds(tick_room)
                    tick_deadline = live_draft_timer_deadline(tick_room)
        except Exception as exc:
            session["_live_draft_on_clock_zero_diag"] = {
                **dict(session.get("_live_draft_on_clock_zero_diag") or {}),
                "banner_zero_error": f"{type(exc).__name__}: {exc}"[:160],
            }
        record_timer_diagnostics(session, tick_room, source="on_clock_banner_tick")
        if session.get("_live_draft_timer_diag"):
            diag = dict(session["_live_draft_timer_diag"])
            diag["timer_component_mounted"] = tick_deadline is not None
            diag["timer_component_last_render"] = time.time()
            session["_live_draft_timer_diag"] = diag
        try:
            from live_draft_solo_timer import record_visible_timer_count

            record_visible_timer_count(session, 1)
        except ImportError:
            pass
        try:
            from live_draft_solo_heartbeat import shared_banner_should_repaint

            force_repaint = int(remaining or 0) <= 0 and str(tick_room.get("status") or "") == "in_progress"
            if shared_banner_should_repaint(
                session,
                pick_index=tick_idx,
                deadline=float(tick_deadline) if tick_deadline is not None else None,
                force=force_repaint,
            ):
                try:
                    from live_draft_cloud_diagnostics import note_fragment_owner, render_surface_stamp

                    note_fragment_owner(session, "shared_on_clock_banner", delta=1)
                    render_surface_stamp(
                        st,
                        session,
                        component="on_clock_banner",
                        render_owner="shared_banner_fragment",
                        room=tick_room,
                        fragment_id="shared-banner",
                        extra={"remaining": int(remaining or 0)},
                    )
                except ImportError:
                    pass
                _render_on_clock_banner_html(
                    st,
                    tick_slot,
                    int(remaining or 0),
                    next_pick=next_pick_view,
                    pick_index=tick_idx,
                    deadline=tick_deadline,
                    flash=False,
                )
        except ImportError:
            _render_on_clock_banner_html(
                st,
                tick_slot,
                int(remaining or 0),
                next_pick=next_pick_view,
                pick_index=tick_idx,
                deadline=tick_deadline,
                flash=False,
            )
        if (
            int(remaining or 0) <= 0
            and str(tick_room.get("status") or "") == "in_progress"
        ):
            # Fragment re-paint: keep a single Auto-picking caption under On-the-Clock.
            session["visible_auto_picking_status_count"] = 0
            _emit_primary_auto_picking_status(st, session)

    _banner_tick()
    _mark_on_clock_done()
