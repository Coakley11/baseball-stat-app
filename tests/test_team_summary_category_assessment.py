"""Team Summary category diagnosis (owner review, 2026-11-08).

The owner saw "Top Weaknesses: AVG, HR" while the standings table called HR "Middle" (39 vs a league best
of 45) and RBI, R, SB and AVG "Weakness". Causes:
* the table used a ratio to the league best (below 0.85 meant Weakness);
* Top Weaknesses used league rank, and ties were broken alphabetically, so AVG and HR always won a tie.

Now one assessment drives every section. Status comes from the league rank (top third = Strength, bottom
third = Weakness); order comes from a direction-aware z-score, because categories have different units.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from fantasy_actionable_recommendations import league_weakness_categories
from fantasy_waiver_wire import analyze_current_team_needs, build_category_action_table, build_category_standings_table

CATS = ("HR", "RBI", "R", "SB", "AVG")
ROOT = Path(__file__).resolve().parents[1]


def _league(rows, cats=("HR", "RBI", "R", "SB", "BA")):
    return pd.DataFrame([dict(Team=t, **dict(zip(cats, vals))) for t, *vals in rows])


# The owner's example: last in every hitting category; HR 39 vs the league best of 45.
OWNER = [("Mine", 39, 150, 160, 10, .225), ("Best", 45, 200, 210, 30, .270),
         ("C", 42, 185, 195, 24, .258), ("D", 41, 180, 190, 20, .252)]


def _needs(rows, cats=CATS):
    df = _league(rows)
    return analyze_current_team_needs(df[df.Team == "Mine"], df, categories=cats)


class OwnerExampleTests(unittest.TestCase):
    def test_top_weaknesses_follow_the_z_score_not_the_alphabet(self) -> None:
        needs = _needs(OWNER)
        self.assertEqual(needs["weaknesses"][:2], ["AVG", "RBI"])
        self.assertNotIn("HR", needs["weaknesses"][:2])  # HR is the least-bad category here
        self.assertEqual(league_weakness_categories(needs["category_ranks"], n_teams=4), ["AVG", "HR"])  # the old rule

    def test_the_table_and_the_summary_agree(self) -> None:
        needs = _needs(OWNER)
        table = build_category_action_table(needs, categories=CATS)
        status = dict(zip(table["Category"], table["Status"]))
        self.assertEqual(status["HR"], "Weakness")  # last of 4 teams: not "Middle"
        for cat in needs["weaknesses"][:2]:
            self.assertEqual(status[cat], "Weakness")
        standings = build_category_standings_table(needs, categories=CATS)
        self.assertEqual(dict(zip(standings["Category"], standings["Status"])), status)


class RuleTests(unittest.TestCase):
    def test_a_rate_stat_near_the_bottom_is_a_weakness(self) -> None:
        # AVG .238, 11th of 12, was "Middle" under the old 0.85-of-best ratio rule.
        rows = [("Mine", 30, 160, 170, 15, .238)] + [(f"T{i}", 30 + i, 170 + i, 180 + i, 16 + i, .240 + i / 100)
                                                      for i in range(11)]
        rows[1] = ("T0", 29, 150, 160, 10, .230)  # one team below us
        needs = _needs(rows)
        self.assertEqual(needs["category_ranks"]["AVG"], 11)
        self.assertEqual(needs["category_status"]["AVG"], "Weakness")

    def test_lower_is_better_categories(self) -> None:
        df = pd.DataFrame([dict(Team="Mine", ERA=2.90, WHIP=1.05), dict(Team="B", ERA=3.80, WHIP=1.25),
                           dict(Team="C", ERA=4.20, WHIP=1.30)])
        needs = analyze_current_team_needs(df[df.Team == "Mine"], df, categories=("ERA", "WHIP"))
        self.assertEqual(needs["category_ranks"], {"ERA": 1, "WHIP": 1})
        self.assertEqual(needs["category_status"], {"ERA": "Strength", "WHIP": "Strength"})
        self.assertGreater(needs["category_z"]["ERA"], 0)

    def test_middle_of_the_league_is_middle(self) -> None:
        rows = [("Mine", 40, 175, 185, 20, .250), ("A", 45, 200, 210, 30, .270), ("B", 35, 150, 160, 10, .230),
                ("C", 44, 190, 200, 28, .265), ("D", 36, 155, 165, 12, .232), ("E", 38, 165, 175, 16, .240)]
        needs = _needs(rows)
        self.assertEqual(set(needs["category_status"].values()), {"Middle"})
        self.assertEqual(needs["weaknesses"], [])

    def test_never_both_a_strength_and_a_weakness(self) -> None:
        needs = _needs(OWNER + [("E", 50, 220, 230, 35, .280)])
        self.assertFalse(set(needs["strengths"]) & set(needs["weaknesses"]))

    def test_rank_ties_break_by_z_score_when_given(self) -> None:
        ranks = {"AVG": 4, "HR": 4, "RBI": 4}
        z = {"AVG": -1.0, "HR": -0.5, "RBI": -1.6}
        self.assertEqual(league_weakness_categories(ranks, n_teams=4, category_z=z), ["RBI", "AVG"])

    def test_waiver_targets_use_the_same_order(self) -> None:
        needs = _needs(OWNER)
        self.assertEqual(needs["targets"], needs["weaknesses"])


class PageTests(unittest.TestCase):
    def test_the_page_reads_one_assessment_and_labels_it(self) -> None:
        ui = (ROOT / "fantasy_lineup_management_ui.py").read_text(encoding="utf-8")
        self.assertIn('_weakness_cats = list(_needs.get("weaknesses") or [])[:2]', ui)
        self.assertIn("Your whole roster (starters and bench), current-season stats", ui)
        cache = (ROOT / "fantasy_perf_cache.py").read_text(encoding="utf-8")
        self.assertIn('"category_rule_v2"', cache)  # summaries cached under the old rule aren't reused


if __name__ == "__main__":
    unittest.main()
