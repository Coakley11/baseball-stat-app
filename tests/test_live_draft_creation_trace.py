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

    def test_watchdog_is_non_terminal_after_active_page_entered(self) -> None:
        from live_draft_creation_trace import (
            POST_CREATE_DEADLINE_KEY,
            POST_CREATE_FAIL_KEY,
            evaluate_post_create_watchdog,
            mark_active_draft_page_entered,
            maybe_mark_active_draft_page_entered,
        )

        session = _armed_post_create_session()
        session[POST_CREATE_DEADLINE_KEY] = 0.0
        self.assertTrue(maybe_mark_active_draft_page_entered(session, lifecycle="active_draft"))
        self.assertFalse(maybe_mark_active_draft_page_entered(session, lifecycle="setup"))
        fail = evaluate_post_create_watchdog(session)
        receipt = session["_live_draft_creation_receipt"]
        self.assertIsNone(fail)
        self.assertIsNone(session.get(POST_CREATE_FAIL_KEY))
        self.assertTrue(receipt["active_page_entered"])
        self.assertTrue(receipt["creation_success"])
        mark_active_draft_page_entered(session, lifecycle="active_draft")
        self.assertTrue(session["_live_draft_creation_receipt"]["creation_success"])

    def test_watchdog_recovery_when_watchdog_fired_first(self) -> None:
        from live_draft_creation_trace import (
            POST_CREATE_DEADLINE_KEY,
            POST_CREATE_FAIL_KEY,
            evaluate_post_create_watchdog,
            mark_active_draft_page_entered,
        )

        session = _armed_post_create_session()
        session[POST_CREATE_DEADLINE_KEY] = 0.0
        fail = evaluate_post_create_watchdog(session)
        self.assertIsNotNone(fail)
        self.assertFalse(session["_live_draft_creation_receipt"].get("creation_success"))
        self.assertIsNotNone(session.get(POST_CREATE_FAIL_KEY))
        mark_active_draft_page_entered(session, lifecycle="active_draft")
        receipt = session["_live_draft_creation_receipt"]
        self.assertTrue(receipt["active_page_entered"])
        self.assertTrue(receipt["creation_success"])
        self.assertIsNone(session.get(POST_CREATE_FAIL_KEY))
        self.assertNotIn("post_create_failed_step", receipt)
        self.assertIsNone(evaluate_post_create_watchdog(session))
        self.assertEqual(user_facing_creation_status(session), "")

    def test_watchdog_still_detects_genuine_never_entered(self) -> None:
        from live_draft_creation_trace import (
            POST_CREATE_DEADLINE_KEY,
            POST_CREATE_FAIL_KEY,
            evaluate_post_create_watchdog,
        )

        session = _armed_post_create_session()
        session[POST_CREATE_DEADLINE_KEY] = 0.0
        first = evaluate_post_create_watchdog(session)
        second = evaluate_post_create_watchdog(session)
        self.assertIsNotNone(first)
        self.assertEqual((first or {}).get("failed_step"), (second or {}).get("failed_step"))
        self.assertIsNotNone(session.get(POST_CREATE_FAIL_KEY))
        self.assertFalse(session["_live_draft_creation_receipt"].get("active_page_entered"))
        self.assertIn("active page did not open", str((first or {}).get("detail") or ""))

    def test_streamlit_marks_active_page_before_watchdog_and_placement_stops(self) -> None:
        from pathlib import Path

        src = Path(__file__).resolve().parents[1].joinpath("streamlit_app.py").read_text(
            encoding="utf-8"
        )
        mark_at = src.find("maybe_mark_active_draft_page_entered")
        p2a_at = src.find("try_micro_p2a_before_early_reconcile")
        p2b_at = src.find("try_micro_p2b_after_early_reconcile")
        progress_at = src.find("render_draft_start_progress(st, st.session_state")
        late_mark = src.rfind("mark_active_draft_page_entered(")
        self.assertGreater(mark_at, 0)
        self.assertLess(mark_at, p2a_at)
        self.assertLess(mark_at, p2b_at)
        self.assertLess(mark_at, progress_at)
        self.assertLess(progress_at, late_mark)


def _armed_post_create_session() -> dict:
    session: dict = {
        "live_draft_room": {
            "draft_room_id": "SOLO-1",
            "status": "in_progress",
            "draft_board": [],
            "teams": ["Team A"],
            "pick_order": [{"Pick": 1, "Team": "Team A"}],
            "config": {"draft_setup_mode": "solo", "timer_seconds": 30},
        }
    }
    init_creation_trace(session, mode="new")
    finalize_creation_receipt(session, success=True, lifecycle="active_draft")
    return session


if __name__ == "__main__":
    unittest.main()
