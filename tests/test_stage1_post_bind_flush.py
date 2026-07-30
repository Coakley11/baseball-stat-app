"""Post-bind flush orchestration after delivery-only observation (P8 transport)."""

from __future__ import annotations

import time
from unittest import mock

from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY,
    SOLO_PERSISTENT_WAKE_LATCH_KEY,
    SOLO_PERSISTENT_WAKE_TOKEN_KEY,
    flush_persistent_wake_delivery,
)
from live_draft_stage1_expire_audit import (
    SOLO_TOKEN_DELIVERY_OWNER_KEY,
    authorize_production_callback_source,
    try_claim_token_delivery,
)
from live_draft_stage1_post_bind_flush import (
    bound_token_matches_mount_expire,
    complete_delivery_only_observation_and_actionable_flush,
    post_bind_flush_already_dispatched,
    widget_bound_token,
)
from live_draft_stage1_process_token_gate import (
    delivery_only_observation_completed,
    mark_delivery_only_observation_completed,
)
from solo_countdown_component import build_solo_expire_token


def _room(*, pick: int = 0, draft_id: str = "ROOM1234") -> dict:
    deadline = time.time() + 30.0
    return {
        "draft_room_id": draft_id,
        "current_pick_index": pick,
        "status": "in_progress",
        "timer_deadline": deadline,
        "config": {"timer_seconds": 30, "draft_setup_mode": "solo"},
    }


def test_mount_token_without_widget_bind_does_not_observe_or_flush() -> None:
    room = _room()
    mount_token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {}
    session: dict = {"live_draft_room": room}
    assert widget_bound_token(raw_component_value=None, session_state_value=None) == ""
    assert not complete_delivery_only_observation_and_actionable_flush(
        st,
        session,
        bound_token="",
        mount_expire_token=mount_token,
        widget_key="solo_countdown_wake_solo_persistent",
        production_room=room,
    )
    assert not delivery_only_observation_completed(session, mount_token)


def test_exact_bound_token_triggers_observation_once() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {"live_draft_room": room}
    with mock.patch(
        "live_draft_solo_persistent_wake.flush_persistent_wake_delivery",
    ) as flush_mock:
        ok1 = complete_delivery_only_observation_and_actionable_flush(
            st,
            session,
            bound_token=token,
            mount_expire_token=token,
            widget_key="solo_countdown_wake_solo_persistent",
            production_room=room,
            raw_component_value=token,
        )
        ok2 = complete_delivery_only_observation_and_actionable_flush(
            st,
            session,
            bound_token=token,
            mount_expire_token=token,
            widget_key="solo_countdown_wake_solo_persistent",
            production_room=room,
            raw_component_value=token,
        )
    assert ok1 is True
    assert ok2 is False
    assert delivery_only_observation_completed(session, token)
    flush_mock.assert_called_once()


def test_observation_then_actionable_flush_same_rerun() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: False,
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "live_draft_room": room,
        "_solo_persistent_return_value_delivery": True,
        "_solo_expire_owner": "wake",
    }
    with mock.patch(
        "live_draft_solo_persistent_wake.process_production_expire_token",
        return_value=True,
    ) as proc:
        complete_delivery_only_observation_and_actionable_flush(
            st,
            session,
            bound_token=token,
            mount_expire_token=token,
            widget_key="solo_countdown_wake_solo_persistent",
            production_room=room,
        )
    assert session.get("_solo_stage1_last_delivery_only") is False
    assert session[SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY] is True
    proc.assert_called_once()
    assert proc.call_args.kwargs.get("source") == "return_value_session_bind"


def test_return_value_session_bind_is_canonical_actionable_source() -> None:
    ok, canonical, _ = authorize_production_callback_source("return_value_session_bind")
    assert ok and canonical == "return_value_session_bind"


def test_observation_path_does_not_claim() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    session: dict = {}
    mark_delivery_only_observation_completed(session, token, source="return_value_session_bind")
    owners = session.get(SOLO_TOKEN_DELIVERY_OWNER_KEY) or {}
    assert token not in owners


def test_actionable_flush_reaches_try_claim_once() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "live_draft_room": room,
        "_solo_persistent_return_value_delivery": True,
        "_solo_expire_owner": "wake",
    }
    with mock.patch(
        "live_draft_stage1_expire_audit.try_claim_token_delivery",
        wraps=try_claim_token_delivery,
    ) as claim_mock:
        flush_persistent_wake_delivery(st, session)
    assert claim_mock.call_count >= 1
    owners = session.get(SOLO_TOKEN_DELIVERY_OWNER_KEY) or {}
    assert owners.get(token) == "return_value_session_bind"


def test_completed_token_suppressed() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {"live_draft_room": room}
    from live_draft_stage1_expire_audit import mark_token_action_complete

    mark_token_action_complete(session, token, pick_index_before=0, pick_index_after=1)
    assert not complete_delivery_only_observation_and_actionable_flush(
        st,
        session,
        bound_token=token,
        mount_expire_token=token,
        widget_key="solo_countdown_wake_solo_persistent",
        production_room=room,
    )


def test_new_pick_token_remains_eligible() -> None:
    room0 = _room(pick=0)
    room1 = _room(pick=1)
    token0 = build_solo_expire_token(room0)
    token1 = build_solo_expire_token(room1)
    from live_draft_stage1_expire_audit import mark_token_action_complete

    session: dict = {}
    mark_token_action_complete(session, token0, pick_index_before=0, pick_index_after=1)
    assert bound_token_matches_mount_expire(token1, token1)
    assert not bound_token_matches_mount_expire(token0, token1)


def test_stale_mount_mismatch_does_not_flush() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    stale = build_solo_expire_token(_room(draft_id="OTHER1"))
    st = mock.MagicMock()
    session: dict = {}
    with mock.patch("live_draft_solo_persistent_wake.flush_persistent_wake_delivery") as flush_mock:
        assert not complete_delivery_only_observation_and_actionable_flush(
            st,
            session,
            bound_token=stale,
            mount_expire_token=token,
            widget_key="solo_countdown_wake_solo_persistent",
            production_room=room,
        )
    flush_mock.assert_not_called()


def test_unknown_source_still_rejected() -> None:
    ok, _, reason = authorize_production_callback_source("not_a_real_source")
    assert not ok
    assert reason == "callback_source_not_allowed"


def test_post_bind_dispatch_guard() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    session: dict = {}
    from live_draft_stage1_post_bind_flush import mark_post_bind_flush_dispatched

    mark_post_bind_flush_dispatched(session, token)
    assert post_bind_flush_already_dispatched(session, token)


def test_flush_does_not_loop_on_second_page_flush() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "live_draft_room": room,
        "_solo_persistent_return_value_delivery": True,
        "_solo_expire_owner": "wake",
    }
    with mock.patch(
        "live_draft_solo_persistent_wake.process_production_expire_token",
        return_value=True,
    ) as proc:
        flush_persistent_wake_delivery(st, session)
        from live_draft_stage1_post_bind_flush import mark_post_bind_flush_dispatched

        mark_post_bind_flush_dispatched(session, token)
        flush_persistent_wake_delivery(st, session)
    proc.assert_called_once()
