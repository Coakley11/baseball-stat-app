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
SOLO_WAKE_QUERY_KEY = "solo_wake"
SOLO_WAKE_QUERY_SEEN_KEY = "_solo_wake_query_token"
SOLO_COMPONENT_WAKE_SEEN_KEY = "_solo_component_wake_seen_token"
SOLO_IDLE_EGRESS_KEY = "_solo_timer_idle_egress"
SOLO_CLOUD_POLL_MIN_INTERVAL_KEY = "_solo_cloud_poll_min_interval_sec"
SOLO_CLOUD_POLL_LAST_AT_KEY = "_solo_cloud_poll_last_at"
SOLO_CLOUD_POLL_INTERVAL_SEC = 2.0


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
    """Client-side wake — URL navigation is primary on Cloud; button click is secondary."""
    deadline_js = "null" if deadline is None else f"{float(deadline):.3f}"
    repeat = max(0, int(repeat_ms))
    return f"""
    (function() {{
      const deadline = {deadline_js};
      function triggerWakeUrl() {{
        try {{
          const win = window.top || window.parent || window;
          const url = new URL(win.location.href);
          url.searchParams.set("{SOLO_WAKE_QUERY_KEY}", String(Date.now()));
          win.location.assign(url.toString());
          return true;
        }} catch (e) {{}}
        return false;
      }}
      function clickWake() {{
        try {{
          const doc = (window.top || window.parent || window).document;
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
        if (!triggerWakeUrl()) clickWake();
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


def _clear_solo_wake_query(st: Any) -> None:
    try:
        qp = getattr(st, "query_params", None)
        if qp is not None and SOLO_WAKE_QUERY_KEY in qp:
            del qp[SOLO_WAKE_QUERY_KEY]
    except Exception:
        pass


def _solo_wake_query_token(st: Any) -> str:
    try:
        from live_draft_cloud_diagnostics import _qp_get

        return _qp_get(st, SOLO_WAKE_QUERY_KEY)
    except ImportError:
        return ""


def _handle_solo_wake_delivery(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    via: str,
    clicked: bool = False,
    pending_rerun: bool = False,
    pending_wake: bool = False,
) -> None:
    try:
        from live_draft_solo_expire_chain import note_solo_expire_chain

        note_solo_expire_chain(
            session,
            "wake_received",
            source="wake",
            via=via,
            clicked=clicked,
            pending_rerun=pending_rerun,
            pending_wake=pending_wake,
        )
    except ImportError:
        pass
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


def _coerce_wake_token(component_value: Any) -> str:
    if component_value is None:
        return ""
    if isinstance(component_value, dict):
        for key in ("token", "expire_token", "value"):
            text = str(component_value.get(key) or "").strip()
            if text:
                return text
        return ""
    return str(component_value).strip()


def process_solo_component_wake(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    component_value: str,
) -> bool:
    """Consume Streamlit component expire token — sole Cloud wake delivery."""
    token = _coerce_wake_token(component_value)
    if not token:
        return False
    try:
        from live_draft_solo_expire_chain import note_solo_expire_chain, solo_expire_owner
        from live_draft_solo_countdown_component import parse_solo_expire_token

        if solo_expire_owner(session) != "wake":
            return False
        parsed = parse_solo_expire_token(token)
        if not parsed:
            note_solo_expire_chain(
                session,
                "expire_rejected",
                source="component",
                reason="bad_token",
                token=token,
            )
            return False
        if token == str(session.get(SOLO_COMPONENT_WAKE_SEEN_KEY) or ""):
            return False
        live = _resolve_tick_room(session) or room
        live_draft_id = str(live.get("draft_room_id") or live.get("draft_id") or "").strip()
        if parsed["draft_id"] and live_draft_id and parsed["draft_id"] != live_draft_id:
            note_solo_expire_chain(
                session,
                "expire_rejected",
                source="component",
                reason="draft_mismatch",
                token=token,
            )
            return False
        if int(live.get("current_pick_index") or 0) != int(parsed["pick_index"]):
            note_solo_expire_chain(
                session,
                "expire_rejected",
                source="component",
                reason="pick_mismatch",
                token=token,
            )
            return False
        session[SOLO_COMPONENT_WAKE_SEEN_KEY] = token
        note_solo_expire_chain(
            session,
            "component_value_received",
            source="component",
            token=token,
        )
    except ImportError:
        session[SOLO_COMPONENT_WAKE_SEEN_KEY] = token
    _handle_solo_wake_delivery(st, session, room, via="component")
    return True


def render_solo_countdown_wake_component(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
) -> bool:
    """Mount bidirectional countdown component; process returned expire token."""
    try:
        from live_draft_solo_countdown_component import render_solo_countdown_wake
        from live_draft_solo_expire_chain import solo_expire_owner
        from live_draft_solo_timer import is_solo_live_draft
    except ImportError:
        return False
    if solo_expire_owner(session) != "wake":
        return False
    if not is_solo_live_draft(session, room):
        return False
    if str(room.get("status") or "") != "in_progress":
        return False
    draft_id = str(room.get("draft_room_id") or room.get("draft_id") or "solo").strip()
    pick_index = int(room.get("current_pick_index") or 0)
    key = f"solo_countdown_wake_{draft_id}_{pick_index}"

    def _on_component_change() -> None:
        try:
            from live_draft_solo_delivery_diag import note_production_on_change_if_diag

            note_production_on_change_if_diag(st, session, room, key)
        except ImportError:
            pass
        raw = st.session_state.get(key)
        token = _coerce_wake_token(raw)
        if token:
            try:
                from live_draft_solo_delivery_diag import delivery_diag_active, note_delivery_stage

                if delivery_diag_active(st, session):
                    note_delivery_stage(session, "token_coercion_complete", token=token)
                    note_delivery_stage(session, "process_solo_component_wake_entered", token=token)
            except ImportError:
                pass
            process_solo_component_wake(st, session, room, token)

    mounted = render_solo_countdown_wake(
        st,
        room,
        key=key,
        session=session,
        on_change=_on_component_change,
    )
    return mounted is not None


def process_solo_wake_query(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    """Consume ?solo_wake= from JS countdown zero-cross — sole Cloud wake delivery."""
    token = _solo_wake_query_token(st)
    if not token:
        return False
    try:
        from live_draft_solo_expire_chain import solo_expire_owner

        if solo_expire_owner(session) != "wake":
            _clear_solo_wake_query(st)
            return False
    except ImportError:
        pass
    if token == str(session.get(SOLO_WAKE_QUERY_SEEN_KEY) or ""):
        _clear_solo_wake_query(st)
        return False
    session[SOLO_WAKE_QUERY_SEEN_KEY] = token
    _clear_solo_wake_query(st)
    try:
        from live_draft_solo_expire_chain import note_solo_expire_chain

        note_solo_expire_chain(session, "url_wake_triggered", source="wake", token=token)
    except ImportError:
        pass
    _handle_solo_wake_delivery(st, session, room, via="query")
    return True


def render_solo_timer_wake_button(st: Any, session: dict[str, Any], room: dict[str, Any]) -> None:
    """Hidden control — JS clicks at countdown zero; sole Cloud expiration owner."""
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if not is_solo_live_draft(session, room):
            return
    except ImportError:
        return
    if str(room.get("status") or "") != "in_progress":
        return
    try:
        from live_draft_solo_expire_chain import note_solo_expire_chain, solo_expire_owner

        if solo_expire_owner(session) != "wake":
            return
    except ImportError:
        pass
    btn_key = solo_timer_wake_button_key(session, room)
    st.markdown(
        """<style>
        button[aria-label="solo-timer-wake"],
        button[title="solo-timer-wake"] {
          position: fixed !important;
          left: 0 !important;
          top: 0 !important;
          width: 1px !important;
          height: 1px !important;
          opacity: 0.01 !important;
          z-index: 9999 !important;
          pointer-events: auto !important;
        }
        </style>""",
        unsafe_allow_html=True,
    )
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
    _handle_solo_wake_delivery(
        st,
        session,
        room,
        via="button",
        clicked=bool(clicked),
        pending_rerun=pending_rerun,
        pending_wake=pending_wake,
    )


def note_solo_timer_poll_tick(session: dict[str, Any], *, expired: bool) -> dict[str, Any]:
    """Track Supabase deltas during idle Solo countdown ticks (admin / acceptance diagnostics)."""
    try:
        from suite_egress_trace import get_run_egress_summary

        summary = get_run_egress_summary()
    except ImportError:
        summary = {}
    reads = int(summary.get("reads") or 0)
    writes = int(summary.get("writes") or 0)
    full_room = int(summary.get("full_room_loads") or 0)
    now = time.time()
    slot = dict(session.get(SOLO_IDLE_EGRESS_KEY) or {})
    prev_reads = int(slot.get("last_reads") if slot.get("last_reads") is not None else reads)
    prev_writes = int(slot.get("last_writes") if slot.get("last_writes") is not None else writes)
    prev_full = int(slot.get("last_full_room") if slot.get("last_full_room") is not None else full_room)
    delta_reads = max(0, reads - prev_reads)
    delta_writes = max(0, writes - prev_writes)
    delta_full = max(0, full_room - prev_full)
    if not expired:
        slot["idle_ticks"] = int(slot.get("idle_ticks") or 0) + 1
        slot["idle_delta_reads"] = int(slot.get("idle_delta_reads") or 0) + delta_reads
        slot["idle_delta_writes"] = int(slot.get("idle_delta_writes") or 0) + delta_writes
        slot["idle_delta_full_room"] = int(slot.get("idle_delta_full_room") or 0) + delta_full
    slot["last_reads"] = reads
    slot["last_writes"] = writes
    slot["last_full_room"] = full_room
    slot["poll_owner"] = "local_page"
    slot["last_tick_at"] = now
    if not slot.get("window_started_at"):
        slot["window_started_at"] = now
    window = max(1.0, now - float(slot.get("window_started_at") or now))
    idle_ticks = int(slot.get("idle_ticks") or 0)
    slot["idle_reads_per_min"] = round(int(slot.get("idle_delta_reads") or 0) * 60.0 / window, 2)
    slot["idle_writes_per_min"] = round(int(slot.get("idle_delta_writes") or 0) * 60.0 / window, 2)
    slot["idle_full_room_per_min"] = round(int(slot.get("idle_delta_full_room") or 0) * 60.0 / window, 2)
    session[SOLO_IDLE_EGRESS_KEY] = slot
    return slot


def get_solo_timer_idle_egress_report(session: dict[str, Any]) -> dict[str, Any]:
    slot = dict(session.get(SOLO_IDLE_EGRESS_KEY) or {})
    if not slot:
        return {
            "poll_owner": "local_page",
            "idle_ticks": 0,
            "idle_reads_per_min": 0.0,
            "idle_writes_per_min": 0.0,
            "idle_full_room_per_min": 0.0,
        }
    return {
        "poll_owner": str(slot.get("poll_owner") or "local_page"),
        "idle_ticks": int(slot.get("idle_ticks") or 0),
        "idle_reads_per_min": float(slot.get("idle_reads_per_min") or 0.0),
        "idle_writes_per_min": float(slot.get("idle_writes_per_min") or 0.0),
        "idle_full_room_per_min": float(slot.get("idle_full_room_per_min") or 0.0),
        "idle_delta_reads": int(slot.get("idle_delta_reads") or 0),
        "idle_delta_writes": int(slot.get("idle_delta_writes") or 0),
    }


def schedule_solo_cloud_expire_poll(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    """Retired — Solo expiration uses one owner (wake on Cloud, fragment locally)."""
    return False


def solo_page_expire_poll_active(session: dict[str, Any], room: dict[str, Any] | None) -> bool:
    return False


def solo_cloud_page_poll_active(session: dict[str, Any], room: dict[str, Any] | None) -> bool:
    return False


def render_solo_expire_owner(st: Any, session: dict[str, Any], room: dict[str, Any]) -> None:
    """Mount exactly one Solo server expiration owner."""
    try:
        from live_draft_solo_expire_chain import solo_expire_owner
    except ImportError:
        solo_expire_owner = lambda _s: "fragment"  # type: ignore[assignment,misc]
    owner = solo_expire_owner(session)
    if owner == "wake":
        render_solo_countdown_wake_component(st, session, room)
    elif owner == "fragment":
        render_solo_live_draft_heartbeat(st, session, room)


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
    try:
        from live_draft_solo_expire_chain import note_solo_expire_chain

        note_solo_expire_chain(
            session,
            "page_repaint_completed",
            source=commit_source,
            pick_index=int(tick_room.get("current_pick_index") or 0),
            deadline=getattr(result, "timer_deadline", None) or tick_room.get("timer_deadline"),
        )
    except ImportError:
        pass
    return True


def run_solo_expire_tick(st: Any, session: dict[str, Any], *, source: str = "heartbeat") -> Any | None:
    """Authoritative Solo expire step — single owner entry (wake or fragment)."""
    tick_room = _resolve_tick_room(session)
    if not isinstance(tick_room, dict):
        _log_tick(session, None, phase=f"{source}_no_room")
        return None
    try:
        from live_draft_solo_expire_chain import note_solo_expire_chain, solo_expire_owner

        note_solo_expire_chain(
            session,
            "expire_entered",
            source=source,
            owner=solo_expire_owner(session),
        )
    except ImportError:
        pass
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
        try:
            from live_draft_solo_expire_chain import note_solo_expire_chain

            note_solo_expire_chain(
                session,
                "expire_rejected",
                source=source,
                reason="not_expired",
                remaining=remaining,
            )
        except ImportError:
            pass
        return None

    try:
        from live_draft_solo_expire_chain import note_solo_expire_chain

        note_solo_expire_chain(
            session,
            "deadline_confirmed_expired",
            source=source,
            remaining=remaining,
            deadline=deadline,
        )
    except ImportError:
        pass
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
        try:
            from live_draft_solo_expire_chain import note_solo_expire_chain

            note_solo_expire_chain(
                session,
                "pick_committed",
                source=source,
                reason=getattr(result, "reason", ""),
                pick_index=int(tick_room.get("current_pick_index") or 0),
                new_deadline=tick_room.get("timer_deadline"),
            )
        except ImportError:
            pass
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
    elif result is not None:
        try:
            from live_draft_solo_expire_chain import note_solo_expire_chain

            note_solo_expire_chain(
                session,
                "expire_rejected",
                source=source,
                reason=getattr(result, "reason", ""),
                error=getattr(result, "error", ""),
            )
        except ImportError:
            pass
    return result


def render_solo_live_draft_heartbeat(st: Any, session: dict[str, Any], room: dict[str, Any]) -> None:
    """Mount the sole Solo 1 Hz fragment — local-only expiration owner."""
    del room  # always read authoritative room from session on each tick
    try:
        from live_draft_solo_expire_chain import solo_expire_owner

        if solo_expire_owner(session) != "fragment":
            session.pop(SOLO_HEARTBEAT_ACTIVE_KEY, None)
            return
    except ImportError:
        pass
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
    """Retired — Solo expiration uses one owner (wake on Cloud, fragment locally)."""
    return
