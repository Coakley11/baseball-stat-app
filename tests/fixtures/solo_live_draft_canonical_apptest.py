"""Minimal rendered Solo Live Draft room: canonical pick/team + expire advance."""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from draft_actions import draft_action_context
from live_draft_canonical_snapshot import (
    apply_canonical_to_slot_views,
    format_canonical_diag_line,
)
from live_draft_on_clock_ui import render_live_on_clock_banner
from live_draft_solo_timer import expire_current_pick_and_advance, is_solo_live_draft
from live_draft_timer_logic import live_draft_current_slot, live_draft_reset_timer, live_draft_seconds_remaining

_DEFAULTS = {
    "auth_user_id": "user:daniel",
    "workspace_id": "ws1",
    "live_draft_setup_mode": "solo",
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

if "live_draft_room" not in st.session_state or not isinstance(st.session_state.get("live_draft_room"), dict):
    teams = ["Team A", "Team B"]
    pick_order = []
    pick_n = 1
    for rnd in range(1, 6):
        seq = teams if rnd % 2 == 1 else list(reversed(teams))
        for team in seq:
            pick_order.append({"Pick": pick_n, "Round": rnd, "Team": team})
            pick_n += 1
    pool = pd.DataFrame(
        [
            {
                "playerID": f"p{i}",
                "fullName": f"Player {i}",
                "Primary Position": "OF",
                "Expected Fantasy Value": 200 - i,
                "Decision Score": 100.0 - i,
                "Draft Fit Score": 90.0 - i,
            }
            for i in range(1, 60)
        ]
    )
    room = {
        "draft_room_id": "SOLO-RENDER-CANON",
        "status": "in_progress",
        "current_pick_index": 0,
        "teams": teams,
        "pick_order": pick_order,
        "draft_board": [],
        "drafted_player_ids": [],
        "rosters": {t: [] for t in teams},
        "revision": 1,
        "meta": {"sync": {"revision": 1}},
        "config": {
            "num_teams": 2,
            "picks_per_team": 5,
            "rounds": 5,
            "timer_seconds": 30,
            "teams": teams,
            "your_team": "Team A",
            "user_team": "Team A",
            "draft_setup_mode": "solo",
            "auto_pick_rule": "balanced recommendation",
            "queue_auto_pick": False,
        },
        "pool": pool,
    }
    live_draft_reset_timer(room)
    st.session_state["live_draft_room"] = room
    st.session_state["draft_queue"] = [f"Player {i}" for i in range(1, 12)]

room = st.session_state["live_draft_room"]
assert is_solo_live_draft(st.session_state, room)

canon = apply_canonical_to_slot_views(st.session_state, room, refresh=True)
ctx = draft_action_context(st.session_state)
slot = live_draft_current_slot(room)

st.subheader("Solo Live Draft — canonical sync")
st.caption(format_canonical_diag_line(canon))
st.markdown(
    f"**Sidebar context:** pick={ctx.get('current_pick')} · "
    f"team={ctx.get('on_clock_team')} · idx={ctx.get('current_pick_index')} · "
    f"rev={ctx.get('revision')}"
)
st.markdown(
    f"**Canonical:** pick={canon.get('current_pick')} · "
    f"team={canon.get('team_on_clock')} · idx={canon.get('current_pick_index')} · "
    f"rev={canon.get('revision')}"
)

if slot:
    render_live_on_clock_banner(st, st.session_state, room=room, slot=slot, next_pick=None)

st.metric("Board size", len(room.get("draft_board") or []))
st.metric("Seconds remaining", live_draft_seconds_remaining(room))
st.write("Queue:", st.session_state.get("draft_queue") or [])

if st.button("Force expire + auto-pick", key="solo_force_expire_btn"):
    room["timer_deadline"] = time.time() - 0.05
    result = expire_current_pick_and_advance(room, session=st.session_state)
    st.session_state["_last_expire_ok"] = bool(result.ok)
    st.session_state["_last_expire_committed"] = int(result.committed_picks or 0)
    st.session_state["_last_expire_team"] = str(result.team_on_clock or "")
    st.rerun()

if st.session_state.get("_last_expire_ok"):
    st.success(
        f"Advanced to pick #{st.session_state.get('_last_expire_committed')} · "
        f"on clock: {st.session_state.get('_last_expire_team')}"
    )
