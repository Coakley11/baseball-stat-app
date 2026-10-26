"""Roster moves across scoring periods (rule: a move takes effect from the next period).

The locked snapshot scores its period: a starter dropped or traded mid-period still counts
for that period, and a player added mid-period counts only once he is in a later period's
lineup. A new period's lineup may only start players the team owns now.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from fantasy_league_context import get_active_league_context, upsert_league_context
from fantasy_season_ledger import configure_season_calendar, get_period_lineup, league_today
from fantasy_season_results import finalize_period, official_standings, period_result
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from fantasy_weekly_lineup import save_weekly_lineup
from tests.test_team_control_and_local_saves import STATS, _as, _league

COMM = {"user_id": "local:qa", "acting_as": "owner"}


def _period_stats(**hr_ab_h):
    """name=(HR, AB, H) -> one period's date-range stat rows."""
    rows = []
    for name, (hr, ab, h) in hr_ab_h.items():
        rows.append({"Player": name.replace("_", " "), "MLBAM ID": None, "PA": ab, "AB": ab, "H": h, "2B": 0, "3B": 0,
                     "HR": hr, "R": hr, "RBI": hr, "SB": 0, "BB": 0, "HBP": 0, "SF": 0, "TB": h + 3 * hr, "G": 6})
    return pd.DataFrame(rows)


# Perez and Smith both hit in both weeks; which week counts for whom depends only on the snapshots.
WEEK1 = _period_stats(Cal_Raleigh=(1, 20, 5), Aaron_Judge=(2, 20, 6), Salvador_Perez=(2, 20, 5),
                      Kyle_Tucker=(1, 20, 4), Will_Smith=(3, 20, 8))
WEEK2 = _period_stats(Cal_Raleigh=(0, 20, 4), Aaron_Judge=(4, 20, 7), Salvador_Perez=(5, 20, 9),
                      Kyle_Tucker=(1, 20, 5), Will_Smith=(2, 20, 6))


def _roster_df(team: str, names: list[str]) -> pd.DataFrame:
    df = STATS[STATS["Player"].isin(names)].copy()
    df["Team"] = team
    return df


class CrossWeekRosterMoveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))
        self.session: dict = {}
        _league(self.session)  # local:qa owns Team A and is commissioner; Team B and Team C are unclaimed
        self.first_day = league_today() + timedelta(days=3)
        with _as("local:qa"):
            ctx = get_active_league_context(self.session)
            ok, err = configure_season_calendar(ctx, first_day=self.first_day, period_count=2)
            self.assertTrue(ok, err)
            upsert_league_context(self.session, ctx)
            for team, c, of in (("Team A", "Cal Raleigh", "Aaron Judge"), ("Team C", "Salvador Perez", "Kyle Tucker")):
                saved = self._save(1, team, {"C": c, "OF": of}, [c, of])
                self.assertTrue(saved["ok"], saved)
        self.after_season = datetime.combine(self.first_day + timedelta(days=15), time(12), ZoneInfo("America/New_York"))

    def tearDown(self):
        set_shared_league_store(None)
        self._tmp.cleanup()

    def _save(self, week, team, assignments, roster_names):
        return save_weekly_lineup(self.session, week=week, slots=["C", "OF"], assignments=assignments, my_team=team,
                                  roster_df=_roster_df(team, roster_names))

    def _ctx(self):
        return get_active_league_context(self.session)

    def _finalize(self, week, stats):
        ctx = self._ctx()
        ok, err, result = finalize_period(ctx, week, stats_df=stats, actor=COMM, is_commissioner=True,
                                          score_missing_lineups_as_zero=True, now=self.after_season)
        self.assertTrue(ok, err)
        upsert_league_context(self.session, ctx)
        return result

    def test_mid_period_drop_and_add_take_effect_next_period(self):
        from fantasy_waiver_wire import apply_waiver_move_pairs

        with _as("local:qa"):
            moved = apply_waiver_move_pairs(self.session, [{"add_player": "Will Smith", "drop_player": "Salvador Perez"}],
                                            stats_pool=STATS, team="Team C")
            self.assertTrue(moved["ok"], moved)
            # The Week 1 snapshot is untouched by the move.
            week1_c = get_period_lineup(self._ctx(), 1, "Team C")
            self.assertEqual([s["player_name"] for s in week1_c["starters"]], ["Salvador Perez", "Kyle Tucker"])
            # A stale page (roster loaded before the drop) cannot start Perez in Week 2.
            stale = self._save(2, "Team C", {"C": "Salvador Perez", "OF": "Kyle Tucker"}, ["Salvador Perez", "Kyle Tucker"])
            self.assertFalse(stale["ok"])
            self.assertIn("Salvador Perez is no longer on Team C's roster", " ".join(stale["errors"]))
            self.assertIsNone(get_period_lineup(self._ctx(), 2, "Team C"))
            fresh = self._save(2, "Team C", {"C": "Will Smith", "OF": "Kyle Tucker"}, ["Will Smith", "Kyle Tucker"])
            self.assertTrue(fresh["ok"], fresh)

        week1 = self._finalize(1, WEEK1)
        week2 = self._finalize(2, WEEK2)
        # Week 1: dropped Perez still counts (2 + Tucker 1); Smith, added mid-week, does not.
        self.assertEqual(week1["teams"]["Team C"]["totals"]["HR"], 3)
        self.assertEqual(week1["teams"]["Team C"]["totals"]["H"], 9)
        # Week 2: Smith counts (2 + Tucker 1); Perez's 5 HR for his new life on waivers do not.
        self.assertEqual(week2["teams"]["Team C"]["totals"]["HR"], 3)
        self.assertEqual(week2["teams"]["Team C"]["totals"]["H"], 11)
        table, weeks = official_standings(self._ctx())
        self.assertEqual(weeks, [1, 2])
        c = table.set_index("Team").loc["Team C"]
        self.assertEqual(c["HR"], 6)
        self.assertAlmostEqual(c["AVG"], (9 + 11) / 80)

    def test_mid_period_trade_keeps_the_period_with_the_old_owner(self):
        from fantasy_trade_proposals import execute_commissioner_trade

        with _as("local:qa"):
            _p, err = execute_commissioner_trade(self.session, team_a="Team A", team_b="Team C", team_a_gives=["Aaron Judge"],
                                                 team_b_gives=["Kyle Tucker"], confirmed=True)
            self.assertEqual(err, "")
            refused = self._save(2, "Team A", {"C": "Cal Raleigh", "OF": "Aaron Judge"}, ["Cal Raleigh", "Aaron Judge"])
            self.assertFalse(refused["ok"])
            self.assertIn("Aaron Judge is no longer on Team A's roster", " ".join(refused["errors"]))
            self.assertTrue(self._save(2, "Team A", {"C": "Cal Raleigh", "OF": "Kyle Tucker"}, ["Cal Raleigh", "Kyle Tucker"])["ok"])
            self.assertTrue(self._save(2, "Team C", {"C": "Salvador Perez", "OF": "Aaron Judge"}, ["Salvador Perez", "Aaron Judge"])["ok"])

        self._finalize(1, WEEK1)
        week1_before = period_result(self._ctx(), 1)
        self._finalize(2, WEEK2)
        self.assertEqual(period_result(self._ctx(), 1), week1_before)
        a1, c1 = week1_before["teams"]["Team A"]["totals"], week1_before["teams"]["Team C"]["totals"]
        week2 = period_result(self._ctx(), 2)["teams"]
        self.assertEqual((a1["HR"], c1["HR"]), (1 + 2, 2 + 1))  # Judge's Week 1 HR stay with Team A
        self.assertEqual((week2["Team A"]["totals"]["HR"], week2["Team C"]["totals"]["HR"]), (0 + 1, 5 + 4))
        row = official_standings(self._ctx())[0].set_index("Team")
        self.assertEqual((row.loc["Team A", "HR"], row.loc["Team C", "HR"]), (4, 12))

    def test_unchanged_roster_saves_the_next_period_normally(self):
        with _as("local:qa"):
            saved = self._save(2, "Team A", {"C": "Cal Raleigh", "OF": "Aaron Judge"}, ["Cal Raleigh", "Aaron Judge"])
        self.assertTrue(saved["ok"], saved)
        snap = get_period_lineup(self._ctx(), 2, "Team A")
        self.assertEqual([s["owner_at_snapshot"] for s in snap["starters"]], ["Team A", "Team A"])


if __name__ == "__main__":
    unittest.main()
