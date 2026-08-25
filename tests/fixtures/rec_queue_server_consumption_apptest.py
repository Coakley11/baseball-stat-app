"""Production-equivalent ScriptRun sequencing for Add-to-Queue same-run consumption.

Mirrors the proven 19ea13e failure mode:

  run 21: register Add-to-Queue (DONE + interactive)
  end of run: invalidate REC_CACHE like deferred full-pool (keep interactive snapshot)
  run 22: button trigger must be consumed on THIS run — not deferred to run 23
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY, render_deferred_heavy_paint_fragment
from live_draft_rec_live_paint import (
    INTERACTIVE_PAINT_STATUS_KEY,
    INTERACTIVE_TOP_REC_SNAPSHOT_KEY,
    PREPARED_REC_INTERACTIVE_KEY,
    RUN_STAGE_LEDGER_KEY,
    render_rec_interactive_widgets,
    store_interactive_top_rec_snapshot,
    store_prepared_rec_interactive,
)
from live_draft_rec_queue_click_trace import (
    build_rec_card_queue_widget_key,
    lifecycle_for_widget,
)
from live_draft_ui_cache import REC_CACHE_KEY, invalidate_live_draft_ui_caches

ROOM_ID = "CBA003B1"
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
    ss.setdefault("_solo_stage1_script_run_seq", 20)
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
        "status": "paused",
        "config": {"user_team": "Team A", "your_team": "Team A"},
        "draft_board": [],
        "rosters": {"Team A": []},
        "pool": _df_for(pid, name),
        "teams": ["Team A"],
        "pick_order": [{"Team": "Team A", "Pick": 1, "Round": 1}],
    }


def _seed_prepared_and_cache() -> None:
    """Populate prep + cache + snapshot like a successful prior heavy/interactive paint."""
    pid, name = _current_player()
    top = _df_for(pid, name)
    store_prepared_rec_interactive(
        st.session_state,
        room_id=ROOM_ID,
        gaps=[],
        category_needs=[],
        max_cards=1,
    )
    st.session_state[REC_CACHE_KEY] = {"top_rec": top, "key": "proof"}
    store_interactive_top_rec_snapshot(st.session_state, top, room_id=ROOM_ID)


def _paint_body() -> None:
    """Fallback paint_body: restore prep/cache/snapshot only (no st.button)."""
    _seed_prepared_and_cache()


def _paint_interactive() -> bool:
    """Real product interactive registrar (not a fake button path)."""
    room = _room()
    ok = render_rec_interactive_widgets(st, st.session_state, room)
    pid, name = _current_player()
    key = build_rec_card_queue_widget_key(
        room_id=ROOM_ID, pick_index=0, stable_key=pid, surface="rec_card"
    )
    status = dict(st.session_state.get(INTERACTIVE_PAINT_STATUS_KEY) or {})
    # Capture whether the product path registered the target key this run.
    buttons = []
    try:
        # AppTest inspects widgets after run; here we stamp intent from session registry.
        reg = st.session_state.get("_live_draft_rec_queue_render_registry") or []
        buttons = [
            r
            for r in reg
            if isinstance(r, dict) and str(r.get("widget_key") or "") == key
        ]
    except Exception:
        buttons = []
    lc = lifecycle_for_widget(st.session_state, key) if key else {}
    # Detect button return via dispatch / queue growth stamped by product path.
    q = list(st.session_state.get("draft_queue") or [])
    clicked = any(str(x).lower().find(name.split()[-1].lower()) >= 0 for x in q)
    # Prefer explicit consumption diag if present.
    cons = st.session_state.get("_live_draft_rec_button_consumption_last") or {}
    if cons.get("widget_key") == key:
        clicked = bool(cons.get("button_return_value")) or clicked
    st.session_state["_proof_last_button"] = {
        "user_key": key,
        "player_id": pid,
        "player_name": name,
        "script_run_seq": int(st.session_state.get("_solo_stage1_script_run_seq") or 0),
        "interactive_ok": bool(ok),
        "paint_status": status,
        "registry_hit": bool(buttons),
        "lifecycle_seq": lc.get("widget_last_rendered_run_seq"),
        "button_return_value": bool(clicked),
    }
    if ok and clicked:
        st.session_state["_proof_player_idx"] = int(st.session_state.get("_proof_player_idx") or 0) + 1
        # Advance proof player cards after successful queue add (next distinct player).
        _seed_prepared_and_cache()
    return bool(ok)


def main() -> None:
    _ensure_session()
    seq = int(st.session_state.get("_solo_stage1_script_run_seq") or 0)

    # First boot (run 21 equivalent): seed state then register via real interactive path.
    if not isinstance(st.session_state.get(PREPARED_REC_INTERACTIVE_KEY), dict):
        _seed_prepared_and_cache()

    # Production deferred-pool / poll invalidate AFTER a successful registration run:
    # clear REC_CACHE but keep interactive snapshot when DONE (new policy).
    force_hard = bool(st.session_state.pop("_proof_force_hard_cache_and_snapshot_miss", None))
    force_soft = bool(st.session_state.pop("_proof_force_cache_miss", None))
    if force_hard:
        invalidate_live_draft_ui_caches(st.session_state, keep_interactive_snapshot=False)
        st.session_state.pop(INTERACTIVE_TOP_REC_SNAPSHOT_KEY, None)
        st.session_state["_proof_invalidated_on_seq"] = seq
        # Still keep prep so rebuild/fallback can run (matches production invalidate).
        if not isinstance(st.session_state.get(PREPARED_REC_INTERACTIVE_KEY), dict):
            store_prepared_rec_interactive(
                st.session_state, room_id=ROOM_ID, gaps=[], category_needs=[], max_cards=1
            )
    elif force_soft:
        invalidate_live_draft_ui_caches(
            st.session_state,
            keep_interactive_snapshot=bool(st.session_state.get(HEAVY_PAINT_DONE_KEY)),
        )
        st.session_state["_proof_invalidated_on_seq"] = seq

    render_deferred_heavy_paint_fragment(
        st,
        st.session_state,
        _paint_body,
        paint_interactive=_paint_interactive,
    )

    last = st.session_state.get("_proof_last_button") or {}
    key = str(last.get("user_key") or "")
    lc = lifecycle_for_widget(st.session_state, key) if key else {}
    stages = [
        r.get("stage")
        for r in (st.session_state.get(RUN_STAGE_LEDGER_KEY) or [])
        if isinstance(r, dict) and int(r.get("run_seq") or 0) == seq
    ]
    st.session_state["_proof_snapshot"] = {
        "seq": seq,
        "queue": list(st.session_state.get("draft_queue") or []),
        "last_button": last,
        "lifecycle_seq": lc.get("widget_last_rendered_run_seq"),
        "fallback_ok": st.session_state.get("_live_draft_rec_interactive_fallback_ok"),
        "cache_present": isinstance(st.session_state.get(REC_CACHE_KEY), dict),
        "snapshot_present": isinstance(st.session_state.get(INTERACTIVE_TOP_REC_SNAPSHOT_KEY), dict),
        "stages_this_run": stages,
        "paint_status": dict(st.session_state.get(INTERACTIVE_PAINT_STATUS_KEY) or {}),
        "incoming_id_stable_user_key": key,
    }


main()
