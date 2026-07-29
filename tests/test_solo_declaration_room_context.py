"""Tests for declaration room context and claim path after post-rerun restore."""

from __future__ import annotations

import copy
import time
import unittest
from unittest import mock

from live_draft_solo_declaration_room_context import (
    clear_declaration_room_context,
    register_production_countdown_declaration_context,
    resolve_effective_production_room,
    validate_declaration_room_for_token,
)
from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY,
    SOLO_PERSISTENT_WAKE_LATCH_KEY,
    SOLO_PERSISTENT_WAKE_TOKEN_KEY,
    SOLO_PERSISTENT_WAKE_WIDGET_KEY,
    process_production_expire_token,
)
from live_draft_stage1_expire_audit import try_claim_token_delivery
from solo_countdown_component import build_solo_expire_token


def _room(*, pick: int = 0, draft_id: str = "ROOM1234") -> dict:
    deadline = time.time() + 30.0
    return {
        "draft_room_id": draft_id,
        "draft_id": draft_id,
        "current_pick_index": pick,
        "status": "in_progress",
        "timer_deadline": deadline,
        "config": {"timer_seconds": 30, "draft_setup_mode": "solo"},
        "pick_order": ["A", "B"],
    }


class DeclarationRoomContextTests(unittest.TestCase):
    def test_live_room_reaches_claim(self) -> None:
        room = _room()
        token = build_solo_expire_token(room)
        session = {
            SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
            "live_draft_room": room,
            SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
            SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True,
        }
        st = mock.MagicMock()
        st.session_state = {"live_draft_room": room}
        with mock.patch(
            "live_draft_solo_persistent_wake._production_deliver_callback",
        ) as deliver:
            self.assertTrue(
                process_production_expire_token(
                    st,
                    session,
                    raw_token=token,
                    widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
                )
            )
            deliver.assert_called_once()

    def test_declaration_room_restores_and_reaches_claim(self) -> None:
        room = _room(draft_id="ABCD9999")
        token = build_solo_expire_token(room)
        session = {
            SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
            SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
            SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True,
        }
        st = mock.MagicMock()
        st.session_state = {}
        register_production_countdown_declaration_context(
            st,
            session,
            room=room,
            expected_token=token,
            widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
        )
        room_copy = copy.deepcopy(room)
        with mock.patch(
            "live_draft_solo_persistent_wake._production_deliver_callback",
        ) as deliver:
            self.assertTrue(
                process_production_expire_token(
                    st,
                    session,
                    raw_token=token,
                    widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
                    declaration_room=room_copy,
                )
            )
            deliver.assert_called_once()
        self.assertTrue(session.get("live_draft_room"))

    def test_mismatched_declaration_room_id_rejected(self) -> None:
        room = _room(draft_id="ROOMAAAA")
        token = build_solo_expire_token(_room(draft_id="ROOMBBBB"))
        ok, reason = validate_declaration_room_for_token(
            {},
            declaration_room=room,
            token=token,
            widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
        )
        self.assertFalse(ok)
        self.assertIn("mismatch", reason)

    def test_stale_pick_context_rejected(self) -> None:
        room = _room(pick=1)
        token = build_solo_expire_token(_room(pick=0))
        session: dict = {}
        register_production_countdown_declaration_context(
            None,
            session,
            room=_room(pick=0),
            expected_token=token,
            widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
        )
        ok, reason = validate_declaration_room_for_token(
            session,
            declaration_room=room,
            token=token,
            widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
        )
        self.assertFalse(ok)

    def test_single_claim_two_delivery_paths(self) -> None:
        session: dict = {}
        token = build_solo_expire_token(_room())
        ok1, _ = try_claim_token_delivery(session, token, "native_component_return")
        ok2, code2 = try_claim_token_delivery(session, token, "native_component_return")
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertIn(code2, ("already_consumed", "callback_source_not_allowed"))

    def test_resolve_prefers_session_live_over_declaration(self) -> None:
        live = _room(draft_id="LIVE0001")
        decl = _room(draft_id="DECL0001")
        token = build_solo_expire_token(live)
        st = mock.MagicMock()
        st.session_state = {"live_draft_room": live}
        resolved, source, _ = resolve_effective_production_room(
            st,
            {},
            declaration_room=decl,
            token=token,
        )
        self.assertEqual(source, "st_session_state_live_draft_room")
        self.assertEqual(str(resolved.get("draft_room_id")), "LIVE0001")

    def test_clear_on_room_change(self) -> None:
        session: dict = {}
        register_production_countdown_declaration_context(
            None,
            session,
            room=_room(pick=0),
            expected_token="x",
            widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
        )
        register_production_countdown_declaration_context(
            None,
            session,
            room=_room(pick=1),
            expected_token="y",
            widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
        )
        ctx = session.get("_solo_persistent_wake_declaration_room_context") or {}
        self.assertEqual(int(ctx.get("pick_index") or 0), 1)


if __name__ == "__main__":
    unittest.main()
