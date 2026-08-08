"""AppTest: context isolation C0 top-level callback."""

import streamlit as st

from live_draft_stage1_fragment_context_isolation import render_stage1_fragment_context_isolation

st.session_state["_solo_component_diag_enabled"] = True
render_stage1_fragment_context_isolation(st, st.session_state, "APPTESTCTX")
