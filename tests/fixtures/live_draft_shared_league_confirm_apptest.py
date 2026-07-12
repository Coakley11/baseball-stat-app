"""AppTest fixture — completed Draft Complete panel + Create Shared League."""

from __future__ import annotations

import streamlit as st

import pandas as pd

from draft_archive_ui import render_live_draft_completion_panel
from live_draft_completion import apply_live_draft_completion


room = st.session_state.get("live_draft_test_room")
if not isinstance(room, dict):
    st.error("Missing test room")
    st.stop()

room = apply_live_draft_completion(dict(room), st.session_state)
render_live_draft_completion_panel(
    st,
    st.session_state,
    room,
    team_name=str(st.session_state.get("live_draft_test_team") or "Daniel"),
    board_df_fn=lambda draft_room: pd.DataFrame(draft_room.get("draft_board") or []),
)

if st.session_state.get("_live_draft_shared_league_confirm_open"):
    st.markdown("SHARED_LEAGUE_CONFIRM_OPEN:yes")

diag = st.session_state.get("_live_draft_shared_league_diag") or {}
if isinstance(diag, dict):
    st.markdown(f"SHARED_LEAGUE_DIAG_CALLBACK:{diag.get('shared_button_callback_count')}")
    if diag.get("confirmation_render_entered"):
        st.markdown("SHARED_LEAGUE_CONFIRM_RENDERED:yes")
    if diag.get("preview_call_completed"):
        st.markdown("SHARED_LEAGUE_PREVIEW_OK:yes")
