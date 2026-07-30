"""P8B callback-source boundary: return_value_session_bind must be actionable on production path."""

from __future__ import annotations

import time
from unittest import mock

from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY,
    SOLO_PERSISTENT_WAKE_LATCH_KEY,
    SOLO_PERSISTENT_WAKE_TOKEN_KEY,
    _production_deliver_callback,
    flush_persistent_wake_delivery,
)
from live_draft_stage1_expire_audit import (
    CALLBACK_SOURCES,
    SOLO_TOKEN_DELIVERY_OWNER_KEY,
    authorize_production_callback_source,
    callback_sources_allowlist,
    canonical_production_source,
    normalize_callback_source,
    try_claim_token_delivery,
)
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


def test_allowlist_contains_return_value_session_bind() -> None:
    allowed = callback_sources_allowlist()
    assert "return_value_session_bind" in allowed
    assert "return_value_session_bind" in CALLBACK_SOURCES


def test_canonicalization_before_membership() -> None:
    ok, canonical, reason = authorize_production_callback_source("return_value_session_bind")
    assert ok is True
    assert canonical == "return_value_session_bind"
    assert reason == ""
    original, normalized = canonical_production_source("  return_value_session_bind  ")
    assert original == "return_value_session_bind"
    assert normalized == "return_value_session_bind"


def test_unknown_source_rejected() -> None:
    ok, canonical, reason = authorize_production_callback_source("mystery_source")
    assert ok is False
    assert canonical == "other"
    assert reason == "callback_source_not_allowed"


def test_pre_claim_accepts_return_value_bind_when_actionable_flag_false() -> None:
    session: dict = {
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: False,
        "_solo_persistent_wake_early_latch": True,
    }
    ctx = {
        "delivery_only": False,
        "source": "return_value_session_bind",
        "canonical_source": "return_value_session_bind",
        "return_value_delivery_active": True,
        "persistent_wake_eligible": True,
        "normalized_token": "ROOM1234|0|1.0",
        "widget_key": "solo_countdown_wake_solo_persistent",
    }
    ok, reason = pre_claim_actionable_eligible(None, session, ctx)
    assert ok is True
    assert reason == ""


def test_pre_claim_rejects_delivery_only_return_value_bind() -> None:
    session: dict = {SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True}
    ctx = {
        "delivery_only": True,
        "source": "return_value_session_bind",
        "canonical_source": "return_value_session_bind",
        "return_value_delivery_active": True,
        "persistent_wake_eligible": True,
    }
    ok, reason = pre_claim_actionable_eligible(None, session, ctx)
    assert ok is False
    assert reason == "delivery_only_observation"


def test_return_value_bind_reaches_try_claim_after_observation() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {SOLO_PERSISTENT_WAKE_TOKEN_KEY: token, "solo_countdown_wake_solo_persistent": token}
    session: dict = {
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: False,
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
        "live_draft_room": room,
        "_solo_persistent_return_value_delivery": True,
        "_solo_persistent_wake_early_latch": True,
        "_solo_stage1_last_delivery_only": False,
        "_solo_pending_callback_source": "return_value_session_bind",
    }
    with mock.patch(
        "live_draft_solo_heartbeat.process_solo_component_wake",
        return_value=mock.Mock(ok=True, advanced=True, complete=False, reason="autopick"),
    ):
        _production_deliver_callback(st, session, token, "solo_countdown_wake_solo_persistent")
    owners = session.get(SOLO_TOKEN_DELIVERY_OWNER_KEY) or {}
    assert owners.get(token) == "return_value_session_bind"


def test_conflicting_source_still_rejected_at_try_claim() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    session: dict = {}
    ok1, _ = try_claim_token_delivery(session, token, "native_component_return")
    assert ok1 is True
    ok2, reason = try_claim_token_delivery(session, token, "return_value_session_bind")
    assert ok2 is False
    assert reason == "callback_source_not_allowed"


def test_flush_sets_actionable_before_return_value_bind() -> None:
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
        flush_persistent_wake_delivery(st, session)
    assert session[SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY] is True
    proc.assert_called_once()
    assert proc.call_args.kwargs.get("source") == "return_value_session_bind"


def test_normalize_preserves_return_value_session_bind() -> None:
    assert normalize_callback_source("return_value_session_bind") == "return_value_session_bind"
