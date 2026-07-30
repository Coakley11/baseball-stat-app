"""Tests for authoritative bound-token gate and post-bind orchestration."""

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
    complete_delivery_only_observation_and_actionable_flush,
    evaluate_bound_token_gate,
    post_bind_flush_already_dispatched,
)
from live_draft_stage1_process_token_gate import delivery_only_observation_completed
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


def test_mount_token_alone_cannot_pass_gate() -> None:
    room = _room()
    mount_token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {}
    session: dict = {"live_draft_room": room}
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token=mount_token,
        mount_expire_token=mount_token,
        pending_token=mount_token,
        raw_component_return=None,
        session_state_value=None,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    assert not gate.passed
    assert gate.decision == "reject_mount_token_not_bound"


def test_pending_token_alone_cannot_emit_post_bind() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {}
    session: dict = {"live_draft_room": room, "_solo_parity_expected_token": token}
    with mock.patch("live_draft_solo_persistent_wake.flush_persistent_wake_delivery") as flush_mock:
        assert not complete_delivery_only_observation_and_actionable_flush(
            st,
            session,
            expected_expiration_token=token,
            mount_expire_token=token,
            pending_token=token,
            widget_key="solo_countdown_wake_solo_persistent",
            production_room=room,
        )
    flush_mock.assert_not_called()


def test_direct_return_passes_gate() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {}
    session: dict = {"live_draft_room": room}
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token=token,
        mount_expire_token=token,
        raw_component_return=token,
        session_state_value=None,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    assert gate.passed
    assert gate.candidate_source == "direct_component_return"


def test_session_state_passes_gate_when_key_present() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {"live_draft_room": room}
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token=token,
        mount_expire_token=token,
        raw_component_return=None,
        session_state_value=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    assert gate.passed
    assert gate.candidate_source == "same_key_session_state"


def test_observation_and_flush_once_with_direct_return() -> None:
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
        ok1 = complete_delivery_only_observation_and_actionable_flush(
            st,
            session,
            expected_expiration_token=token,
            mount_expire_token=token,
            pending_token="",
            widget_key="solo_countdown_wake_solo_persistent",
            production_room=room,
            raw_component_value=token,
        )
        ok2 = complete_delivery_only_observation_and_actionable_flush(
            st,
            session,
            expected_expiration_token=token,
            mount_expire_token=token,
            pending_token="",
            widget_key="solo_countdown_wake_solo_persistent",
            production_room=room,
            raw_component_value=token,
        )
    assert ok1 is True
    assert ok2 is False
    assert delivery_only_observation_completed(session, token)
    proc.assert_called_once()


def test_return_value_session_bind_canonical() -> None:
    ok, canonical, _ = authorize_production_callback_source("return_value_session_bind")
    assert ok and canonical == "return_value_session_bind"


def test_unknown_source_rejected() -> None:
    ok, _, reason = authorize_production_callback_source("mystery_source")
    assert not ok
    assert reason == "callback_source_not_allowed"


def test_actionable_flush_claims_once() -> None:
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


def test_post_bind_dispatch_blocks_duplicate_flush() -> None:
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


def test_post_bind_dispatch_guard() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    session: dict = {}
    from live_draft_stage1_post_bind_flush import mark_post_bind_flush_dispatched

    mark_post_bind_flush_dispatched(session, token)
    assert post_bind_flush_already_dispatched(session, token)


def test_later_direct_return_validates_against_declaration_snapshot() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {
        "live_draft_room": room,
        "_solo_stage1_deployment_sha": "b6e20ca",
    }
    from live_draft_solo_declaration_room_context import register_production_countdown_declaration_context

    register_production_countdown_declaration_context(
        st,
        session,
        room=room,
        expected_token=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    session.pop("live_draft_room", None)
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token="",
        mount_expire_token="",
        pending_token=token,
        raw_component_return=token,
        session_state_value=token,
        widget_key="solo_countdown_wake_solo_persistent",
        call_site="test_later_script_run",
    )
    assert gate.passed
    assert gate.candidate_source == "direct_component_return"
    assert gate.exact_match


def test_declaration_snapshot_alone_cannot_pass_gate() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {}
    session: dict = {"live_draft_room": room}
    from live_draft_solo_declaration_room_context import register_production_countdown_declaration_context

    register_production_countdown_declaration_context(
        st,
        session,
        room=room,
        expected_token=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token="",
        mount_expire_token=token,
        pending_token=token,
        raw_component_return=None,
        session_state_value=None,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    assert not gate.passed


def test_snapshot_wrong_room_rejected() -> None:
    room = _room(draft_id="ROOM1111")
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {"live_draft_room": room}
    from live_draft_solo_declaration_room_context import register_production_countdown_declaration_context

    register_production_countdown_declaration_context(
        st,
        session,
        room=room,
        expected_token=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    other = _room(draft_id="ROOM9999", pick=0)
    other_token = build_solo_expire_token(other)
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token="",
        mount_expire_token="",
        raw_component_return=other_token,
        session_state_value=other_token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    assert not gate.passed


def test_stale_consumed_snapshot_rejected() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {"live_draft_room": room}
    from live_draft_solo_declaration_room_context import (
        consume_expiration_validation_snapshot,
        register_production_countdown_declaration_context,
    )

    register_production_countdown_declaration_context(
        st,
        session,
        room=room,
        expected_token=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    consume_expiration_validation_snapshot(session, token, reason="test")
    register_production_countdown_declaration_context(
        st,
        session,
        room=room,
        expected_token=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    session["_solo_stage1_expiration_snapshot_consumed_token"] = token
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token="",
        mount_expire_token="",
        raw_component_return=token,
        session_state_value=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    assert not gate.passed


def test_later_bind_dispatches_post_bind_flush_once_with_snapshot() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: False,
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "_solo_persistent_return_value_delivery": True,
        "_solo_expire_owner": "wake",
        "_solo_stage1_deployment_sha": "b6e20ca",
    }
    from live_draft_solo_declaration_room_context import register_production_countdown_declaration_context

    register_production_countdown_declaration_context(
        st,
        session,
        room=room,
        expected_token=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    session.pop("live_draft_room", None)
    with mock.patch(
        "live_draft_solo_persistent_wake.flush_persistent_wake_delivery",
        return_value=True,
    ) as flush_mock:
        ok = complete_delivery_only_observation_and_actionable_flush(
            st,
            session,
            expected_expiration_token="",
            mount_expire_token="",
            pending_token="",
            widget_key="solo_countdown_wake_solo_persistent",
            production_room=None,
            raw_component_value=token,
        )
    assert ok is True
    flush_mock.assert_called_once()
    assert delivery_only_observation_completed(session, token)


def test_new_pick_snapshot_eligible_after_pick_advance() -> None:
    room0 = _room(pick=0)
    tok0 = build_solo_expire_token(room0)
    room1 = _room(pick=1)
    room1["timer_deadline"] = room0["timer_deadline"] + 30.0
    tok1 = build_solo_expire_token(room1)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": tok1}
    session: dict = {"live_draft_room": room1}
    from live_draft_solo_declaration_room_context import register_production_countdown_declaration_context

    register_production_countdown_declaration_context(
        st,
        session,
        room=room0,
        expected_token=tok0,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    register_production_countdown_declaration_context(
        st,
        session,
        room=room1,
        expected_token=tok1,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    session.pop("live_draft_room", None)
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token="",
        mount_expire_token="",
        raw_component_return=tok1,
        session_state_value=tok1,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    assert gate.passed
    assert gate.selected_bound_token == tok1


def test_later_session_state_validates_against_snapshot() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {"_solo_stage1_deployment_sha": "b6e20ca"}
    from live_draft_solo_declaration_room_context import register_production_countdown_declaration_context

    register_production_countdown_declaration_context(
        st,
        session,
        room=room,
        expected_token=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token="",
        mount_expire_token="",
        raw_component_return=None,
        session_state_value=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    assert gate.passed
    assert gate.candidate_source == "same_key_session_state"


def test_wrong_fingerprint_rejected() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {"live_draft_room": room}
    from live_draft_solo_declaration_room_context import register_production_countdown_declaration_context

    register_production_countdown_declaration_context(
        st,
        session,
        room=room,
        expected_token=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    ctx = session["_solo_persistent_wake_declaration_room_context"]
    ctx["room_fingerprint"] = "stale-fingerprint"
    session.pop("live_draft_room", None)
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token="",
        mount_expire_token="",
        raw_component_return=token,
        session_state_value=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    assert not gate.passed


def test_wrong_deployment_sha_rejected() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {"live_draft_room": room, "_solo_stage1_deployment_sha": "deadbeef"}
    from live_draft_solo_declaration_room_context import register_production_countdown_declaration_context

    register_production_countdown_declaration_context(
        st,
        session,
        room=room,
        expected_token=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    session["_solo_persistent_wake_declaration_room_context"]["deployment_sha"] = "b6e20ca"
    session.pop("live_draft_room", None)
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token="",
        mount_expire_token="",
        raw_component_return=token,
        session_state_value=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    assert not gate.passed


def test_wrong_widget_key_rejected() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {"live_draft_room": room}
    from live_draft_solo_declaration_room_context import register_production_countdown_declaration_context

    register_production_countdown_declaration_context(
        st,
        session,
        room=room,
        expected_token=token,
        widget_key="solo_countdown_wake_solo_persistent",
    )
    session.pop("live_draft_room", None)
    gate = evaluate_bound_token_gate(
        st,
        session,
        expected_expiration_token="",
        mount_expire_token="",
        raw_component_return=token,
        session_state_value=token,
        widget_key="wrong_widget_key",
    )
    assert not gate.passed
