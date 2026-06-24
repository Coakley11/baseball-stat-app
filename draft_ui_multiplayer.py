"""Live Draft Room multiplayer panel — create/join shared rooms."""

from __future__ import annotations

import time
from typing import Any

from draft_room_diagnostics import render_shared_room_diagnostics
from draft_source_validation import ALLOW_FREE_POOL_KEY


def _show_join_auth_hint(st: Any, session: dict[str, Any]) -> bool:
    """Warn and offer sign-in when shared rooms require Real Accounts. Returns True if blocked."""
    try:
        from baseball_account_sidebar import request_account_sign_in_panel
        from draft_room_join_trace import render_shared_room_auth_diagnostics
        from draft_room_membership import shared_room_requires_auth
        from draft_room_join_trace import get_shared_room_auth_diagnostics
    except ImportError:
        return False

    if not shared_room_requires_auth():
        return False
    diag = get_shared_room_auth_diagnostics(session)
    if diag.get("join_would_pass"):
        return False

    st.warning(
        "Shared draft rooms require **Real Account sign-in**. "
        "Workspace/cloud sync is not enough."
    )
    st.caption(
        "Open **Account & sign-in** in the sidebar (or tap below), then try Join again."
    )
    if st.button("Open sign-in", key="shared_draft_open_sign_in_btn", type="secondary"):
        request_account_sign_in_panel(session)
        return True

    render_shared_room_auth_diagnostics(st, session)
    return False


def _render_supabase_error_detail(st: Any, session: dict[str, Any]) -> None:
    try:
        from draft_room_join_trace import join_trace_visible
    except ImportError:
        return
    if not join_trace_visible(session):
        return
    diag = session.get("_draft_room_supabase_error")
    if not isinstance(diag, dict):
        return
    with st.expander("Supabase error detail (dev)", expanded=True):
        st.text(f"status_code: {diag.get('status_code')}")
        st.text(f"method: {diag.get('method')}")
        st.text(f"path: {diag.get('path')}")
        if diag.get("detail"):
            st.code(str(diag.get("detail"))[:2000])


def _finalize_successful_join(session: dict[str, Any], message: str) -> None:
    from draft_room_context import prepare_global_draft_context

    prepare_global_draft_context(session)
    session["_draft_join_flash"] = message
    session["_shared_draft_poll_ts"] = time.time()
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(
            type("S", (), {"session_state": session})(),
            reason="shared_draft_join",
        )
    except ImportError:
        pass


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
        from draft_room_join_trace import render_join_trace_panel, render_shared_room_auth_diagnostics, trace_join_step
        from draft_room_supabase_health import render_shared_room_supabase_health
        from live_draft_state import LIVE_DRAFT_ROOM_KEY
    except ImportError:
        return False

    join_flash = session.pop("_draft_join_flash", None)
    if join_flash:
        st.success(str(join_flash))

    join_error = session.pop("_draft_join_error", None)
    if join_error:
        st.error(str(join_error))

    ctx = get_global_draft_context(session)
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    room_active = isinstance(room, dict) and str(room.get("status") or "") in ("in_progress", "paused", "not_started")

    with st.container(border=True):
        st.markdown("#### Shared Draft Room")
        render_shared_room_supabase_health(st, session)
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
            trace_join_step(
                session,
                "multiplayer_ui_active",
                room_code=ctx.get("room_code"),
                assigned_team=ctx.get("participant_team"),
                backend=ctx.get("shared_storage_backend"),
            )
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
            render_shared_room_auth_diagnostics(st, session)
            render_join_trace_panel(st, session)
            return False

        needs_sign_in_rerun = _show_join_auth_hint(st, session)

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
                        _render_supabase_error_detail(st, session)
                    else:
                        _finalize_successful_join(session, f"Shared room created. Share code **{code}** with other managers.")
                    return True
        with col_join:
            with st.form("shared_draft_join_form", clear_on_submit=False):
                join_input = st.text_input(
                    "Join room code",
                    placeholder="ABC123",
                    help="Enter the code from the host device, then tap Join.",
                )
                submitted = st.form_submit_button("Join Room by Code", type="primary")
            if submitted:
                trace_join_step(session, "join_button_clicked", room_code_entered=str(join_input or "").strip().upper() or None)
                ok, msg, _ = join_shared_draft_room(session, join_input)
                if ok:
                    _finalize_successful_join(session, msg)
                else:
                    session["_draft_join_error"] = msg
                    _render_supabase_error_detail(st, session)
                    trace_join_step(session, "join_failed", message=msg)
                return True

        render_shared_room_auth_diagnostics(st, session)
        render_join_trace_panel(st, session)

        if needs_sign_in_rerun:
            return True

    return False
