"""Live Draft Room setup UI — draft mode selector and shared-room workflow."""

from __future__ import annotations

from typing import Any, Callable

from live_draft_setup_mode import (
    LIVE_DRAFT_SETUP_MODE_KEY,
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    can_start_live_draft,
    get_live_draft_setup_mode,
    is_shared_multiplayer_intent,
    is_solo_draft_mode,
    set_live_draft_setup_mode,
    setup_is_read_only,
    shared_room_code,
    shared_room_ready_for_start,
)
from live_draft_team_ownership import (
    count_joined_teams,
    format_team_ownership_line,
    lookup_open_teams_for_code,
    team_claim_rows,
)


def _mode_label(mode: str) -> str:
    if mode == SETUP_MODE_SHARED:
        return "Shared Multiplayer Draft Room"
    return "Solo Draft"


def render_live_draft_mode_selector(st: Any, session: dict[str, Any], *, disabled: bool = False) -> str:
    """Top-of-setup draft mode selector. Returns active mode."""
    current = get_live_draft_setup_mode(session)
    options = {
        SETUP_MODE_SOLO: "Solo Draft — you control all teams (no room code)",
        SETUP_MODE_SHARED: "Shared Multiplayer Draft Room — room code, other users join",
    }
    labels = list(options.values())
    values = list(options.keys())
    index = values.index(current) if current in values else 0

    selected_label = st.radio(
        "Draft Mode",
        labels,
        index=index,
        key="_live_draft_mode_radio_label",
        disabled=disabled,
        help="Multiple team names alone does not make a draft multiplayer — choose Shared Multiplayer for a joinable room code.",
    )
    mode = values[labels.index(selected_label)] if selected_label in labels else current
    set_live_draft_setup_mode(session, mode)

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
    with st.container(border=True):
        st.markdown("#### Shared Multiplayer Draft Room")
        if code:
            st.success(f"Invite players with this room code: **{code}**")
            try:
                st.code(code, language=None)
            except TypeError:
                st.code(code)
            st.caption("Share this 6-character code. Each player joins and claims their team before picking.")
            assigned = str(session.get("room_your_team") or "").strip()
            if assigned:
                st.markdown(f"**Your team (host):** {assigned}")
        else:
            st.warning(
                "Create the shared draft room before starting. Other managers need the room code to join."
            )

        host_team = str(session.get("live_draft_host_team_pick") or "").strip()
        valid_teams = [str(t).strip() for t in team_names if str(t).strip()]
        if valid_teams:
            default_idx = valid_teams.index(host_team) if host_team in valid_teams else 0
            picked_team = st.selectbox(
                "I control",
                valid_teams,
                index=default_idx,
                key="live_draft_host_team_pick",
                help="Team you will draft for. Guests choose from the remaining teams when they join.",
            )
            session["room_your_team"] = picked_team

        create_disabled = bool(code) or str(room_status or "") == "in_progress"
        if st.button(
            "Create Shared Draft Room",
            type="primary",
            key="live_draft_prepare_shared_btn",
            disabled=create_disabled,
            help="Builds the draft room and generates a 6-character join code (draft has not started yet).",
        ):
            session["_start_live_draft_mode"] = "prepare_shared"
            session["_start_live_draft_pending"] = True

        st.markdown("---")
        render_guest_join_with_team_claim(st, session)


def render_guest_join_with_team_claim(st: Any, session: dict[str, Any]) -> None:
    """Join flow: room code lookup, explicit team claim, then join."""
    st.markdown("**Already have a code?** Join an existing shared draft room:")
    join_col1, join_col2 = st.columns([2, 1])
    with join_col1:
        code_input = st.text_input(
            "Draft Room Code",
            key="live_draft_join_code_input",
            placeholder="ABC123",
            help="Enter the 6-character code from the host.",
        )
    code = str(code_input or session.get("live_draft_join_code_input") or "").strip().upper()
    open_teams: list[str] = []
    lookup_err = ""
    if len(code) >= 6:
        open_teams, lookup_err = lookup_open_teams_for_code(code)
    if lookup_err and len(code) >= 6:
        st.caption(f"⚠ {lookup_err}")
    picked_team = ""
    if open_teams:
        default_idx = 0
        prev = str(session.get("live_draft_join_team_pick") or "").strip()
        if prev in open_teams:
            default_idx = open_teams.index(prev)
        picked_team = st.selectbox(
            "Choose your team",
            open_teams,
            index=default_idx,
            key="live_draft_join_team_pick",
            help="Pick the team you control. Teams are never assigned automatically.",
        )
    elif code:
        st.caption("Enter a valid 6-character code to see available teams.")
    with join_col2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("Join Room", key="live_draft_join_from_setup_btn", type="primary"):
            session["_join_shared_draft_from_setup"] = True
            session["_join_requested_team"] = str(picked_team or session.get("live_draft_join_team_pick") or "").strip()


def render_guest_join_from_setup(st: Any, session: dict[str, Any]) -> bool:
    """Process join-from-setup button. Returns True if rerun needed."""
    if not session.pop("_join_shared_draft_from_setup", None):
        return False
    code = str(session.get("live_draft_join_code_input") or "").strip().upper()
    requested_team = str(session.pop("_join_requested_team", "") or session.get("live_draft_join_team_pick") or "").strip()
    if not code:
        st.error("Enter a 6-character draft room code.")
        return False
    if not requested_team:
        st.error("Choose a team before joining.")
        return False
    try:
        from draft_room_context import join_shared_draft_room

        ok, msg, _doc = join_shared_draft_room(session, code, requested_team=requested_team)
    except ImportError:
        st.error("Join is unavailable.")
        return False
    if ok:
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED)
        session["_draft_join_flash"] = msg or f"Joined room {code} as **{requested_team}**."
        return True
    session["_draft_join_error"] = msg or "Could not join room."
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
    status_txt = _room_status_label(room)
    mode = "Shared Multiplayer" if is_shared_multiplayer_intent(session, room=room) else "Solo Draft"

    with st.container(border=True):
        st.markdown("#### Draft Information")
        st.markdown(f"**Mode:** {mode}")
        if code:
            st.markdown(f"**Room Code:** `{code}`")
        if is_host:
            st.markdown(f"**Host:** {host_team or 'You'}")
        elif host_team:
            st.markdown(f"**Host team:** {host_team}")
        st.markdown(f"**Teams joined:** {joined} of {total}")
        st.markdown(f"**Status:** {status_txt}")
        if pick_label:
            st.markdown(f"**{pick_label}**")
        if on_clock_team:
            st.markdown(f"**On the clock:** {on_clock_team}")

        st.markdown("**Team ownership**")
        for row in team_claim_rows(session, room):
            st.markdown(f"- {format_team_ownership_line(row)}")

        action_col1, action_col2 = st.columns(2)
        with action_col1:
            if st.button("Refresh room", key="live_draft_lobby_refresh_btn", use_container_width=True):
                try:
                    from draft_room_context import sync_shared_draft_room

                    sync_shared_draft_room(session, force=True)
                except ImportError:
                    pass
                session["_live_draft_lobby_refresh"] = True
        with action_col2:
            if st.button("Leave room", key="live_draft_lobby_leave_btn", use_container_width=True):
                try:
                    from draft_room_context import leave_shared_draft_room

                    leave_shared_draft_room(session)
                    session["_live_draft_lobby_left"] = True
                except ImportError:
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
    joined, total = count_joined_teams(session, room)
    is_host = _is_room_host(session)
    start_disabled, start_help = start_button_disabled(session)

    with st.container(border=True):
        st.markdown("### Shared Draft Room Ready")
        if code:
            st.markdown(f"**Room Code:** `{code}`")
        st.markdown(f"**Teams joined:** {joined} of {total}")

        if is_host:
            st.info(
                "Press **Start Live Draft** when all participants have joined and you are ready to begin."
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
            st.warning("Waiting for host to start the draft.")


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
