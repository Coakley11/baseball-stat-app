"""Bridge transition paired diagnostic (unit)."""

from __future__ import annotations

from unittest import mock

from live_draft_solo_bridge_transition_diag import (
    TRANSITION_WIDGET_KEY,
    _frozen_control_a_mount,
    bridge_transition_control,
    enable_bridge_transition_from_query,
)


def test_control_a_frozen_token_stable_across_calls() -> None:
    st = mock.MagicMock()
    session: dict = {}
    a1, t1, _, _ = _frozen_control_a_mount(st, session)
    a2, t2, _, _ = _frozen_control_a_mount(st, session)
    assert a1 and a2
    assert t1 == t2
    assert t1 == session["_solo_bridge_transition_frozen_token"]


def test_query_enables_transition_and_disables_flush_flag() -> None:
    st = mock.MagicMock()
    session: dict = {}
    with mock.patch(
        "live_draft_solo_bridge_transition_diag._qp_get",
        return_value="B",
    ):
        enable_bridge_transition_from_query(st, session)
    assert session.get("_solo_bridge_transition_enabled")
    assert session.get("_solo_persistent_wake_flush_disabled")
    assert bridge_transition_control(st, session) == "B"


def test_widget_key_is_production_persistent() -> None:
    assert TRANSITION_WIDGET_KEY == "solo_countdown_wake_solo_persistent"
