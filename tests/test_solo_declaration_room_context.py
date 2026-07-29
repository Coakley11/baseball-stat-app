"""Tests for declaration room context and claim path after post-rerun restore."""

from __future__ import annotations

import copy
import time
import unittest
from unittest import mock

from live_draft_solo_declaration_room_context import (
    SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
    clear_declaration_room_context,
    register_production_countdown_declaration_context,
    resolve_effective_production_room,
    validate_declaration_room_for_token,
    validate_registered_declaration_context,
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


def _room(*, pick: int = 0, draft_id: str = "ROOM1234", status: str = "in_progress") -> dict:
    deadline = time.time() + 30.0
    return {
        "draft_room_id": draft_id,
        "draft_id": draft_id,
        "current_pick_index": pick,
        "status": status,
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

    def test_registered_pick_zero_validates(self) -> None:
        room = _room(pick=0, draft_id="PICK0ROOM")
        token = build_solo_expire_token(room)
        session: dict = {"_live_draft_script_run_id": "run-a"}
        register_production_countdown_declaration_context(
            None,
            session,
            room=room,
            expected_token=token,
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
        )
        ok, reason, validated = validate_registered_declaration_context(session, token=token)
        self.assertTrue(ok, reason)
        self.assertIsNotNone(validated)
        self.assertEqual(int(validated.get("current_pick_index", -1)), 0)

    def test_registered_in_progress_restores_and_reaches_claim(self) -> None:
        room = _room(draft_id="ABCD9999")
        token = build_solo_expire_token(room)
        session = {
            SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
            SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
            SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True,
            "_live_draft_script_run_id": "run-b",
        }
        st = mock.MagicMock()
        st.session_state = {}
        register_production_countdown_declaration_context(
            st,
            session,
            room=room,
            expected_token=token,
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
        )
        with mock.patch(
            "live_draft_solo_persistent_wake._production_deliver_callback",
        ) as deliver:
            self.assertTrue(
                process_production_expire_token(
                    st,
                    session,
                    raw_token=token,
                    widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
                    declaration_room={"draft_room_id": "ABCD9999", "current_pick_index": 0},
                )
            )
            deliver.assert_called_once()
        self.assertTrue(session.get("live_draft_room"))

    def test_incomplete_explicit_does_not_block_registered(self) -> None:
        room = _room(draft_id="REG00001")
        token = build_solo_expire_token(room)
        session: dict = {"_live_draft_script_run_id": "run-c"}
        register_production_countdown_declaration_context(
            None,
            session,
            room=room,
            expected_token=token,
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
        )
        incomplete = {"draft_room_id": "REG00001", "current_pick_index": 0}
        resolved, source, meta = resolve_effective_production_room(
            mock.MagicMock(),
            session,
            explicit_declaration_room=incomplete,
            token=token,
        )
        self.assertEqual(source, "validated_registered_declaration_context")
        self.assertTrue(meta.get("registered_context_validation_ok"))
        self.assertTrue(meta.get("explicit_context_rejected"))

    def test_stale_registered_room_id_rejected(self) -> None:
        room = _room(draft_id="STALE0001")
        token = build_solo_expire_token(_room(draft_id="TOKEN0002"))
        session: dict = {"_live_draft_script_run_id": "run-d"}
        register_production_countdown_declaration_context(
            None,
            session,
            room=room,
            expected_token=build_solo_expire_token(room),
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
        )
        ok, reason, _ = validate_registered_declaration_context(session, token=token)
        self.assertFalse(ok)
        self.assertIn("mismatch", reason)

    def test_stale_pick_deadline_token_rejected(self) -> None:
        room0 = _room(pick=0)
        token1 = build_solo_expire_token(_room(pick=1))
        session: dict = {"_live_draft_script_run_id": "run-e"}
        register_production_countdown_declaration_context(
            None,
            session,
            room=room0,
            expected_token=build_solo_expire_token(room0),
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
        )
        ok, reason, _ = validate_registered_declaration_context(session, token=token1)
        self.assertFalse(ok)

    def test_completed_registered_context_rejected(self) -> None:
        room = _room(status="completed")
        token = build_solo_expire_token(_room())
        session: dict = {}
        register_production_countdown_declaration_context(
            None,
            session,
            room=room,
            expected_token=token,
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
        )
        self.assertNotIn("_solo_persistent_wake_declaration_room_context", session)

    def test_newer_declaration_supersedes_older(self) -> None:
        session: dict = {"_live_draft_script_run_id": "run-f"}
        r0 = _room(pick=0, draft_id="SUPER001")
        t0 = build_solo_expire_token(r0)
        register_production_countdown_declaration_context(
            None,
            session,
            room=r0,
            expected_token=t0,
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
        )
        r1 = _room(pick=1, draft_id="SUPER001")
        t1 = build_solo_expire_token(r1)
        register_production_countdown_declaration_context(
            None,
            session,
            room=r1,
            expected_token=t1,
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
        )
        ctx = session.get("_solo_persistent_wake_declaration_room_context") or {}
        self.assertEqual(int(ctx.get("pick_index") or 0), 1)
        ok, _, _ = validate_registered_declaration_context(session, token=t0)
        self.assertFalse(ok)

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
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
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
            explicit_declaration_room=decl,
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
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
        )
        register_production_countdown_declaration_context(
            None,
            session,
            room=_room(pick=1),
            expected_token="y",
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
        )
        ctx = session.get("_solo_persistent_wake_declaration_room_context") or {}
        self.assertEqual(int(ctx.get("pick_index") or 0), 1)


class Stage1QueueHarnessTests(unittest.TestCase):
    def test_queue_seed_rejects_page_text_without_container_player(self) -> None:
        from scripts.run_production_stage1_authenticated import queue_seed_satisfied

        meta = {
            "clicked": True,
            "queue_container": {"found": True, "empty": True, "players": []},
            "queue_excerpt_before": "Advanced filters\nSome recommendation — UTIL",
        }
        self.assertFalse(queue_seed_satisfied(meta))

    def test_queue_seed_accepts_container_player(self) -> None:
        from scripts.run_production_stage1_authenticated import queue_seed_satisfied

        meta = {
            "queue_container": {
                "found": True,
                "players": [{"name": "Mike Trout", "slot": "OF"}],
            },
        }
        self.assertTrue(queue_seed_satisfied(meta))
        self.assertEqual(meta.get("player_hint"), "Mike Trout")


if __name__ == "__main__":
    unittest.main()
