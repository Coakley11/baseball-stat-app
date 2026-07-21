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


def render_solo_live_draft_heartbeat(st: Any, session: dict[str, Any], room: dict[str, Any]) -> None:
    """Mount the sole Solo 1 Hz fragment — expire at zero, no banner repaints."""
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if not is_solo_live_draft(session, room):
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

    if str(room.get("status") or "") not in ("in_progress",):
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
            from live_draft_timer_ui import _resolve_live_room

            tick_room = _resolve_live_room(session, room)
        except Exception:
            tick_room = session.get("live_draft_room")
            if not isinstance(tick_room, dict):
                return

        try:
            from live_draft_solo_timer import (
                install_solo_display_snapshot,
                is_solo_live_draft,
                note_solo_fragment_owned_expire,
                solo_clock_expired,
            )

            if not is_solo_live_draft(session, tick_room):
                return
            install_solo_display_snapshot(session, tick_room)
            if not solo_clock_expired(tick_room):
                return
            note_solo_fragment_owned_expire(session)
            from live_draft_solo_timer import expire_current_pick_and_advance

            result = expire_current_pick_and_advance(
                tick_room, session=session, request_full_rerun=False
            )
            tick_room = _resolve_live_room(session, tick_room)
            if result.ok and (result.advanced or result.complete):
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
                        zero_to_commit_ms=result.zero_to_commit_ms,
                        team_after=result.team_on_clock,
                    )
                except ImportError:
                    pass
                session["_live_draft_solo_board_stale"] = True
                session.pop(ON_CLOCK_BANNER_PAINT_TOKEN_KEY, None)
                try:
                    from live_draft_safe_mode import request_live_draft_rerun

                    request_live_draft_rerun(st, session, "solo_expire", room=tick_room)
                except Exception:
                    st.rerun()
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
                room=room,
                fragment_id=f"hb-{mount_seq}",
            )
        except ImportError:
            pass
        _solo_heartbeat_tick()


def solo_heartbeat_active(session: dict[str, Any]) -> bool:
    return bool(session.get(SOLO_HEARTBEAT_ACTIVE_KEY))
