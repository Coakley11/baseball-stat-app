"""U1B: answer text is built only from the rows the page ranked, scoped to what was shown."""

from __future__ import annotations

import unittest

import pandas as pd

import u1_answers as a

SEASONS = pd.DataFrame([
    {"fullName": "Aaron Judge", "yearID": 2022, "HR": 62, "RBI": 131, "BA": 0.311, "OPS": 1.111,
     "teamHistoricalName": "New York Yankees", "displayPosition": "OF"},
    {"fullName": "Shohei Ohtani", "yearID": 2024, "HR": 54, "RBI": 130, "BA": 0.310, "OPS": 1.036,
     "teamHistoricalName": "Los Angeles Dodgers", "displayPosition": "DH"},
    {"fullName": "Pete Alonso", "yearID": 2019, "HR": 53, "RBI": 120, "BA": 0.260, "OPS": 0.941,
     "teamHistoricalName": "New York Mets", "displayPosition": "1B"},
])


class SeasonAnswerTests(unittest.TestCase):
    def test_counting_stat(self):
        r = a.season_answer(SEASONS, "HR", (2010, 2025), team_col="teamHistoricalName")
        self.assertEqual(r["headline"], "Aaron Judge, 2022: 62 home runs")
        self.assertEqual(r["body"], "Aaron Judge's 62 home runs in 2022 are the most among the 3 seasons shown "
                                    "(2010–2025). Next: Shohei Ohtani (2024), 54.")
        self.assertEqual(r["context"], "2022 · New York Yankees · OF")
        self.assertEqual([t[0] for t in r["tiles"]], ["HR", "RBI", "AVG", "OPS"])
        self.assertEqual(r["player"], "Aaron Judge")

    def test_rate_stat_and_ascending(self):
        by_ba = SEASONS.sort_values("BA", ascending=False)
        r = a.season_answer(by_ba, "BA", (2019, 2024))
        self.assertIn(".311 batting average in 2022 is the highest", r["body"])
        asc = SEASONS.sort_values("HR")
        r = a.season_answer(asc, "HR", (2019, 2024), ascending=True)
        self.assertIn("are the fewest", r["body"])

    def test_tie_and_empty(self):
        tied = SEASONS.assign(HR=[62, 62, 50])
        self.assertIn("Tied with Shohei Ohtani", a.season_answer(tied, "HR", (2010, 2025))["body"])
        self.assertIsNone(a.season_answer(SEASONS.iloc[0:0], "HR", (2010, 2025)))
        self.assertIsNone(a.season_answer(SEASONS, "XYZ", (2010, 2025)))

    def test_possessive_and_last_name(self):
        r = a.season_answer(SEASONS.assign(fullName=["Chris Davis", "B", "C"]), "HR", (2010, 2025))
        self.assertTrue(r["body"].startswith("Chris Davis' 62"))
        self.assertEqual(a.last_name("Bobby Witt Jr."), "Witt")
        self.assertEqual(a.last_name("Vladimir Guerrero Jr"), "Guerrero")


class LeaderboardAnswerTests(unittest.TestCase):
    def test_score_explains_weights(self):
        rows = SEASONS.assign(score=[300.0, 290.5, 250.0])
        r = a.leaderboard_answer(rows, "score", (2020, 2025), weights={"HR": 1.0, "RBI": 1.0, "SB": 1.0, "BA": 0.0})
        self.assertEqual(r["headline"], "Aaron Judge leads 2020–2025 in score: 300")
        self.assertIn("Ahead of Shohei Ohtani (290.5) and Pete Alonso (250)", r["body"])
        self.assertIn("Score adds up HR + RBI + SB over 2020–2025.", r["body"])
        self.assertNotIn("×100", r["body"])
        r = a.leaderboard_answer(rows, "score", (2020, 2025), weights={"HR": 2.0, "OPS": 1.0})
        self.assertIn("2× HR + OPS", r["body"])
        self.assertIn("rate stats count ×100", r["body"])

    def test_rate_stat(self):
        r = a.leaderboard_answer(SEASONS.sort_values("OPS", ascending=False), "OPS", (2020, 2025))
        self.assertIn("OPS from each player's combined totals over 2020–2025.", r["body"])
        self.assertEqual(r["podium"][0], {"rank": 1, "name": "Aaron Judge", "value": "1.111"})


class QualificationTextTests(unittest.TestCase):
    def test_reads_the_same_state_as_the_minimum_control(self):
        import rate_stat_qualification as rsq

        session = {rsq.ab_min_key("leaders"): 2349, rsq.mode_key("leaders"): rsq.MODE_AUTO}
        self.assertEqual(a.qualification_text(session, "leaders", "OPS", (2020, 2025)),
                         "Qualified hitters · at least 2,349 AB over 2020–2025")
        self.assertEqual(a.qualification_text(session, "leaders", "HR", (2020, 2025)), "")
        session[rsq.mode_key("leaders")] = rsq.MODE_MANUAL
        self.assertTrue(a.qualification_text(session, "leaders", "OPS", (2020, 2025)).startswith("Minimum you set"))
        hist = {rsq.ab_min_key("hist"): 437}
        self.assertEqual(a.qualification_text(hist, "hist", "BA", (2010, 2025), per_season=True),
                         "Qualified seasons · at least 437 AB in the season")
        self.assertIn("No at-bat minimum", a.qualification_text({}, "hist", "BA", (2010, 2025)))


if __name__ == "__main__":
    unittest.main()
