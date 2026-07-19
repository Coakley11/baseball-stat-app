"""Creation trace / protect-new-room / user-facing step labels."""

from __future__ import annotations

import unittest

from live_draft_creation_trace import (
    finalize_creation_receipt,
    init_creation_trace,
    new_room_is_protected,
    note_creation_step,
    protect_new_room,
    user_facing_creation_status,
)


class CreationTraceTests(unittest.TestCase):
    def test_steps_and_receipt(self) -> None:
        session: dict = {}
        init_creation_trace(session, mode="prepare_shared")
        note_creation_step(session, "pool_build_start", ok=True)
        note_creation_step(
            session,
            "commissioner_registered",
            ok=True,
            draft_id="D1",
            room_code="ABC123",
        )
        protect_new_room(session)
        finalize_creation_receipt(session, success=True, lifecycle="waiting_shared_lobby")
        receipt = session["_live_draft_creation_receipt"]
        self.assertTrue(receipt["creation_success"])
        self.assertEqual(receipt["draft_id"], "D1")
        self.assertEqual(receipt["room_code"], "ABC123")
        self.assertEqual(receipt["lifecycle_after_creation"], "waiting_shared_lobby")
        self.assertTrue(new_room_is_protected(session))

    def test_user_facing_status_is_step_specific(self) -> None:
        session: dict = {}
        init_creation_trace(session, mode="new")
        note_creation_step(session, "pool_build_start", ok=True)
        label = user_facing_creation_status(session)
        self.assertIn("pool", label.lower())
        self.assertNotEqual(label, "Preparing Draft…")

    def test_no_still_working_after_draft_ready(self) -> None:
        session: dict = {}
        init_creation_trace(session, mode="new")
        # Soft-timeout is per-step duration, not total create elapsed.
        note_creation_step(session, "pool_build_start", ok=True, step_ms=9000)
        self.assertEqual(session["_live_draft_creation_trace"].get("soft_timeout_step"), "pool_build_start")
        finalize_creation_receipt(session, success=True, lifecycle="active_draft")
        self.assertIsNone(session["_live_draft_creation_trace"].get("soft_timeout_step"))
        label = user_facing_creation_status(session)
        self.assertNotIn("Still working", label)
        self.assertIn("Opening", label)

    def test_soft_timeout_uses_step_ms_not_total(self) -> None:
        session: dict = {}
        init_creation_trace(session, mode="new")
        session["_live_draft_creation_trace"]["started_mono"] = __import__("time").monotonic() - 20.0
        session["_live_draft_creation_trace"]["elapsed_ms"] = 19000
        # room_initialized itself only took 50ms — must NOT soft-timeout.
        note_creation_step(session, "room_initialized", ok=True, step_ms=50)
        self.assertNotEqual(
            session["_live_draft_creation_trace"].get("soft_timeout_step"),
            "room_initialized",
        )

    def test_post_create_watchdog_surfaces_failed_step(self) -> None:
        from live_draft_creation_trace import (
            POST_CREATE_DEADLINE_KEY,
            evaluate_post_create_watchdog,
            open_preserved_created_draft,
        )

        session: dict = {
            "live_draft_room": {
                "draft_room_id": "SOLO-1",
                "status": "in_progress",
                "draft_board": [],
                "teams": ["Team A"],
                "pick_order": [{"Pick": 1, "Team": "Team A"}],
                "config": {"draft_setup_mode": "solo", "timer_seconds": 30},
            },
            "_live_draft_force_setup_after_delete": True,
        }
        init_creation_trace(session, mode="new")
        finalize_creation_receipt(session, success=True, lifecycle="active_draft")
        # Expire watchdog immediately.
        session[POST_CREATE_DEADLINE_KEY] = 0.0
        # Force lifecycle back to setup path without wiping room (simulate gate).
        session["_live_draft_force_setup_after_delete"] = True
        session.pop("_live_draft_protect_new_room_until", None)
        fail = evaluate_post_create_watchdog(session)
        self.assertIsNotNone(fail)
        self.assertIn("failed_step", fail or {})
        opened = open_preserved_created_draft(session)
        self.assertTrue(opened.get("ok"))
        self.assertEqual(opened.get("draft_id"), "SOLO-1")
        self.assertFalse(session.get("_live_draft_force_setup_after_delete"))


if __name__ == "__main__":
    unittest.main()
