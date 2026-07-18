"""Live Draft Room setup UI — draft mode selector and shared-room workflow."""

from __future__ import annotations

from typing import Any, Callable

from live_draft_setup_mode import (
    LIVE_DRAFT_SETUP_MODE_KEY,
    MODE_TRACE_KEY,
    SETUP_MODE_LABELS,
    SETUP_MODE_OPTIONS,
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    can_start_live_draft,
    commit_live_draft_mode_from_widget,
    get_live_draft_setup_mode,
    is_shared_multiplayer_intent,
    is_solo_draft_mode,
    normalize_setup_mode,
    record_setup_mode_trace,
    seed_live_draft_setup_mode_before_widget,
    setup_is_read_only,
    shared_room_code,
    shared_room_ready_for_start,
)
from live_draft_team_ownership import (
    count_joined_teams,
    distinct_claimed_owner_count,
    format_team_claim_status,
    format_team_ownership_line,
    lookup_open_teams_for_code,
    team_claim_rows,
    waiting_participant_count,
)


def _mode_label(mode: str) -> str:
    if mode == SETUP_MODE_SHARED:
        return "Shared Multiplayer Draft Room"
    return "Solo Draft"


def render_live_draft_mode_selector(st: Any, session: dict[str, Any], *, disabled: bool = False) -> str:
    """Top-of-setup draft mode selector. Returns active mode.

    Canonical Streamlit key is ``live_draft_setup_mode`` (same as the preference key).
    Never assign that key after ``st.radio`` is created in the same run.
    """
    mode_at_entry = session.get(LIVE_DRAFT_SETUP_MODE_KEY)
    persisted_hint = ""
    try:
        from user_page_preferences import PAGE_KEY_LIVE_DRAFT_SETUP, get_user_page_preferences

        prefs = get_user_page_preferences(
            str(session.get("auth_user_id") or ""),
            str(session.get("_suite_active_workspace_id") or session.get("workspace_id") or ""),
            PAGE_KEY_LIVE_DRAFT_SETUP,
            session=session,
        ) or {}
        persisted_hint = str(prefs.get(LIVE_DRAFT_SETUP_MODE_KEY) or "")
    except ImportError:
        persisted_hint = ""

    seeded = seed_live_draft_setup_mode_before_widget(session)
    before_widget = session.get(LIVE_DRAFT_SETUP_MODE_KEY)
    record_setup_mode_trace(
        session,
        mode_at_page_entry=mode_at_entry,
        persisted_mode_loaded=persisted_hint or seeded,
        session_mode_before_widget=before_widget,
        overwrite_path="",
    )

    # Do not pass index when key is set — session state owns the selection.
    # Do not assign session[LIVE_DRAFT_SETUP_MODE_KEY] again after this call.
    selected = st.radio(
        "Draft Mode",
        list(SETUP_MODE_OPTIONS),
        format_func=lambda m: SETUP_MODE_LABELS.get(m, str(m)),
        key=LIVE_DRAFT_SETUP_MODE_KEY,
        disabled=disabled,
        help="Multiple team names alone does not make a draft multiplayer — choose Shared Multiplayer for a joinable room code.",
    )
    mode = normalize_setup_mode(selected)
    after_widget = session.get(LIVE_DRAFT_SETUP_MODE_KEY)
    committed = commit_live_draft_mode_from_widget(session, mode, st=st)
    record_setup_mode_trace(
        session,
        widget_result=selected,
        mode_after_widget=after_widget,
        value_saved_to_preferences=committed,
        session_mode_final=session.get(LIVE_DRAFT_SETUP_MODE_KEY),
    )

    try:
        from suite_workspace import can_show_developer_tools

        if can_show_developer_tools(st=st):
            trace = session.get(MODE_TRACE_KEY) or {}
            st.caption(
                "Draft Mode trace · "
                f"entry=`{trace.get('mode_at_page_entry')}` · "
                f"persisted=`{trace.get('persisted_mode_loaded')}` · "
                f"before_widget=`{trace.get('session_mode_before_widget')}` · "
                f"widget=`{trace.get('widget_result')}` · "
                f"after_widget=`{trace.get('mode_after_widget')}` · "
                f"saved=`{trace.get('value_saved_to_preferences')}` · "
                f"final=`{trace.get('session_mode_final')}`"
            )
    except ImportError:
        pass

    if mode == SETUP_MODE_SOLO:
        st.info(
            "**Solo draft:** you control all teams. No room code is created and other users cannot join."
        )
    else:
        st.markdown(
            "**Shared multiplayer:** creates a 6-character room code so each manager can claim a team. "
            "Create the shared room before starting the draft."
        )
    return mode


def _shared_create_blocked(session: dict[str, Any]) -> tuple[bool, str]:
    """Return (disabled, help) when auth or an existing code blocks create."""
    try:
        from draft_room_membership import ensure_authenticated_for_shared_room, shared_room_requires_auth

        if shared_room_requires_auth():
            ok, msg = ensure_authenticated_for_shared_room(session, for_create=True)
            if not ok:
                return True, msg
    except ImportError:
        pass
    return False, ""


def should_render_shared_room_created_card(session: dict[str, Any]) -> bool:
    """Show the created-room card only for the current waiting lobby room."""
    code = str(shared_room_code(session) or "").strip().upper()
    if not code:
        return False
    try:
        from live_draft_termination import is_live_draft_permanently_retired

        if is_live_draft_permanently_retired(session, room_code=code):
            return False
    except ImportError:
        pass
    try:
        from live_draft_completion import is_live_draft_ended_tombstoned

        if is_live_draft_ended_tombstoned(session, room_code=code):
            return False
    except ImportError:
        pass
    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        # Stale code without a room — clear and hide.
        try:
            from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY

            session.pop(ACTIVE_SHARED_ROOM_CODE_KEY, None)
        except ImportError:
            session.pop("active_shared_draft_room_code", None)
        return False
    status = str(room.get("status") or "").strip().lower()
    if status in ("ended", "closed", "deleted", "complete", "completed"):
        return False
    return status in ("waiting", "not_started", "in_progress", "paused")


def render_shared_multiplayer_setup(
    st: Any,
    session: dict[str, Any],
    *,
    team_names: list[str],
    room_status: str | None = None,
) -> None:
    """Shared-room create/join UI embedded in draft setup (not hidden in a side panel)."""
    if not is_shared_multiplayer_intent(session):
        return

    code = shared_room_code(session)
    show_created = should_render_shared_room_created_card(session)
    if code and not show_created:
        # Stale confirmation after delete/end — do not paint the card.
        code = ""
    auth_blocked, auth_help = _shared_create_blocked(session)
    with st.container(border=True):
        st.markdown("#### Shared Multiplayer Draft Room")
        if show_created and code:
            st.success("**Shared Draft Room created**")
            st.markdown(f"**Join code:** `{code}`")
            try:
                st.code(code, language=None)
            except TypeError:
                st.code(code)
            waiting = 0
            room = session.get("live_draft_room")
            if isinstance(room, dict):
                try:
                    from live_draft_presence import count_required_joined, format_participant_status_line

                    joined_n, total_n, prow = count_required_joined(session, room)
                    waiting = max(0, total_n - joined_n)
                    st.markdown(f"**Participants:** {joined_n} of {total_n} joined")
                    for row in prow:
                        st.markdown(f"- {format_participant_status_line(row)}")
                except ImportError:
                    waiting = waiting_participant_count(session, room)
                    for row in team_claim_rows(session, room):
                        st.markdown(f"- {format_team_claim_status(session, row)}")
            if waiting > 0:
                st.info(f"Waiting for **{waiting}** more participant{'s' if waiting != 1 else ''}")
            assigned = str(session.get("room_your_team") or "").strip()
            if assigned:
                st.caption(f"Commissioner team: **{assigned}**")
        else:
            st.warning(
                "Create the shared draft room before starting. Other managers need the room code to join."
            )
            if auth_blocked and auth_help:
                st.error(auth_help)

        host_team = str(session.get("live_draft_host_team_pick") or "").strip()
        valid_teams = [str(t).strip() for t in team_names if str(t).strip()]
        if valid_teams and not code:
            default_idx = valid_teams.index(host_team) if host_team in valid_teams else 0
            picked_team = st.selectbox(
                "I control",
                valid_teams,
                index=default_idx,
                key="live_draft_host_team_pick",
                help="Team you will draft for. Guests choose from the remaining teams when they join.",
            )
            session["room_your_team"] = picked_team

        create_disabled = bool(code) or str(room_status or "") == "in_progress" or auth_blocked
        try:
            from draft_ui import on_prepare_shared_draft_room
        except ImportError:
            on_prepare_shared_draft_room = None  # type: ignore[assignment,misc]
        st.button(
            "Create Shared Draft Room",
            type="primary",
            key="live_draft_prepare_shared_btn",
            disabled=create_disabled,
            help=auth_help or "Builds the draft room and generates a 6-character join code (draft has not started yet).",
            on_click=on_prepare_shared_draft_room,
        )

        st.markdown("---")
        render_guest_join_with_team_claim(st, session)


def render_guest_join_with_team_claim(st: Any, session: dict[str, Any]) -> None:
    """Join flow: room code lookup, explicit team claim, then join."""
    st.markdown("**Join Shared Draft Room**")
    join_col1, join_col2 = st.columns([2, 1])
    with join_col1:
        code_input = st.text_input(
            "Enter code",
            key="live_draft_join_code_input",
            placeholder="ABC123",
            help="Enter the 6-character code from the host.",
        )
    code = str(code_input or session.get("live_draft_join_code_input") or "").strip().upper()
    open_teams: list[str] = []
    lookup_err = ""
    already_team = ""
    if len(code) >= 6:
        open_teams, lookup_err = lookup_open_teams_for_code(code, session=session)
        claim_diag = session.get("_draft_room_claim_diag")
        if isinstance(claim_diag, dict):
            already_team = str(claim_diag.get("already_joined_team") or "").strip()
        if not already_team and lookup_err and "already joined" in lookup_err.lower():
            # Parse "You already joined this room as Team B"
            marker = " as "
            idx = lookup_err.lower().rfind(marker)
            if idx >= 0:
                already_team = lookup_err[idx + len(marker) :].strip().rstrip(".")
    if already_team and len(code) >= 6:
        st.info(f"You are already joined as {already_team}")
    elif lookup_err and len(code) >= 6:
        st.caption(f"⚠ {lookup_err}")
    picked_team = ""
    if open_teams and not already_team:
        if len(open_teams) == 1:
            picked_team = open_teams[0]
            st.info(f"Only **{picked_team}** is open — you will join as that team.")
            session["live_draft_join_team_pick"] = picked_team
        else:
            default_idx = 0
            prev = str(session.get("live_draft_join_team_pick") or "").strip()
            if prev in open_teams:
                default_idx = open_teams.index(prev)
            picked_team = st.selectbox(
                "Which team are you?",
                open_teams,
                index=default_idx,
                key="live_draft_join_team_pick",
                help="Select one of the currently unclaimed teams.",
            )
    elif code and not already_team and not lookup_err:
        st.caption("Enter a valid 6-character code to see available teams.")
    with join_col2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        try:
            from draft_ui import on_join_shared_draft_from_setup
        except ImportError:
            on_join_shared_draft_from_setup = None  # type: ignore[assignment,misc]
        if already_team:
            st.button(
                "Re-enter Draft",
                key="live_draft_reenter_from_setup_btn",
                type="primary",
                on_click=on_join_shared_draft_from_setup,
                kwargs={
                    "requested_code": code,
                    "requested_team": already_team,
                    "selectbox_return_value": already_team,
                },
            )
        else:
            join_label = "Join Room"
            if len(open_teams) == 1 and picked_team:
                join_label = f"Join as {picked_team}"
            st.button(
                join_label,
                key="live_draft_join_from_setup_btn",
                type="primary",
                on_click=on_join_shared_draft_from_setup,
                kwargs={
                    "requested_code": code,
                    "requested_team": str(picked_team or "").strip(),
                    "selectbox_return_value": str(picked_team or "").strip(),
                },
            )
    try:
        from draft_room_join_trace import (
            render_claim_availability_diagnostics,
            render_join_attempt_diagnostics,
            render_join_trace_panel,
            render_room_sync_diagnostics,
        )

        render_join_attempt_diagnostics(st, session)
        render_room_sync_diagnostics(st, session)
        render_claim_availability_diagnostics(st, session)
        render_join_trace_panel(st, session)
    except ImportError:
        pass


def _format_join_user_message(*, ok: bool, code: str, team: str, backend_msg: str) -> str:
    if ok:
        return str(backend_msg or f"Joined room {code} as {team}.")
    raw = str(backend_msg or "").strip()
    if not raw:
        return "Could not join room: unknown error."
    low = raw.lower()
    try:
        from draft_room_membership import ERR_TEAM_ALREADY_ASSIGNED
        from live_draft_team_ownership import ROOM_NOT_FOUND_MSG

        if raw == ROOM_NOT_FOUND_MSG or "not found for that code" in low or low == "room code not found":
            return "Room code not found"
        if raw == ERR_TEAM_ALREADY_ASSIGNED or "already claimed" in low or "already assigned" in low:
            return "Team is already claimed"
    except ImportError:
        pass
    if "no longer joinable" in low:
        return raw if raw.startswith("Room is no longer joinable") else f"Room is no longer joinable — {raw}"
    if "already joined" in low:
        return raw
    if "choose a team" in low:
        return "Choose a team before joining"
    if "no open" in low or "no teams are available" in low:
        return "No teams are available"
    if "could not be loaded" in low:
        return "Room data could not be loaded"
    if "unable to save participant" in low:
        return raw if raw.startswith("Unable to save") else f"Unable to save participant — {raw}"
    if "workspace" in low and "mismatch" in low:
        return "Workspace identity mismatch"
    if raw.startswith("Could not join room:"):
        return raw
    return f"Could not join room: {raw}"


def _resolve_requested_team_for_join(
    session: dict[str, Any],
    code: str,
    requested_team: str,
) -> tuple[str, bool, bool, str]:
    """Resolve team for join; single open team is a safe fallback. Returns (team, fallback_used, lookup_attempted, lookup_error)."""
    team = str(requested_team or "").strip()
    if team:
        return team, False, False, ""
    if not code:
        return "", False, False, ""
    open_teams, lookup_err = lookup_open_teams_for_code(code, session=session)
    if len(open_teams) == 1:
        return open_teams[0], True, True, str(lookup_err or "")
    return "", False, True, str(lookup_err or "")


def _record_join_validation_failure(
    session: dict[str, Any],
    *,
    code: str,
    requested_team: str,
    msg: str,
    room_lookup_attempted: bool = False,
    room_lookup_ok: bool = False,
    room_lookup_error: str = "",
) -> None:
    try:
        from draft_room_diagnostics import merge_join_flow_diagnostics

        merge_join_flow_diagnostics(
            session,
            join_code=code,
            captured_requested_team=requested_team,
            room_lookup_attempted=room_lookup_attempted,
            room_lookup_ok=room_lookup_ok,
            room_lookup_error=room_lookup_error,
            claim_attempted=False,
            claim_ok=False,
            claim_error=msg,
        )
    except ImportError:
        pass


def _record_join_flow_outcome(
    session: dict[str, Any],
    *,
    code: str,
    requested_team: str,
    ok: bool,
    msg: str,
    doc: dict[str, Any] | None,
    team_fallback_used: bool = False,
    room_lookup_attempted: bool = True,
) -> None:
    try:
        from draft_room_diagnostics import merge_join_flow_diagnostics
    except ImportError:
        return
    load_diag = session.get("_draft_room_join_load_diag")
    room_lookup_ok = False
    room_lookup_error = ""
    if isinstance(load_diag, dict):
        room_lookup_ok = bool(load_diag.get("found"))
        room_lookup_error = str(load_diag.get("reason") or load_diag.get("query_error") or "")
    joined_room_id = ""
    participant_write_ok = False
    participant_readback_ok = False
    if isinstance(doc, dict):
        room_blob = doc.get("room") if isinstance(doc.get("room"), dict) else {}
        joined_room_id = str(room_blob.get("draft_room_id") or doc.get("draft_room_id") or "")
        participant_write_ok = bool(doc.get("participants"))
        try:
            from draft_room_shared_state import get_shared_room_store

            reloaded = get_shared_room_store().load(code)
            if isinstance(reloaded, dict):
                participant_readback_ok = bool(reloaded.get("participants"))
                if not joined_room_id:
                    rb = reloaded.get("room") if isinstance(reloaded.get("room"), dict) else {}
                    joined_room_id = str(rb.get("draft_room_id") or reloaded.get("draft_room_id") or "")
        except ImportError:
            participant_readback_ok = participant_write_ok
    merge_join_flow_diagnostics(
        session,
        join_code=code,
        captured_requested_team=requested_team,
        team_fallback_used=team_fallback_used,
        room_lookup_attempted=room_lookup_attempted,
        room_lookup_ok=room_lookup_ok,
        room_lookup_error=room_lookup_error,
        claim_attempted=True,
        claim_ok=ok,
        claim_error="" if ok else msg,
        joined_room_id=joined_room_id,
        joined_as_team=requested_team if ok else "",
        participant_write_ok=participant_write_ok,
        participant_readback_ok=participant_readback_ok,
    )


def render_join_attempt_feedback(st: Any, session: dict[str, Any]) -> None:
    """Show join success/error in pre-draft setup (never silent)."""
    flash = session.pop("_draft_join_flash", None)
    if flash:
        st.success(str(flash))
    err = session.pop("_draft_join_error", None)
    if err:
        st.error(str(err))


def render_guest_join_from_setup(st: Any, session: dict[str, Any]) -> bool:
    """Process join-from-setup button. Returns True if rerun needed."""
    if not session.pop("_join_shared_draft_from_setup", None):
        return False
    code = str(
        session.pop("_join_requested_code", "")
        or session.get("live_draft_join_code_input")
        or ""
    ).strip().upper()
    captured_team = str(session.pop("_join_requested_team", "") or "").strip()
    selectbox_return = str(session.pop("_join_selectbox_return_value", "") or "").strip()
    session_widget = str(
        session.pop("_join_session_team_widget_value", "")
        or session.get("live_draft_join_team_pick")
        or ""
    ).strip()
    requested_team = str(captured_team or selectbox_return or session_widget or "").strip()
    team_fallback_used = False
    fallback_lookup_attempted = False
    fallback_lookup_error = ""
    if not requested_team and code:
        requested_team, team_fallback_used, fallback_lookup_attempted, fallback_lookup_error = (
            _resolve_requested_team_for_join(session, code, requested_team)
        )
    try:
        from draft_room_diagnostics import merge_join_flow_diagnostics

        merge_join_flow_diagnostics(
            session,
            join_attempted=True,
            join_code=code,
            requested_team=captured_team,
            selectbox_return_value=selectbox_return,
            session_team_widget_value=session_widget,
            captured_requested_team=requested_team,
            team_fallback_used=team_fallback_used,
            join_button_callback_count=int(session.get("_join_button_callback_count") or 0),
        )
    except ImportError:
        pass
    if not code:
        msg = "Enter a 6-character draft room code."
        session["_draft_join_error"] = msg
        _record_join_validation_failure(session, code=code, requested_team=requested_team, msg=msg)
        return False
    if not requested_team:
        msg = "Choose a team before joining."
        session["_draft_join_error"] = msg
        _record_join_validation_failure(
            session,
            code=code,
            requested_team=requested_team,
            msg=msg,
            room_lookup_attempted=fallback_lookup_attempted,
            room_lookup_ok=False,
            room_lookup_error=fallback_lookup_error,
        )
        return False
    try:
        from draft_room_context import join_shared_draft_room

        ok, msg, doc = join_shared_draft_room(session, code, requested_team=requested_team)
    except ImportError:
        msg = "Join is unavailable."
        session["_draft_join_error"] = msg
        _record_join_flow_outcome(
            session,
            code=code,
            requested_team=requested_team,
            ok=False,
            msg=msg,
            doc=None,
            team_fallback_used=team_fallback_used,
            room_lookup_attempted=True,
        )
        return False
    display = _format_join_user_message(ok=ok, code=code, team=requested_team, backend_msg=msg)
    _record_join_flow_outcome(
        session,
        code=code,
        requested_team=requested_team,
        ok=ok,
        msg=display,
        doc=doc,
        team_fallback_used=team_fallback_used,
        room_lookup_attempted=True,
    )
    if ok:
        # Mode preference is persisted inside join_shared_draft_room (no widget key write).
        session["_draft_join_flash"] = display
        return True
    session["_draft_join_error"] = display
    # Keep structured failure details for Developer Mode + non-silent UI.
    diag = session.get("_draft_room_join_load_diag") or {}
    session.setdefault(
        "_draft_room_join_attempt_diag",
        {
            "entered_code": code,
            "normalized_code": code,
            "lookup_backend": diag.get("backend"),
            "lookup_fallback_used": diag.get("lookup_fallback_used"),
            "found": diag.get("found"),
            "reason": diag.get("reason"),
            "selected_team": requested_team,
            "invitation_required": False,
            "claim_result": display,
        },
    )
    return False


def _room_status_label(room: dict[str, Any]) -> str:
    status = str(room.get("status") or "").replace("_", " ").title()
    if status == "Not Started":
        return "Waiting to Start"
    return status or "—"


def _is_room_host(session: dict[str, Any]) -> bool:
    try:
        from draft_room_context import get_global_draft_context

        ctx = get_global_draft_context(session)
        return bool(ctx.get("is_room_host"))
    except ImportError:
        return False


def render_draft_information_panel(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    on_clock_team: str = "",
    pick_label: str = "",
) -> None:
    """Compact room summary after shared room creation or during live draft."""
    code = shared_room_code(session)
    is_host = _is_room_host(session)
    host_team = str((room.get("config") or {}).get("your_team") or session.get("room_your_team") or "").strip()
    joined, total = count_joined_teams(session, room)
    waiting = max(0, total - joined)
    status_txt = _room_status_label(room)
    mode = "Shared Multiplayer" if is_shared_multiplayer_intent(session, room=room) else "Solo Draft"

    with st.container(border=True):
        st.markdown("#### Draft Information")
        st.markdown(f"**Mode:** {mode}")
        if code:
            st.markdown("**Shared Draft Room created**")
            st.markdown(f"**Join code:** `{code}`")
            if waiting > 0:
                st.info(f"Waiting for **{waiting}** more participant{'s' if waiting != 1 else ''}")
        if is_host:
            st.markdown(f"**Commissioner:** {host_team or 'You'}")
        elif host_team:
            st.markdown(f"**Commissioner team:** {host_team}")
        st.markdown(f"**Teams joined:** {joined} of {total}")
        st.markdown(f"**Status:** {status_txt}")
        if pick_label:
            st.markdown(f"**{pick_label}**")
        if on_clock_team:
            st.markdown(f"**On the clock:** {on_clock_team}")

        st.markdown("**Team ownership**")
        for row in team_claim_rows(session, room):
            st.markdown(f"- {format_team_claim_status(session, row)}")
        try:
            from draft_room_join_trace import render_room_sync_diagnostics

            render_room_sync_diagnostics(st, session)
        except ImportError:
            pass

        action_col1, action_col2, action_col3 = st.columns(3)
        with action_col1:
            if code and st.button("Copy Join Code", key="live_draft_lobby_copy_code_btn", use_container_width=True):
                session["_live_draft_join_code_copied"] = code
                st.success(f"Join code **{code}** — select the code above to copy.")
        with action_col2:
            if st.button("Refresh Lobby", key="live_draft_lobby_refresh_btn", use_container_width=True):
                try:
                    from draft_room_context import sync_shared_draft_room
                    from draft_room_shared_state import invalidate_shared_room_document_cache

                    invalidate_shared_room_document_cache(session, code)
                    sync_shared_draft_room(session, force=True)
                except ImportError:
                    pass
                session["_live_draft_lobby_refresh"] = True
        with action_col3:
            if is_host and st.button("Cancel Shared Room", key="live_draft_lobby_cancel_btn", use_container_width=True):
                try:
                    from draft_room_context import leave_shared_draft_room

                    leave_shared_draft_room(session)
                    session.pop("live_draft_room", None)
                    session["_live_draft_lobby_left"] = True
                except ImportError:
                    pass
        if session.pop("_live_draft_join_code_copied", None):
            pass


def render_shared_draft_ready_card(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    on_start: Callable[[], None] | None = None,
) -> None:
    """Prominent lobby card — host starts draft; guests wait."""
    if not is_shared_multiplayer_intent(session, room=room):
        return
    if str(room.get("status") or "") != "not_started":
        return

    code = shared_room_code(session)
    authority = None
    try:
        from draft_room_context import refresh_shared_lobby_authority

        authority = refresh_shared_lobby_authority(session, force_poll=True)
    except ImportError:
        authority = None
    try:
        from live_draft_presence import count_required_joined, format_participant_status_line

        joined, total, prow = count_required_joined(
            session, room, document=authority if isinstance(authority, dict) else None
        )
    except ImportError:
        joined, total = count_joined_teams(session, room)
        prow = []
    is_host = _is_room_host(session)
    start_disabled, start_help = start_button_disabled(session)

    with st.container(border=True):
        st.markdown("### Shared Draft Room Ready")
        if code:
            # Canonical room-code panel lives in render_live_draft_room_code_header.
            st.markdown(f"**Room Code:** `{code}`")
        else:
            st.error("Room code missing — recreate the shared room before inviting managers.")
        st.markdown(f"**Participants joined:** {joined} of {total}")
        if prow:
            for row in prow:
                st.markdown(f"- {format_participant_status_line(row)}")
        distinct = distinct_claimed_owner_count(
            session, room
        )
        if is_host and distinct < 2 and total >= 2:
            st.caption(
                f"**{distinct}** distinct owner(s) — need **2** before starting (Phase 1)."
            )

        if is_host:
            st.info(
                "Press **Start Live Draft** when all required participants have joined and claimed their teams."
            )
            st.button(
                "Start Live Draft",
                type="primary",
                key="live_draft_lobby_start_btn",
                disabled=start_disabled,
                help=start_help or None,
                on_click=on_start,
                use_container_width=True,
            )
        else:
            st.warning("Waiting for commissioner to start the draft.")
            if start_help:
                st.caption(start_help)


def render_edit_setup_expander(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    render_setup_fn: Callable[..., None],
    **setup_kwargs: Any,
) -> None:
    """Host-only collapsed setup editor before first pick."""
    if not _is_room_host(session):
        return
    if setup_is_read_only(room):
        st.caption("Draft setup is read-only after the first pick.")
        return
    with st.expander("Edit Draft Setup (host only)", expanded=False):
        render_setup_fn(st, session, **setup_kwargs)


def render_active_draft_mode_banner(st: Any, session: dict[str, Any], *, room: dict[str, Any]) -> None:
    """Compact mode banner during active or prepared draft."""
    if is_solo_draft_mode(session, room=room):
        teams = [str(t) for t in (room.get("teams") or []) if str(t).strip()]
        team_note = f" ({len(teams)} teams)" if len(teams) > 1 else ""
        st.caption(f"**Mode: Solo Draft** · You control all teams{team_note} · No room code")
        return
    if is_shared_multiplayer_intent(session, room=room):
        code = shared_room_code(session)
        if code:
            st.caption(f"**Mode: Shared Multiplayer** · Room Code **{code}**")
        else:
            st.warning(
                "Shared multiplayer was selected but no room code is active. "
                "Could not create shared room — this draft cannot be joined by others."
            )


def start_button_disabled(session: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = can_start_live_draft(session)
    return not ok, reason


def render_lobby_status_panel(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
) -> None:
    """Cleaner lobby join status with checkmarks and ready state."""
    if not is_shared_multiplayer_intent(session, room=room):
        return
    if str(room.get("status") or "") != "not_started":
        return
    authority = None
    try:
        from draft_room_context import refresh_shared_lobby_authority

        authority = refresh_shared_lobby_authority(session, force_poll=True)
    except ImportError:
        authority = None
    rows = team_claim_rows(
        session, room, document=authority if isinstance(authority, dict) else None
    )
    joined_lines: list[str] = []
    waiting_lines: list[str] = []
    for row in rows:
        team = str(row.get("team") or "").strip()
        if row.get("claimed"):
            line = format_team_claim_status(session, row)
            joined_lines.append(f"✓ {line}")
        else:
            waiting_lines.append(team)
    with st.container(border=True):
        st.markdown("#### Lobby Status")
        code = shared_room_code(session)
        if code:
            st.markdown(f"**Room Code:** `{code}`")
        for line in joined_lines:
            st.markdown(line)
        st.markdown("**Waiting:**")
        if waiting_lines:
            for team in waiting_lines:
                st.markdown(f"- {team}")
        else:
            st.markdown("None")
        joined, total = count_joined_teams(session, room)
        if joined >= total and total > 0:
            st.success("Ready to Start")
        diag = session.get("_shared_lobby_sync_diag")
        show_diag = isinstance(diag, dict)
        if show_diag:
            try:
                from draft_room_join_trace import join_trace_visible

                show_diag = join_trace_visible(session)
            except ImportError:
                show_diag = bool(session.get("developer_mode"))
        if show_diag and isinstance(diag, dict):
            with st.expander("Lobby sync diagnostics (Developer Mode)", expanded=True):
                for key in (
                    "entered_room_code",
                    "canonical_room_id",
                    "shared_document_storage_key",
                    "room_revision",
                    "configured_teams",
                    "required_human_teams",
                    "raw_participants",
                    "joined_participants",
                    "raw_team_claims",
                    "canonicalized_claims",
                    "current_account_participant_id",
                    "claimed_team",
                    "last_shared_document_update",
                    "participants_joined",
                    "participants_required",
                ):
                    st.text(f"{key}: {diag.get(key)}")


def render_draft_status_summary_card(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    on_clock_team: str = "",
    pick_label: str = "",
    round_no: str = "",
) -> None:
    """Compact commissioner / room summary — room code, managers, draft status."""
    code = shared_room_code(session)
    is_host = _is_room_host(session)
    host_team = str((room.get("config") or {}).get("your_team") or session.get("room_your_team") or "").strip()
    joined, total = count_joined_teams(session, room)
    status_txt = _room_status_label(room)
    commissioner_label = host_team or "You"
    if is_host:
        commissioner_label = "You"
    try:
        from live_draft_ux import format_participant_identity

        commissioner_line = format_participant_identity(
            commissioner_label,
            role="Commissioner",
            team=host_team,
        )
    except ImportError:
        commissioner_line = f"**Commissioner:** {commissioner_label}"

    show_pick_clock = str(room.get("status") or "").strip() in {"in_progress", "paused", "complete"}
    if not show_pick_clock:
        on_clock_team = ""
        pick_label = ""
        round_no = ""

    with st.container(border=True):
        st.markdown("#### Draft Status Summary")
        if code:
            # Canonical room-code panel is rendered once by the waiting/active header.
            st.markdown(f"**Room Code:** `{code}`")
        else:
            st.warning("Room code missing for this shared draft.")
        st.markdown(f"**{commissioner_line}**")
        if pick_label:
            st.markdown(f"**Current Pick:** {pick_label}")
        if round_no:
            st.markdown(f"**Current Round:** {round_no}")
        st.markdown(f"**Draft Status:** {status_txt}")
        st.markdown(f"**Connected Managers:** {joined} of {total}")
        if on_clock_team and str(on_clock_team) not in {"", "—"}:
            st.markdown(f"**On the Clock:** {on_clock_team}")
        st.markdown("**Claimed Teams**")
        for row in team_claim_rows(session, room):
            st.markdown(f"- {format_team_claim_status(session, row)}")
