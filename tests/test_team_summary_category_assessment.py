"""Team Summary category diagnosis (owner reviews, 2026-11-08).

History:
* v1 had a ratio rule in the table and an alphabetical tie-break in the summary, which showed "AVG, HR" while
  the table called HR "Middle".
* v2 benchmarked against MLB team-to-team spread. The owner rejected it: MLB team spread doesn't represent
  fantasy leagues, and "2nd of 2" alone isn't a weakness.

v3 uses two separate, explainable measures:
1. League standing (relative): rank among the league's teams, gap to the leader, and Leading / Middle / Trailing.
2. Category strength: this team's per-hitter production compared with MLB regulars this season, as a percentile.
   Per hitter, so roster size, team count and incomplete rosters don't distort it; the percentile puts
   categories with different units on one scale. Weaknesses are categories below the 35th percentile.
   Without a stats pool, the page falls back to league standing and labels it an estimate.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from fantasy_actionable_recommendations import league_weakness_categories
from fantasy_waiver_wire import analyze_current_team_needs, build_category_action_table, build_category_standings_table

ROOT = Path(__file__).resolve().parents[1]
REAL_CATS = ("HR", "RBI", "R", "SB", "AVG", "OPS")


def _roster(team, players):
    return pd.DataFrame([dict(Team=team, Player=n, AB=ab, H=h, HR=hr, RBI=rbi, R=r, SB=sb, BA=round(h / ab, 3), OPS=ops)
                         for n, ab, h, hr, rbi, r, sb, ops in players])


def _regulars(n=200, seed=7):
    """A season-to-date pool of MLB regulars with realistic per-player spreads (synthetic, deterministic)."""
    rng = np.random.default_rng(seed)
    ab = rng.integers(250, 600, n)
    ba = np.clip(rng.normal(0.250, 0.025, n), 0.180, 0.330)
    return pd.DataFrame({"Player": [f"R{i}" for i in range(n)], "AB": ab, "H": (ab * ba).round(),
                         "BA": ba.round(3), "HR": rng.gamma(3.0, 6.0, n).round(), "RBI": rng.normal(65, 20, n).round(),
                         "R": rng.normal(65, 18, n).round(), "SB": rng.gamma(1.2, 7.0, n).round(),
                         "OPS": np.clip(rng.normal(0.730, 0.070, n), 0.550, 1.050).round(3)})


# The owner's ACTUAL screen: a 2-team league, 2 hitters per team, "2nd of 2" in every category.
# Dave totals: HR 39, RBI 90, R 108, SB 8, AVG .231, OPS .778; Bob: HR 45, RBI 122, R 157, SB 54, AVG .279, OPS .845.
DAVE = _roster("Dave", [("Aaron Judge", 300, 70, 24, 50, 60, 4, 0.840), ("Francisco Lindor", 300, 69, 15, 40, 48, 4, 0.716)])
BOB = _roster("Bob", [("B1", 300, 84, 25, 64, 80, 30, 0.880), ("B2", 300, 83, 20, 58, 77, 24, 0.810)])
LEAGUE = pd.concat([DAVE, BOB], ignore_index=True)


class OwnerRealScreenTests(unittest.TestCase):
    def test_the_inputs_match_the_owners_screen(self) -> None:
        needs = analyze_current_team_needs(DAVE, LEAGUE, categories=REAL_CATS)
        vals = needs["category_values"]
        self.assertEqual((vals["HR"], vals["RBI"], vals["R"], vals["SB"]), (39, 90, 108, 8))
        self.assertAlmostEqual(vals["AVG"], 139 / 600, places=3)  # .231 from summed H/AB
        self.assertEqual(set(needs["category_ranks"].values()), {2})

    def test_without_season_stats_the_page_shows_league_standing_only(self) -> None:
        needs = analyze_current_team_needs(DAVE, LEAGUE, categories=REAL_CATS)
        self.assertEqual(needs["strength_basis"], "league")
        self.assertEqual(set(needs["category_standing"].values()), {"Trailing"})
        # Ordered by how far behind the leader, as a share of the leader's value: SB 85%, R 31%, RBI 26%, ...
        self.assertEqual(needs["weaknesses"][:3], ["SB", "R", "RBI"])
        self.assertAlmostEqual(needs["category_behind_pct"]["SB"], 46 / 54, places=3)

    def test_second_of_two_is_not_automatically_a_weakness(self) -> None:
        needs = analyze_current_team_needs(DAVE, LEAGUE, categories=REAL_CATS, player_pool=_regulars())
        self.assertEqual(needs["strength_basis"], "mlb_regulars")
        self.assertEqual(needs["category_standing"]["HR"], "Trailing")       # behind Bob
        self.assertNotEqual(needs["category_status"]["HR"], "Weakness")      # 19.5 HR per hitter is solid
        self.assertNotIn("HR", needs["weaknesses"])
        # Every status follows its percentile (below 35th = Weakness, 65th+ = Strength), whatever the standing.
        for cat, info in needs["category_strength"].items():
            want = "Weakness" if info["pct"] < 0.35 else "Strength" if info["pct"] >= 0.65 else "Middle"
            self.assertEqual(needs["category_status"][cat], want, cat)
        self.assertLess(needs["category_strength"]["SB"]["pct"], needs["category_strength"]["HR"]["pct"])

    def test_the_table_shows_both_measures(self) -> None:
        needs = analyze_current_team_needs(DAVE, LEAGUE, categories=REAL_CATS, player_pool=_regulars())
        table = build_category_action_table(needs, categories=REAL_CATS)
        row = table.set_index("Category").loc["HR"]
        self.assertEqual(row["Standing"], "Trailing")
        self.assertIn("per hitter", row["Vs MLB regulars"])
        pct = int(round(needs["category_strength"]["HR"]["pct"] * 100))
        suffix = "th" if 10 <= pct % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(pct % 10, "th")
        self.assertIn(f"{pct}{suffix} pct", row["Vs MLB regulars"])  # "73rd pct", never "73th pct"
        import re

        for value in table["Vs MLB regulars"]:
            m = re.search(r"(\d+)(st|nd|rd|th) pct$", str(value))
            if m:
                n = int(m.group(1))
                want = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
                self.assertEqual(m.group(2), want, value)
        # The summary's weaknesses are exactly the table's Weakness rows, weakest first.
        statuses = dict(zip(table["Category"], table["Status"]))
        self.assertEqual(sorted(needs["weaknesses"]), sorted(c for c, s in statuses.items() if s == "Weakness"))
        pcts = [needs["category_strength"][c]["pct"] for c in needs["weaknesses"]]
        self.assertEqual(pcts, sorted(pcts))


class MethodTests(unittest.TestCase):
    def test_per_hitter_values_and_percentiles_are_computed_from_the_inputs(self) -> None:
        pool = _regulars()
        needs = analyze_current_team_needs(DAVE, LEAGUE, categories=("HR", "SB"), player_pool=pool)
        hr = needs["category_strength"]["HR"]
        self.assertEqual((hr["per_player"], hr["n_hitters"]), (19.5, 2))
        regs = pool[pool["AB"] >= max(50, pool["AB"].median())]
        expected = float((regs["HR"] < 19.5).mean()) + 0.5 * float((regs["HR"] == 19.5).mean())
        self.assertAlmostEqual(hr["pct"], expected, places=3)

    def test_roster_size_does_not_distort_strength(self) -> None:
        pool = _regulars()
        two = analyze_current_team_needs(DAVE, LEAGUE, categories=("HR",), player_pool=pool)["category_strength"]["HR"]
        four = pd.concat([DAVE, DAVE.assign(Player=DAVE["Player"] + " (2)")], ignore_index=True)
        big = analyze_current_team_needs(four, pd.concat([four, BOB]), categories=("HR",), player_pool=pool)["category_strength"]["HR"]
        self.assertEqual(two["pct"], big["pct"])  # same per-hitter production, same strength

    def test_lower_is_better_categories(self) -> None:
        team = pd.DataFrame([dict(Team="Mine", ERA=2.90, AB=0), dict(Team="Mine", ERA=3.00, AB=0)])
        pool = pd.DataFrame({"ERA": np.linspace(2.5, 5.5, 50)})
        df = pd.concat([team, pd.DataFrame([dict(Team="B", ERA=4.0, AB=0)])])
        needs = analyze_current_team_needs(team.drop(columns="AB"), df.drop(columns="AB"), categories=("ERA",), player_pool=pool)
        self.assertGreater(needs["category_strength"]["ERA"]["pct"], 0.8)
        self.assertEqual(needs["category_status"]["ERA"], "Strength")

    def test_never_both_a_strength_and_a_weakness(self) -> None:
        needs = analyze_current_team_needs(DAVE, LEAGUE, categories=REAL_CATS, player_pool=_regulars())
        self.assertFalse(set(needs["strengths"]) & set(needs["weaknesses"]))

    def test_waiver_targets_use_the_same_order(self) -> None:
        needs = analyze_current_team_needs(DAVE, LEAGUE, categories=REAL_CATS, player_pool=_regulars())
        self.assertEqual(needs["targets"], needs["weaknesses"])

    def test_standings_table_agrees_with_the_action_table(self) -> None:
        needs = analyze_current_team_needs(DAVE, LEAGUE, categories=REAL_CATS, player_pool=_regulars())
        a = build_category_action_table(needs, categories=REAL_CATS)
        b = build_category_standings_table(needs, categories=REAL_CATS)
        self.assertEqual(dict(zip(a["Category"], a["Status"])), dict(zip(b["Category"], b["Status"])))

    def test_rank_ties_never_fall_back_to_alphabetical_order_in_the_page(self) -> None:
        self.assertEqual(league_weakness_categories({"AVG": 2, "HR": 2}, n_teams=2), ["AVG", "HR"])  # old helper
        ui = (ROOT / "fantasy_lineup_management_ui.py").read_text(encoding="utf-8")
        self.assertIn('_weakness_cats = list(_needs.get("weaknesses") or [])[:2]', ui)  # the page reads the assessment
        self.assertIn("player_pool=_pool_for_needs", ui)


class PageTests(unittest.TestCase):
    def test_the_page_explains_both_measures_and_flags_small_samples(self) -> None:
        ui = (ROOT / "fantasy_lineup_management_ui.py").read_text(encoding="utf-8")
        self.assertIn("**Standing** is league-relative", ui)
        self.assertIn("per-player production compared with MLB", ui)
        self.assertIn("so treat it as an estimate", ui)
        self.assertIn("league standing only (an estimate)", ui)
        cache = (ROOT / "fantasy_perf_cache.py").read_text(encoding="utf-8")
        self.assertIn('"category_rule_v2"', cache)


if __name__ == "__main__":
    unittest.main()
