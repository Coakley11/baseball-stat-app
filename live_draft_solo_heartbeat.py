"""Single Solo Live Draft heartbeat — one 1 Hz fragment for expire only.

The On-the-Clock banner paints once per full page with a client-side JS countdown.
Repainting ``components.html`` every second caused ghost/stale timer iframes on Cloud.
"""

from __future__ import annotations

import time
from typing import Any

SOLO_HEARTBEAT_ACTIVE_KEY = "_solo_live_draft_heartbeat_active"
SOLO_HEARTBEAT_TICK_KEY = "_solo_live_draft_heartbeat_tick"
SOLO_HEARTBEAT_MOUNT_KEY = "_solo_live_draft_heartbeat_mount_seq"
ON_CLOCK_BANNER_PAINT_TOKEN_KEY = "_on_clock_banner_paint_token"
SOLO_WAKE_BUTTON_LABEL = "solo-timer-wake"
SOLO_WAKE_PENDING_RERUN_KEY = "_solo_timer_wake_pending_rerun"


def solo_banner_uses_static_paint(session: dict[str, Any]) -> bool:
    """Solo banner is painted once; heartbeat owns expire without HTML remounts."""
    try:
        from live_draft_cloud_diagnostics import solo_no_fragment_mode

        if solo_no_fragment_mode(session):
            return True
    except ImportError:
        pass
    return True


def shared_banner_should_repaint(
    session: dict[str, Any],
    *,
    pick_index: int,
    deadline: float | None,
    force: bool = False,
) -> bool:
    token = f"{int(pick_index)}|{float(deadline):.3f}" if deadline is not None else f"{int(pick_index)}|none"
    if force:
        session[ON_CLOCK_BANNER_PAINT_TOKEN_KEY] = token
        return True
    last = str(session.get(ON_CLOCK_BANNER_PAINT_TOKEN_KEY) or "")
    if last == token:
        return False
    session[ON_CLOCK_BANNER_PAINT_TOKEN_KEY] = token
    return True


def solo_heartbeat_active(session: dict[str, Any]) -> bool:
    return bool(session.get(SOLO_HEARTBEAT_ACTIVE_KEY))


def solo_heartbeat_recent(session: dict[str, Any], *, max_age_sec: float = 3.0) -> bool:
    try:
        from live_draft_solo_heartbeat_diagnostics import solo_heartbeat_recent as _recent

        return _recent(session, max_age_sec=max_age_sec)
    except ImportError:
        return solo_heartbeat_active(session)


def _resolve_tick_room(session: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        live = session.get(LIVE_DRAFT_ROOM_KEY)
        if isinstance(live, dict):
            return live
    except ImportError:
        pass
    live = session.get("live_draft_room")
    return live if isinstance(live, dict) else None


def solo_timer_wake_button_key(session: dict[str, Any], room: dict[str, Any]) -> str:
    draft_id = str(room.get("draft_room_id") or room.get("draft_id") or "solo").strip()[:12]
    return f"solo_timer_wake_{draft_id}"


def _click_solo_wake_button_js(*, deadline: float | None = None, repeat_ms: int = 0) -> str:
    """Client-side wake — clicks hidden Streamlit button; server owns expire."""
    deadline_js = "null" if deadline is None else f"{float(deadline):.3f}"
    repeat = max(0, int(repeat_ms))
    return f"""
    (function() {{
      const deadline = {deadline_js};
      function clickWake() {{
        try {{
          const doc = window.parent.document;
          for (const b of doc.querySelectorAll('button')) {{
            const title = (b.getAttribute('title') || b.getAttribute('aria-label') || '').toLowerCase();
            const text = (b.innerText || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            if (title.includes('solo-timer-wake') || text === 'solo-timer-wake') {{
              b.click();
              return true;
            }}
          }}
        }} catch (e) {{}}
        return false;
      }}
      function maybeWakeAtZero() {{
        if (deadline !== null && (deadline - Date.now() / 1000) > 0.25) return;
        clickWake();
      }}
      maybeWakeAtZero();
      window.setTimeout(maybeWakeAtZero, 120);
      window.setTimeout(maybeWakeAtZero, 450);
      if ({repeat} > 0) {{
        window.setInterval(maybeWakeAtZero, {repeat});
      }}
    }})();
    """


def emit_solo_timer_wake_click(st: Any, *, deadline: float | None = None) -> None:
    """Schedule a full-page wake without st.rerun() from inside a fragment."""
    try:
        import streamlit.components.v1 as components

        components.html(
            f"<script>{_click_solo_wake_button_js(deadline=deadline, repeat_ms=0)}</script>",
            height=0,
        )
    except ImportError:
        pass


def render_solo_timer_wake_button(st: Any, session: dict[str, Any], room: dict[str, Any]) -> None:
    """Hidden control — JS clicks at countdown zero when fragments stall on Cloud."""
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if not is_solo_live_draft(session, room):
            return
    except ImportError:
        return
    if str(room.get("status") or "") != "in_progress":
        return
    btn_key = solo_timer_wake_button_key(session, room)
    try:
        clicked = st.button(
            SOLO_WAKE_BUTTON_LABEL,
            key=btn_key,
            help="solo-timer-wake",
            label_visibility="collapsed",
        )
    except TypeError:
        clicked = st.button(SOLO_WAKE_BUTTON_LABEL, key=btn_key, help="solo-timer-wake")
    pending_rerun = bool(session.pop(SOLO_WAKE_PENDING_RERUN_KEY, None))
    pending_wake = bool(session.pop("_solo_timer_wake", None))
    if not (clicked or pending_wake or pending_rerun):
        return
    result = run_solo_expire_tick(st, session, source="wake")
    need_rerun = bool(pending_rerun or pending_wake or clicked)
    if result is not None and result.ok and (result.advanced or result.complete):
        need_rerun = True
    if not need_rerun:
        return
    live = _resolve_tick_room(session) or room
    rerun_ok = False
    try:
        from live_draft_safe_mode import request_live_draft_rerun

        rerun_ok = bool(request_live_draft_rerun(st, session, "solo_expire_wake", room=live))
    except ImportError:
        pass
    if not rerun_ok:
        try:
            st.rerun()
        except Exception:
            pass


def schedule_solo_cloud_expire_poll(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    """Streamlit Cloud Solo: 1 Hz full-page poll — authoritative expire when fragments stall."""
    if not solo_page_expire_poll_active(session, room):
        return False
    page = str(session.get("active_page") or session.get("active_page_name") or "").strip()
    if page and page != "Live Draft Room":
        return False
    try:
        from app_page_generation import fragment_allowed

        if not fragment_allowed(session, expected_page="Live Draft Room"):
            return False
    except ImportError:
        pass
    try:
        from live_draft_heavy_paint_ui import DEFER_HEAVY_LOADING_KEY, HEAVY_PAINT_DONE_KEY
        from live_draft_cloud_diagnostics import CONTROL_CENTER_MOUNT_KEY

        cc_log = list(session.get(CONTROL_CENTER_MOUNT_KEY) or [])
        if not session.get(HEAVY_PAINT_DONE_KEY) and not cc_log:
            if not session.get(DEFER_HEAVY_LOADING_KEY):
                return False
    except ImportError:
        pass
    run_solo_expire_tick(st, session, source="page_poll")
    session[SOLO_HEARTBEAT_TICK_KEY] = int(session.get(SOLO_HEARTBEAT_TICK_KEY) or 0) + 1
    try:
        from live_draft_solo_heartbeat_diagnostics import SOLO_HEARTBEAT_LAST_TICK_AT_KEY

        session[SOLO_HEARTBEAT_LAST_TICK_AT_KEY] = time.time()
    except ImportError:
        pass
    # Always chain the next full-page pass — a 1s throttle here deadlocked after the
    # first rerun when Cloud rendered the follow-up page in under one second.
    try:
        from live_draft_safe_mode import request_live_draft_rerun

        return bool(request_live_draft_rerun(st, session, "solo_cloud_poll", room=room))
    except ImportError:
        try:
            st.rerun()
            return True
        except Exception:
            return False


def solo_page_expire_poll_active(session: dict[str, Any], room: dict[str, Any] | None) -> bool:
    """Use page-level 1 Hz expire on Streamlit Cloud (all Solo drafts, not only ld_accept)."""
    try:
        from live_draft_cloud_diagnostics import cloud_accept_active, streamlit_cloud_runtime
        from live_draft_solo_timer import is_solo_live_draft
    except ImportError:
        return False
    if not isinstance(room, dict) or not is_solo_live_draft(session, room):
        return False
    if str(room.get("status") or "") != "in_progress":
        return False
    if streamlit_cloud_runtime():
        return True
    return bool(cloud_accept_active(session))


def solo_cloud_page_poll_active(session: dict[str, Any], room: dict[str, Any] | None) -> bool:
    """Back-compat alias for mount gating."""
    return solo_page_expire_poll_active(session, room)


def _log_tick(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    phase: str,
    remaining: int | None = None,
    **fields: Any,
) -> None:
    try:
        from live_draft_solo_heartbeat_diagnostics import log_solo_heartbeat_tick

        log_solo_heartbeat_tick(
            session,
            room,
            phase=phase,
            remaining=remaining,
            **fields,
        )
    except ImportError:
        pass


def _after_expire_success(
    st: Any,
    session: dict[str, Any],
    tick_room: dict[str, Any],
    result: Any,
    *,
    commit_source: str = "solo_heartbeat",
) -> bool:
    """Invalidate paint, bump diagnostics, and request full-page rerun for banner/board."""
    try:
        from live_draft_canonical_snapshot import (
            align_room_pick_index,
            begin_live_draft_paint,
            invalidate_live_draft_paint,
            note_action_timing,
        )

        invalidate_live_draft_paint(session)
        align_room_pick_index(tick_room)
        begin_live_draft_paint(session, tick_room, state_source="solo_heartbeat_expire")
        note_action_timing(
            session,
            "solo_heartbeat_expire",
            zero_to_commit_ms=getattr(result, "zero_to_commit_ms", None),
            team_after=getattr(result, "team_on_clock", None),
        )
        try:
            from live_draft_cloud_diagnostics import note_expiration_commit

            note_expiration_commit(session, source=commit_source)
        except ImportError:
            pass
    except ImportError:
        pass
    session["_live_draft_solo_board_stale"] = True
    session.pop(ON_CLOCK_BANNER_PAINT_TOKEN_KEY, None)
    shared_banner_should_repaint(
        session,
        pick_index=int(tick_room.get("current_pick_index") or 0),
        deadline=getattr(result, "timer_deadline", None) or tick_room.get("timer_deadline"),
        force=True,
    )
    # Never st.rerun() from inside @fragment — it stalls run_every on Streamlit Cloud.
    session[SOLO_WAKE_PENDING_RERUN_KEY] = True
    try:
        from live_draft_solo_timer import SOLO_TIMER_WAKE_KEY

        session[SOLO_TIMER_WAKE_KEY] = time.time()
    except ImportError:
        session["_solo_timer_wake"] = time.time()
    deadline = getattr(result, "timer_deadline", None) or tick_room.get("timer_deadline")
    emit_solo_timer_wake_click(st, deadline=deadline)
    return True


def run_solo_expire_tick(st: Any, session: dict[str, Any], *, source: str = "heartbeat") -> Any | None:
    """Authoritative Solo expire step — safe to call from heartbeat or page fallback."""
    tick_room = _resolve_tick_room(session)
    if not isinstance(tick_room, dict):
        _log_tick(session, None, phase=f"{source}_no_room")
        return None
    try:
        from live_draft_solo_timer import (
            SOLO_EXPIRE_APPLIED_KEY,
            install_solo_display_snapshot,
            is_solo_live_draft,
            note_solo_fragment_owned_expire,
            solo_clock_expired,
        )
        from live_draft_timer_logic import live_draft_seconds_remaining, live_draft_timer_deadline
    except ImportError:
        return None

    if not is_solo_live_draft(session, tick_room):
        return None

    remaining = int(live_draft_seconds_remaining(tick_room))
    deadline = live_draft_timer_deadline(tick_room)
    snap = install_solo_display_snapshot(session, tick_room)
    _log_tick(
        session,
        tick_room,
        phase=f"{source}_tick",
        remaining=remaining,
        deadline=deadline,
        expiration_claimed=str(tick_room.get(SOLO_EXPIRE_APPLIED_KEY) or ""),
        snapshot_rebuilt=True,
        extra={"revision": snap.draft_revision},
    )

    if not solo_clock_expired(tick_room):
        return None

    note_solo_fragment_owned_expire(session)
    from live_draft_solo_timer import expire_current_pick_and_advance

    _log_tick(
        session,
        tick_room,
        phase=f"{source}_expire_attempt",
        remaining=remaining,
        deadline=deadline,
        expiration_claimed=str(tick_room.get(SOLO_EXPIRE_APPLIED_KEY) or ""),
        auto_pick_attempted=True,
    )
    result = expire_current_pick_and_advance(
        tick_room, session=session, request_full_rerun=False
    )
    tick_room = _resolve_tick_room(session) or tick_room
    _log_tick(
        session,
        tick_room,
        phase=f"{source}_expire_result",
        remaining=int(live_draft_seconds_remaining(tick_room)),
        deadline=tick_room.get("timer_deadline"),
        expiration_claimed=str(tick_room.get(SOLO_EXPIRE_APPLIED_KEY) or ""),
        auto_pick_attempted=True,
        auto_pick_result=f"ok={result.ok} reason={result.reason} err={result.error or ''}",
        commit_confirmed=bool(result.ok and (result.advanced or result.complete)),
        new_deadline=getattr(result, "timer_deadline", None),
        snapshot_rebuilt=True,
    )

    if result.ok and (result.advanced or result.complete):
        rerun_ok = _after_expire_success(
            st, session, tick_room, result, commit_source=source
        )
        _log_tick(
            session,
            tick_room,
            phase=f"{source}_expire_committed",
            remaining=int(live_draft_seconds_remaining(tick_room)),
            deadline=tick_room.get("timer_deadline"),
            commit_confirmed=True,
            new_deadline=tick_room.get("timer_deadline"),
            rerender_requested=True,
            rerender_completed=rerun_ok,
        )
    return result


def render_solo_live_draft_heartbeat(st: Any, session: dict[str, Any], room: dict[str, Any]) -> None:
    """Mount the sole Solo 1 Hz fragment — expire at zero, no banner repaints."""
    del room  # always read authoritative room from session on each tick
    try:
        from live_draft_solo_timer import is_solo_live_draft

        live = _resolve_tick_room(session)
        if not is_solo_live_draft(session, live):
            session.pop(SOLO_HEARTBEAT_ACTIVE_KEY, None)
            return
    except ImportError:
        return

    try:
        from live_draft_cloud_diagnostics import solo_no_fragment_mode

        if solo_no_fragment_mode(session):
            session.pop(SOLO_HEARTBEAT_ACTIVE_KEY, None)
            return
    except ImportError:
        pass

    try:
        from live_draft_termination import live_draft_fragments_suppressed

        if live_draft_fragments_suppressed(session):
            return
    except ImportError:
        pass

    live = _resolve_tick_room(session)
    if not isinstance(live, dict) or str(live.get("status") or "") not in ("in_progress",):
        session.pop(SOLO_HEARTBEAT_ACTIVE_KEY, None)
        return

    try:
        from app_page_generation import fragment_allowed

        if not fragment_allowed(session, expected_page="Live Draft Room"):
            return
    except ImportError:
        pass

    fragment = getattr(st, "fragment", None)
    if fragment is None:
        return

    session[SOLO_HEARTBEAT_ACTIVE_KEY] = True
    session[SOLO_HEARTBEAT_MOUNT_KEY] = int(session.get(SOLO_HEARTBEAT_MOUNT_KEY) or 0) + 1
    try:
        from live_draft_cloud_diagnostics import note_fragment_owner

        note_fragment_owner(session, "solo_heartbeat", delta=1)
    except ImportError:
        pass

    mount_seq = int(session.get(SOLO_HEARTBEAT_MOUNT_KEY) or 0)

    @fragment(run_every=1)
    def _solo_heartbeat_tick() -> None:
        session[SOLO_HEARTBEAT_TICK_KEY] = int(session.get(SOLO_HEARTBEAT_TICK_KEY) or 0) + 1
        try:
            from live_draft_solo_heartbeat_diagnostics import SOLO_HEARTBEAT_LAST_TICK_AT_KEY

            session[SOLO_HEARTBEAT_LAST_TICK_AT_KEY] = time.time()
        except ImportError:
            pass
        try:
            run_solo_expire_tick(st, session, source="heartbeat")
        except Exception as exc:
            try:
                from live_draft_solo_heartbeat_diagnostics import note_solo_heartbeat_error

                note_solo_heartbeat_error(session, exc)
            except ImportError:
                pass

    with st.container():
        try:
            from live_draft_cloud_diagnostics import render_surface_stamp

            render_surface_stamp(
                st,
                session,
                component="solo_heartbeat",
                render_owner="solo_heartbeat_fragment",
                room=live,
                fragment_id=f"hb-{mount_seq}",
            )
        except ImportError:
            pass
        _solo_heartbeat_tick()


def render_solo_expire_watchdog(st: Any, session: dict[str, Any]) -> None:
    """Secondary 1 Hz expire path when the primary heartbeat stops ticking (Cloud headless)."""
    try:
        from live_draft_cloud_diagnostics import cloud_accept_active

        if not cloud_accept_active(session):
            return
    except ImportError:
        return
    try:
        from live_draft_solo_timer import is_solo_live_draft
    except ImportError:
        return
    live = _resolve_tick_room(session)
    if not isinstance(live, dict) or not is_solo_live_draft(session, live):
        return
    if str(live.get("status") or "") != "in_progress":
        return
    fragment = getattr(st, "fragment", None)
    if fragment is None:
        return

    @fragment(run_every=1)
    def _solo_expire_watchdog() -> None:
        if solo_heartbeat_recent(session, max_age_sec=2.5):
            return
        try:
            run_solo_expire_tick(st, session, source="watchdog")
        except Exception as exc:
            try:
                from live_draft_solo_heartbeat_diagnostics import note_solo_heartbeat_error

                note_solo_heartbeat_error(session, exc)
            except ImportError:
                pass

    _solo_expire_watchdog()
