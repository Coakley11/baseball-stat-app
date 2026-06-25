"""Live Draft Room multiplayer panel — create/join shared rooms."""

from __future__ import annotations

import time
from typing import Any

from draft_room_diagnostics import (
    render_compact_pool_diagnostics,
    render_join_assignment_diagnostics,
    render_shared_room_create_diagnostics,
    render_shared_room_diagnostics,
    render_shared_room_join_load_diagnostics,
)
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
            prepare_global_draft_context,
            sync_shared_draft_room,
        )
        from draft_room_join_trace import render_join_trace_panel, render_shared_room_auth_diagnostics, trace_join_step
        from draft_room_supabase_health import render_shared_room_supabase_health
        from live_draft_state import LIVE_DRAFT_ROOM_KEY
        from live_draft_setup_mode import is_solo_draft_mode
    except ImportError:
        return False

    room = session.get(LIVE_DRAFT_ROOM_KEY)
    try:
        from live_draft_setup_mode import should_hide_legacy_shared_panel

        if should_hide_legacy_shared_panel(session, room if isinstance(room, dict) else None):
            return False
    except ImportError:
        pass

    if is_solo_draft_mode(session) and not is_multiplayer_draft_active(session):
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
        try:
            from suite_workspace import can_show_developer_tools

            if can_show_developer_tools(st=st):
                render_shared_room_supabase_health(st, session)
        except ImportError:
            pass
        mode = ctx.get("mode") or "none"
        if mode == "multiplayer":
            share = str(ctx.get("room_code") or "").strip().upper()
            internal_id = str(ctx.get("draft_room_id") or "").strip()
            st.caption(
                f"**Multiplayer draft** · Draft Room Code **{share}** · "
                f"Your team: **{ctx.get('participant_team') or '—'}**"
            )
            try:
                from suite_workspace import can_show_developer_tools

                if can_show_developer_tools(st=st):
                    backend = (ctx.get("shared_storage_backend") or "unknown")
                    st.caption(
                        f"Dev: internal session `{internal_id}` · revision {ctx.get('shared_revision') or '—'} · backend `{backend}`"
                    )
            except ImportError:
                pass
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
            free_pool_default = bool(room_cfg.get(ALLOW_FREE_POOL_KEY, session.get(ALLOW_FREE_POOL_KEY, True)))
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
                "Draft Room Code",
                value=str(ctx.get("room_code") or ""),
                key="shared_draft_room_code_display",
                disabled=True,
                help="Other managers enter this 6-character code to join — not the internal session ID.",
            )
            if st.button("Refresh board now", key="shared_draft_refresh_btn"):
                sync_shared_draft_room(session, force=True)
                return True
            if st.button("Leave shared room", key="shared_draft_leave_btn"):
                leave_shared_draft_room(session)
                try:
                    from baseball_persistent_state import force_save_baseball_state

                    force_save_baseball_state(st, reason="shared_draft_leave")
                except ImportError:
                    pass
                st.info("Left shared draft room. Your private queue and watchlist are saved.")
                return True
            try:
                from suite_workspace import can_show_developer_tools

                if can_show_developer_tools(st=st):
                    if st.button("Reset multiplayer membership (dev)", key="shared_draft_reset_membership_btn"):
                        from draft_room_participant_state import clear_multiplayer_membership_for_account

                        clear_multiplayer_membership_for_account(session)
                        prepare_global_draft_context(session)
                        st.warning("Cleared stale membership/team globals for this auth account. Re-join the room if needed.")
                        return True
            except ImportError:
                pass
            render_shared_room_diagnostics(st, session)
            render_join_assignment_diagnostics(st, session)
            render_compact_pool_diagnostics(st, session)
            try:
                from draft_room_runtime_diagnostics import render_runtime_diagnostic_table

                render_runtime_diagnostic_table(st, session)
            except ImportError:
                pass
            render_shared_room_create_diagnostics(st, session)
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
                help="Requires an active live draft. Creates a 6-character Draft Room Code for other managers to join.",
            ):
                if isinstance(room, dict):
                    try:
                        from draft_room_create_verify import init_create_flow_diagnostics

                        init_create_flow_diagnostics(
                            session,
                            clicked=True,
                        )
                        session["_draft_room_create_diag"]["internal_draft_session_id"] = str(
                            room.get("draft_room_id") or ""
                        ).strip().upper()
                    except ImportError:
                        session["_draft_room_create_diag"] = {"create_button_clicked": True}
                    session[ALLOW_FREE_POOL_KEY] = False
                    cfg = dict(room.get("config") or {})
                    cfg[ALLOW_FREE_POOL_KEY] = False
                    room["config"] = cfg
                    code, doc = create_and_host_shared_room(session, room)
                    render_shared_room_create_diagnostics(st, session)
                    if not code:
                        err = session.pop("_draft_room_last_error", "Could not create shared room.")
                        st.error(err or "Could not create shared room. This draft cannot be joined by others.")
                        _render_supabase_error_detail(st, session)
                    else:
                        try:
                            from draft_room_create_verify import is_plausible_share_code

                            if not is_plausible_share_code(code):
                                session.pop("_draft_room_last_error", None)
                                st.error(f"Invalid share code returned ({code!r}). Shared room was not activated.")
                            else:
                                _finalize_successful_join(
                                    session,
                                    f"Draft room created. **Draft Room Code: {code}** — share this code so others can join.",
                                )
                        except ImportError:
                            _finalize_successful_join(
                                session,
                                f"Draft room created. **Draft Room Code: {code}**",
                            )
                    return True
        with col_join:
            join_code_val = st.text_input(
                "Draft Room Code",
                key="shared_draft_join_code_legacy",
                placeholder="ABC123",
                help="Enter the 6-character Draft Room Code from your host.",
            )
            code = str(join_code_val or "").strip().upper()
            open_teams: list[str] = []
            if len(code) >= 6:
                try:
                    from live_draft_team_ownership import lookup_open_teams_for_code

                    open_teams, lookup_err = lookup_open_teams_for_code(code)
                    if lookup_err:
                        st.caption(f"⚠ {lookup_err}")
                except ImportError:
                    lookup_err = ""
            requested_team = ""
            if open_teams:
                requested_team = st.selectbox(
                    "Choose your team",
                    open_teams,
                    key="shared_draft_join_team_pick",
                )
            if st.button("Join Room by Code", key="shared_draft_join_btn", type="primary"):
                trace_join_step(session, "join_button_clicked", room_code_entered=code or None)
                if not code:
                    session["_draft_join_error"] = "Enter a 6-character draft room code."
                    return True
                if not requested_team:
                    session["_draft_join_error"] = "Choose a team before joining."
                    return True
                ok, msg, _ = join_shared_draft_room(session, code, requested_team=requested_team)
                if ok:
                    _finalize_successful_join(session, msg)
                    render_join_assignment_diagnostics(st, session)
                else:
                    session["_draft_join_error"] = msg
                    render_shared_room_join_load_diagnostics(st, session)
                    _render_supabase_error_detail(st, session)
                    trace_join_step(session, "join_failed", message=msg)
                return True

        render_shared_room_auth_diagnostics(st, session)
        render_join_trace_panel(st, session)

        if needs_sign_in_rerun:
            return True

    return False
