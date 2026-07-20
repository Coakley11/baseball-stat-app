"""Minimal Streamlit page: Solo Start Draft click path (rendered AppTest)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from draft_ui import on_start_new_live_draft
from live_draft_start_setup import (
    LIVE_DRAFT_SETUP_ERROR,
    peek_setup_validation_error,
)

_DEFAULTS = {
    "auth_user_id": "user:daniel",
    "workspace_id": "ws1",
    "_suite_active_workspace_id": "ws1",
    "live_draft_setup_mode": "solo",
    "live_draft_room": None,
    "live_draft_team_count": 2,
    "live_draft_picks_per_team": 4,
    "live_slot_c": 1,
    "live_slot_1b": 1,
    "live_slot_2b": 1,
    "live_slot_3b": 0,
    "live_slot_ss": 1,
    "live_slot_of": 1,
    "live_slot_dh": 0,
    "live_slot_p": 0,
    "live_slot_bench": 0,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

st.number_input("Picks per team", min_value=1, max_value=30, key="live_draft_picks_per_team")
st.number_input("C", min_value=0, max_value=3, key="live_slot_c")
st.number_input("1B", min_value=0, max_value=3, key="live_slot_1b")
st.number_input("2B", min_value=0, max_value=3, key="live_slot_2b")
st.number_input("3B", min_value=0, max_value=3, key="live_slot_3b")
st.number_input("SS", min_value=0, max_value=3, key="live_slot_ss")
st.number_input("OF", min_value=0, max_value=5, key="live_slot_of")
st.number_input("DH", min_value=0, max_value=3, key="live_slot_dh")
st.number_input("P", min_value=0, max_value=10, key="live_slot_p")
st.number_input("Bench", min_value=0, max_value=15, key="live_slot_bench")

# Mirror streamlit_app pending handler (solo create only — no shared / cloud).
if st.session_state.pop("_start_live_draft_pending", False):
    from live_draft_start_setup import fail_closed_setup_check, store_setup_validation_error

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
    check = fail_closed_setup_check(
        st.session_state, picks_per_team=picks, slots=slots, solo_mode=True
    )
    if not check.get("ok"):
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
                    "Model Rank": i + 1,
                    "Market Rank": i + 1,
                }
            )
        pool = pd.DataFrame(rows)
        config = {
            "league_name": "AppTest League",
            "num_teams": 2,
            "picks_per_team": picks,
            "teams": ["Team A", "Team B"],
            "user_team": "Team A",
            "your_team": "Team A",
            "slots": dict(check.get("slots_for_room") or slots),
            "timer_seconds": 60,
            "scoring_type": "Roto (5x5)",
            "fantasy_format": "5x5 Roto",
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
    st.write(f"PICKS_PER_TEAM={(room.get('config') or {}).get('picks_per_team')}")
    st.write(f"BN_SLOTS={((room.get('config') or {}).get('slots') or {}).get('BN')}")
    st.write(f"TIMER={room.get('timer_deadline') is not None}")
    order = room.get("pick_order") or []
    on_clock = str((order[0] or {}).get("Team") or "") if order else ""
    st.write(f"ON_CLOCK={on_clock}")
else:
    st.write("STATUS=setup")
