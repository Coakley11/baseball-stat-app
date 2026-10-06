"""The Ready-time Solo clock prewarm mount must be inert.

Prewarming exists only to pay Streamlit's component-registration round-trip
while the timer is off, so the real on-clock paint does not land with a keyed
container and no iframe child (measured at +4.2s on a fresh process before the
fix). Browser runs confirm the mount is height-zero, textless and digit-free
during Ready; these tests pin the structural reasons it CANNOT do anything else,
so the guarantee survives refactors:

  it cannot tick            the frontend clears the tick and returns before paint()
  it cannot expire          emitExpire is gated behind a non-empty token, and the
                            prewarm call passes expire_token=""
  it cannot own a deadline  deadline=0.0 and clock_seconds=0
  it is a separate element  its own key prefix, so it is never mistaken for the
                            real clock by CSS or by a test selector
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from solo_live_clock_component import (
    solo_live_clock_prewarm_key,
    solo_live_clock_widget_key,
)

_PKG = Path(__file__).resolve().parents[1] / "solo_live_clock_component"
_INIT = (_PKG / "__init__.py").read_text(encoding="utf-8")
_FRONTEND = (_PKG / "frontend" / "index.html").read_text(encoding="utf-8")


def _prewarm_call_kwargs() -> dict[str, ast.expr]:
    """The _COMPONENT(...) call inside prewarm_solo_live_clock."""
    tree = ast.parse(_INIT)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "prewarm_solo_live_clock")
    call = next(n for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_COMPONENT")
    return {kw.arg: kw.value for kw in call.keywords if kw.arg}


class PrewarmCallIsInertTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kw = _prewarm_call_kwargs()

    def test_marks_itself_as_prewarm(self) -> None:
        self.assertIn("prewarm", self.kw)
        self.assertIs(ast.literal_eval(self.kw["prewarm"]), True)

    def test_cannot_emit_an_expire_event(self) -> None:
        """emitExpire is gated behind a truthy token; prewarm passes an empty one."""
        self.assertEqual(ast.literal_eval(self.kw["expire_token"]), "")
        self.assertIn("if (sec <= 0 && token) {", _FRONTEND)

    def test_carries_no_deadline_authority(self) -> None:
        self.assertEqual(float(ast.literal_eval(self.kw["deadline"])), 0.0)
        self.assertEqual(int(ast.literal_eval(self.kw["clock_seconds"])), 0)

    def test_registers_no_callback(self) -> None:
        """The real clock passes on_change; the prewarm mount must not."""
        self.assertNotIn("on_change", self.kw)

    def test_does_not_mutate_draft_state(self) -> None:
        tree = ast.parse(_INIT)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "prewarm_solo_live_clock")
        src = ast.get_source_segment(_INIT, fn) or ""
        for banned in ("live_draft_room", "expire_current_pick_and_advance",
                       "live_draft_reset_timer", "process_solo_component_wake",
                       "session[", "timer_deadline"):
            self.assertNotIn(banned, src, banned)


class PrewarmFrontendTests(unittest.TestCase):
    def test_prewarm_branch_returns_before_painting(self) -> None:
        start = _FRONTEND.index("if (props.prewarm === true")
        branch = _FRONTEND[start:start + 700]
        body = branch[:branch.index("return;")]
        self.assertIn("clearTick();", body)
        self.assertIn('setFrameHeight", { height: 0 }', body)
        self.assertNotIn("paint(", body)


class PrewarmIdentityTests(unittest.TestCase):
    def test_prewarm_key_is_distinct_from_the_real_clock_key(self) -> None:
        warm, live = solo_live_clock_prewarm_key("ABC123"), solo_live_clock_widget_key("ABC123")
        self.assertNotEqual(warm, live)
        self.assertTrue(warm.startswith("solo_live_clock_prewarm_"))
        self.assertFalse(live.startswith("solo_live_clock_prewarm_"))
        # The real clock's prefix is a substring of the prewarm key, which is why
        # every selector for the real clock has to exclude the prewarm prefix.
        self.assertTrue(warm.startswith("solo_live_clock_"))

    def test_prewarm_container_is_collapsed_every_run(self) -> None:
        """A once-only <style> disappears on later reruns (measured 0 -> 40 -> 26),
        so the collapse must not sit behind a session flag."""
        self.assertIn('[class*="st-key-solo_live_clock_prewarm_"]{', _INIT)
        self.assertIn("height:0!important", _INIT)
        fn_src = _INIT[_INIT.index("def prewarm_solo_live_clock"):]
        fn_src = fn_src[:fn_src.index("\ndef ")]
        self.assertFalse(re.search(r"if .*session_state\.get\(.*prewarm.*\)", fn_src))


if __name__ == "__main__":
    unittest.main()
