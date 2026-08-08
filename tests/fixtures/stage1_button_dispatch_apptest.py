"""AppTest fixture — button dispatch probe only."""

import streamlit as st

from live_draft_stage1_button_dispatch_probe import render_stage1_button_dispatch_probe

st.session_state["_solo_component_diag_enabled"] = True
st.session_state["_solo_stage1_script_run_seq"] = 3
render_stage1_button_dispatch_probe(st, st.session_state, "APPTESTDSP")
