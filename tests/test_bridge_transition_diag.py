"""Bridge transition paired diagnostic (unit)."""

from __future__ import annotations

from unittest import mock

from live_draft_solo_bridge_transition_diag import (
    PLACEHOLDER_DRAFT_ID,
    TRANSITION_WIDGET_KEY,
    _placeholder_token,
    bridge_transition_control,
    enable_bridge_transition_from_query,
    resolve_transition_mount,
)


def test_setup_placeholder_same_for_a_and_b_token_shape() -> None:
    session: dict = {}
    a_action, a_tok, _, _ = resolve_transition_mount(session, None, "A")
    b_action, b_tok, _, _ = resolve_transition_mount(session, None, "B")
    assert a_action is True
    assert b_action is False
    assert a_tok == _placeholder_token()
    assert b_tok == ""


def test_post_activation_same_live_token_a_and_b() -> None:
    import time

    session = {"live_draft_setup_mode": "solo"}
    room = {
        "draft_room_id": "ABCD1234",
        "current_pick_index": 0,
        "status": "in_progress",
        "timer_deadline": time.time() + 10,
        "config": {"draft_setup_mode": "solo", "timer_seconds": 10},
    }
    _aa, tok_a, _, ph_a = resolve_transition_mount(session, room, "A")
    session2 = {"live_draft_setup_mode": "solo"}
    _ba, tok_b, _, ph_b = resolve_transition_mount(session2, room, "B")
    assert ph_a == "active" and ph_b == "active"
    assert tok_a == tok_b
    assert _aa is True and _ba is True


def test_query_enables_transition_and_disables_flush() -> None:
    st = mock.MagicMock()
    session: dict = {}
    with mock.patch("live_draft_solo_bridge_transition_diag._qp_get", return_value="B"):
        enable_bridge_transition_from_query(st, session)
    assert session.get("_solo_persistent_wake_flush_disabled")
    assert bridge_transition_control(st, session) == "B"


def test_widget_key_is_production_persistent() -> None:
    assert TRANSITION_WIDGET_KEY == "solo_countdown_wake_solo_persistent"
    assert PLACEHOLDER_DRAFT_ID in _placeholder_token()
