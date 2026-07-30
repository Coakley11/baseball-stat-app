"""Stage 1A post-claim gates: delivery_only must not consume actionable expiration claims."""

from __future__ import annotations

import time
from unittest import mock

from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY,
    SOLO_PERSISTENT_WAKE_LATCH_KEY,
    SOLO_PERSISTENT_WAKE_TOKEN_KEY,
    _production_deliver_callback,
    process_production_expire_token,
)
from live_draft_stage1_expire_audit import (
    SOLO_STAGE1_ACTION_COMPLETE_KEY,
    SOLO_TOKEN_DELIVERY_OWNER_KEY,
    canonical_production_source,
    is_token_action_complete,
    mark_token_action_complete,
    normalize_callback_source,
    record_pick_commit_audit,
    try_claim_token_delivery,
)
from live_draft_stage1_process_token_gate import (
    compute_pending_session_delivery_only,
    delivery_only_observation_completed,
    mark_delivery_only_observation_completed,
    pre_claim_actionable_eligible,
)
from solo_countdown_component import build_solo_expire_token


def _room(*, pick: int = 0) -> dict:
    deadline = time.time() + 30.0
    return {
        "draft_room_id": "ROOM1234",
        "current_pick_index": pick,
        "status": "in_progress",
        "timer_deadline": deadline,
        "config": {"timer_seconds": 30, "draft_setup_mode": "solo"},
    }


def test_pre_claim_rejects_delivery_only_observation() -> None:
    session: dict = {SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True}
    ctx = {"delivery_only": True}
    ok, reason = pre_claim_actionable_eligible(None, session, ctx)
    assert ok is False
    assert reason == "delivery_only_observation"


def test_delivery_only_callback_does_not_consume_claim() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    session = {
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "live_draft_room": room,
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True,
        "_solo_stage1_last_delivery_only": True,
        "_solo_stage1_production_ledger_enabled": True,
    }
    with mock.patch(
        "live_draft_stage1_production_ledger.stage1_production_ledger_enabled",
        return_value=True,
    ):
        with mock.patch(
            "live_draft_solo_heartbeat.process_solo_component_wake",
        ) as wake:
            _production_deliver_callback(st, session, token, "solo_countdown_wake_solo_persistent")
            wake.assert_not_called()
    owners = session.get(SOLO_TOKEN_DELIVERY_OWNER_KEY) or {}
    assert token not in owners


def test_actionable_callback_claims_once_and_enters_wake() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    session = {
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "live_draft_room": room,
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True,
        "_solo_stage1_last_delivery_only": False,
        "_solo_stage1_production_ledger_enabled": True,
    }
    events: list[str] = []

    def _capture_event(_session, event, **kwargs):
        events.append(str(event))

    with mock.patch(
        "live_draft_stage1_production_ledger.stage1_production_ledger_enabled",
        return_value=True,
    ):
        with mock.patch(
            "live_draft_stage1_production_ledger.note_stage1_event",
            side_effect=_capture_event,
        ):
            with mock.patch(
                "live_draft_solo_heartbeat.process_solo_component_wake",
                return_value=True,
            ) as wake:
                _production_deliver_callback(st, session, token, "solo_countdown_wake_solo_persistent")
                wake.assert_called_once()
    ok1, _ = try_claim_token_delivery(session, token, "native_component_return")
    assert ok1 is False
    assert "production_stage1_post_claim_entered" in events
    assert "production_stage1_autopick_about_to_enter" in events


def test_already_consumed_does_not_block_first_actionable_wake() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    session = {
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "live_draft_room": room,
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True,
        "_solo_stage1_last_delivery_only": True,
    }
    with mock.patch("live_draft_solo_heartbeat.process_solo_component_wake") as wake:
        _production_deliver_callback(st, session, token, "k1")
        wake.assert_not_called()
    session["_solo_stage1_last_delivery_only"] = False
    with mock.patch("live_draft_solo_heartbeat.process_solo_component_wake", return_value=True) as wake2:
        _production_deliver_callback(st, session, token, "k2")
        wake2.assert_called_once()
    owners = session.get(SOLO_TOKEN_DELIVERY_OWNER_KEY) or {}
    assert owners.get(token) == "native_component_on_change"


def test_parity_p6_pick_disabled_does_not_consume_claim() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    session = {
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "live_draft_room": room,
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True,
        "_solo_stage1_last_delivery_only": False,
        "_solo_parity_p6_active": True,
        "_solo_parity_p6_disable_pick_processing": True,
    }
    with mock.patch(
        "live_draft_solo_persistent_parity_ladder.parity_p6_pick_processing_disabled",
        return_value=True,
    ):
        with mock.patch("live_draft_solo_heartbeat.process_solo_component_wake") as wake:
            _production_deliver_callback(st, session, token, "k")
            wake.assert_not_called()
    owners = session.get(SOLO_TOKEN_DELIVERY_OWNER_KEY) or {}
    assert token not in owners


def test_observation_marks_token_and_actionable_pass_uses_delivery_only_false() -> None:
    token = "ROOM1234|0|123.456"
    session: dict = {SOLO_PERSISTENT_WAKE_LATCH_KEY: True}
    assert compute_pending_session_delivery_only(
        session,
        pending_token=token,
        pending_raw=token,
        latch_active=True,
    )
    mark_delivery_only_observation_completed(session, token, source="native_component_return")
    assert delivery_only_observation_completed(session, token)
    assert not compute_pending_session_delivery_only(
        session,
        pending_token=token,
        pending_raw=token,
        latch_active=True,
    )


def test_observation_then_actionable_claims_once() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    session = {
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "live_draft_room": room,
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True,
        "_solo_stage1_last_delivery_only": True,
    }
    with mock.patch("live_draft_solo_heartbeat.process_solo_component_wake") as wake:
        _production_deliver_callback(st, session, token, "k")
        wake.assert_not_called()
    session["_solo_stage1_last_delivery_only"] = False
    with mock.patch("live_draft_solo_heartbeat.process_solo_component_wake", return_value=True) as wake2:
        _production_deliver_callback(st, session, token, "k2")
        wake2.assert_called_once()
    owners = session.get(SOLO_TOKEN_DELIVERY_OWNER_KEY) or {}
    assert owners.get(token) == "native_component_on_change"
    assert not delivery_only_observation_completed(session, token)


def test_pre_claim_still_rejects_delivery_only_without_observation_marker() -> None:
    session: dict = {SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True}
    ok, reason = pre_claim_actionable_eligible(None, session, {"delivery_only": True})
    assert ok is False
    assert reason == "delivery_only_observation"


def test_return_value_session_bind_is_canonical_source() -> None:
    assert normalize_callback_source("return_value_session_bind") == "return_value_session_bind"
    original, canonical = canonical_production_source("return_value_session_bind")
    assert original == "return_value_session_bind"
    assert canonical == "return_value_session_bind"
    assert canonical != "other"


def test_actionable_bind_records_return_value_session_bind_owner() -> None:
    from live_draft_solo_persistent_wake import SOLO_PENDING_CALLBACK_SOURCE_KEY

    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    session = {
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "live_draft_room": room,
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True,
        "_solo_stage1_last_delivery_only": False,
        SOLO_PENDING_CALLBACK_SOURCE_KEY: "return_value_session_bind",
    }
    with mock.patch("live_draft_solo_heartbeat.process_solo_component_wake", return_value=True):
        _production_deliver_callback(st, session, token, "k")
    owners = session.get(SOLO_TOKEN_DELIVERY_OWNER_KEY) or {}
    assert owners.get(token) == "return_value_session_bind"


def test_completed_token_suppressed_on_later_processing() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    session = {
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "live_draft_room": room,
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True,
        SOLO_TOKEN_DELIVERY_OWNER_KEY: {token: "return_value_session_bind"},
    }
    mark_token_action_complete(
        session,
        token,
        pick_index_before=0,
        pick_index_after=1,
        committed_player="Test Player",
        claim_source="return_value_session_bind",
    )
    with mock.patch("live_draft_solo_heartbeat.process_solo_component_wake") as wake:
        ok = process_production_expire_token(
            st,
            session,
            raw_token=token,
            widget_key="solo_countdown_wake_solo_persistent",
            source="native_component_return",
        )
        wake.assert_not_called()
    assert ok is False
    assert is_token_action_complete(session, token)


def test_new_pick_token_not_suppressed_by_prior_action_complete() -> None:
    room = _room(pick=1)
    old_token = build_solo_expire_token(_room(pick=0))
    new_token = build_solo_expire_token(room)
    session: dict = {SOLO_STAGE1_ACTION_COMPLETE_KEY: {old_token: {"token": old_token}}}
    assert not is_token_action_complete(session, new_token)
    ok, reason = try_claim_token_delivery(session, new_token, "return_value_session_bind")
    assert ok is True
    assert reason == ""


def test_pick_commit_audit_zero_based_pick_index_fields() -> None:
    room = _room(pick=1)
    session: dict = {"_solo_stage1_expire_audit_enabled": True}
    st = mock.MagicMock()
    with mock.patch(
        "live_draft_stage1_expire_audit.stage1_expire_audit_active",
        return_value=True,
    ):
        row = record_pick_commit_audit(
            st,
            session,
            room=room,
            team="Team A",
            player="Jazz Chisholm Jr.",
            selection_source="expired_advanced",
            pick_before=1,
            pick_after=2,
            triggering_token="tok",
            triggering_callback_seq=None,
        )
    assert row["pick_index_before"] == 0
    assert row["pick_index_after"] == 1
    assert row["pick_number_before"] == 1
    assert row["pick_number_after"] == 2
