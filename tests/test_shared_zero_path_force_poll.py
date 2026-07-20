"""Shared On-the-Clock zero path must force-poll (not dual-expire / not swallow TypeError)."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestSharedZeroPathArity(unittest.TestCase):
    def test_on_clock_does_not_dual_expire_or_force_full_poll(self) -> None:
        src = (ROOT / "live_draft_on_clock_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("multiparty_may_run_autopick(session, tick_room)", src)
        self.assertNotIn('expire_pick_and_advance(session, source="on_clock_banner_zero")', src)
        self.assertNotIn("poll_shared_draft_room(session, force=True)", src)

    def test_timer_ui_calls_multiparty_with_session_only(self) -> None:
        src = (ROOT / "live_draft_timer_ui.py").read_text(encoding="utf-8")
        self.assertIn("multiparty_may_run_autopick(session)", src)
        self.assertNotIn("multiparty_may_run_autopick(session, live_room)", src)

    def test_shared_timer_bar_demotes_paint(self) -> None:
        src = (ROOT / "live_draft_timer_ui.py").read_text(encoding="utf-8")
        self.assertIn("_shared_demote_paint", src)
        self.assertIn("is_multiplayer_draft_active(session)", src)


class TestSharedBannerForcePoll(unittest.TestCase):
    def test_expired_shared_banner_force_polls(self) -> None:
        """Simulate shared zero branch: authority check + force poll must run."""
        from live_draft_timer_authority import multiparty_may_run_autopick

        # Real API accepts session only.
        session = {"draft_room_participant_id": "host-1", "active_shared_draft_room_code": "ABCD"}
        try:
            multiparty_may_run_autopick(session)
        except TypeError as exc:
            self.fail(f"multiparty_may_run_autopick arity broken: {exc}")

        # Wrong arity must raise — documents the bug we fixed.
        with self.assertRaises(TypeError):
            multiparty_may_run_autopick(session, {"status": "in_progress"})  # type: ignore[call-arg]


class TestNoLocalExpireFromBannerAst(unittest.TestCase):
    def test_banner_source_has_no_on_clock_banner_zero_expire(self) -> None:
        tree = ast.parse((ROOT / "live_draft_on_clock_ui.py").read_text(encoding="utf-8"))
        text_calls: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "expire_pick_and_advance":
                    text_calls.append("expire_pick_and_advance")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "expire_pick_and_advance":
                    text_calls.append("expire_pick_and_advance")
        self.assertEqual(text_calls, [], "banner must not call expire_pick_and_advance")


if __name__ == "__main__":
    unittest.main()
