"""Authorized focused P8 stop-before-claim and diagnostic-only handoff tests."""

from __future__ import annotations

from unittest import mock

import pytest

from live_draft_prod_callback_handoff import (
    STATUS_STALE,
    get_handoff_record,
    handoff_storage_key,
    validate_handoff_for_declaration,
    write_callback_handoff_from_on_change,
)
from live_draft_solo_p8_focused_binding import (
    SOLO_P8_AUTH_STATE_KEY,
    SOLO_P8_FOCUSED_EFFECTIVE_KEY,
    SOLO_P8_FOCUSED_TXN_KEY,
    SOLO_P8_HARNESS_TXN_KEY,
    bootstrap_solo_p8_focused_binding,
    solo_p8_focused_binding_effective,
)
from live_draft_stage1_post_bind_flush import complete_delivery_only_observation_and_actionable_flush
from live_draft_stage1_process_token_gate import pre_claim_actionable_eligible
from solo_countdown_component import build_solo_expire_token


def _room(*, pick: int = 0) -> dict:
    return {
        "draft_room_id": "ROOM1234",
        "current_pick_index": pick,
        "status": "in_progress",
        "timer_deadline": 999.0,
        "config": {"timer_seconds": 30, "draft_setup_mode": "solo"},
    }


def _diag_session(**extra: object) -> dict:
    harness = str(extra.get(SOLO_P8_HARNESS_TXN_KEY) or "a1b2c3d4e5f67890")
    base = {
        "_solo_component_diag_enabled": True,
        "_solo_stage1_production_ledger_enabled": True,
        SOLO_P8_HARNESS_TXN_KEY: harness,
        SOLO_P8_AUTH_STATE_KEY: {
            "focused_param_requested": True,
            "focused_authorized": True,
            "focused_effective": True,
            "authorization_result": "authorized",
            "denial_reason": "",
            "harness_transaction_id": harness,
        },
        SOLO_P8_FOCUSED_TXN_KEY: {
            "harness_run_id": harness,
            "streamlit_session_id": "test-session",
            "build_sha": "cff25b8",
            "created_ts": 1.0,
            "expires_ts": 9999999999.0,
            "terminal": False,
            "component_diag_armed": True,
            "focused_param_seen": True,
        },
        **extra,
    }
    return base


def test_query_param_alone_does_not_activate_focused_mode() -> None:
    st = mock.MagicMock()
    st.query_params = {"solo_p8_focused_binding": "1"}
    session: dict = {}
    bootstrap_solo_p8_focused_binding(st, session)
    assert session.get(SOLO_P8_FOCUSED_EFFECTIVE_KEY) is False


def test_authorized_diagnostic_query_activates_focused_mode() -> None:
    st = mock.MagicMock()
    st.query_params = {
        "solo_p8_focused_binding": "1",
        "solo_p8_harness_run_id": "f71d5f97331343de",
        "solo_component_diag": "1",
    }
    session = _diag_session()
    with mock.patch("live_draft_cloud_diagnostics._admin_ok", return_value=True):
        bootstrap_solo_p8_focused_binding(st, session)
    assert session.get(SOLO_P8_FOCUSED_EFFECTIVE_KEY) is True
    st.query_params = {}
    assert solo_p8_focused_binding_effective(st, session)


def test_focused_post_bind_stops_without_flush() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session = _diag_session(**{SOLO_P8_FOCUSED_EFFECTIVE_KEY: True})
    with mock.patch("live_draft_solo_persistent_wake.flush_persistent_wake_delivery") as flush_mock:
        ok = complete_delivery_only_observation_and_actionable_flush(
            st,
            session,
            expected_expiration_token=token,
            mount_expire_token=token,
            pending_token=token,
            widget_key="solo_countdown_wake_solo_persistent",
            production_room=room,
            raw_component_value=token,
        )
    assert ok
    flush_mock.assert_not_called()


def test_flush_guard_blocks_when_focused_effective() -> None:
    from live_draft_solo_persistent_wake import flush_persistent_wake_delivery

    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session = _diag_session(
        **{
            SOLO_P8_FOCUSED_EFFECTIVE_KEY: True,
            "_solo_persistent_wake_latch": True,
            "_solo_return_value_delivery_active": True,
        }
    )
    with mock.patch(
        "live_draft_solo_persistent_wake.production_return_value_delivery_active",
        return_value=True,
    ), mock.patch(
        "live_draft_solo_persistent_wake.solo_persistent_wake_active",
        return_value=True,
    ), mock.patch(
        "live_draft_solo_persistent_wake.process_production_expire_token",
    ) as proc_mock:
        flush_persistent_wake_delivery(st, session)
    proc_mock.assert_not_called()


def test_pre_claim_guard_blocks_try_claim_path() -> None:
    session = _diag_session(**{SOLO_P8_FOCUSED_EFFECTIVE_KEY: True})
    ok, reason = pre_claim_actionable_eligible(
        None,
        session,
        {
            "delivery_only": False,
            "canonical_source": "return_value_session_bind",
            "return_value_delivery_active": True,
            "persistent_wake_eligible": True,
            "normalized_token": "R|0|1.0",
            "widget_key": "solo_countdown_wake_solo_persistent",
        },
    )
    assert not ok
    assert reason == "p8_focused_binding_stop_before_claim"


def test_diagnostic_handoff_marked_and_rejected_in_normal_mode() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    session = _diag_session(**{SOLO_P8_FOCUSED_EFFECTIVE_KEY: True})
    write_callback_handoff_from_on_change(
        st,
        session,
        widget_key="solo_countdown_wake_solo_persistent",
        raw_value=token,
        expected_token=token,
        callback_invocation_id="inv1",
        production_room=room,
    )
    rec = get_handoff_record(session, "solo_countdown_wake_solo_persistent")
    assert rec and rec.get("diagnostic_only") is True
    from live_draft_solo_p8_focused_binding import mark_focused_transaction_terminal

    mark_focused_transaction_terminal(session, reason="focused_diagnostic_complete_no_claim")
    session[SOLO_P8_FOCUSED_EFFECTIVE_KEY] = False
    _, reject = validate_handoff_for_declaration(
        session,
        widget_key="solo_countdown_wake_solo_persistent",
        expected_token=token,
        st=st,
    )
    assert reject == "handoff_diagnostic_only"


def test_diagnostic_cleanup_does_not_erase_newer_handoff() -> None:
    room = _room()
    token0 = build_solo_expire_token(room)
    room1 = dict(room)
    room1["current_pick_index"] = 1
    token1 = build_solo_expire_token(room1)
    st = mock.MagicMock()
    session = _diag_session(**{SOLO_P8_FOCUSED_EFFECTIVE_KEY: True})
    write_callback_handoff_from_on_change(
        st,
        session,
        widget_key="solo_countdown_wake_solo_persistent",
        raw_value=token0,
        expected_token=token0,
        callback_invocation_id="inv0",
        production_room=room,
    )
    from live_draft_prod_callback_handoff import mark_handoff_terminal

    mark_handoff_terminal(
        session,
        "solo_countdown_wake_solo_persistent",
        raw_token=token0,
        reason="focused_diagnostic_complete_no_claim",
        st=st,
        status=STATUS_STALE,
    )
    session[handoff_storage_key("solo_countdown_wake_solo_persistent")] = {
        "raw_token": token1,
        "status": "pending",
        "created_ts": 9999999999.0,
        "widget_user_key": "solo_countdown_wake_solo_persistent",
        "diagnostic_only": False,
    }
    mark_handoff_terminal(
        session,
        "solo_countdown_wake_solo_persistent",
        raw_token=token0,
        reason="focused_diagnostic_complete_no_claim",
        st=st,
        status=STATUS_STALE,
    )
    kept = session.get(handoff_storage_key("solo_countdown_wake_solo_persistent"))
    assert isinstance(kept, dict)
    assert kept.get("raw_token") == token1


def test_non_focused_post_bind_still_calls_flush() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": token}
    session: dict = {"live_draft_room": room}
    with mock.patch("live_draft_solo_persistent_wake.flush_persistent_wake_delivery") as flush_mock:
        complete_delivery_only_observation_and_actionable_flush(
            st,
            session,
            expected_expiration_token=token,
            mount_expire_token=token,
            pending_token=token,
            widget_key="solo_countdown_wake_solo_persistent",
            production_room=room,
            raw_component_value=token,
        )
    flush_mock.assert_called_once()
