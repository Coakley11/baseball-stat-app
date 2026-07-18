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


if __name__ == "__main__":
    unittest.main()
