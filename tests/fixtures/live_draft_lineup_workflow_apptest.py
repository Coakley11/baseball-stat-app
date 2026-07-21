"""Completed Live Draft → Lineup Management origin (rendered)."""

from __future__ import annotations

import streamlit as st

from fantasy_league_context import activate_league_context, get_active_league_context
from fantasy_league_lineup_format_ui import render_lineup_format_setup

_DEFAULTS = {
    "auth_user_id": "user:daniel",
    "workspace_id": "ws1",
    "draft_archive_teams": [],
    "fantasy_league_context_state": {"contexts": {}},
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

if "_lineup_workflow_ready" not in st.session_state:
    from fantasy_league_context import create_league_context_from_live_room
    from tests.live_draft_accelerated_harness import (
        accelerated_draft_patches,
        build_four_team_eight_round_room,
        expire_one_pick,
        seed_session,
    )

    room = build_four_team_eight_round_room(timer_seconds=5)
    session = seed_session(room)
    metrics = __import__(
        "tests.live_draft_accelerated_harness", fromlist=["DraftRunMetrics"]
    ).DraftRunMetrics()
    with accelerated_draft_patches():
        while str(room.get("status") or "") != "complete":
            expire_one_pick(session, room, metrics)
    ctx = create_league_context_from_live_room(
        st.session_state,
        room,
        my_team_name="Team A",
        league_name="Lineup Workflow League",
        source_draft_id=str(room.get("draft_room_id") or "LINEUP-WF"),
        persist=True,
    )
    activate_league_context(st.session_state, str(ctx.get("league_context_id") or ""))
    st.session_state["_lineup_workflow_ready"] = True
    st.session_state["_lineup_context_id"] = ctx.get("league_context_id")

context = get_active_league_context(st.session_state)
ready = render_lineup_format_setup(st, st.session_state, team_roster=None, editing=False)
st.write(f"FORMAT_READY={ready}")
st.write(f"CONTEXT_ID={st.session_state.get('_lineup_context_id')}")
if context:
    from fantasy_league_lineup_format import needs_lineup_format_setup

    st.write(f"NEEDS_SETUP={needs_lineup_format_setup(context)}")
