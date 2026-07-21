"""Bench=0 preference persistence — rendered save + reload."""

from __future__ import annotations

import streamlit as st

from user_page_preferences import (
    ensure_live_draft_setup_preferences_loaded,
    live_draft_setup_number_default,
    persist_live_draft_setup_preferences,
)

_DEFAULTS = {
    "auth_user_id": "user:daniel",
    "workspace_id": "ws1",
    "_suite_active_workspace_id": "ws1",
    "live_draft_picks_per_team": 5,
    "live_slot_c": 1,
    "live_slot_1b": 1,
    "live_slot_2b": 1,
    "live_slot_3b": 1,
    "live_slot_ss": 1,
    "live_slot_of": 3,
    "live_slot_dh": 0,
    "live_slot_p": 0,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

st.number_input("Bench", min_value=0, max_value=15, key="live_slot_bench")
st.write(f"DEFAULT_BENCH={live_draft_setup_number_default(st.session_state, 'live_slot_bench', 5)}")

if st.button("Save setup prefs", key="bench_save_prefs"):
    persist_live_draft_setup_preferences(st.session_state, force_disk=False)
    st.session_state["_bench_saved"] = True

if st.button("Simulate fresh session reload", key="bench_reload_prefs"):
    st.session_state.pop("live_slot_bench", None)
    st.session_state.pop("_user_page_preferences_initialized", None)
    for key in list(st.session_state.keys()):
        if str(key).startswith("_user_page_preferences_initialized:"):
            st.session_state.pop(key, None)
    ensure_live_draft_setup_preferences_loaded(st.session_state)
    st.session_state["_bench_reloaded_value"] = live_draft_setup_number_default(
        st.session_state, "live_slot_bench", 5
    )

st.write(f"BENCH_WIDGET={st.session_state.get('live_slot_bench')}")
if "_bench_reloaded_value" in st.session_state:
    st.write(f"BENCH_AFTER_RELOAD={st.session_state.get('_bench_reloaded_value')}")
