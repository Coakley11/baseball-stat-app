"""Minimal Streamlit app: Add-to-Queue server-consumption boundary (local proof only)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY, render_deferred_heavy_paint_fragment
from live_draft_rec_live_paint import (
    INTERACTIVE_PAINT_STATUS_KEY,
    PREPARED_REC_INTERACTIVE_KEY,
    _top_rec_from_cache,
    store_prepared_rec_interactive,
)
from live_draft_rec_queue_click_trace import (
    build_rec_card_queue_widget_key,
    lifecycle_for_widget,
    note_rec_queue_widget_button_rendered,
)
from live_draft_room_ui import execute_rec_card_queue_click
from live_draft_ui_cache import REC_CACHE_KEY, invalidate_live_draft_ui_caches

ROOM_ID = "77DAD3EE"
PLAYERS = [
    ("231", "Francisco Lindor"),
    ("414", "Ketel Marte"),
    ("592", "Jose Ramirez"),
]


def _df_for(player_id: str, name: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fullName": name,
                "Primary Position": "SS",
                "playerID": player_id,
                "Fantasy Edge": 1.0,
                "Survival Probability": 0.5,
                "Decision Score": 90.0,
            }
        ]
    )


def _ensure_session() -> None:
    ss = st.session_state
    ss.setdefault("draft_queue", [])
    ss.setdefault("_solo_stage1_script_run_seq", 0)
    ss["_solo_stage1_script_run_seq"] = int(ss.get("_solo_stage1_script_run_seq") or 0) + 1
    ss.setdefault("_proof_player_idx", 0)
    ss.setdefault(HEAVY_PAINT_DONE_KEY, True)
    ss["_live_draft_rec_queue_interactive_owner"] = "script_run_no_run_every"
    ss["_solo_stage1_last_recommendation_paint"] = {"via": "full_page_interactive_live"}


def _current_player() -> tuple[str, str]:
    idx = int(st.session_state.get("_proof_player_idx") or 0) % len(PLAYERS)
    return PLAYERS[idx]


def _room() -> dict:
    pid, name = _current_player()
    return {
        "draft_room_id": ROOM_ID,
        "current_pick_index": 0,
        "status": "in_progress",
        "config": {"user_team": "Team A"},
        "draft_board": [],
        "rosters": {},
        "pool": _df_for(pid, name),
    }


def _paint_body() -> None:
    pid, name = _current_player()
    store_prepared_rec_interactive(
        st.session_state,
        room_id=ROOM_ID,
        gaps=[],
        category_needs=[],
        max_cards=1,
    )
    st.session_state[REC_CACHE_KEY] = {"top_rec": _df_for(pid, name)}


def _paint_interactive() -> bool:
    """Mirrors render_rec_interactive_widgets cache/rebuild gate, then one product button."""
    status: dict = {
        "ok": False,
        "fail_reason": "",
        "cache_rebuilt": False,
        "script_run_seq": int(st.session_state.get("_solo_stage1_script_run_seq") or 0),
    }
    prep = st.session_state.get(PREPARED_REC_INTERACTIVE_KEY)
    if not isinstance(prep, dict):
        status["fail_reason"] = "prepared_interactive_missing"
        st.session_state[INTERACTIVE_PAINT_STATUS_KEY] = status
        return False
    top = _top_rec_from_cache(st.session_state)
    if top is None or getattr(top, "empty", True):
        # Production path: rebuild (or fall back via heavy_paint). For AppTest we rebuild
        # from the current proof player without calling live_draft_recommendations.
        pid, name = _current_player()
        st.session_state[REC_CACHE_KEY] = {"top_rec": _df_for(pid, name), "rebuilt_for_interactive": True}
        status["cache_rebuilt"] = True
        top = _top_rec_from_cache(st.session_state)
        if top is None or getattr(top, "empty", True):
            status["fail_reason"] = "top_rec_missing_after_rebuild"
            st.session_state[INTERACTIVE_PAINT_STATUS_KEY] = status
            return False
    pid, name = _current_player()
    key = build_rec_card_queue_widget_key(
        room_id=ROOM_ID, pick_index=0, stable_key=pid, surface="rec_card"
    )
    clicked = st.button("⭐ Add to Queue", key=key, use_container_width=True)
    note_rec_queue_widget_button_rendered(
        st.session_state, widget_key=key, dispatch_kind="button_return_value"
    )
    status["ok"] = True
    st.session_state[INTERACTIVE_PAINT_STATUS_KEY] = status
    st.session_state["_proof_last_button"] = {
        "user_key": key,
        "player_id": pid,
        "script_run_seq": int(st.session_state.get("_solo_stage1_script_run_seq") or 0),
        "button_return_value": bool(clicked),
        "paint_status": dict(status),
    }
    if clicked:
        execute_rec_card_queue_click(
            st.session_state,
            name=name,
            event_id=f"localproof_{pid}",
            widget_key=key,
            room_id=ROOM_ID,
            pick_idx=0,
            player_id=pid,
        )
        st.session_state["_proof_player_idx"] = int(st.session_state.get("_proof_player_idx") or 0) + 1
    return True


def main() -> None:
    _ensure_session()
    # Simulate production invalidate after HEAVY_PAINT_DONE (poll/deferred pool).
    if st.session_state.pop("_proof_force_cache_miss", None):
        invalidate_live_draft_ui_caches(st.session_state)
    # Keep prep so interactive can rebuild (matches production: prep survives invalidate).
    if not isinstance(st.session_state.get(PREPARED_REC_INTERACTIVE_KEY), dict):
        store_prepared_rec_interactive(
            st.session_state, room_id=ROOM_ID, gaps=[], category_needs=[], max_cards=1
        )
    render_deferred_heavy_paint_fragment(
        st,
        st.session_state,
        _paint_body,
        paint_interactive=_paint_interactive,
    )
    last = st.session_state.get("_proof_last_button") or {}
    key = str(last.get("user_key") or "")
    lc = lifecycle_for_widget(st.session_state, key) if key else {}
    st.session_state["_proof_snapshot"] = {
        "seq": st.session_state.get("_solo_stage1_script_run_seq"),
        "queue": list(st.session_state.get("draft_queue") or []),
        "last_button": last,
        "lifecycle_seq": lc.get("widget_last_rendered_run_seq"),
        "fallback_ok": st.session_state.get("_live_draft_rec_interactive_fallback_ok"),
        "cache_present": isinstance(st.session_state.get(REC_CACHE_KEY), dict),
        "incoming_id_stable_user_key": key,
    }


main()
