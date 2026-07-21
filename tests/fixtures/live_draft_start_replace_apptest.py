"""Start Draft validation — shared mode + replace resumable (rendered AppTest)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from draft_ui import on_start_new_live_draft
from live_draft_setup_mode import SETUP_MODE_SHARED, SETUP_MODE_SOLO
from live_draft_start_setup import LIVE_DRAFT_SETUP_ERROR, fail_closed_setup_check, peek_setup_validation_error

_DEFAULTS = {
    "auth_user_id": "user:daniel",
    "workspace_id": "ws1",
    "_suite_active_workspace_id": "ws1",
    "live_draft_setup_mode": SETUP_MODE_SOLO,
    "live_draft_room": None,
    "live_draft_team_count": 2,
    "live_draft_picks_per_team": 5,
    "live_slot_c": 1,
    "live_slot_1b": 1,
    "live_slot_2b": 1,
    "live_slot_3b": 0,
    "live_slot_ss": 1,
    "live_slot_of": 1,
    "live_slot_dh": 0,
    "live_slot_p": 0,
    "live_slot_bench": 0,
    "active_shared_draft_room_code": "",
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

mode = str(st.session_state.get("live_draft_setup_mode") or SETUP_MODE_SOLO)
st.caption(f"Draft mode: **{mode}**")

st.number_input("Picks per team", min_value=1, max_value=30, key="live_draft_picks_per_team")
st.number_input("Bench", min_value=0, max_value=15, key="live_slot_bench")

if st.session_state.get("_live_draft_start_replace_resumable_pending"):
    st.warning(
        str(
            st.session_state.get("_live_draft_start_replace_resumable_message")
            or "Disregard the saved draft and start a new draft?"
        )
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "Disregard Saved Draft and Start New",
            key="live_draft_start_replace_confirm_btn",
            type="primary",
        ):
            st.session_state.pop("_live_draft_start_replace_resumable_pending", None)
            st.session_state.pop("_live_draft_start_replace_resumable_message", None)
            from live_draft_resumable_ops import execute_replace_transactional

            result = execute_replace_transactional(st.session_state, st=st)
            st.session_state["_replace_result_ok"] = bool(result.get("ok"))
            st.session_state["_replace_result_mode"] = str(result.get("mode") or "")
    with c2:
        if st.button("Cancel", key="live_draft_start_replace_cancel_btn"):
            st.session_state.pop("_live_draft_start_replace_resumable_pending", None)
            st.session_state.pop("_live_draft_start_replace_resumable_message", None)

if st.session_state.pop("_start_live_draft_pending", False):
    picks = int(st.session_state.get("live_draft_picks_per_team") or 0)
    slots = {
        "C": int(st.session_state.get("live_slot_c") or 0),
        "1B": int(st.session_state.get("live_slot_1b") or 0),
        "2B": int(st.session_state.get("live_slot_2b") or 0),
        "3B": int(st.session_state.get("live_slot_3b") or 0),
        "SS": int(st.session_state.get("live_slot_ss") or 0),
        "OF": int(st.session_state.get("live_slot_of") or 0),
        "DH": int(st.session_state.get("live_slot_dh") or 0),
        "P": int(st.session_state.get("live_slot_p") or 0),
        "BN": int(st.session_state.get("live_slot_bench") or 0),
    }
    solo_mode = str(st.session_state.get("live_draft_setup_mode") or SETUP_MODE_SOLO) != SETUP_MODE_SHARED
    check = fail_closed_setup_check(
        st.session_state, picks_per_team=picks, slots=slots, solo_mode=solo_mode
    )
    if not check.get("ok"):
        from live_draft_start_setup import store_setup_validation_error

        store_setup_validation_error(
            st.session_state, str(check.get("error") or LIVE_DRAFT_SETUP_ERROR)
        )
    else:
        rows = []
        for i in range(40):
            rows.append(
                {
                    "playerID": f"p{i}",
                    "fullName": f"Player {i}",
                    "Primary Position": ["C", "1B", "2B", "3B", "SS", "OF"][i % 6],
                    "Expected Fantasy Value": float(100 - i),
                }
            )
        pool = pd.DataFrame(rows)
        config = {
            "league_name": "Replace AppTest League",
            "num_teams": 2,
            "picks_per_team": picks,
            "teams": ["Team A", "Team B"],
            "user_team": "Team A",
            "your_team": "Team A",
            "slots": dict(check.get("slots_for_room") or slots),
            "timer_seconds": 60,
            "draft_setup_mode": str(st.session_state.get("live_draft_setup_mode") or SETUP_MODE_SOLO),
        }
        try:
            from live_draft_roster_slots import freeze_slot_instances_on_config

            config = freeze_slot_instances_on_config(config)
        except ImportError:
            pass
        from streamlit_app import live_draft_init_room, live_draft_start

        room = live_draft_init_room(config, pool)
        live_draft_start(room)
        st.session_state["live_draft_room"] = room
        st.session_state["_start_result_mode"] = str(config.get("draft_setup_mode") or "")

st.button(
    "Start New Live Draft",
    key="live_draft_start_btn",
    on_click=on_start_new_live_draft,
)

_err = peek_setup_validation_error(st.session_state)
if _err:
    st.error(_err)

room = st.session_state.get("live_draft_room")
if isinstance(room, dict):
    st.write(f"STATUS={room.get('status')}")
    st.write(f"MODE={(room.get('config') or {}).get('draft_setup_mode')}")
    st.write(f"BN={(room.get('config') or {}).get('slots', {}).get('BN')}")
else:
    st.write("STATUS=setup")
    if st.session_state.get("_live_draft_start_replace_resumable_pending"):
        st.write("REPLACE_PENDING=1")
