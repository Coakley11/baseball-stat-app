"""Live Draft Room multiplayer panel — create/join shared rooms."""

from __future__ import annotations

from typing import Any

from draft_room_diagnostics import render_shared_room_diagnostics
from draft_source_validation import ALLOW_FREE_POOL_KEY


def render_shared_draft_room_panel(st: Any, session: dict[str, Any]) -> bool:
    """Render create/join/status UI. Returns True if session should rerun."""
    try:
        from draft_room_context import (
            create_and_host_shared_room,
            get_global_draft_context,
            is_multiplayer_draft_active,
            join_shared_draft_room,
            leave_shared_draft_room,
            sync_shared_draft_room,
        )
        from live_draft_state import LIVE_DRAFT_ROOM_KEY
    except ImportError:
        return False

    ctx = get_global_draft_context(session)
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    room_active = isinstance(room, dict) and str(room.get("status") or "") in ("in_progress", "paused", "not_started")

    with st.container(border=True):
        st.markdown("#### Shared Draft Room")
        mode = ctx.get("mode") or "none"
        if mode == "multiplayer":
            backend = (ctx.get("shared_storage_backend") or "unknown")
            st.caption(
                f"**Multiplayer** · Room code **{ctx.get('room_code')}** · "
                f"Your team: **{ctx.get('participant_team') or '—'}** · "
                f"Revision {ctx.get('shared_revision') or '—'} · Backend `{backend}`"
            )
        elif mode == "single_user_live":
            st.caption("**Single-user** live draft — create a shared room to invite other managers.")
        else:
            st.caption("Start or resume a live draft, then create a shared room for multiplayer.")

        sync_shared_draft_room(session)

        notice = session.pop("_draft_room_membership_notice", None)
        if notice:
            st.warning(str(notice))
        conflict = session.pop("_draft_room_conflict_notice", None)
        if conflict:
            st.warning(str(conflict))

        if is_multiplayer_draft_active(session):
            is_host = bool(ctx.get("is_room_host"))
            room_cfg = dict((room or {}).get("config") or {}) if isinstance(room, dict) else {}
            free_pool_default = bool(room_cfg.get(ALLOW_FREE_POOL_KEY, session.get(ALLOW_FREE_POOL_KEY, False)))
            if is_host:
                free_pool = st.checkbox(
                    "Allow drafting any available player (commissioner)",
                    value=free_pool_default,
                    key="shared_room_allow_free_pool",
                    help="When off, you may only draft from your Queue, Watchlist, or Tracked Players.",
                )
                session[ALLOW_FREE_POOL_KEY] = free_pool
                if isinstance(room, dict):
                    cfg = dict(room.get("config") or {})
                    cfg[ALLOW_FREE_POOL_KEY] = free_pool
                    room["config"] = cfg
            else:
                session[ALLOW_FREE_POOL_KEY] = free_pool_default
                label = "enabled" if free_pool_default else "disabled"
                st.caption(f"Free pool drafting is **{label}** (host commissioner setting).")

            join_code = st.text_input(
                "Room code",
                value=str(ctx.get("room_code") or ""),
                key="shared_draft_room_code_display",
                disabled=True,
            )
            if st.button("Refresh board now", key="shared_draft_refresh_btn"):
                sync_shared_draft_room(session, force=True)
                return True
            if st.button("Leave shared room", key="shared_draft_leave_btn"):
                leave_shared_draft_room(session)
                st.info("Left shared draft room. Your private queue and watchlist are saved.")
                return True
            render_shared_room_diagnostics(st, session)
            return False

        col_create, col_join = st.columns(2)
        with col_create:
            create_disabled = not room_active or str(room.get("status") or "") not in ("in_progress", "paused")
            if st.button(
                "Create Shared Draft Room",
                key="shared_draft_create_btn",
                type="primary",
                disabled=create_disabled,
                help="Requires an active live draft.",
            ):
                if isinstance(room, dict):
                    session[ALLOW_FREE_POOL_KEY] = False
                    cfg = dict(room.get("config") or {})
                    cfg[ALLOW_FREE_POOL_KEY] = False
                    room["config"] = cfg
                    code, doc = create_and_host_shared_room(session, room)
                    if not code:
                        st.error(session.pop("_draft_room_last_error", "Could not create shared room."))
                    else:
                        st.success(f"Shared room created. Share code **{code}** with other managers.")
                    return True
        with col_join:
            join_input = st.text_input("Join room code", key="shared_draft_join_code_input", placeholder="ABC123")
            if st.button("Join Room by Code", key="shared_draft_join_btn"):
                ok, msg, _ = join_shared_draft_room(session, join_input)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
                return True

    return False
