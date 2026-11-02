"""AppTest fixture: the Draft Control Center for a guest (not commissioner, may not auto-pick)."""

import streamlit as st

import live_draft_control_center_ui as cc

_commissioner = bool(st.session_state.get("_fixture_commissioner"))
cc._resolve_commissioner = lambda session: (_commissioner, None)  # noqa: E731
import shared_draft_permissions

shared_draft_permissions.participant_may_auto_pick = lambda *a, **k: _commissioner  # noqa: E731

room = st.session_state.setdefault(
    "_fixture_room", {"status": st.session_state.get("_fixture_status", "paused"), "draft_room_id": "R1"}
)
calls = st.session_state.setdefault("_fixture_calls", [])


def _persist(room_obj, reason):
    calls.append(("persist", reason, room_obj.get("status")))


import live_draft_autopick

live_draft_autopick.live_draft_auto_pick = lambda *a, **k: calls.append(("auto_pick",)) or (False, "fixture")  # noqa: E731
cc.render_live_draft_control_center(st, st.session_state, room, cfg={}, persist_room=_persist, show_heading=False)
