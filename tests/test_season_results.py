"""Finalized scoring periods and official standings — deterministic fixtures, hand-computed
expectations, immutability under later roster moves."""

from __future__ import annotations

import copy
import unittest.mock
import unittest
from datetime import datetime, timezone

import pandas as pd

from fantasy_season_ledger import build_lineup_snapshot, configure_season_calendar, save_period_lineup
from fantasy_season_results import (
    compute_period_result,
    finalize_period,
    official_standings,
    period_category_table,
    period_result,
    standings_from_totals,
)

COMM = {"user_id": "local:qa", "acting_as": "owner"}
AFTER_SEASON = datetime(2026, 5, 1, 16, tzinfo=timezone.utc)
IDS = {"Aaron Judge": 592450, "Juan Soto": 665742, "Cal Raleigh": 663728, "Adley Rutschman": 668939, "Bench Guy": 1}


def _stat(name, **c):
    row = {"MLBAM ID": IDS.get(name, 0), "Player": name}
    for comp in ("PA", "AB", "H", "2B", "3B", "HR", "R", "RBI", "SB", "BB", "HBP", "SF", "TB", "G"):
        row[comp] = c.get(comp, 0)
    return row


def _roster(names):
    return pd.DataFrame([{"Player": n, "MLBAM ID": IDS.get(n, 0), "Primary Position": "C" if n in ("Cal Raleigh", "Adley Rutschman") else "OF"} for n in names])


def _league():
    ctx = {"league_context_id": "archive:qa", "context_type": "real_league", "fantasy_format": "5x5 Roto",
           "league_rosters": {"A": {"players": [{"player_name": n} for n in ("Aaron Judge", "Cal Raleigh", "Bench Guy")]},
                              "B": {"players": [{"player_name": n} for n in ("Juan Soto", "Adley Rutschman")]}}}
    assert configure_season_calendar(ctx, first_day="2026-04-06", period_count=3)[0]
    return ctx


def _lineup(ctx, week, team, assignments, roster):
    snap = build_lineup_snapshot(team=team, slots=["C", "OF"], slot_assignments=assignments, roster_df=_roster(roster))
    ok, err = save_period_lineup(ctx, number=week, team=team, snapshot=snap, actor=COMM, is_commissioner=True, now=AFTER_SEASON)
    assert ok, err


# Week 1: Judge 2 HR 5-for-10, Raleigh 1 HR 2-for-10, Bench Guy 3 HR (bench — must not count),
#         Soto 1 HR 3-for-12, Rutschman 4-for-8.
WEEK1 = pd.DataFrame([
    _stat("Aaron Judge", AB=10, H=5, HR=2, R=3, RBI=4, BB=2, TB=12, PA=12),
    _stat("Cal Raleigh", AB=10, H=2, HR=1, R=1, RBI=2, TB=5, PA=10),
    _stat("Bench Guy", AB=10, H=6, HR=3, R=3, RBI=6, TB=15, PA=10),
    _stat("Juan Soto", AB=12, H=3, HR=1, R=2, RBI=1, BB=3, TB=6, PA=15),
    _stat("Adley Rutschman", AB=8, H=4, R=1, RBI=2, TB=5, PA=8),
])
# Week 2: Judge now on B (traded); 4 HR 6-for-12. Raleigh 0-for-10 for A. Soto 1-for-4 for A after the trade.
WEEK2 = pd.DataFrame([
    _stat("Aaron Judge", AB=12, H=6, HR=4, R=4, RBI=7, TB=18, PA=13),
    _stat("Cal Raleigh", AB=10, H=0, PA=10),
    _stat("Juan Soto", AB=4, H=1, HR=0, R=1, TB=1, PA=5),
    _stat("Adley Rutschman", AB=10, H=3, HR=2, R=2, RBI=3, TB=9, PA=10),
])


class PeriodScoringTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _league()
        _lineup(self.ctx, 1, "A", {"C": "Cal Raleigh", "OF": "Aaron Judge"}, ["Aaron Judge", "Cal Raleigh", "Bench Guy"])
        _lineup(self.ctx, 1, "B", {"C": "Adley Rutschman", "OF": "Juan Soto"}, ["Juan Soto", "Adley Rutschman"])

    def test_starters_only_and_rates_from_components(self):
        res = compute_period_result(self.ctx, 1, WEEK1)
        a = res["teams"]["A"]
        self.assertEqual(a["totals"]["HR"], 3)  # Judge 2 + Raleigh 1; Bench Guy's 3 HR excluded
        self.assertEqual((a["totals"]["H"], a["totals"]["AB"]), (7, 20))
        self.assertAlmostEqual(a["rates"]["AVG"], 7 / 20)
        self.assertAlmostEqual(a["rates"]["OBP"], (7 + 2) / (20 + 2))
        self.assertAlmostEqual(a["rates"]["OPS"], (7 + 2) / 22 + 17 / 20)
        self.assertEqual(a["bench"], ["Bench Guy"])
        self.assertEqual({l["matched_by"] for l in a["starters"]}, {"player_id"})

    def test_finalize_rules(self):
        ok, err, _ = finalize_period(self.ctx, 1, stats_df=WEEK1, actor=COMM, is_commissioner=False, now=AFTER_SEASON)
        self.assertIn("Only the commissioner", err)
        ok, err, _ = finalize_period(self.ctx, 1, stats_df=WEEK1, actor=COMM, is_commissioner=True,
                                     now=datetime(2026, 4, 9, 16, tzinfo=timezone.utc))
        self.assertIn("after it ends on 2026-04-12", err)
        ok, err, _ = finalize_period(self.ctx, 2, stats_df=WEEK2, actor=COMM, is_commissioner=True, now=AFTER_SEASON)
        self.assertIn("Finalize Week 1 first", err)
        ok, err, _ = finalize_period(self.ctx, 1, stats_df=WEEK1, actor=COMM, is_commissioner=True, now=AFTER_SEASON)
        self.assertTrue(ok, err)
        ok, err, _ = finalize_period(self.ctx, 1, stats_df=WEEK1, actor=COMM, is_commissioner=True, now=AFTER_SEASON)
        self.assertIn("already final", err)

    def test_missing_lineup_needs_explicit_zero(self):
        _lineup(self.ctx, 2, "A", {"C": "Cal Raleigh", "OF": "Aaron Judge"}, ["Aaron Judge", "Cal Raleigh"])
        finalize_period(self.ctx, 1, stats_df=WEEK1, actor=COMM, is_commissioner=True, now=AFTER_SEASON)
        ok, err, _ = finalize_period(self.ctx, 2, stats_df=WEEK2, actor=COMM, is_commissioner=True, now=AFTER_SEASON)
        self.assertFalse(ok)
        self.assertIn("No Week 2 lineup for: B", err)
        ok, err, res = finalize_period(self.ctx, 2, stats_df=WEEK2, actor=COMM, is_commissioner=True, now=AFTER_SEASON,
                                       score_missing_lineups_as_zero=True)
        self.assertTrue(ok, err)
        self.assertEqual(res["missing_lineups_scored_zero"], ["B"])
        self.assertEqual(res["teams"]["B"]["totals"]["HR"], 0)


class ImmutabilityAndRosterMoveTests(unittest.TestCase):
    """Week 1: Judge starts for A. Then Judge is traded to B. Week 1 must still credit A."""

    def setUp(self):
        self.ctx = _league()
        _lineup(self.ctx, 1, "A", {"C": "Cal Raleigh", "OF": "Aaron Judge"}, ["Aaron Judge", "Cal Raleigh", "Bench Guy"])
        _lineup(self.ctx, 1, "B", {"C": "Adley Rutschman", "OF": "Juan Soto"}, ["Juan Soto", "Adley Rutschman"])
        ok, err, _ = finalize_period(self.ctx, 1, stats_df=WEEK1, actor=COMM, is_commissioner=True, now=AFTER_SEASON)
        assert ok, err
        self.week1 = period_result(self.ctx, 1)
        # Trade after Week 1: Judge -> B, Soto -> A. Drop Bench Guy.
        self.ctx["league_rosters"] = {"A": {"players": [{"player_name": n} for n in ("Juan Soto", "Cal Raleigh")]},
                                      "B": {"players": [{"player_name": n} for n in ("Aaron Judge", "Adley Rutschman")]}}

    def test_finalized_week_is_not_rewritten_by_later_moves(self):
        self.assertEqual(period_result(self.ctx, 1), self.week1)
        a_names = [s["player_name"] for s in period_result(self.ctx, 1)["teams"]["A"]["starters"]]
        self.assertIn("Aaron Judge", a_names)
        ok, err = save_period_lineup(self.ctx, number=1, team="A", snapshot={"starters": []}, actor=COMM, is_commissioner=True, now=AFTER_SEASON)
        self.assertFalse(ok)
        self.assertIn("finalized", err)

    def test_week2_follows_the_new_owner_and_season_totals_add_up(self):
        _lineup(self.ctx, 2, "A", {"C": "Cal Raleigh", "OF": "Juan Soto"}, ["Juan Soto", "Cal Raleigh"])
        _lineup(self.ctx, 2, "B", {"C": "Adley Rutschman", "OF": "Aaron Judge"}, ["Aaron Judge", "Adley Rutschman"])
        ok, err, week2 = finalize_period(self.ctx, 2, stats_df=WEEK2, actor=COMM, is_commissioner=True, now=AFTER_SEASON)
        self.assertTrue(ok, err)
        self.assertEqual(week2["teams"]["B"]["totals"]["HR"], 6)  # Judge 4 + Rutschman 2, now for B
        self.assertEqual(period_result(self.ctx, 1)["teams"]["A"]["totals"]["HR"], 3)  # Judge's Week 1 stays with A
        table, weeks = official_standings(self.ctx)
        self.assertEqual(weeks, [1, 2])
        row = table.set_index("Team")
        self.assertEqual(row.loc["A", "HR"], 3 + 0)  # 3 then 0
        self.assertEqual(row.loc["B", "HR"], 1 + 6)  # 1 then 6
        # Season AVG is total H / total AB, not the average of weekly averages.
        self.assertAlmostEqual(row.loc["A", "AVG"], (7 + 1) / (20 + 14))
        self.assertAlmostEqual(row.loc["B", "AVG"], (7 + 9) / (20 + 22))
        weekly_mean = ((7 / 20) + (1 / 14)) / 2
        self.assertNotAlmostEqual(row.loc["A", "AVG"], weekly_mean)
        self.assertEqual(int(row.loc["B", "HR Points"]), 2)
        self.assertFalse(period_category_table(self.ctx, 2).empty)


class CumulativeStandingsTests(unittest.TestCase):
    def test_brief_example_cumulative_hr(self):
        # Week 1: A 5 HR, B 3 HR. Week 2: A 1 HR, B 6 HR. Season: A 6, B 9.
        totals = {"A": {"HR": 5 + 1, "H": 0, "AB": 0}, "B": {"HR": 3 + 6, "H": 0, "AB": 0}}
        table = standings_from_totals(totals, ("HR",)).set_index("Team")
        self.assertEqual((table.loc["A", "HR"], table.loc["B", "HR"]), (6, 9))
        self.assertEqual((table.loc["A", "HR Points"], table.loc["B", "HR Points"]), (1.0, 2.0))

    def test_ties_split_points_in_cumulative_standings(self):
        def cat_points(values):
            totals = {t: {"HR": v} for t, v in values.items()}
            return standings_from_totals(totals, ("HR",)).set_index("Team")["HR Points"].to_dict()

        self.assertEqual(cat_points({"A": 9, "B": 9, "C": 4, "D": 1}), {"A": 3.5, "B": 3.5, "C": 2.0, "D": 1.0})
        self.assertEqual(cat_points({"A": 5, "B": 5, "C": 5, "D": 1, "E": 1}), {"A": 4.0, "B": 4.0, "C": 4.0, "D": 1.5, "E": 1.5})

    def test_legacy_league_has_no_official_standings(self):
        table, weeks = official_standings({"league_rosters": {"A": {}}})
        self.assertTrue(table.empty)
        self.assertEqual(weeks, [])


if __name__ == "__main__":
    unittest.main()


class SharedLeagueLedgerTests(unittest.TestCase):
    def _ledger_with(self, lineup_saved_at=None, finalized_at=""):
        ctx = _league()
        if lineup_saved_at:
            _lineup(ctx, 1, "A", {"C": "Cal Raleigh", "OF": "Aaron Judge"}, ["Aaron Judge", "Cal Raleigh"])
            ctx["workflow"]["season_ledger"]["periods"]["P1"]["lineups"]["A"]["saved_at"] = lineup_saved_at
        if finalized_at:
            ctx["workflow"]["season_ledger"]["periods"]["P1"]["finalized_at"] = finalized_at
            ctx["workflow"]["season_ledger"]["periods"]["P1"]["result"] = {"marker": finalized_at}
        return ctx["workflow"]["season_ledger"]

    def test_merge_rules(self):
        from fantasy_season_ledger import merge_season_ledgers

        older, newer = self._ledger_with("2026-04-05T10:00:00"), self._ledger_with("2026-04-05T12:00:00")
        merged = merge_season_ledgers(older, newer)
        self.assertEqual(merged["periods"]["P1"]["lineups"]["A"]["saved_at"], "2026-04-05T12:00:00")
        final = self._ledger_with(finalized_at="2026-04-14T00:00:00")
        self.assertEqual(merge_season_ledgers(newer, final)["periods"]["P1"]["result"], {"marker": "2026-04-14T00:00:00"})
        self.assertEqual(merge_season_ledgers(final, newer)["periods"]["P1"]["result"], {"marker": "2026-04-14T00:00:00"})
        later_final = self._ledger_with(finalized_at="2026-04-20T00:00:00")
        self.assertEqual(merge_season_ledgers(later_final, final)["periods"]["P1"]["finalized_at"], "2026-04-14T00:00:00")
        other_calendar = copy.deepcopy(newer)
        other_calendar["periods"]["P1"]["start"] = "2026-05-01"
        other_calendar["calendar"]["configured_at"] = "9999"
        merged = merge_season_ledgers(older, other_calendar)
        self.assertEqual(merged["periods"]["P1"]["start"], "2026-05-01")
        self.assertEqual(merged["periods"]["P1"]["lineups"]["A"]["saved_at"], "2026-04-05T12:00:00")  # not mixed with older's

    def test_ledger_push_shares_lineups_without_touching_rosters(self):
        import tempfile
        from pathlib import Path

        from fantasy_shared_league_store import (
            LocalFileSharedLeagueStore,
            merge_shared_into_context,
            push_season_ledger_to_shared,
        )

        with tempfile.TemporaryDirectory() as tmp:
            store = LocalFileSharedLeagueStore(root=Path(tmp))
            ctx = _league()
            ctx["metadata"] = {"league_id": "lg-1"}
            store.save({"league_id": "lg-1", "revision": 3, "league_rosters": {"A": {"players": [{"player_name": "Shared Truth"}]}}})
            _lineup(ctx, 1, "A", {"C": "Cal Raleigh", "OF": "Aaron Judge"}, ["Aaron Judge", "Cal Raleigh"])
            with unittest.mock.patch("fantasy_shared_league_store.resolve_canonical_league_id", return_value="lg-1"):
                saved = push_season_ledger_to_shared({}, ctx, store=store)
            self.assertEqual(saved["league_rosters"]["A"]["players"][0]["player_name"], "Shared Truth")
            self.assertEqual(saved["revision"], 4)
            commissioner_view = merge_shared_into_context(_league(), store.load("lg-1"))
            lineup = commissioner_view["workflow"]["season_ledger"]["periods"]["P1"]["lineups"]["A"]
            self.assertEqual([s["player_name"] for s in lineup["starters"]], ["Cal Raleigh", "Aaron Judge"])

    def test_full_push_keeps_the_shared_ledger(self):
        import tempfile
        from pathlib import Path

        from fantasy_shared_league_store import LocalFileSharedLeagueStore, push_league_context_to_shared

        with tempfile.TemporaryDirectory() as tmp:
            store = LocalFileSharedLeagueStore(root=Path(tmp))
            shared_ledger = self._ledger_with(finalized_at="2026-04-14T00:00:00")
            store.save({"league_id": "lg-2", "revision": 1, "season_ledger": shared_ledger})
            ctx = {"league_context_id": "x", "league_rosters": {"A": {"players": []}}, "metadata": {"league_id": "lg-2"}}
            with unittest.mock.patch("fantasy_shared_league_store.resolve_canonical_league_id", return_value="lg-2"), \
                    unittest.mock.patch("fantasy_league_context.upsert_league_context"):
                push_league_context_to_shared({}, ctx, store=store)  # e.g. a trade by a manager without the ledger
            self.assertEqual(store.load("lg-2")["season_ledger"]["periods"]["P1"]["finalized_at"], "2026-04-14T00:00:00")


class NoAtBatsTests(unittest.TestCase):
    def test_team_without_at_bats_ranks_last_in_avg(self):
        totals = {"A": {"H": 52, "AB": 199, "HR": 11}, "B": {"H": 0, "AB": 0, "HR": 0}, "C": {"H": 0, "AB": 0, "HR": 0}}
        table = standings_from_totals(totals, ("HR", "AVG")).set_index("Team")
        self.assertEqual(table.loc["A", "AVG Points"], 3.0)  # was tied with the no-AB teams
        self.assertEqual((table.loc["B", "AVG Points"], table.loc["C", "AVG Points"]), (1.5, 1.5))
