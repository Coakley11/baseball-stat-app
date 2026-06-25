"""Live Draft Room setup UI — draft mode selector and shared-room workflow."""

from __future__ import annotations

from typing import Any

from live_draft_setup_mode import (
    LIVE_DRAFT_SETUP_MODE_KEY,
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    can_start_live_draft,
    get_live_draft_setup_mode,
    is_shared_multiplayer_intent,
    is_solo_draft_mode,
    set_live_draft_setup_mode,
    shared_room_code,
    shared_room_ready_for_start,
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
                "Your team (host)",
                valid_teams,
                index=default_idx,
                key="live_draft_host_team_pick",
                help="Team you control when drafting. Other teams are claimed by guests who join.",
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
        st.markdown("**Already have a code?** Join an existing shared draft room:")
        join_col1, join_col2 = st.columns([2, 1])
        with join_col1:
            st.text_input(
                "Draft Room Code",
                key="live_draft_join_code_input",
                placeholder="ABC123",
                help="Enter the 6-character code from the host.",
            )
        with join_col2:
            if st.button("Join Room", key="live_draft_join_from_setup_btn"):
                session["_join_shared_draft_from_setup"] = True


def render_guest_join_from_setup(st: Any, session: dict[str, Any]) -> bool:
    """Process join-from-setup button. Returns True if rerun needed."""
    if not session.pop("_join_shared_draft_from_setup", None):
        return False
    code = str(session.get("live_draft_join_code_input") or "").strip().upper()
    if not code:
        st.error("Enter a 6-character draft room code.")
        return False
    try:
        from draft_room_context import join_shared_draft_room

        ok, msg, _doc = join_shared_draft_room(session, code)
    except ImportError:
        st.error("Join is unavailable.")
        return False
    if ok:
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED)
        session["_draft_join_flash"] = msg or f"Joined room {code}."
        return True
    session["_draft_join_error"] = msg or "Could not join room."
    return False


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
