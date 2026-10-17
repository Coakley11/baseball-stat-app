"""Multi-position eligibility from games played — one rule for Lineup, Waivers, Trades and
roster completeness; no assumed substitutions."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from fantasy_position_eligibility import (
    ELIGIBLE_COL,
    MIN_GAMES,
    attach_eligible_positions,
    build_eligibility_map,
    eligible_positions_from_row,
    positions_from_games,
    prior_season_lahman_positions,
    split_positions,
)

SPRINGER = 543807
# Current season: DH 118, LF 2. Prior season (Lahman): OF 67.
CURRENT = {
    SPRINGER: {"games": {"DH": 118, "LF": 2}, "birth_date": "1989-09-19", "name": "George Springer"},
    1: {"games": {"1B": 160}, "birth_date": "1997-11-09", "name": "Michael Busch"},
    2: {"games": {"SS": 9, "2B": 30}, "birth_date": "2000-01-01", "name": "Nine Games"},
    3: {"games": {"RF": 5, "LF": 6}, "birth_date": "2001-02-02", "name": "Split Outfielder"},
}
PRIOR = {("1989-09-19", "springer", "g"): {"OF": 67}}


class EligibilityRuleTests(unittest.TestCase):
    def test_threshold_is_games_played_at_the_position(self):
        self.assertEqual(MIN_GAMES, 10)
        self.assertEqual(positions_from_games({"SS": 9, "2B": 30}), {"2B"})
        self.assertEqual(positions_from_games({"RF": 5, "LF": 6}), {"OF"})  # outfield spots add up

    def test_prior_season_counts_only_with_an_exact_person_match(self):
        elig = build_eligibility_map(2026, current=CURRENT, prior=PRIOR)
        self.assertEqual(elig[SPRINGER], {"DH", "OF"})
        other = build_eligibility_map(2026, current={SPRINGER: {**CURRENT[SPRINGER], "birth_date": "1989-09-20"}}, prior=PRIOR)
        self.assertEqual(other[SPRINGER], {"DH"})  # birth date differs -> no prior-season positions

    def test_attach_keeps_primary_and_never_guesses(self):
        stats = pd.DataFrame([
            {"Player": "George Springer", "MLBAM ID": SPRINGER, "Primary Position": "DH"},
            {"Player": "Michael Busch", "MLBAM ID": 1, "Primary Position": "1B"},
            {"Player": "No Fielding Data", "MLBAM ID": 999, "Primary Position": "3B"},
        ])
        out = attach_eligible_positions(stats, build_eligibility_map(2026, current=CURRENT, prior=PRIOR))
        self.assertEqual(list(out[ELIGIBLE_COL]), ["OF, DH", "1B", "3B"])

    def test_row_reading_and_normalisation(self):
        self.assertEqual(split_positions("LF/CF, ss"), ["OF", "SS"])
        self.assertEqual(eligible_positions_from_row({ELIGIBLE_COL: "OF, DH", "Primary Position": "DH"}), {"OF", "DH"})
        self.assertEqual(eligible_positions_from_row({"Primary Position": "TWP"}), {"DH"})

    def test_lahman_prior_season_source(self):
        prior = prior_season_lahman_positions(2025)
        self.assertEqual(prior[("1989-09-19", "springer", "g")].get("OF"), 67)


class SlotRuleTests(unittest.TestCase):
    def test_no_assumed_substitutions(self):
        from fantasy_weekly_lineup import player_eligible_for_slot

        self.assertFalse(player_eligible_for_slot(["1B"], "3B"))  # was allowed: "1B can play 3B"
        self.assertFalse(player_eligible_for_slot(["SS"], "2B"))  # was allowed: "SS can play 2B"
        self.assertTrue(player_eligible_for_slot(["1B", "3B"], "3B"))
        self.assertTrue(player_eligible_for_slot(["DH"], "UTIL"))
        self.assertFalse(player_eligible_for_slot(["DH"], "OF"))
        self.assertTrue(player_eligible_for_slot(["DH", "P"], "UTIL"))  # two-way player is a hitter
        self.assertFalse(player_eligible_for_slot(["P"], "UTIL"))


ROSTER = pd.DataFrame([
    {"Player": "Cal Raleigh", "Primary Position": "C", ELIGIBLE_COL: "C, DH"},
    {"Player": "George Springer", "Primary Position": "DH", ELIGIBLE_COL: "OF, DH"},
    {"Player": "Michael Busch", "Primary Position": "1B", ELIGIBLE_COL: "1B"},
])


class SharedConsumerTests(unittest.TestCase):
    def test_lineup_validation_uses_eligibility(self):
        from fantasy_weekly_lineup import validate_weekly_lineup

        ok = validate_weekly_lineup(["C", "OF", "1B"], {"C": "Cal Raleigh", "OF": "George Springer", "1B": "Michael Busch"}, ROSTER)
        self.assertTrue(ok["ok"], ok)
        bad = validate_weekly_lineup(["C", "OF", "3B"], {"C": "Cal Raleigh", "OF": "George Springer", "3B": "Michael Busch"}, ROSTER)
        self.assertIn("Michael Busch is not eligible for Third Base.", bad["messages"])

    def test_waiver_positions_use_eligibility(self):
        from fantasy_waiver_wire import _player_eligible_at

        self.assertTrue(_player_eligible_at(ROSTER.iloc[1], "OF"))

    def test_roster_completeness_uses_eligibility(self):
        from fantasy_roster_validation import missing_positions_for_roster

        self.assertEqual(missing_positions_for_roster(ROSTER, {"C": 1, "OF": 1, "1B": 1, "DH": 0}), [])
        self.assertEqual(missing_positions_for_roster(ROSTER, {"C": 1, "OF": 1, "3B": 1}), ["3B"])

    def test_trade_warnings_use_eligibility(self):
        from fantasy_trade_legality import trade_roster_warnings

        ctx = {
            "my_team_name": "A",
            "league_rosters": {
                "A": {"players": [{"player_name": "George Springer", "positions": ["DH"]}, {"player_name": "Juan Soto", "positions": ["OF"]}]},
                "B": {"players": [{"player_name": "Will Smith", "positions": ["C"]}, {"player_name": "Kyle Tucker", "positions": ["OF"]}]},
            },
            "roster_settings": {"roster_slots": {"C": 1, "OF": 1}, "slot_instances": []},
        }
        trade = dict(proposer_team="A", recipient_team="B", proposer_gives=["Juan Soto"], proposer_receives=["Will Smith"])
        # Stored as DH only, Springer cannot take over OF once Soto leaves...
        b_loses_catcher = "This trade leaves B without an eligible C for the required lineup."
        self.assertEqual(trade_roster_warnings(ctx, **trade, stats_pool=None),
                         ["This trade leaves your team without an eligible OF for the required lineup.", b_loses_catcher])
        # ...but with his games-played eligibility (OF last season) the lineup stays legal.
        stats = pd.DataFrame([{"Player": "George Springer", "Primary Position": "DH", ELIGIBLE_COL: "OF, DH"}])
        self.assertEqual(trade_roster_warnings(ctx, **trade, stats_pool=stats), [b_loses_catcher])


class FeedWiringTests(unittest.TestCase):
    def _payload(self):
        return {"stats": [{"splits": [{"player": {"fullName": "George Springer", "id": SPRINGER, "primaryPosition": {"abbreviation": "DH"}},
                                         "team": {"name": "Toronto Blue Jays"}, "stat": {"atBats": 400, "hits": 100, "homeRuns": 20}}]}]}

    def test_feed_attaches_eligible_positions(self):
        import mlb_hitter_stats

        resp = mock.Mock(); resp.json.return_value = self._payload(); resp.raise_for_status.return_value = None
        with mock.patch("requests.get", return_value=resp), \
                mock.patch("fantasy_position_eligibility.eligibility_for_season", return_value={SPRINGER: {"DH", "OF"}}):
            df = mlb_hitter_stats.fetch_mlb_api_hitter_stats(2026)
        self.assertEqual(df.loc[0, ELIGIBLE_COL], "OF, DH")

    def test_feed_survives_an_eligibility_failure(self):
        import mlb_hitter_stats

        resp = mock.Mock(); resp.json.return_value = self._payload(); resp.raise_for_status.return_value = None
        with mock.patch("requests.get", return_value=resp), \
                mock.patch("fantasy_position_eligibility.eligibility_for_season", side_effect=RuntimeError("offline")):
            df = mlb_hitter_stats.fetch_mlb_api_hitter_stats(2026)
        self.assertEqual(df.loc[0, "Primary Position"], "DH")
        self.assertNotIn(ELIGIBLE_COL, df.columns)


if __name__ == "__main__":
    unittest.main()
