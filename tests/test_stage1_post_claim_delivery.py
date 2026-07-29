"""Stage 1A post-claim gates: delivery_only must not consume actionable expiration claims."""

from __future__ import annotations

import time
from unittest import mock

from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY,
    SOLO_PERSISTENT_WAKE_LATCH_KEY,
    SOLO_PERSISTENT_WAKE_TOKEN_KEY,
    _production_deliver_callback,
)
from live_draft_stage1_expire_audit import SOLO_TOKEN_DELIVERY_OWNER_KEY, try_claim_token_delivery
from live_draft_stage1_process_token_gate import pre_claim_actionable_eligible
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
