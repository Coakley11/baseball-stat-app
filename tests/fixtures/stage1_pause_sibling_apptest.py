"""AppTest: Control Center with pause-sibling probe."""

import streamlit as st

from live_draft_control_center_ui import render_live_draft_control_center

st.session_state["_solo_component_diag_enabled"] = True
st.session_state["_solo_stage1_script_run_seq"] = 4
room = {
    "draft_room_id": "APPSIB01",
    "status": "in_progress",
    "current_pick_index": 0,
}


def _persist(r, _reason):
    pass


render_live_draft_control_center(
    st,
    st.session_state,
    room,
    cfg={"timer_seconds": 60},
    persist_room=_persist,
)
