"""Seeded, offline preview of the real Baseball Explorer app (CI and local).

    streamlit run ci/preview_app.py --server.headless true
    open ?mode=solo | ?mode=host, optionally &page=<sidebar page key> (e.g. Draft%20Strategy%20Assistant)

Synthetic data only: the seed is tests/live_draft_real_app_harness.py (fake players p001..). Rooms live
in a temporary local-file store (BASEBALL_SHARED_DRAFT_ROOM_BACKEND=local), never Supabase; no secrets
are read, and the workspace is fresh. BX_PREVIEW_REPO overrides the repo root (default: the parent of
this file's folder).
"""
import copy
import os
import runpy
import sys

REPO = os.environ.get("BX_PREVIEW_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
os.chdir(REPO)

import streamlit as st  # noqa: E402


@st.cache_resource
def _world():
    from tests import live_draft_real_app_harness as h
    from live_draft_pick_engine import live_draft_make_pick

    h.isolate_environment()
    solo = h.solo_seed()
    room = solo["live_draft_room"]
    pool = room["pool"]
    for pid in ("p001", "p002", "p003", "p004", "p005"):  # five picks: Team A, B, C, D, then D again
        ok, msg = live_draft_make_pick(room, pool[pool["playerID"] == pid].iloc[0].to_dict(), "Manual pick",
                                       enrich_pick_context=False)
        assert ok, msg
    code, host, _guest = h.shared_seeds()
    return {"solo": solo, "host": host, "code": code}


world = _world()
if "_bx_preview_seeded" not in st.session_state:
    mode = str(st.query_params.get("mode") or "solo")
    for key, value in copy.deepcopy(world["host" if mode == "host" else "solo"]).items():
        st.session_state[key] = value
    page = str(st.query_params.get("page") or "").strip()
    if page:
        st.session_state["_navigate_to_page"] = page
    st.session_state["_bx_preview_seeded"] = mode

runpy.run_path(os.path.join(REPO, "streamlit_app.py"), run_name="__main__")
