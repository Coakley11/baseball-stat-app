"""Why Recommended leads with the most actionable reason (owner review, 2026-11-08).

A strong hitter's projection lines used to fill the 4-bullet cap, so "Fills your remaining SS starter slot" was
cut. Now the order is: a required roster slot first, then a weak category it helps, then value against the
market, then the projections. A multi-position player is credited for any open position they're listed at.
"""

import re
import unittest

import pandas as pd

from live_draft_room_ui import build_rec_card_detail_body


def _bullets(row, **kw):
    return re.findall(r"<li>(.*?)</li>", build_rec_card_detail_body(pd.Series(row), **kw))


STAR = {"fullName": "Star Shortstop", "Primary Position": "SS", "proj_HR": 32, "proj_RBI": 100, "proj_R": 110,
        "proj_SB": 35, "proj_BA": 0.290, "Expected Fantasy Value": 0.95, "Model Rank": 3, "Market Rank": 12}


class WhyRecommendedPriorityTests(unittest.TestCase):
    def test_the_open_slot_comes_first_and_is_never_cut(self) -> None:
        b = _bullets(STAR, gaps=["SS", "OF"])
        self.assertEqual(b[0], "Fills your remaining SS starter slot")
        self.assertLessEqual(len(b), 4)

    def test_a_multi_position_player_fills_an_open_listed_position(self) -> None:
        b = _bullets({**STAR, "Primary Position": "2B", "Positions": "2B/SS"}, gaps=["SS"])
        self.assertEqual(b[0], "Fills your remaining SS starter slot")
        b2 = _bullets({**STAR, "Primary Position": "2B"}, gaps=["SS"])  # 2B only: no SS claim
        self.assertNotIn("Fills your remaining SS starter slot", b2)

    def test_value_and_category_help_come_before_projection_lines(self) -> None:
        b = _bullets(STAR, gaps=[], category_needs=["SB"])
        self.assertIn("directly improves your weakest category", b[0])
        self.assertTrue(b[1].startswith("Model ranks Star Shortstop"))

    def test_no_gendered_pronoun_in_the_value_line(self) -> None:
        text = " ".join(_bullets(STAR, gaps=[]))
        self.assertNotIn("ranks him", text)


if __name__ == "__main__":
    unittest.main()
