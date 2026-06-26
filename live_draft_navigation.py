"""Leave / return draft navigation for Live Draft Room and Draft Simulator."""

from __future__ import annotations

from typing import Any

BROWSING_AWAY_KEY = "_live_draft_browsing_away"
FORCE_SYNC_ON_RETURN_KEY = "_live_draft_force_sync_on_return"
DEFAULT_BROWSE_PAGE = "Fantasy Trends"


def on_browse_other_pages(session: dict[str, Any], *, target_page: str | None = None) -> None:
    """Leave Live Draft Room without ending or pausing the draft."""
    page = str(target_page or session.get("_live_draft_browse_return_page") or DEFAULT_BROWSE_PAGE).strip()
    session[BROWSING_AWAY_KEY] = True
    session["_navigate_to_page"] = page
    session["active_page"] = page
    session["main_sidebar_page"] = page
    session["_suite_page_user_nav"] = True


def on_return_to_live_draft(session: dict[str, Any]) -> None:
    session.pop(BROWSING_AWAY_KEY, None)
    session[FORCE_SYNC_ON_RETURN_KEY] = True
    session["_navigate_to_page"] = "Live Draft Room"
    session["active_page"] = "Live Draft Room"
    session["main_sidebar_page"] = "Live Draft Room"
    session["_suite_page_user_nav"] = True


def on_return_to_draft_simulator(session: dict[str, Any]) -> None:
    session.pop(BROWSING_AWAY_KEY, None)
    session["_navigate_to_page"] = "Draft Room Simulator"
    session["active_page"] = "Draft Room Simulator"
    session["main_sidebar_page"] = "Draft Room Simulator"
    session["_suite_page_user_nav"] = True


def _seconds_remaining(room: dict[str, Any]) -> int | None:
    try:
        from live_draft_timer_logic import live_draft_seconds_remaining

        if str(room.get("status") or "") == "in_progress":
            return int(live_draft_seconds_remaining(room))
        paused = room.get("paused_remaining_seconds")
        if paused is not None:
            return int(paused)
    except ImportError:
        pass
    return None


def get_draft_return_context(session: dict[str, Any]) -> dict[str, Any] | None:
    """Sidebar card context for active live draft, lobby, completed draft, or simulator."""
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        try:
            from live_draft_state import analyze_live_draft_progress, has_active_live_draft
            from live_draft_setup_mode import is_shared_multiplayer_intent, shared_room_code

            progress = analyze_live_draft_progress(room)
            cfg = dict(room.get("config") or {})
            teams = [str(t) for t in (room.get("teams") or []) if str(t).strip()]
            team_label = " vs ".join(teams[:4]) if teams else str(cfg.get("league_name") or "Draft")
            mode_label = "Shared Multiplayer" if is_shared_multiplayer_intent(session, room=room) else "Solo Draft"
            code = shared_room_code(session) or ""
            user_team = str(session.get("draft_room_participant_team") or cfg.get("your_team") or cfg.get("user_team") or "")
            slot = progress.get("slot") or {}
            round_no = slot.get("Round") if isinstance(slot, dict) else None
            pick_no = progress.get("current_pick")
            on_clock = progress.get("on_clock_team") or "—"
            done = int(progress.get("draft_board_count") or 0)
            total = int(progress.get("total_picks") or 0)

            if progress.get("draft_complete"):
                return {
                    "kind": "live_complete",
                    "title": "Draft Completed",
                    "team_label": team_label,
                    "picks_label": f"{done} of {total} picks completed" if total else f"{done} picks",
                    "room_code": code,
                    "mode_label": mode_label,
                    "user_team": user_team,
                }

            if has_active_live_draft(session) or str(room.get("status") or "") == "not_started":
                return {
                    "kind": "live_active" if has_active_live_draft(session) else "live_lobby",
                    "title": "Return to Live Draft",
                    "team_label": team_label,
                    "room_code": code,
                    "mode_label": mode_label,
                    "user_team": user_team,
                    "round_no": round_no,
                    "pick_no": pick_no,
                    "on_clock": on_clock,
                    "picks_label": f"{done} / {total} picks made" if total else f"{done} picks",
                    "seconds_remaining": _seconds_remaining(room),
                }
        except ImportError:
            pass

    try:
        from draft_room_state import ACTIVE_DRAFT_MODE_LIVE, get_active_draft_status

        status = get_active_draft_status(session)
        if status.get("active"):
            mode = status.get("mode")
            if mode == ACTIVE_DRAFT_MODE_LIVE:
                return None
            return {
                "kind": "simulator",
                "title": "Return to Draft Simulator",
                "picks_label": f"{status.get('pick_count', 0)} pick(s) logged",
                "round_no": status.get("current_round"),
                "pick_no": status.get("current_pick"),
                "on_clock": status.get("on_clock_team") or "—",
                "user_team": status.get("your_team") or "",
            }
    except ImportError:
        pass
    return None


def apply_force_sync_on_return(session: dict[str, Any]) -> bool:
    """Fetch latest shared draft state when user returns to Live Draft Room."""
    if not session.pop(FORCE_SYNC_ON_RETURN_KEY, None):
        return False
    synced = False
    try:
        from draft_room_context import is_multiplayer_draft_active, poll_shared_draft_room, sync_shared_draft_room

        if is_multiplayer_draft_active(session):
            sync_shared_draft_room(session, force=True)
            poll_shared_draft_room(session)
            synced = True
    except ImportError:
        pass
    try:
        from draft_room_state import ensure_live_draft_synced_to_canonical_board

        ensure_live_draft_synced_to_canonical_board(session, reason="force_sync_on_return")
        synced = True
    except ImportError:
        pass
    return synced


def render_return_to_draft_sidebar(st: Any, session: dict[str, Any], *, active_page: str = "") -> None:
    """Prominent sidebar card to return to active live draft, completed draft, or simulator."""
    ctx = get_draft_return_context(session)
    if not ctx:
        return

    kind = str(ctx.get("kind") or "")
    if active_page == "Live Draft Room" and kind == "live_complete":
        return
    with st.sidebar.container(border=True):
        st.markdown(f"**{ctx.get('title')}**")
        if ctx.get("team_label"):
            st.caption(str(ctx["team_label"]))
        if ctx.get("room_code"):
            st.caption(f"Room **{ctx['room_code']}** · {ctx.get('mode_label', '')}")
        if ctx.get("user_team"):
            st.caption(f"Your team: **{ctx['user_team']}**")
        if ctx.get("round_no") and ctx.get("pick_no"):
            st.caption(f"Round **{ctx['round_no']}** · Pick **{ctx['pick_no']}**")
        if ctx.get("on_clock"):
            st.caption(f"On clock: **{ctx['on_clock']}**")
        if ctx.get("picks_label"):
            st.caption(str(ctx["picks_label"]))
        sec = ctx.get("seconds_remaining")
        if sec is not None and kind == "live_active":
            st.caption(f"Time remaining: **{sec}s**")

        if kind in ("live_active", "live_lobby"):
            st.button(
                "Return to Draft",
                type="primary",
                key="sidebar_return_live_draft_btn",
                use_container_width=True,
                on_click=on_return_to_live_draft,
                args=(session,),
            )
        elif kind == "live_complete":
            st.button(
                "Open Live Draft Room",
                key="sidebar_open_completed_draft_btn",
                use_container_width=True,
                on_click=on_return_to_live_draft,
                args=(session,),
            )
        elif kind == "simulator":
            st.button(
                "Return to Draft Simulator",
                type="primary",
                key="sidebar_return_simulator_btn",
                use_container_width=True,
                on_click=on_return_to_draft_simulator,
                args=(session,),
            )


def render_leave_draft_button(st: Any, session: dict[str, Any]) -> None:
    """In-room control to browse other pages without ending the draft."""
    st.button(
        "Leave Draft / Browse Other Pages",
        key="live_draft_browse_other_btn",
        help="Draft continues running. Use the sidebar Return to Draft button to come back.",
        on_click=on_browse_other_pages,
        args=(session,),
    )
