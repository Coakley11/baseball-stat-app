"""Regression tests for production component return binding (S9C / BIND5)."""

from __future__ import annotations

from unittest import mock

from live_draft_component_binding_trace import (
    PRODUCTION_PERSISTENT_KEY,
    declaration_count_this_run,
    peek_trace,
    record_binding_boundary,
)
from solo_countdown_component import build_solo_expire_token


def _room() -> dict:
    return {
        "draft_room_id": "ROOM1234",
        "current_pick_index": 0,
        "status": "in_progress",
        "timer_deadline": 9999999999.0,
        "config": {"timer_seconds": 10},
    }


def test_duplicate_mount_skipped_second_call_same_run() -> None:
    from solo_countdown_wake_micro_core import render_micro_isolation_once

    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {}
    session: dict = {"_live_draft_script_run_id": "run-a", "_solo_stage1_script_run_seq": 1}
    deliver = mock.MagicMock()
    with mock.patch(
        "solo_countdown_component.mount_solo_countdown_wake_with_token",
        return_value=token,
    ) as mount:
        render_micro_isolation_once(
            st,
            session,
            placement="PROD",
            location="test",
            production_room=room,
            production_expire_token=token,
            widget_key=PRODUCTION_PERSISTENT_KEY,
            deliver_callback=deliver,
            production_use_return_value_delivery=True,
            session_prefix="_solo_persistent_wake_",
            persistent=True,
        )
        render_micro_isolation_once(
            st,
            session,
            placement="PROD",
            location="test2",
            production_room=room,
            production_expire_token=token,
            widget_key=PRODUCTION_PERSISTENT_KEY,
            deliver_callback=deliver,
            production_use_return_value_delivery=True,
            session_prefix="_solo_persistent_wake_",
            persistent=True,
        )
        assert mount.call_count == 1


def test_raw_return_cached_on_session() -> None:
    from solo_countdown_wake_micro_core import render_micro_isolation_once

    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {}
    session: dict = {"_live_draft_script_run_id": "run-b"}
    with mock.patch(
        "solo_countdown_component.mount_solo_countdown_wake_with_token",
        return_value=token,
    ):
        render_micro_isolation_once(
            st,
            session,
            placement="PROD",
            location="test",
            production_room=room,
            production_expire_token=token,
            widget_key=PRODUCTION_PERSISTENT_KEY,
            deliver_callback=mock.MagicMock(),
            production_use_return_value_delivery=True,
            session_prefix="_solo_persistent_wake_",
            persistent=True,
        )
    assert session.get(f"_solo_prod_raw_return_{PRODUCTION_PERSISTENT_KEY}") == token


def test_binding_trace_records_mount() -> None:
    session: dict = {"_live_draft_script_run_id": "run-c"}
    record_binding_boundary(
        session,
        boundary="component_mount",
        call_site="unit",
        user_key=PRODUCTION_PERSISTENT_KEY,
        raw_out="tok",
    )
    assert declaration_count_this_run(session, PRODUCTION_PERSISTENT_KEY) == 1
    assert len(peek_trace(session)) == 1
