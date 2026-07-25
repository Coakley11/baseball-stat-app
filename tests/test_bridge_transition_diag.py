"""Bridge transition diagnostic (unit)."""

from __future__ import annotations

import time
from unittest import mock

from live_draft_solo_bridge_transition_diag import (
    A0_DRAFT_ID,
    PLACEHOLDER_DRAFT_ID,
    TRANSITION_WIDGET_KEY,
    _placeholder_token,
    bridge_transition_control,
    enable_bridge_transition_from_query,
    normalize_control,
    resolve_transition_mount,
)


def test_normalize_control_maps_legacy_a_to_a1() -> None:
    assert normalize_control("A") == "A1"
    assert normalize_control("a0") == "A0"


def test_a1_b_setup_placeholder() -> None:
    session: dict = {}
    _a1, tok_a, _, _ = resolve_transition_mount(session, None, "A1")
    _b_action, b_tok, _, _ = resolve_transition_mount(session, None, "B")
    assert tok_a == _placeholder_token()
    assert _b_action is False
    assert b_tok == ""


def test_a0_frozen_token_stable() -> None:
    session: dict = {}
    _a, t1, _, p1 = resolve_transition_mount(session, None, "A0")
    _b, t2, _, p2 = resolve_transition_mount(session, None, "A0")
    assert t1 == t2
    assert A0_DRAFT_ID in t1
    assert p1 == "setup" and p2 == "setup"


def test_post_activation_same_live_token_a1_and_b() -> None:
    session = {"live_draft_setup_mode": "solo"}
    room = {
        "draft_room_id": "ABCD1234",
        "current_pick_index": 0,
        "status": "in_progress",
        "timer_deadline": time.time() + 10,
        "config": {"draft_setup_mode": "solo", "timer_seconds": 10},
    }
    _aa, tok_a, _, ph_a = resolve_transition_mount(session, room, "A1")
    session2 = {"live_draft_setup_mode": "solo"}
    _ba, tok_b, _, ph_b = resolve_transition_mount(session2, room, "B")
    assert ph_a == "active" and ph_b == "active"
    assert tok_a == tok_b


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
