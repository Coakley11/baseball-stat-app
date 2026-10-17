"""Fantasy screens use one slot rule: what Recommended Starters suggests, Save Lineup accepts.

Before: the Lineup Assistant's recommended starters and the Waiver Wire position filter used
the older token rule (1B<->3B and 2B<->SS interchangeable, primary position only), while the
lineup board and Save Lineup used Phase D3 games-played eligibility.
"""

from __future__ import annotations

import random
import unittest

import pandas as pd

from fantasy_lineup_scoring import build_lineup_assistant_scores, build_position_aware_lineup
from fantasy_slot_eligibility import enrich_lineup_roster_positions, filter_players_by_fantasy_position
from fantasy_weekly_lineup import player_eligible_for_slot, position_tokens_from_row


def _row(name, primary, eligible, hr):
    return {"Player": name, "Team": "A", "Primary Position": primary, "Eligible Positions": eligible,
            "AB": 100, "H": 25, "HR": hr, "RBI": hr * 3, "R": hr * 3, "SB": 1, "BA": 0.25, "OPS": 0.7 + hr / 100}


class RecommendedStartersTests(unittest.TestCase):
    def _recommend(self, rows, slots):
        scored = enrich_lineup_roster_positions(build_lineup_assistant_scores(pd.DataFrame(rows), "5x5 Roto"))
        return build_position_aware_lineup(scored, slots=slots)

    def test_first_baseman_is_not_recommended_at_third(self):
        pkg = self._recommend([_row("Michael Busch", "1B", "1B", 20), _row("Pete Alonso", "1B", "1B", 30)], ["1B", "3B"])
        self.assertEqual(pkg["lineup_df"]["Player"].tolist(), ["Pete Alonso"])
        self.assertEqual(pkg["missing_slots"], ["3B"])

    def test_games_played_eligibility_is_used(self):
        pkg = self._recommend([_row("George Springer", "DH", "OF, DH", 20), _row("Cal Raleigh", "C", "C", 40)], ["C", "OF"])
        self.assertEqual(dict(zip(pkg["lineup_df"]["Fantasy slot"], pkg["lineup_df"]["Player"])),
                         {"C": "Cal Raleigh", "OF1": "George Springer"})

    def test_every_recommended_starter_passes_the_save_rule(self):
        rng = random.Random(7)
        options = [("C", "C"), ("1B", "1B"), ("1B", "1B, 3B"), ("2B", "2B, SS"), ("SS", "SS"), ("3B", "3B"),
                   ("OF", "OF"), ("DH", "OF, DH"), ("DH", "DH"), ("2B", "2B")]
        slots = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"]
        for trial in range(200):
            rows = [_row(f"P{trial}-{i}", *rng.choice(options), rng.randint(0, 40)) for i in range(rng.randint(3, 14))]
            pkg = self._recommend(rows, slots)
            for _, r in pkg["lineup_df"].iterrows():
                slot = "OF" if str(r["Fantasy slot"]).startswith("OF") else str(r["Fantasy slot"])
                self.assertTrue(player_eligible_for_slot(position_tokens_from_row(r), slot), (r["Player"], slot))


class PositionFilterTests(unittest.TestCase):
    def setUp(self):
        self.pool = enrich_lineup_roster_positions(pd.DataFrame([
            _row("First Only", "1B", "1B", 10), _row("Corner", "1B", "1B, 3B", 10), _row("Third", "3B", "3B", 10),
            _row("Second Only", "2B", "2B", 10), _row("Springer", "DH", "OF, DH", 10),
        ]))

    def test_waiver_filter_uses_the_fantasy_rule(self):
        names = lambda choice: sorted(filter_players_by_fantasy_position(self.pool, choice, strict=True)["Player"])
        self.assertEqual(names("3B"), ["Corner", "Third"])
        self.assertEqual(names("SS"), [])
        self.assertEqual(names("OF"), ["Springer"])

    def test_research_filter_is_unchanged(self):
        names = lambda choice: sorted(filter_players_by_fantasy_position(self.pool, choice)["Player"])
        self.assertEqual(names("3B"), ["Corner", "First Only", "Third"])  # older shortcut kept for research pages
        self.assertEqual(names("SS"), ["Second Only"])


if __name__ == "__main__":
    unittest.main()
