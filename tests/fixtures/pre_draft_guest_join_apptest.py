"""Minimal Streamlit app for AppTest — pre-draft guest Join Room one-click."""

from __future__ import annotations

import streamlit as st

from live_draft_setup_mode import SETUP_MODE_SHARED, set_live_draft_setup_mode
from live_draft_setup_ui import (
    render_guest_join_from_setup,
    render_guest_join_with_team_claim,
    render_join_attempt_feedback,
)


set_live_draft_setup_mode(st.session_state, SETUP_MODE_SHARED)

if render_guest_join_from_setup(st, st.session_state):
    st.rerun()

render_join_attempt_feedback(st, st.session_state)
render_guest_join_with_team_claim(st, st.session_state)

room = st.session_state.get("live_draft_room")
if isinstance(room, dict):
    st.markdown(f"GUEST_ROOM_ID:{room.get('draft_room_id')}")

code = str(st.session_state.get("active_shared_draft_room_code") or "").strip().upper()
if code:
    st.markdown(f"GUEST_ACTIVE_CODE:{code}")

team = str(
    st.session_state.get("draft_room_participant_team")
    or st.session_state.get("room_your_team")
    or ""
).strip()
if team:
    st.markdown(f"GUEST_TEAM:{team}")
