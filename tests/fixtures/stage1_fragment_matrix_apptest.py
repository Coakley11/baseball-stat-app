"""Minimal AppTest page — Stage1 fragment identity matrix S0–D1."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Fragment matrix AppTest", layout="wide")
st.session_state["_solo_component_diag_enabled"] = True
st.session_state["_solo_stage1_script_run_seq"] = 1

from live_draft_stage1_fragment_identity_matrix import render_stage1_fragment_identity_matrix

render_stage1_fragment_identity_matrix(st, st.session_state, "APPTEST1")
