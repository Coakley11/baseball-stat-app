"""Minimal Streamlit page for AppTest Draft Mode snap-back reproduction."""

import streamlit as st

from live_draft_setup_ui import render_live_draft_mode_selector
from user_page_preferences import ensure_live_draft_setup_preferences_loaded

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
st.write(f"ACTIVE_MODE={mode}")
st.write(f"SESSION_MODE={st.session_state.get('live_draft_setup_mode')}")
