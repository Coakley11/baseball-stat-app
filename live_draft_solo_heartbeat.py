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
    expire_token: str = "",
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
    result = run_solo_expire_tick(st, session, source="wake", expire_token=expire_token)
    need_rerun = bool(pending_rerun or pending_wake or clicked)
    if result is not None and result.ok and (result.advanced or result.complete):
        need_rerun = True
    if not need_rerun:
        return
    # Banner fragment already painted the next pick — do not full-ScriptRun remount.
    if bool(session.get("_solo_server_timer_active")):
        session["_solo_needs_post_expire_board_sync"] = True
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
    *,
    delivery_via: str = "",
) -> bool:
    """Consume Streamlit component expire token — sole Cloud wake delivery."""
    try:
        from live_draft_room_mutation_audit import room_mutation_checkpoint

        room_mutation_checkpoint(
            session,
            "process_solo_component_wake_entry",
            st=st,
            extra={"delivery_via": delivery_via},
        )
    except ImportError:
        pass
    token = _coerce_wake_token(component_value)
    if not token:
        try:
            from live_draft_stage1_expire_audit import record_callback_invocation

            record_callback_invocation(
                st,
                session,
                callback_source=delivery_via,
                raw_value=component_value,
                room=room,
                reject_code="empty_raw",
                delivery_claimed=False,
            )
        except ImportError:
            pass
        return False

    def _reject(reason: str, *, audit_code: str | None = None) -> bool:
        code = audit_code or reason
        try:
            from live_draft_stage1_expire_audit import (
                clear_persistent_wake_widget_value,
                map_legacy_reject_reason,
                mark_wake_token_rejected,
                record_callback_invocation,
            )

            mark_wake_token_rejected(session, token, code)
            clear_persistent_wake_widget_value(st, session, token)
            record_callback_invocation(
                st,
                session,
                callback_source=delivery_via,
                raw_value=component_value,
                room=_resolve_tick_room(session) or room,
                reject_code=map_legacy_reject_reason(code),
                delivery_claimed=False,
                token_already_consumed=code in ("already_consumed", "duplicate_token"),
            )
        except ImportError:
            pass
        try:
            from live_draft_solo_expire_chain import note_solo_expire_chain

            note_solo_expire_chain(
                session,
                "expire_rejected",
                source="component",
                reason=code,
                token=token,
                delivery_via=delivery_via or "",
            )
        except ImportError:
            pass
        return False

    try:
        from live_draft_solo_expire_chain import note_solo_expire_chain, solo_expire_owner
        from live_draft_solo_countdown_component import parse_solo_expire_token

        if solo_expire_owner(session) != "wake":
            return False
        parsed = parse_solo_expire_token(token)
        if not parsed:
            return _reject("bad_token", audit_code="malformed_token")
        if token == str(session.get(SOLO_COMPONENT_WAKE_SEEN_KEY) or ""):
            return _reject("duplicate_token", audit_code="already_consumed")
        live = _resolve_tick_room(session) or room
        if str(live.get("status") or "") != "in_progress":
            return _reject("room_not_in_progress")
        live_draft_id = str(live.get("draft_room_id") or live.get("draft_id") or "").strip()
        if parsed["draft_id"] and live_draft_id and parsed["draft_id"] != live_draft_id:
            return _reject("draft_mismatch", audit_code="wrong_room")
        if int(live.get("current_pick_index") or 0) != int(parsed["pick_index"]):
            return _reject("pick_mismatch", audit_code="wrong_pick")
        try:
            from live_draft_timer_logic import live_draft_timer_deadline

            live_deadline = live_draft_timer_deadline(live)
            tok_deadline = float(parsed.get("deadline") or 0.0)
            if live_deadline is not None and tok_deadline > 0:
                if abs(float(live_deadline) - tok_deadline) > 0.75:
                    return _reject("stale_deadline")
        except ImportError:
            pass
        session[SOLO_COMPONENT_WAKE_SEEN_KEY] = token
        note_solo_expire_chain(
            session,
            "component_value_received",
            source="component",
            token=token,
            delivery_via=delivery_via or "unknown",
        )
        note_solo_expire_chain(
            session,
            "token_processed",
            source="component",
            token=token,
            delivery_via=delivery_via or "unknown",
        )
    except ImportError:
        session[SOLO_COMPONENT_WAKE_SEEN_KEY] = token
    try:
        from live_draft_solo_placement_ladder import placement_blocks_pick_processing

        if placement_blocks_pick_processing(session):
            try:
                from live_draft_solo_delivery_diag import note_delivery_stage

                note_delivery_stage(
                    session,
                    "pick_processing_blocked",
                    token=token,
                    reason="placement_ladder",
                )
            except ImportError:
                pass
            return True
    except ImportError:
        pass
    _handle_solo_wake_delivery(st, session, room, via="component", expire_token=token)
    try:
        from live_draft_stage1_expire_audit import clear_persistent_wake_widget_value

        clear_persistent_wake_widget_value(st, session, token)
    except ImportError:
        pass
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
    try:
        from live_draft_solo_placement_ladder import try_placement_wake_component_context

        if try_placement_wake_component_context(st, session, room):
            return True
    except ImportError:
        pass
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
        try:
            from live_draft_solo_component_diagnostics import solo_component_diag_enabled
            from live_draft_solo_expire_chain import note_solo_expire_chain

            if solo_component_diag_enabled(st, session):
                note_solo_expire_chain(
                    session,
                    "on_change_callback_entry",
                    source="component",
                    widget_key=key,
                )
                note_solo_expire_chain(
                    session,
                    "session_state_raw_received",
                    source="component",
                    widget_key=key,
                    raw_type=type(raw).__name__ if raw is not None else "NoneType",
                )
        except ImportError:
            pass
        token = _coerce_wake_token(raw)
        if token:
            try:
                from live_draft_solo_delivery_diag import delivery_diag_active, note_delivery_stage

                if delivery_diag_active(st, session):
                    note_delivery_stage(session, "token_coercion_complete", token=token)
                    note_delivery_stage(session, "process_solo_component_wake_entered", token=token)
            except ImportError:
                pass
            process_solo_component_wake(st, session, room, token, delivery_via="on_change")

    mounted = render_solo_countdown_wake(
        st,
        room,
        key=key,
        session=session,
        on_change=_on_component_change,
    )
    if mounted:
        token = _coerce_wake_token(mounted)
        if token:
            try:
                from live_draft_solo_component_diagnostics import solo_component_diag_enabled
                from live_draft_solo_expire_chain import note_solo_expire_chain

                if solo_component_diag_enabled(st, session):
                    note_solo_expire_chain(
                        session,
                        "component_return_value_received",
                        source="component",
                        token=token,
                        widget_key=key,
                    )
            except ImportError:
                pass
            process_solo_component_wake(st, session, room, token, delivery_via="return_value")
    return mounted is not None


def process_solo_wake_query(st: Any, session: dict[str, Any], room: dict[str, Any]) -> bool:
    """Consume ?solo_wake= from JS countdown zero-cross.

    Primary on Cloud (wake owner). Also accepted locally as a backup when the
    Solo On-the-Clock JS countdown hits zero and the heartbeat fragment missed
    the cross — otherwise the UI freezes at 0:00.
    """
    token = _solo_wake_query_token(st)
    if not token:
        return False
    if token == str(session.get(SOLO_WAKE_QUERY_SEEN_KEY) or ""):
        _clear_solo_wake_query(st)
        return False
    session[SOLO_WAKE_QUERY_SEEN_KEY] = token
    _clear_solo_wake_query(st)
    try:
        from live_draft_solo_expire_chain import note_solo_expire_chain

        note_solo_expire_chain(session, "url_wake_triggered", source="wake_or_backup", token=token)
    except ImportError:
        pass
    _handle_solo_wake_delivery(st, session, room, via="query")
    return True


def render_solo_timer_wake_button(st: Any, session: dict[str, Any], room: dict[str, Any]) -> None:
    """Hidden control — JS clicks at countdown zero; Cloud owner + local fragment backup."""
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if not is_solo_live_draft(session, room):
            return
    except ImportError:
        return
    if str(room.get("status") or "") != "in_progress":
        return
    btn_key = solo_timer_wake_button_key(session, room)
    st.markdown(
        """<style>
        button[aria-label="solo-timer-wake"],
        button[title="solo-timer-wake"],
        button:has(div:contains('solo-timer-wake')) {
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
    # data attribute for reliable JS targeting (no help= tooltip twin)
    st.markdown(
        f'<div id="solo-timer-wake-anchor" data-wake-key="{btn_key}" style="display:none"></div>',
        unsafe_allow_html=True,
    )
    try:
        # No help= — Streamlit tooltip clones a hidden twin button; JS wake clicks miss.
        clicked = st.button(
            SOLO_WAKE_BUTTON_LABEL,
            key=btn_key,
            label_visibility="collapsed",
        )
    except TypeError:
        clicked = st.button(SOLO_WAKE_BUTTON_LABEL, key=btn_key)
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
        from live_draft_solo_wiring_matrix_diag import try_wiring_matrix_ldr_entry, wiring_matrix_active

        if wiring_matrix_active(st, session):
            try_wiring_matrix_ldr_entry(st, session, room)
            return
    except ImportError:
        pass
    try:
        from live_draft_solo_persistent_wake import solo_persistent_wake_active

        if solo_persistent_wake_active(session):
            return
    except ImportError:
        pass
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
        from pathlib import Path
        import json as _json

        out = (
            Path(__file__).resolve().parent
            / "data"
            / "tb_probe"
            / "solo_after_expire_entered.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            _json.dumps(
                {
                    "ts": time.time(),
                    "source": commit_source,
                    "status": str(tick_room.get("status") or ""),
                    "board_len": len(tick_room.get("draft_board") or []),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass
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
    # Durable persist: fragment ticks often lack ScriptRunContext for force_save.
    # Write canonical session keys + immediate workspace disk save.
    session["live_draft_room"] = tick_room
    session["_solo_expire_needs_disk_persist"] = {
        "reason": f"solo_expire_{commit_source}",
        "status": str(tick_room.get("status") or ""),
        "board_len": len(tick_room.get("draft_board") or []),
        "ts": time.time(),
    }
    try:
        from live_draft_state import write_canonical_live_draft_state

        write_canonical_live_draft_state(
            session, tick_room, reason=f"solo_expire_{commit_source}", local_edit=True
        )
    except Exception as exc:
        session["_solo_expire_persist_err"] = f"canon:{type(exc).__name__}: {exc}"[:160]
    try:
        from suite_user_persistence import save_user_state, _load_raw
        from live_draft_state import (
            LIVE_DRAFT_ROOM_KEY,
            LIVE_DRAFT_STATE_KEY,
            enrich_save_payload_with_live_draft,
            room_to_persist_dict,
        )

        ws = str(
            session.get("_suite_active_workspace_id")
            or session.get("workspace_id")
            or "daniel"
        ).strip() or "daniel"
        # Prefer compact pool so fragment disk writes stay small/reliable.
        persist_room = room_to_persist_dict(tick_room, compact_pool=True)
        session[LIVE_DRAFT_ROOM_KEY] = tick_room
        try:
            from live_draft_state import write_canonical_live_draft_state as _wcs

            _wcs(session, tick_room, reason=f"solo_expire_disk_{commit_source}", local_edit=True)
        except Exception:
            session[LIVE_DRAFT_STATE_KEY] = persist_room
        disk_state: dict[str, Any] = {}
        try:
            existing, _warn, _saved = _load_raw("baseball", workspace_id=ws)
            if isinstance(existing, dict):
                disk_state = dict(existing)
        except Exception:
            disk_state = {}
        # Full enrich so top-level + page_filter_state both carry the room
        # (cold restore reads page_filter / live_draft_state, not only room key).
        disk_state, _enrich_diag = enrich_save_payload_with_live_draft(session, disk_state)
        disk_state["active_page"] = session.get("active_page") or "Live Draft Room"
        disk_state["_suite_active_workspace_id"] = ws
        ok = bool(save_user_state("baseball", disk_state, workspace_id=ws))
        # Readback proof — catch silent wipe races immediately.
        readback_ok = False
        readback_status = ""
        readback_board = 0
        try:
            rb, _, _ = _load_raw("baseball", workspace_id=ws)
            rb_room = (rb or {}).get(LIVE_DRAFT_ROOM_KEY) or (rb or {}).get(LIVE_DRAFT_STATE_KEY) or {}
            if isinstance(rb_room, dict) and str(rb_room.get("draft_room_id") or ""):
                readback_ok = str(rb_room.get("status") or "") in {"complete", "completed", "in_progress", "paused", "not_started"}
                readback_status = str(rb_room.get("status") or "")
                readback_board = len(rb_room.get("draft_board") or [])
        except Exception:
            pass
        session["_solo_expire_disk_save"] = {
            "ok": ok,
            "readback_ok": readback_ok,
            "workspace": ws,
            "status": str(persist_room.get("status") or ""),
            "board_len": len(persist_room.get("draft_board") or []),
            "readback_status": readback_status,
            "readback_board": readback_board,
            "enrich": {
                "injected": bool((_enrich_diag or {}).get("injected_from_session")),
                "has_payload": bool((_enrich_diag or {}).get("cloud_payload_has_live_draft_state")),
            },
        }
        try:
            from pathlib import Path
            import json as _json

            out = (
                Path(__file__).resolve().parent
                / "data"
                / "tb_probe"
                / "solo_expire_disk_save.json"
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                _json.dumps(session["_solo_expire_disk_save"], indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
    except Exception as exc:
        session["_solo_expire_persist_err"] = f"disk:{type(exc).__name__}: {exc}"[:160]
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


def run_solo_expire_tick(st: Any, session: dict[str, Any], *, source: str = "heartbeat", expire_token: str = "") -> Any | None:
    """Authoritative Solo expire step — single owner entry (wake or fragment)."""
    if session.get("_solo_placement_ladder_suppress_heartbeat_tick"):
        return None
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
    try:
        from pathlib import Path
        import json as _json

        proof = {
            "ts": time.time(),
            "source": source,
            "ok": bool(getattr(result, "ok", False)),
            "advanced": bool(getattr(result, "advanced", False)),
            "complete": bool(getattr(result, "complete", False)),
            "reason": str(getattr(result, "reason", "") or ""),
            "error": str(getattr(result, "error", "") or "")[:200],
            "remaining_after": int(live_draft_seconds_remaining(tick_room)),
            "status": str(tick_room.get("status") or ""),
            "pick_index": int(tick_room.get("current_pick_index") or 0),
            "board_len": len(tick_room.get("draft_board") or []),
        }
        out = (
            Path(__file__).resolve().parent
            / "data"
            / "tb_probe"
            / "solo_expire_result.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps(proof, indent=2), encoding="utf-8")
    except Exception:
        pass

    # Persist + rerun IMMEDIATELY — _log_tick / audit must never skip durable complete.
    if result is not None and bool(getattr(result, "ok", False)) and (
        bool(getattr(result, "advanced", False)) or bool(getattr(result, "complete", False))
    ):
        try:
            note_solo_fragment_owned_expire(session)
        except Exception:
            pass
        # Banner fragment owns the next-clock paint; skip heavy disk I/O here so the
        # 1 Hz fragment can remount the new full clock instead of dying at visible 0.
        if str(source or "") == "solo_banner_fragment":
            session["live_draft_room"] = tick_room
            session["_solo_banner_force_paint"] = True
            session.pop(ON_CLOCK_BANNER_PAINT_TOKEN_KEY, None)
            # Defer disk/canonical persistence — next-clock paint must not wait on I/O.
            session["_solo_expire_needs_disk_persist"] = {
                "reason": f"solo_expire_{source}",
                "status": str(tick_room.get("status") or ""),
                "board_len": len(tick_room.get("draft_board") or []),
                "ts": time.time(),
            }
            try:
                from live_draft_solo_timer import install_solo_display_snapshot

                install_solo_display_snapshot(session, tick_room)
            except Exception:
                pass
        else:
            try:
                _after_expire_success(
                    st, session, tick_room, result, commit_source=source
                )
            except Exception as _after_exc:
                session["_solo_expire_after_err"] = (
                    f"{type(_after_exc).__name__}: {_after_exc}"
                )[:160]

    try:
        _log_tick(
            session,
            tick_room,
            phase=f"{source}_expire_result",
            remaining=int(live_draft_seconds_remaining(tick_room)),
            deadline=tick_room.get("timer_deadline"),
            expiration_claimed=str(tick_room.get(SOLO_EXPIRE_APPLIED_KEY) or ""),
            auto_pick_attempted=True,
            auto_pick_result=(
                f"ok={getattr(result, 'ok', None)} reason={getattr(result, 'reason', None)} "
                f"err={getattr(result, 'error', None) or ''}"
            ),
            commit_confirmed=bool(
                getattr(result, "ok", False)
                and (
                    getattr(result, "advanced", False)
                    or getattr(result, "complete", False)
                )
            ),
            new_deadline=getattr(result, "timer_deadline", None),
            snapshot_rebuilt=True,
        )
    except Exception:
        pass

    if result is not None and bool(getattr(result, "ok", False)) and (
        bool(getattr(result, "advanced", False)) or bool(getattr(result, "complete", False))
    ):
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
        except Exception:
            pass
        try:
            from live_draft_stage1_expire_audit import record_pick_commit_audit

            snap = getattr(result, "snapshot_before", None)
            if snap is not None:
                pick_index_before = int(getattr(snap, "pick_index", 0) or 0)
            else:
                pick_index_after_raw = int(tick_room.get("current_pick_index") or 0)
                pick_index_before = max(0, pick_index_after_raw - 1)
            pick_index_after = int(tick_room.get("current_pick_index") or 0)
            board = tick_room.get("draft_board") or []
            last_pick = board[-1] if isinstance(board, list) and board else {}
            player = ""
            if isinstance(last_pick, dict):
                player = str(last_pick.get("Player") or last_pick.get("player") or "")
            seq = session.get("_solo_last_callback_seq")
            triggering_token = str(expire_token or session.get(SOLO_COMPONENT_WAKE_SEEN_KEY) or "")
            record_pick_commit_audit(
                st,
                session,
                room=tick_room,
                team=str(getattr(result, "team_on_clock", "") or getattr(snap, "team", "") or ""),
                player=player,
                selection_source=str(getattr(result, "reason", "") or "unknown"),
                pick_before=pick_index_before + 1,
                pick_after=pick_index_after + 1,
                triggering_token=triggering_token,
                triggering_callback_seq=int(seq) if seq is not None else None,
            )
        except Exception as _audit_exc:
            session["_solo_expire_audit_err"] = f"{type(_audit_exc).__name__}: {_audit_exc}"[:160]
        # Force Solo banner fragment to remount with the next full clock.
        session["_solo_banner_force_paint"] = True
        session.pop(ON_CLOCK_BANNER_PAINT_TOKEN_KEY, None)
        session.pop("_solo_banner_paint_token", None)
        # Heartbeat/wake expire must force a full-page remount of the static Solo
        # banner; otherwise JS stays at visible 0 after the server already advanced.
        if str(source or "") not in {"on_clock_zero_paint", "solo_banner_fragment"}:
            try:
                st.rerun()
            except Exception:
                pass
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
    """Mount Solo heartbeat — skipped when server-driven banner timer owns expire."""
    # Banner fragment owns expire + paint; a second 1 Hz expire fragment caused
    # duplicate work and Streamlit unresponsiveness under iframe remounts.
    if bool(session.get("_solo_server_timer_active")):
        session.pop(SOLO_HEARTBEAT_ACTIVE_KEY, None)
        return
    try:
        from live_draft_solo_placement_ladder import try_placement_in_heartbeat_fragment

        if try_placement_in_heartbeat_fragment(st, session, room):
            return
    except ImportError:
        pass
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
        # Durable probe for browser acceptance — proves the 1 Hz expire owner is alive.
        try:
            from pathlib import Path
            import json as _json

            tick_room = _resolve_tick_room(session)
            rem = None
            try:
                from live_draft_timer_logic import live_draft_seconds_remaining

                if isinstance(tick_room, dict):
                    rem = int(live_draft_seconds_remaining(tick_room))
            except Exception:
                pass
            proof = {
                "ts": time.time(),
                "tick": int(session.get(SOLO_HEARTBEAT_TICK_KEY) or 0),
                "remaining": rem,
                "status": str((tick_room or {}).get("status") or ""),
            }
            out = (
                Path(__file__).resolve().parent
                / "data"
                / "tb_probe"
                / "solo_heartbeat_tick.json"
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_json.dumps(proof, indent=2), encoding="utf-8")
        except Exception:
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
