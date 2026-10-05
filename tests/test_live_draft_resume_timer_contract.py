"""Resume Draft timer-restoration contract.

History worth keeping: Resume was briefly suspected of losing clicks. It was
not. Resume is ``type="primary"`` WITH ``help=``, so Streamlit renders two
matching buttons -- the real 236x40 control inside ``stTooltipHoverTarget`` and
a 0x0 clone whose ``offsetParent`` is null. Measured on a live paused room:

    plain Playwright .click()  -> returns OK, handler never runs, room stays paused (rev 8->8)
    .click(force=True)         -> handler runs, room resumes in_progress     (rev 8->9)

So the product was correct and the automation was clicking a non-delivering
target; the harness now forces the click. The repo documents the same trap for
the Solo Start button ("Streamlit clones a hidden primary button into the
tooltip hover target, and Playwright often clicks the invisible twin").

These tests therefore pin the *timer-restoration semantics* Resume must keep --
the part that is real product behavior -- rather than a widget-wiring style.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CC = _REPO / "live_draft_control_center_ui.py"


class ResumeTimerRestorationTests(unittest.TestCase):
    def test_resume_restores_deadline_from_paused_remainder(self) -> None:
        """paused -> Resume -> in_progress keeps the remaining time, not a full clock."""
        from live_draft_timer_logic import live_draft_resume_timer

        room = {
            "draft_room_id": "R1",
            "status": "paused",
            "config": {"timer_seconds": 60},
            "timer_deadline": None,
            "timer_started_at": None,
            "paused_remaining_seconds": 26,
            "current_pick_index": 4,
        }
        before = time.time()
        live_draft_resume_timer(room, int(room["paused_remaining_seconds"]))
        after = time.time()

        self.assertEqual(room["status"], "in_progress")
        self.assertIsNotNone(room["timer_deadline"])
        # ~26s out, NOT reset to the configured 60s.
        self.assertGreaterEqual(room["timer_deadline"], before + 25)
        self.assertLessEqual(room["timer_deadline"], after + 27)
        # Remainder consumed so a later resume cannot reuse a stale value.
        self.assertIsNone(room["paused_remaining_seconds"])
        self.assertEqual(room["timer_handled_index"], -1)

    def test_resume_falls_back_to_configured_timer_when_remainder_missing(self) -> None:
        """Observed live: a paused room can carry paused_remaining_seconds=None."""
        from live_draft_timer_logic import live_draft_resume_timer

        room = {"status": "paused", "config": {"timer_seconds": 45}}
        cfg = dict(room.get("config") or {})
        # Mirrors the handler's own expression.
        pause_left = int(room.get("paused_remaining_seconds") or cfg.get("timer_seconds", 60))
        self.assertEqual(pause_left, 45)
        live_draft_resume_timer(room, pause_left)
        self.assertEqual(room["status"], "in_progress")
        self.assertIsNotNone(room["timer_deadline"])

    def test_paused_room_reports_paused_display_seconds(self) -> None:
        from live_draft_timer_logic import live_draft_display_seconds

        self.assertEqual(
            live_draft_display_seconds(
                {"status": "paused", "paused_remaining_seconds": 26, "config": {"timer_seconds": 60}}
            ),
            26,
        )


class ResumeControlContractTests(unittest.TestCase):
    """Guard the one real wiring invariant: Resume stays commissioner+paused gated."""

    def test_resume_button_keeps_commissioner_and_paused_gate(self) -> None:
        import ast

        src = _CC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        target = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name != "button":
                continue
            for kw in node.keywords:
                if (
                    kw.arg == "key"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value == "live_draft_resume"
                ):
                    target = node
        self.assertIsNotNone(target, "st.button(key='live_draft_resume') not found")
        disabled = next(
            (ast.unparse(kw.value) for kw in target.keywords if kw.arg == "disabled"), ""
        )
        self.assertIn("paused", disabled)
        self.assertIn("is_commissioner", disabled)


if __name__ == "__main__":
    unittest.main()
