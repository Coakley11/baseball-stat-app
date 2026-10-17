"""U2 answer builders: every claim comes from the page's own rows, ties and neutral trends are
worded honestly, and nothing declares an overall winner."""

import unittest

import pandas as pd

import u2_answers as u2a


def _career(**cols):
    return pd.DataFrame(cols)


class ComparisonAnswerTests(unittest.TestCase):
    def test_leaders_by_metric_and_no_overall_winner(self):
        career = _career(fullName=["Aaron Judge", "Juan Soto"], HR=[312, 244], RBI=[706, 697], SB=[56, 95],
                         OBP=[0.415, 0.417], OPS=[1.035, 0.948], AB=[3479, 3857])
        ans = u2a.comparison_answer(career, seasons={"Aaron Judge": 8, "Juan Soto": 8}, span_text="2018–2025")
        self.assertEqual(ans["headline"], "Judge leads in HR, RBI and OPS; Soto leads in SB and OBP")
        self.assertIn("No overall winner", ans["body"])
        self.assertIn("Judge 8 seasons, 3,479 AB", ans["body"])
        self.assertNotIn("better player", ans["body"].lower())

    def test_ties_use_displayed_precision(self):
        career = _career(fullName=["A One", "B Two"], HR=[30, 30], RBI=[90, 80], SB=[5, 5], OBP=[0.3504, 0.3496], OPS=[0.8, 0.7], AB=[500, 500])
        ans = u2a.comparison_answer(career)
        self.assertIn("tied in HR, SB and OBP", ans["headline"])
        hr = next(g for g in ans["bars"] if g["label"] == "HR")
        self.assertFalse(any(r["lead"] for r in hr["rows"]), "a tie highlights nobody")

    def test_playing_time_note_only_when_at_bats_differ(self):
        career = _career(fullName=["A One", "B Two"], HR=[40, 20], RBI=[90, 80], SB=[5, 9], OBP=[0.35, 0.36], OPS=[0.8, 0.7], AB=[600, 300])
        body = u2a.comparison_answer(career)["body"]
        self.assertIn("One had 100% more at-bats", body)
        self.assertIn("are rates and adjust for playing time", body)

    def test_small_sample_flagged(self):
        career = _career(fullName=["A One", "B Two"], HR=[4, 20], RBI=[9, 80], SB=[1, 9], OBP=[0.45, 0.36], OPS=[1.0, 0.7], AB=[120, 500])
        self.assertIn("Small sample for One", u2a.comparison_answer(career)["body"])

    def test_needs_two_players(self):
        self.assertIsNone(u2a.comparison_answer(_career(fullName=["A One"], HR=[1])))
        one = u2a.single_player_summary({"fullName": "A One", "HR": 10, "OPS": 0.8, "AB": 300}, seasons=2, span_text="2024–2025")
        self.assertEqual(one["headline"], "A One, 2024–2025")
        self.assertIn("2 seasons", one["context"])


class CareerAnswerTests(unittest.TestCase):
    def setUp(self):
        self.rows = pd.DataFrame({
            "playerID": ["a", "b", "c"], "fullName": ["Mike Trout", "Bob X", "Cy Z"], "HR": [378, 300, 290],
            "G": [1593, 1500, 1400], "BA": [0.299, 0.25, 0.26], "OBP": [0.41, 0.30, 0.31], "SLG": [0.581, 0.4, 0.4],
            "RBI": [900, 800, 700], "SB": [200, 10, 5], "OPS": [0.991, 0.7, 0.71], "displayTeam": ["Angels", "", ""],
        })
        self.seasons = pd.DataFrame({"yearID": [2011, 2012, 2019, 2019], "HR": [5, 30, 20, 25]})

    def test_story_scoped_and_best_season_sums_stints(self):
        ans = u2a.career_answer(self.rows, "HR", (2010, 2025), seasons=self.seasons)
        self.assertEqual(ans["headline"], "Mike Trout: 378 home runs over 3 seasons (2011–2019)")
        self.assertIn("Best season for home runs: 45 in 2019", ans["body"])
        self.assertIn("Leads the 3 hitters shown for 2010–2025, ahead of Bob X (300) and Cy Z (290)", ans["body"])
        self.assertIn(".299 AVG / .410 OBP / .581 SLG", ans["body"])

    def test_no_best_season_for_rate_stats(self):
        self.assertNotIn("Best season", u2a.career_answer(self.rows, "OBP", (2010, 2025), seasons=self.seasons)["body"])

    def test_ties_say_tied(self):
        rows = self.rows.assign(HR=[300, 300, 290])
        self.assertIn("Tied for the lead", u2a.career_answer(rows, "HR", (2010, 2025))["body"])


if __name__ == "__main__":
    unittest.main()
