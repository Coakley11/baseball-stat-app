"""Return-value delivery owner for production persistent Solo wake."""

from __future__ import annotations

import time
from unittest import mock

from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_RETURN_VALUE_DELIVERY_KEY,
    SOLO_PERSISTENT_WAKE_LATCH_KEY,
    SOLO_PERSISTENT_WAKE_TOKEN_KEY,
    _production_expire_token_matches_state,
    process_production_expire_token,
    production_return_value_delivery_active,
    resolve_production_component_delivery_mode,
)
from live_draft_stage1_expire_audit import SOLO_TOKEN_DELIVERY_OWNER_KEY, try_claim_token_delivery
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


def test_resolve_production_delivery_mode_default_return_value() -> None:
    st = mock.MagicMock()
    session: dict = {}
    from live_draft_solo_persistent_wake import _production_deliver_callback

    assert resolve_production_component_delivery_mode(st, session, _production_deliver_callback) == "return_value"


def test_none_return_not_processed() -> None:
    st = mock.MagicMock()
    session = {
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: build_solo_expire_token(_room()),
        "live_draft_room": _room(),
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
    }
    with mock.patch("live_draft_solo_persistent_wake._production_deliver_callback") as deliver:
        assert process_production_expire_token(st, session, raw_token=None, widget_key="k") is False
        deliver.assert_not_called()


def test_exact_token_invokes_delivery_once() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    session = {
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "live_draft_room": room,
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        "_solo_persistent_wake_actionable": True,
    }
    with mock.patch("live_draft_solo_persistent_wake._production_deliver_callback") as deliver:
        assert process_production_expire_token(st, session, raw_token=token, widget_key="solo_countdown_wake_solo_persistent")
        deliver.assert_called_once()
    with mock.patch("live_draft_solo_persistent_wake._production_deliver_callback") as deliver2:
        process_production_expire_token(st, session, raw_token=token, widget_key="solo_countdown_wake_solo_persistent")
        deliver2.assert_called_once()


def test_try_claim_blocks_duplicate_delivery_source() -> None:
    session: dict = {}
    token = build_solo_expire_token(_room())
    ok1, _ = try_claim_token_delivery(session, token, "native_component_return")
    ok2, code2 = try_claim_token_delivery(session, token, "native_component_return")
    assert ok1 is True
    assert ok2 is False
    assert code2 == "already_consumed"
    owners = session.get(SOLO_TOKEN_DELIVERY_OWNER_KEY) or {}
    assert owners[token] == "native_component_return"


def test_stale_expected_token_ignored() -> None:
    room = _room(pick=2)
    stale = build_solo_expire_token(_room(pick=1))
    session = {SOLO_PERSISTENT_WAKE_TOKEN_KEY: build_solo_expire_token(room)}
    ok, code = _production_expire_token_matches_state(session, stale, room)
    assert ok is False
    assert code in ("expected_token_mismatch", "wrong_pick")


def test_wrong_room_rejected() -> None:
    room = _room(draft_id="ROOMAAAA")
    token = build_solo_expire_token(_room(draft_id="ROOMBBBB"))
    session = {SOLO_PERSISTENT_WAKE_TOKEN_KEY: token}
    ok, code = _production_expire_token_matches_state(session, token, room)
    assert ok is False
    assert code in ("wrong_room", "expected_token_mismatch")


def test_flush_disabled_when_return_value_delivery_active() -> None:
    session = {SOLO_PERSISTENT_RETURN_VALUE_DELIVERY_KEY: True, SOLO_PERSISTENT_WAKE_LATCH_KEY: True}
    assert production_return_value_delivery_active(session)


def test_micro_mount_uses_on_change_none_when_return_value_flag() -> None:
    from solo_countdown_wake_micro_core import render_micro_isolation_once

    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {}
    session: dict = {}
    deliver = mock.MagicMock()
    with mock.patch(
        "solo_countdown_component.mount_solo_countdown_wake_with_token",
        return_value=None,
    ) as mount:
        with mock.patch("live_draft_solo_persistent_wake.process_production_expire_token") as proc:
            render_micro_isolation_once(
                st,
                session,
                placement="PROD",
                location="test",
                production_room=room,
                production_expire_token=token,
                deliver_callback=deliver,
                production_use_return_value_delivery=True,
                session_prefix="_solo_persistent_wake_",
                persistent=True,
            )
            assert mount.call_args.kwargs.get("on_change") is None
            proc.assert_called_once()
