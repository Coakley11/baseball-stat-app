"""Rendered Solo Live Draft — mixed manual/auto/queue/control/nav operations."""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from draft_actions import draft_action_context, draft_status_summary
from draft_ui import render_draft_sidebar_status, render_live_draft_queue_panel
from live_draft_canonical_snapshot import (
    align_room_pick_index,
    apply_canonical_to_slot_views,
    begin_live_draft_paint,
    format_canonical_diag_line,
    get_live_draft_paint_snapshot,
    invalidate_live_draft_paint,
)
from live_draft_control_center_ui import render_live_draft_control_center
from live_draft_on_clock_ui import render_live_on_clock_banner
from live_draft_pick_commit import commit_live_draft_pick
from live_draft_solo_timer import expire_current_pick_and_advance, is_solo_live_draft
from live_draft_state import live_draft_get_available
from live_draft_timer_logic import live_draft_current_slot, live_draft_reset_timer, live_draft_seconds_remaining
from live_draft_ui_cache import REC_CACHE_KEY

_DEFAULTS = {
    "auth_user_id": "user:daniel",
    "workspace_id": "ws1",
    "live_draft_setup_mode": "solo",
    "active_page": "Live Draft Room",
    "_fp_sidebar_timer_skipped": True,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


def _noop_persist(room: dict, reason: str) -> None:
    del reason
    st.session_state["live_draft_room"] = room


if "live_draft_room" not in st.session_state or not isinstance(st.session_state.get("live_draft_room"), dict):
    teams = ["Team A", "Team B", "Team C", "Team D"]
    picks_per_team = 8
    pick_order = []
    pick_n = 1
    for rnd in range(1, picks_per_team + 1):
        seq = teams if rnd % 2 == 1 else list(reversed(teams))
        for team in seq:
            pick_order.append({"Pick": pick_n, "Round": rnd, "Team": team})
            pick_n += 1
    pool = pd.DataFrame(
        [
            {
                "playerID": f"p{i:03d}",
                "fullName": f"Player {i:03d}",
                "Primary Position": ["C", "1B", "2B", "3B", "SS", "OF", "DH", "UTIL"][i % 8],
                "Expected Fantasy Value": float(400 - i),
                "Decision Score": float(100.0 - (i % 40)),
                "Draft Fit Score": float(1.0 + (i % 10) * 0.05),
                "Positional Fit": float(0.75 + (i % 5) * 0.05),
            }
            for i in range(1, 120)
        ]
    )
    room = {
        "draft_room_id": "MIXED-MATRIX-4x8",
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
            "num_teams": 4,
            "picks_per_team": picks_per_team,
            "rounds": picks_per_team,
            "timer_seconds": 30,
            "teams": teams,
            "your_team": "Team A",
            "user_team": "Team A",
            "league_name": "Mixed Matrix League",
            "draft_setup_mode": "solo",
            "auto_pick_rule": "balanced recommendation",
            "queue_auto_pick": False,
            "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 0, "P": 0, "BN": 0},
        },
        "pool": pool,
    }
    live_draft_reset_timer(room)
    st.session_state["live_draft_room"] = room
    st.session_state["draft_queue"] = [f"Player {i:03d}" for i in range(10, 30)]
    st.session_state[REC_CACHE_KEY] = {
        "key": ("mixed_matrix",),
        "top_rec": pool.head(12).copy(),
        "best_avail": pool.head(12).copy(),
        "pos_fit": pool.head(8).copy(),
        "value_sleep": pool.head(8).copy(),
    }

room = st.session_state["live_draft_room"]
assert is_solo_live_draft(st.session_state, room)
apply_canonical_to_slot_views(st.session_state, room, refresh=True)
begin_live_draft_paint(st.session_state, room, state_source="mixed_matrix_fixture")

with st.sidebar:
    render_draft_sidebar_status(st, st.session_state)

paint = get_live_draft_paint_snapshot(st.session_state)
ctx = draft_action_context(st.session_state)
summary = draft_status_summary(st.session_state)
slot = live_draft_current_slot(room)
cfg = dict(room.get("config") or {})

st.markdown(f"## {cfg.get('league_name', 'League')}")
st.caption(
    f"Pick {paint.get('current_pick')} · On clock **{paint.get('team_on_clock')}** · "
    f"Sidebar pick={summary.get('pick')} team={summary.get('on_clock_team')} · "
    f"Context pick={ctx.get('current_pick')} team={ctx.get('on_clock_team')}"
)
st.caption(format_canonical_diag_line(paint))

if slot:
    render_live_on_clock_banner(st, st.session_state, room=room, slot=slot, next_pick=None)

st.metric("Timer seconds", live_draft_seconds_remaining(room))
st.metric("Board size", len(room.get("draft_board") or []))

render_live_draft_control_center(
    st,
    st.session_state,
    room,
    cfg=cfg,
    persist_room=_noop_persist,
    show_heading=True,
)

st.markdown("### Draft Queue")
render_live_draft_queue_panel(st, st.session_state)

st.markdown("### Matrix harness controls")
mc1, mc2, mc3 = st.columns(3)
with mc1:
    if st.button("Manual pick", key="matrix_manual_pick"):
        room = st.session_state["live_draft_room"]
        available = live_draft_get_available(room)
        row = available.iloc[0].to_dict()
        result = commit_live_draft_pick(
            st.session_state, room, row, source="matrix_manual", fast_path=True
        )
        st.session_state["_matrix_manual_ok"] = bool(result.ok)
        align_room_pick_index(room)
        invalidate_live_draft_paint(st.session_state)
        apply_canonical_to_slot_views(st.session_state, room, refresh=True)
        begin_live_draft_paint(st.session_state, room, state_source="matrix_after_manual")
        st.rerun()
with mc2:
    if st.button("Queue add front", key="matrix_queue_add"):
        st.session_state.setdefault("draft_queue", []).insert(0, "Player 057")
        st.rerun()
with mc3:
    if st.button("Queue remove head", key="matrix_queue_remove"):
        q = list(st.session_state.get("draft_queue") or [])
        if q:
            st.session_state["draft_queue"] = q[1:]
        st.rerun()

mc4, mc5, mc6 = st.columns(3)
with mc4:
    if st.button("Queue swap top two", key="matrix_queue_reorder"):
        q = list(st.session_state.get("draft_queue") or [])
        if len(q) >= 2:
            q[0], q[1] = q[1], q[0]
            st.session_state["draft_queue"] = q
        st.rerun()
with mc5:
    if st.button("Nav away", key="matrix_nav_away"):
        st.session_state["active_page"] = "Draft Assistant"
        invalidate_live_draft_paint(st.session_state)
        st.rerun()
with mc6:
    if st.button("Nav back", key="matrix_nav_back"):
        st.session_state["active_page"] = "Live Draft Room"
        room = st.session_state["live_draft_room"]
        begin_live_draft_paint(st.session_state, room, state_source="matrix_nav_return")
        st.rerun()

if st.button("Force expire", key="matrix_force_expire"):
    room = st.session_state["live_draft_room"]
    align_room_pick_index(room)
    room["timer_deadline"] = time.time() - 0.05
    result = expire_current_pick_and_advance(room, session=st.session_state)
    st.session_state["_matrix_expire_ok"] = bool(result.ok)
    st.session_state["_matrix_board"] = len(room.get("draft_board") or [])
    align_room_pick_index(room)
    st.session_state["live_draft_room"] = room
    invalidate_live_draft_paint(st.session_state)
    apply_canonical_to_slot_views(st.session_state, room, refresh=True)
    begin_live_draft_paint(st.session_state, room, state_source="matrix_after_expire")
    st.rerun()

if st.session_state.get("_matrix_expire_ok") or st.session_state.get("_matrix_manual_ok"):
    paint2 = get_live_draft_paint_snapshot(st.session_state)
    st.success(
        f"Pick committed · board={len(room.get('draft_board') or [])} · "
        f"paint pick={paint2.get('current_pick')} team={paint2.get('team_on_clock')}"
    )
