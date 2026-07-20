"""Live draft timer display and diagnostics — fragment-safe (no streamlit_app imports)."""

from __future__ import annotations

import time
from typing import Any

from live_draft_timer_logic import (
    ensure_live_draft_timer_for_pick,
    live_draft_display_seconds,
    live_draft_seconds_remaining,
    live_draft_timer_deadline,
    live_draft_timer_expired_for_pick,
)

LIVE_DRAFT_TIMER_DIAG_KEY = "_live_draft_timer_diag"
TIMER_TICK_COUNT_KEY = "_live_draft_timer_tick_count"
TIMER_LAST_TICK_TS_KEY = "_live_draft_timer_last_tick_ts"
from live_draft_expired_pick import (
    EXPIRED_PICK_PENDING_KEY,
    handle_expired_pick_on_page,
    should_attach_timer_fragment,
    should_fragment_trigger_full_rerun,
)
LIVE_DRAFT_GRACE_MARKER_KEY = "_live_draft_grace_marker"
_AUTOPICK_GRACE_SEC = 2.0


def record_timer_diagnostics(session: dict[str, Any], room: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    cfg = dict(room.get("config") or {})
    started = room.get("timer_started_at")
    remaining = live_draft_display_seconds(room)
    deadline = room.get("timer_deadline") or live_draft_timer_deadline(room)
    prev = dict(session.get(LIVE_DRAFT_TIMER_DIAG_KEY) or {})
    tick_active = bool(source == "fragment_tick") or bool(prev.get("timer_tick_active"))
    host_eligible = False
    try:
        from live_draft_expired_pick import _multiplayer_autopick_allowed

        host_eligible = bool(_multiplayer_autopick_allowed(session))
    except ImportError:
        host_eligible = True
    diag = {
        "timer_start_time": started,
        "timer_deadline": deadline,
        "seconds_remaining": remaining,
        "computed_remaining": remaining,
        "local_now": time.time(),
        "timer_refresh_source": source or prev.get("timer_refresh_source"),
        "timer_tick_active": tick_active,
        "timer_fragment_active": tick_active,
        "timer_last_tick_ts": session.get(TIMER_LAST_TICK_TS_KEY),
        "timer_tick_count": int(session.get(TIMER_TICK_COUNT_KEY) or 0),
        "autopick_enabled": room.get("status") == "in_progress",
        "host_auto_pick_eligible": host_eligible,
        "current_pick_index": room.get("current_pick_index"),
        "timer_handled_index": room.get("timer_handled_index"),
        "draft_status": room.get("status"),
        "page_load_grace_active": _page_load_grace_active(session, room),
        "timer_expired_for_pick": live_draft_timer_expired_for_pick(room),
        "last_auto_pick_attempt": session.get("_live_draft_last_autopick_attempt_ts"),
        "timer_component_mounted": prev.get("timer_component_mounted", False),
        "timer_component_last_render": prev.get("timer_component_last_render"),
    }
    if source.endswith("_grace_skip"):
        diag["autopick_skipped_reason"] = "page_load_grace"
    session[LIVE_DRAFT_TIMER_DIAG_KEY] = diag
    return diag


def _grace_marker(session: dict[str, Any], room: dict[str, Any]) -> tuple[str, int]:
    page = str(session.get("active_page") or session.get("_shared_draft_poll_active_page") or "Live Draft Room")
    idx = int(room.get("current_pick_index") or 0)
    return page, idx


def _page_load_grace_active(session: dict[str, Any], room: dict[str, Any] | None = None) -> bool:
    loaded = float(session.get("_live_draft_page_load_ts") or 0)
    if loaded <= 0:
        return False
    if room is not None and live_draft_timer_expired_for_pick(room):
        return False
    return (time.time() - loaded) < _AUTOPICK_GRACE_SEC


def note_live_draft_page_load(session: dict[str, Any], room: dict[str, Any]) -> None:
    """Start grace window only when entering Live Draft or when pick index advances — not every rerun."""
    marker = _grace_marker(session, room)
    if session.get(LIVE_DRAFT_GRACE_MARKER_KEY) != marker:
        session[LIVE_DRAFT_GRACE_MARKER_KEY] = marker
        session["_live_draft_page_load_ts"] = time.time()


def _resolve_live_room(session: dict[str, Any], room: dict[str, Any]) -> dict[str, Any]:
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        live = session.get(LIVE_DRAFT_ROOM_KEY)
        if isinstance(live, dict):
            return live
    except ImportError:
        pass
    return room


def sync_live_draft_timer_state(session: dict[str, Any], room: dict[str, Any]) -> dict[str, Any]:
    """Keep timer deadline authoritative in multiplayer; host publishes repairs."""
    live_room = _resolve_live_room(session, room)
    try:
        from draft_room_context import commit_shared_room_state, is_multiplayer_draft_active, sync_shared_draft_room
        from draft_room_membership import is_room_host
        from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, get_shared_room_store

        mp = is_multiplayer_draft_active(session)
    except ImportError:
        mp = False

    if mp and live_room.get("status") == "in_progress":
        if live_room.get("timer_deadline") is None and live_room.get("timer_started_at") is None:
            try:
                sync_shared_draft_room(session, force=True)
                live_room = _resolve_live_room(session, room)
            except Exception:
                pass

    if ensure_live_draft_timer_for_pick(live_room):
        try:
            from live_draft_ux_latency import ACTION_TIMER_RESET, mark_ux_milestone, note_ux_action

            note_ux_action(
                session,
                ACTION_TIMER_RESET,
                source="ensure_timer_for_pick",
                detail=f"pick={live_room.get('current_pick_index')}",
            )
            mark_ux_milestone(session, "timer_paint_start", rebuild="timer", st=None)
        except ImportError:
            pass
        if mp:
            # Only the timer-authority holder may publish deadline repairs —
            # guests must poll the authoritative deadline, never invent one.
            try:
                from live_draft_timer_authority import multiparty_may_run_autopick

                room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
                document = get_shared_room_store().load(room_code) if room_code else None
                may_publish = bool(is_room_host(session, document))
                try:
                    may_publish = may_publish and multiparty_may_run_autopick(session, live_room)
                except Exception:
                    pass
                if may_publish:
                    commit_shared_room_state(session, live_room)
            except Exception:
                pass
    return live_room


def _sync_room_on_timer_tick(session: dict[str, Any], room: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Refresh shared room in multiplayer so timer_deadline and pick index stay aligned."""
    try:
        from live_draft_start_progress import should_skip_live_draft_poll

        if should_skip_live_draft_poll(session):
            return sync_live_draft_timer_state(session, room), False
    except ImportError:
        pass
    changed = False
    try:
        from draft_room_context import is_multiplayer_draft_active, poll_shared_draft_room, reset_shared_draft_sync_gate
        from suite_egress_policy import shared_draft_poll_interval_sec

        if is_multiplayer_draft_active(session):
            now = time.time()
            last = float(session.get("_live_draft_timer_poll_ts") or 0)
            interval = min(1.0, float(shared_draft_poll_interval_sec(session)))
            # At expiration, poll every tick so non-hosts converge immediately.
            try:
                expired = bool(
                    live_draft_timer_expired_for_pick(room)
                    or live_draft_seconds_remaining(room) <= 0
                )
            except Exception:
                expired = False
            if expired:
                interval = 0.5
            # Prefer the dedicated poll fragment — but still force a poll at zero
            # so guests do not wait 20–30s on a stale pick/deadline.
            if session.get("_live_draft_poll_fragment_active") and not expired:
                live_room = sync_live_draft_timer_state(session, room)
                return live_room, False
            if now - last >= interval:
                session["_live_draft_timer_poll_ts"] = now
                reset_shared_draft_sync_gate(session)
                changed = bool(poll_shared_draft_room(session, force=bool(expired)))
    except ImportError:
        pass
    live_room = sync_live_draft_timer_state(session, room)
    return live_room, changed


def _guest_waiting_for_host_autopick(session: dict[str, Any], room: dict[str, Any]) -> bool:
    """Guests poll when timer hits zero so host auto-picks appear without manual refresh."""
    try:
        from draft_room_context import is_multiplayer_draft_active
        from live_draft_expired_pick import _multiplayer_autopick_allowed

        if not is_multiplayer_draft_active(session):
            return False
        if _multiplayer_autopick_allowed(session):
            return False
        return live_draft_timer_expired_for_pick(room)
    except ImportError:
        return False


def _timer_expired_pending(session: dict[str, Any], room: dict[str, Any]) -> bool:
    live_room = _resolve_live_room(session, room)
    if live_room.get("status") != "in_progress":
        return False
    if _page_load_grace_active(session, live_room):
        return False
    return live_draft_timer_expired_for_pick(live_room)


def render_live_draft_timer_diagnostics(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    if not developer_mode:
        return
    try:
        from page_diagnostics import suppress_inline_diagnostics

        if suppress_inline_diagnostics(developer_mode):
            return
    except ImportError:
        pass
    raw = session.get(LIVE_DRAFT_TIMER_DIAG_KEY)
    if not isinstance(raw, dict):
        return
    with st.expander("Draft timer diagnostics", expanded=False):
        for key in (
            "timer_start_time",
            "timer_deadline",
            "seconds_remaining",
            "computed_remaining",
            "local_now",
            "timer_refresh_source",
            "timer_tick_active",
            "timer_fragment_active",
            "timer_last_tick_ts",
            "timer_tick_count",
            "page_load_grace_active",
            "timer_expired_for_pick",
            "autopick_enabled",
            "host_auto_pick_eligible",
            "last_auto_pick_attempt",
            "autopick_skipped_reason",
            "autopick_triggered",
            "autopick_reason",
            "autopick_deadline",
            "autopick_elapsed_seconds",
            "current_pick_index",
            "timer_handled_index",
            "draft_status",
        ):
            val = raw.get(key)
            st.text(f"{key}: {val if val is not None and val != '' else '—'}")


def _mount_js_countdown(
    st: Any,
    deadline: float,
    *,
    pick_index: int,
    element_id: str | None = None,
    height: int = 72,
    source: str = "timer_bar",
) -> None:
    """Client-side 1 Hz countdown — targets inline element or standalone block."""
    try:
        import streamlit.components.v1 as components
    except ImportError:
        return
    el_id = element_id or f"ld-timer-{pick_index}"
    if element_id:
        components.html(
            f"""
            <script>
            (function() {{
              const deadline = {float(deadline)};
              const doc = window.parent.document;
              function tick() {{
                const el = doc.getElementById("{el_id}");
                if (!el) return;
                const rem = Math.max(0, Math.ceil(deadline - Date.now() / 1000));
                el.textContent = rem > 0 ? (rem + "s") : "0";
                if (rem > 0) window.setTimeout(tick, 1000);
              }}
              tick();
            }})();
            </script>
            """,
            height=height,
        )
        return
    components.html(
        f"""
        <div style="font-family: system-ui, sans-serif;">
          <div style="font-size:12px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:#64748b;">
            Time on clock
          </div>
          <div id="{el_id}" style="font-size:36px;font-weight:900;color:#0f172a;line-height:1.1;">
            --
          </div>
        </div>
        <script>
        (function() {{
          const deadline = {float(deadline)};
          const el = document.getElementById("{el_id}");
          if (!el) return;
          function tick() {{
            const rem = Math.max(0, Math.ceil(deadline - Date.now() / 1000));
            el.textContent = rem > 0 ? (rem + "s") : "0";
            if (rem > 0) window.setTimeout(tick, 1000);
          }}
          tick();
        }})();
        </script>
        """,
        height=height,
    )


def _render_js_countdown(st: Any, deadline: float, *, pick_index: int, session: dict[str, Any] | None = None) -> None:
    """Client-side 1 Hz countdown — does not require shared-room poll."""
    _mount_js_countdown(st, deadline, pick_index=pick_index, source="timer_bar")
    if isinstance(session, dict):
        prev = dict(session.get(LIVE_DRAFT_TIMER_DIAG_KEY) or {})
        prev["timer_component_mounted"] = True
        prev["timer_component_last_render"] = time.time()
        prev["timer_deadline"] = deadline
        session[LIVE_DRAFT_TIMER_DIAG_KEY] = prev


def render_live_draft_timer_bar(st: Any, session: dict[str, Any], room: dict[str, Any]) -> None:
    """Countdown that refreshes every second via Streamlit fragment when available.

    Solo Draft: no countdown here — the On-the-Clock banner is the single primary
    clock and fragment expire owner (avoids duplicate TIME ON CLOCK + 0-freeze).
    """
    try:
        from live_draft_solo_timer import (
            install_solo_display_snapshot,
            is_solo_live_draft,
            record_visible_timer_count,
        )

        if is_solo_live_draft(session, room):
            live_room = _resolve_live_room(session, room)
            # Control Center must not paint a second countdown.
            record_visible_timer_count(session, 0)
            if str(live_room.get("status") or "") == "paused":
                st.caption("Draft paused — use Resume in Control Center")
                return
            install_solo_display_snapshot(session, live_room)
            return
    except ImportError:
        pass

    try:
        from app_page_generation import fragment_allowed

        if not fragment_allowed(session, expected_page="Live Draft Room"):
            return
    except ImportError:
        pass
    try:
        from live_draft_termination import live_draft_fragments_suppressed

        if live_draft_fragments_suppressed(session):
            return
    except ImportError:
        pass
    try:
        from live_draft_ux_latency import mark_ux_milestone

        mark_ux_milestone(session, "timer_paint_start", rebuild="timer", st=st)
    except ImportError:
        pass
    try:
        from live_draft_render_trace import ldr_rerun, ldr_step
    except ImportError:
        ldr_step = None  # type: ignore[assignment]
        ldr_rerun = None  # type: ignore[assignment]

        class _NullStep:
            def __init__(self, *_a: Any, **_k: Any) -> None:
                pass

            def __enter__(self) -> None:
                return None

            def __exit__(self, *_a: Any) -> bool:
                return False

        def ldr_step(*_a: Any, **_k: Any) -> Any:  # type: ignore[misc]
            return _NullStep()

    with ldr_step(session, "timer_bar_resolve_room", st=st):
        live_room = _resolve_live_room(session, room)
    if str(live_room.get("status") or "") == "paused":
        with ldr_step(session, "timer_bar_paused_render", st=st):
            remaining = live_draft_display_seconds(live_room)
            st.markdown(f"**Draft paused** · {remaining}s on clock")
            record_timer_diagnostics(session, live_room, source="paused")
        return
    try:
        from live_draft_pick_timer import frozen_deadline, is_pick_submitting, display_seconds_with_freeze

        with ldr_step(session, "timer_bar_submitting_check", st=st):
            submitting = bool(is_pick_submitting(session))
        if submitting:
            with ldr_step(session, "timer_bar_frozen_countdown", st=st):
                remaining = display_seconds_with_freeze(session, live_room)
                fdl = frozen_deadline(session, live_room)
                pick_idx = int(live_room.get("current_pick_index") or 0)
                if fdl is not None:
                    _render_js_countdown(st, float(fdl), pick_index=pick_idx, session=session)
                st.caption(f"Submitting pick… ({remaining}s frozen)")
            return
    except ImportError:
        pass
    try:
        from live_draft_safe_mode import record_safe_mode_diagnostics, timer_should_run

        with ldr_step(session, "timer_bar_should_run_check", st=st):
            can_run = bool(timer_should_run(session, live_room))
        # Clock already at 0 must keep a recovery path even when reconcile pauses
        # the normal timer UI — otherwise the draft freezes with no fragment ticks.
        _expired_now = False
        try:
            _expired_now = bool(
                live_draft_timer_expired_for_pick(live_room)
                or live_draft_seconds_remaining(live_room) <= 0
                or session.get(EXPIRED_PICK_PENDING_KEY)
            )
        except Exception:
            _expired_now = bool(session.get(EXPIRED_PICK_PENDING_KEY))
        if not can_run and not _expired_now:
            with ldr_step(session, "timer_bar_disabled_countdown", st=st):
                remaining = live_draft_display_seconds(live_room)
                record_safe_mode_diagnostics(session, timer_fragment_active=False, timer_should_run=False)
                deadline = live_draft_timer_deadline(live_room)
                if deadline is not None:
                    _render_js_countdown(st, float(deadline), pick_index=int(live_room.get("current_pick_index") or 0), session=session)
                else:
                    st.markdown(f"**Time on clock:** {remaining}s")
            return
        if not can_run and _expired_now:
            session[EXPIRED_PICK_PENDING_KEY] = True
            record_safe_mode_diagnostics(
                session, timer_fragment_active=True, timer_should_run=False, timer_expired_recovery=True
            )
        else:
            record_safe_mode_diagnostics(session, timer_fragment_active=True, timer_should_run=True)
    except ImportError:
        pass
    with ldr_step(session, "timer_bar_sync_state", st=st):
        live_room = sync_live_draft_timer_state(session, live_room)
        deadline = live_draft_timer_deadline(live_room)
        pick_idx = int(live_room.get("current_pick_index") or 0)
    with ldr_step(session, "timer_bar_js_countdown", st=st, has_deadline=deadline is not None):
        if deadline is not None:
            _render_js_countdown(st, float(deadline), pick_index=pick_idx, session=session)

    with ldr_step(session, "timer_attach_fragment", st=st):
        # Critical sync fix: when the clock is already at 0, attaching @fragment(run_every=1)
        # and immediately invoking it requests timer_fragment_zero → st.rerun() *during*
        # room_controls_timer, aborting the page before handle_expired_pick_on_page runs.
        # Page script owns expiry; fragment only runs while time remains.
        try:
            fragment = st.fragment
        except AttributeError:
            fragment = None

        if not should_attach_timer_fragment(session, live_room):
            with ldr_step(session, "timer_skip_fragment_expired", st=st):
                session[EXPIRED_PICK_PENDING_KEY] = True
                _render_timer_static(st, session, live_room, source="static_expired_no_fragment")
            # Recovery fragment: keep ticking while at 0 so backoff → retry does not
            # require a manual click (previous freeze root cause).
            # Auto-picking status is owned by the On-the-Clock banner only.
            if fragment is None:
                return

            @fragment(run_every=1)
            def _expired_recovery_tick() -> None:
                session[TIMER_TICK_COUNT_KEY] = int(session.get(TIMER_TICK_COUNT_KEY) or 0) + 1
                session[TIMER_LAST_TICK_TS_KEY] = time.time()
                tick_room, _poll_changed = _sync_room_on_timer_tick(session, room)
                if not isinstance(tick_room, dict) or not tick_room:
                    return
                session[EXPIRED_PICK_PENDING_KEY] = True
                _render_timer_static(st, session, tick_room, source="fragment_expired_recovery")
                # Never abort the page script that already owns expire handling.
                if session.get("_live_draft_page_owns_expired"):
                    return
                if should_fragment_trigger_full_rerun(session, tick_room):
                    try:
                        from live_draft_safe_mode import request_live_draft_rerun

                        request_live_draft_rerun(
                            st, session, "timer_fragment_zero", room=tick_room
                        )
                    except ImportError:
                        pass

            with ldr_step(session, "timer_invoke_expired_recovery", st=st):
                _expired_recovery_tick()
            return

        if fragment is None:
            with ldr_step(session, "timer_bar_static_no_fragment", st=st):
                _render_timer_static(st, session, live_room, source="static_no_fragment")
            return

        @fragment(run_every=1)
        def _timer_tick() -> None:
            try:
                from live_draft_render_trace import ldr_rerun as _ldr_rerun
                from live_draft_render_trace import ldr_step as _ldr_step
            except ImportError:
                _ldr_step = ldr_step
                _ldr_rerun = None
            with _ldr_step(session, "timer_fragment_tick", st=st, polling_loop=True):
                session[TIMER_TICK_COUNT_KEY] = int(session.get(TIMER_TICK_COUNT_KEY) or 0) + 1
                session[TIMER_LAST_TICK_TS_KEY] = time.time()
                with _ldr_step(session, "timer_fragment_poll_shared", st=st):
                    tick_room, poll_changed = _sync_room_on_timer_tick(session, room)
                if not isinstance(tick_room, dict) or not tick_room:
                    return
                # If the clock hit zero between ticks, stop this fragment from full-app
                # rerunning again — next full page render owns autopick.
                # Use module-scope should_fragment_trigger_full_rerun / handle_expired_pick_on_page
                # — never re-import those names here (UnboundLocalError on other branches).
                if not should_attach_timer_fragment(session, tick_room):
                    session[EXPIRED_PICK_PENDING_KEY] = True
                    # Host: commit autopick on this fragment tick so Pick N+1 does not
                    # wait for a slow full-page poll (observed ~20s stall at 0).
                    if should_fragment_trigger_full_rerun(session, tick_room):
                        try:
                            expired_result = handle_expired_pick_on_page(
                                session, tick_room, source="timer_fragment_zero"
                            )
                            if expired_result.ok:
                                try:
                                    from draft_state import remove_drafted_player_from_active_queues

                                    pick_name = str(
                                        (session.get("_live_draft_autopick_diag") or {}).get(
                                            "selected_auto_pick_player"
                                        )
                                        or ""
                                    ).strip()
                                    if pick_name:
                                        remove_drafted_player_from_active_queues(session, pick_name)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    with _ldr_step(session, "timer_fragment_render_static", st=st, expired=True):
                        _render_timer_static(st, session, tick_room, source="fragment_tick_expired")
                    if should_fragment_trigger_full_rerun(session, tick_room):
                        try:
                            from live_draft_safe_mode import request_live_draft_rerun

                            if _ldr_rerun is not None:
                                _ldr_rerun(
                                    session,
                                    "timer_fragment_tick",
                                    reason="timer_zero_rerun",
                                    st=st,
                                )
                            request_live_draft_rerun(
                                st, session, "timer_fragment_zero", room=tick_room
                            )
                        except ImportError:
                            pass
                    return
                with _ldr_step(session, "timer_fragment_render_static", st=st):
                    _render_timer_static(st, session, tick_room, source="fragment_tick")
                if poll_changed:
                    try:
                        from live_draft_ui_cache import invalidate_live_draft_ui_caches

                        invalidate_live_draft_ui_caches(session)
                    except ImportError:
                        session.pop("_live_draft_rec_cache", None)
                    try:
                        from live_draft_safe_mode import request_live_draft_rerun

                        if _ldr_rerun is not None:
                            _ldr_rerun(session, "timer_fragment_poll_shared", reason="poll_changed_rerun", st=st)
                        if request_live_draft_rerun(st, session, "poll_fragment", room=tick_room):
                            return
                    except ImportError:
                        st.rerun()
                        return
                elif _guest_waiting_for_host_autopick(session, tick_room):
                    # Status text owned by On-the-Clock — do not duplicate here.
                    pass
                elif should_fragment_trigger_full_rerun(session, tick_room):
                    session[EXPIRED_PICK_PENDING_KEY] = True
                    try:
                        from live_draft_safe_mode import request_live_draft_rerun

                        if _ldr_rerun is not None:
                            _ldr_rerun(session, "timer_fragment_tick", reason="timer_fragment_rerun", st=st)
                        request_live_draft_rerun(st, session, "timer_fragment", room=tick_room)
                    except ImportError:
                        pass

        with ldr_step(session, "timer_invoke_fragment_tick", st=st, callback="_timer_tick"):
            _timer_tick()


def _render_timer_static(st: Any, session: dict[str, Any], room: dict[str, Any], *, source: str = "static") -> None:
    # Fine-grained static tracing removed — stall is on the post-timer-zero rerun path.
    try:
        from live_draft_pick_timer import display_seconds_with_freeze, is_pick_submitting

        remaining = display_seconds_with_freeze(session, room)
        submitting = is_pick_submitting(session)
    except ImportError:
        remaining = live_draft_display_seconds(room)
        submitting = False
    record_timer_diagnostics(session, room, source=source)
    try:
        from live_draft_mp_diagnostics import record_multiplayer_sync_diagnostics

        record_multiplayer_sync_diagnostics(session, room=room)
    except ImportError:
        pass
    # Auto-picking status is owned by the primary On-the-Clock banner only.
    # Do not paint duplicate "Auto-picking…" captions here (timer bar / fragment).
    if int(remaining or 0) <= 0 and str(room.get("status") or "") == "in_progress" and not submitting:
        session["_live_draft_timer_autopick_ui"] = True
        st.markdown(f"**Time on clock:** 0s")
        return
    if source != "fragment_tick":
        if str(room.get("status") or "") == "paused":
            st.markdown(f"**Draft paused** · {remaining}s on clock")
        elif submitting:
            st.markdown(f"**Submitting pick…** · {remaining}s frozen")
        else:
            session.pop("_live_draft_timer_autopick_ui", None)
            st.markdown(f"**Time on clock:** {remaining}s")
