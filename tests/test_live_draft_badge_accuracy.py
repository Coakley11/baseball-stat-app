"""Recommendation badges must reflect the real data and draft context (owner review, 2026-11-08).

Before this fix:
* Elite/Strong Power and Speed Boost were judged only against the 6–8 cards, so a 15-HR hitter could be "Elite Power".
* High Player Grade compared a ×100 value with the raw 0–1 column, so nearly every card qualified.
* High AVG read the historical BA instead of the projection (proj_BA).
* "Best Available SS" looked only at primary position among the cards.
The labels are unchanged, each card still shows at most two badges, and every badge has a tooltip.
"""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_rec_badges import badge_tooltip, build_smart_recommendation_badges


def _labels(row, rec, pool=None, **kw):
    return [b[0] for b in build_smart_recommendation_badges(1, row, rec, pool_df=pool, **kw)]


def _pool(hrs, extra=None) -> pd.DataFrame:
    rows = [{"fullName": f"P{i}", "Primary Position": "OF", "proj_HR": hr, "Decision Score": 1 - i / 100,
             "Expected Fantasy Value": 0.5} for i, hr in enumerate(hrs)]
    return pd.DataFrame(rows + (extra or []))


class BadgeAccuracyTests(unittest.TestCase):
    def test_a_15_hr_hitter_is_not_elite_power_even_when_he_leads_the_cards(self) -> None:
        cards = _pool([15, 12, 10, 9, 8, 7])
        self.assertNotIn("Elite Power", _labels(cards.iloc[0], cards))
        self.assertNotIn("Strong Power", _labels(cards.iloc[0], cards))

    def test_elite_power_is_relative_to_the_whole_available_pool(self) -> None:
        pool = _pool([46, 41, 38, 35, 33, 30, 28, 25, 22, 20, 18, 15, 12, 10, 8, 6, 5, 4, 3, 2])
        cards = pool.iloc[[3, 6, 9]]  # 35, 28, 20 HR
        self.assertIn("Elite Power", _labels(pool.iloc[0], pool.head(6), pool))   # 46 HR
        self.assertNotIn("Elite Power", _labels(cards.iloc[0], cards, pool))      # 35 HR: top of the cards only
        self.assertIn("Strong Power", _labels(cards.iloc[0], cards, pool))

    def test_high_player_grade_follows_the_displayed_grade(self) -> None:
        cards = pd.DataFrame([{"fullName": n, "Primary Position": "1B", "Expected Fantasy Value": g, "Decision Score": d}
                              for n, g, d in (("Good", 0.92, 0.9), ("Mid", 0.6, 0.8), ("Worst", 0.30, 0.7))])
        self.assertIn("High Player Grade", _labels(cards.iloc[0], cards))
        self.assertNotIn("High Player Grade", _labels(cards.iloc[2], cards))
        self.assertNotIn("High Player Grade", _labels(cards.iloc[1], cards))

    def test_high_avg_uses_the_projection(self) -> None:
        row = pd.Series({"fullName": "Contact", "Primary Position": "2B", "proj_BA": 0.305, "BA": 0.240,
                         "Expected Fantasy Value": 0.5})
        self.assertIn("High AVG", _labels(row, pd.DataFrame([row])))
        row2 = pd.Series({"fullName": "Old", "Primary Position": "2B", "proj_BA": 0.240, "BA": 0.310,
                          "Expected Fantasy Value": 0.5})
        self.assertNotIn("High AVG", _labels(row2, pd.DataFrame([row2])))

    def test_best_available_ss_is_the_top_eligible_available_shortstop(self) -> None:
        pool = pd.DataFrame([
            {"fullName": "Multi", "Primary Position": "2B", "Positions": "2B/SS", "Decision Score": 0.90},
            {"fullName": "PureSS", "Primary Position": "SS", "Decision Score": 0.60},
        ])
        cards = pool.iloc[[1]]  # only PureSS is among the cards
        # A better SS-eligible player (2B/SS) is still available, so PureSS isn't "Best Available SS".
        self.assertNotIn("Best Available SS", _labels(cards.iloc[0], cards, pool, gaps=["SS"]))
        # Once that player is gone, PureSS really is the best available shortstop.
        rest = pool.iloc[[1]]
        self.assertIn("Best Available SS", _labels(rest.iloc[0], rest, rest, gaps=["SS"]))

    def test_at_most_two_badges_and_every_badge_explains_itself(self) -> None:
        pool = _pool([46, 41, 38, 35, 33, 30, 28, 25])
        row = pd.Series({"fullName": "Star", "Primary Position": "SS", "Positions": "SS/2B", "proj_HR": 45,
                         "proj_SB": 30, "proj_BA": 0.310, "Expected Fantasy Value": 0.95, "Decision Score": 0.99,
                         "Model Rank": 5, "Market Rank": 30})
        labels = _labels(row, pool, pool, gaps=["SS"])
        self.assertLessEqual(len(labels), 2)
        for label in labels + ["Elite Power", "Model Bargain", "Best Available SS", "Fills OF Need", "Speed Boost",
                               "High AVG", "High Player Grade", "Strong Power"]:
            self.assertTrue(badge_tooltip(label), label)

    def test_model_bargain_scales_with_draft_position(self) -> None:
        early = pd.Series({"fullName": "E", "Primary Position": "OF", "Model Rank": 5, "Market Rank": 16,
                           "Expected Fantasy Value": 0.5})
        late = pd.Series({"fullName": "L", "Primary Position": "OF", "Model Rank": 239, "Market Rank": 250,
                          "Expected Fantasy Value": 0.5})
        self.assertIn("Model Bargain", _labels(early, pd.DataFrame([early])))       # 11 spots at pick 16
        self.assertNotIn("Model Bargain", _labels(late, pd.DataFrame([late])))      # 11 spots at pick 250


if __name__ == "__main__":
    unittest.main()
