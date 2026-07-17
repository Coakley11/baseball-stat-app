"""Minimal Streamlit page for AppTest Draft Mode lifecycle + guest join."""

import streamlit as st

from live_draft_setup_mode import SETUP_MODE_SHARED, get_live_draft_setup_mode
from live_draft_setup_ui import render_guest_join_from_setup, render_live_draft_mode_selector
from user_page_preferences import (
    ensure_live_draft_setup_preferences_loaded,
    reset_live_draft_setup_to_defaults,
)

if "auth_user_id" not in st.session_state:
    st.session_state["auth_user_id"] = "user:daniel"
    st.session_state["workspace_id"] = "ws1"
    st.session_state["_suite_active_workspace_id"] = "ws1"
    st.session_state["page_filter_state"] = {
        "_user_page_preferences": {
            "live_draft_setup": {
                "user_id": "user:daniel",
                "workspace_id": "ws1",
                "settings": {"live_draft_setup_mode": "solo"},
            }
        }
    }
    st.session_state["live_draft_room"] = {
        "status": "not_started",
        "config": {"draft_setup_mode": "solo"},
    }

ensure_live_draft_setup_preferences_loaded(st.session_state)
mode = render_live_draft_mode_selector(st, st.session_state)

# Same order as streamlit_app Live Draft setup — must not mutate widget key.
joined_rerun = render_guest_join_from_setup(st, st.session_state)
if joined_rerun:
    st.rerun()

if mode == SETUP_MODE_SHARED:
    st.write("GUEST_JOIN_SECTION=visible")
    st.text_input("Room code", key="live_draft_join_code_input")
else:
    st.write("GUEST_JOIN_SECTION=hidden")

if st.button("Simulate Reset Setup", key="apptest_reset_setup"):
    reset_live_draft_setup_to_defaults(st.session_state, st=st)
    st.rerun()

st.write(f"ACTIVE_MODE={get_live_draft_setup_mode(st.session_state)}")
st.write(f"SESSION_MODE={st.session_state.get('live_draft_setup_mode')}")
