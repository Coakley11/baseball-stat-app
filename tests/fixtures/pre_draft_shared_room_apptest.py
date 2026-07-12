"""Minimal Streamlit app for AppTest — pre-draft Create Shared Draft Room."""

from __future__ import annotations

import streamlit as st

import pandas as pd

from live_draft_setup_mode import SETUP_MODE_SHARED, finalize_shared_room_create, set_live_draft_setup_mode, shared_room_code
from live_draft_setup_ui import render_shared_multiplayer_setup


def _build_not_started_room(team_names: list[str], *, host_team: str) -> dict:
    teams = [str(t).strip() for t in team_names if str(t).strip()]
    pick_order = [{"Pick": i + 1, "Round": 1, "Team": teams[i % len(teams)]} for i in range(len(teams))]
    pool = pd.DataFrame([{"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"}])
    return {
        "draft_room_id": "PREDRAFT1",
        "status": "not_started",
        "current_pick_index": 0,
        "config": {
            "num_teams": len(teams),
            "your_team": host_team,
            "user_team": host_team,
            "teams": teams,
            "draft_setup_mode": SETUP_MODE_SHARED,
        },
        "teams": teams,
        "pick_order": pick_order,
        "draft_board": [],
        "rosters": {t: [] for t in teams},
        "drafted_player_ids": [],
        "pool": pool,
    }


set_live_draft_setup_mode(st.session_state, SETUP_MODE_SHARED)

team_names = [
    str(st.session_state.get("live_draft_team_name_0") or "Daniel").strip() or "Daniel",
    str(st.session_state.get("live_draft_team_name_1") or "Team 2").strip() or "Team 2",
]

if st.session_state.pop("_start_live_draft_pending", False):
    mode = str(st.session_state.pop("_start_live_draft_mode", "") or "")
    if mode == "prepare_shared":
        host_team = str(st.session_state.get("room_your_team") or team_names[0]).strip() or team_names[0]
        room = _build_not_started_room(team_names, host_team=host_team)
        code, err = finalize_shared_room_create(st.session_state, room, host_team=host_team)
        if not code:
            st.error(err or "Could not create shared room.")
        else:
            st.session_state["live_draft_room"] = room
            st.success(f"JOIN_CODE_VISIBLE:{code}")

render_shared_multiplayer_setup(st, st.session_state, team_names=team_names)

code = shared_room_code(st.session_state)
if code:
    st.markdown(f"LOBBY_JOIN_CODE:{code}")
