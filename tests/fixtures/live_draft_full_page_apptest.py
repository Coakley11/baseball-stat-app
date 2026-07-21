"""Full rendered Solo Live Draft page — real component order, no conflicting mocks."""

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
from live_draft_solo_timer import expire_current_pick_and_advance, is_solo_live_draft
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
        "draft_room_id": "FULL-PAGE-4x8",
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
            "league_name": "Full Page Test League",
            "draft_setup_mode": "solo",
            "auto_pick_rule": "balanced recommendation",
            "queue_auto_pick": False,
            "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 0, "P": 0, "BN": 0},
        },
        "pool": pool,
    }
    live_draft_reset_timer(room)
    st.session_state["live_draft_room"] = room
    st.session_state["draft_queue"] = [f"Player {i:03d}" for i in range(5, 20)]
    st.session_state[REC_CACHE_KEY] = {
        "key": ("full_page",),
        "top_rec": pool.head(12).copy(),
        "best_avail": pool.head(12).copy(),
        "pos_fit": pool.head(8).copy(),
        "value_sleep": pool.head(8).copy(),
    }

room = st.session_state["live_draft_room"]
assert is_solo_live_draft(st.session_state, room)
apply_canonical_to_slot_views(st.session_state, room, refresh=True)
begin_live_draft_paint(st.session_state, room, state_source="full_page_fixture")

with st.sidebar:
    st.markdown("### Workflow sidebar")
    sidebar_summary = render_draft_sidebar_status(st, st.session_state)

paint = get_live_draft_paint_snapshot(st.session_state)
ctx = draft_action_context(st.session_state)
summary = draft_status_summary(st.session_state)
slot = live_draft_current_slot(room)
cfg = dict(room.get("config") or {})

st.markdown(f"## {cfg.get('league_name', 'League')}")
_hdr_pick = paint.get("current_pick")
_hdr_team = paint.get("team_on_clock")
_hdr_round = paint.get("round")
st.caption(
    f"Header: Pick {_hdr_pick} · Round {_hdr_round} · On clock **{_hdr_team}** · "
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

st.markdown("### Recommendations")
_rec = st.session_state.get(REC_CACHE_KEY) or {}
_top = _rec.get("top_rec")
if isinstance(_top, pd.DataFrame) and not _top.empty:
    st.dataframe(_top[["fullName", "Decision Score"]].head(6), use_container_width=True)
else:
    st.caption("No recommendations cached.")

st.markdown("### Roster needs")
st.caption(f"Tracking **{cfg.get('your_team')}** — gaps computed from live roster.")

st.markdown("### Draft board")
_board = room.get("draft_board") or []
if _board:
    st.write(f"Last pick: {_board[-1].get('fullName')} ({_board[-1].get('Team')})")
else:
    st.caption("No picks yet.")

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Force expire", key="full_page_force_expire"):
        room = st.session_state["live_draft_room"]
        align_room_pick_index(room)
        room["timer_deadline"] = time.time() - 0.05
        result = expire_current_pick_and_advance(room, session=st.session_state)
        st.session_state["_fp_expire_ok"] = bool(result.ok)
        st.session_state["_fp_expire_reason"] = str(getattr(result, "reason", "") or "")
        st.session_state["_fp_expire_msg"] = str(getattr(result, "message", "") or "")
        st.session_state["_fp_autopick_msg"] = str(st.session_state.get("_live_draft_last_auto_pick_idempotency_key") or "")
        st.session_state["_fp_board"] = len(room.get("draft_board") or [])
        align_room_pick_index(room)
        st.session_state["live_draft_room"] = room
        invalidate_live_draft_paint(st.session_state)
        apply_canonical_to_slot_views(st.session_state, room, refresh=True)
        begin_live_draft_paint(st.session_state, room, state_source="full_page_after_expire")
        st.rerun()
with col2:
    if st.button("Pause draft", key="full_page_pause"):
        from live_draft_timer_logic import live_draft_pause_timer

        live_draft_pause_timer(room)
        st.session_state["_fp_paused"] = True
        st.rerun()
with col3:
    if st.button("Reset timer", key="full_page_reset_timer"):
        live_draft_reset_timer(room)
        st.session_state["_fp_reset"] = True
        st.rerun()

if st.session_state.get("_fp_expire_ok"):
    paint2 = get_live_draft_paint_snapshot(st.session_state)
    st.success(
        f"Pick committed · board={st.session_state.get('_fp_board')} · "
        f"paint pick={paint2.get('current_pick')} team={paint2.get('team_on_clock')}"
    )
