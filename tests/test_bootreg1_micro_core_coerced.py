"""BOOTREG1 — coerced must be defined before observability reads it."""

from __future__ import annotations

from unittest import mock

import pytest

from live_draft_component_binding_trace import PRODUCTION_PERSISTENT_KEY
from solo_countdown_component import build_solo_expire_token


def _room() -> dict:
    return {
        "draft_room_id": "ROOM1234",
        "current_pick_index": 0,
        "status": "in_progress",
        "timer_deadline": 9999999999.0,
        "config": {"timer_seconds": 10, "draft_setup_mode": "solo"},
    }


def _render_return_delivery(
    *,
    session: dict,
    raw_return: object,
    ledger_enabled: bool,
    delivery_only: bool = False,
    focused_effective: bool = False,
) -> None:
    from solo_countdown_wake_micro_core import render_micro_isolation_once

    room = _room()
    token = build_solo_expire_token(room)
    st = mock.MagicMock()
    st.session_state = {}
    if focused_effective:
        session["_solo_p8_focused_binding_effective"] = True
        session["_solo_component_diag_enabled"] = True
    with mock.patch(
        "solo_countdown_component.mount_solo_countdown_wake_with_token",
        return_value=raw_return,
    ):
        with mock.patch(
            "live_draft_stage1_production_ledger.stage1_production_ledger_enabled",
            return_value=ledger_enabled,
        ):
            render_micro_isolation_once(
                st,
                session,
                placement="PROD",
                location="bootreg1_test",
                production_room=room,
                production_expire_token=token,
                widget_key=PRODUCTION_PERSISTENT_KEY,
                deliver_callback=mock.MagicMock(),
                production_use_return_value_delivery=True,
                production_delivery_only=delivery_only,
                session_prefix="_solo_persistent_wake_",
                persistent=True,
            )


def test_bootreg1_none_return_ledger_disabled_does_not_crash() -> None:
    """Branch that previously used coerced without assignment (ledger off, imports on)."""
    session: dict = {"_live_draft_script_run_id": "bootreg1-a", "_solo_stage1_script_run_seq": 1}
    _render_return_delivery(session=session, raw_return=None, ledger_enabled=False)


def test_bootreg1_empty_string_return_ledger_enabled() -> None:
    session: dict = {"_live_draft_script_run_id": "bootreg1-b", "_solo_stage1_script_run_seq": 1}
    _render_return_delivery(session=session, raw_return="", ledger_enabled=True)


def test_bootreg1_none_return_ledger_enabled_no_valid_token() -> None:
    session: dict = {"_live_draft_script_run_id": "bootreg1-c", "_solo_stage1_script_run_seq": 1}
    _render_return_delivery(session=session, raw_return=None, ledger_enabled=True)


def test_bootreg1_handoff_present_none_direct_return() -> None:
    from live_draft_prod_callback_handoff import write_callback_handoff_from_on_change

    room = _room()
    token = build_solo_expire_token(room)
    session: dict = {"_live_draft_script_run_id": "bootreg1-d", "_solo_stage1_script_run_seq": 1}
    st = mock.MagicMock()
    write_callback_handoff_from_on_change(
        st,
        session,
        widget_key=PRODUCTION_PERSISTENT_KEY,
        raw_value=token,
        expected_token=token,
        callback_invocation_id="inv1",
        production_room=room,
    )
    _render_return_delivery(session=session, raw_return=None, ledger_enabled=True)


def test_bootreg1_focused_delivery_only_none_return() -> None:
    session: dict = {"_live_draft_script_run_id": "bootreg1-e", "_solo_stage1_script_run_seq": 1}
    _render_return_delivery(
        session=session,
        raw_return=None,
        ledger_enabled=True,
        delivery_only=True,
        focused_effective=True,
    )


def test_bootreg1_normal_production_token_return() -> None:
    room = _room()
    token = build_solo_expire_token(room)
    session: dict = {"_live_draft_script_run_id": "bootreg1-f", "_solo_stage1_script_run_seq": 1}
    _render_return_delivery(session=session, raw_return=token, ledger_enabled=True)
