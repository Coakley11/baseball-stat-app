"""Phone order of the Shared drafting screen follows Solo (step 5).

The Shared drafting screen draws the clock, Team Needs, cards and Manual Pick into top-of-page
slots, already in Solo's order. On phones (CSS only): the clock slot takes the clock tier, the
Manual Pick slot takes the action tier as Solo's early Manual Draft does, and the slim control bar
takes no tier (the ldr-m-controls hook would lift it above Team Needs and the cards).
Verified in a browser at 390 px; these checks keep the rules in place.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import live_draft_mobile_layout as L

APP = (Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text(encoding="utf-8")


def _rule_selectors(css: str, order: int) -> list[str]:
    selectors: list[str] = []
    for m in re.finditer(r"([^{}]+)\{\s*order:\s*(-?\d+);\s*\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
        if int(m.group(2)) == order:
            selectors += [s.strip() for s in m.group(1).split(",")]
    return selectors


class SharedDraftPhoneOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = L.live_draft_mobile_css()

    def test_shared_clock_slot_takes_the_clock_tier(self) -> None:
        clock = _rule_selectors(self.css, L.ORDER_CLOCK)
        self.assertTrue(any(s.endswith('> *:has(iframe[srcdoc*="live-draft-on-clock"])') for s in clock), clock)

    def test_shared_manual_pick_slot_takes_the_action_tier_but_not_the_columns_block(self) -> None:
        action = _rule_selectors(self.css, L.ORDER_ACTION)
        slot_rule = [s for s in action if ":not(:has(" in s]
        self.assertEqual(len(slot_rule), 1, action)
        self.assertIn(f"st-key-{L.ACTION_KEY}", slot_rule[0])
        self.assertIn(f"st-key-{L.RECS_KEY}", slot_rule[0])  # the cards' block is excluded

    def test_slim_control_bar_has_no_phone_tier(self) -> None:
        idx = APP.index('_ldr_m_hook("ldr-m-controls")')
        self.assertIn("if not _shared_drafting_view else", APP[idx : idx + 120])


if __name__ == "__main__":
    unittest.main()
