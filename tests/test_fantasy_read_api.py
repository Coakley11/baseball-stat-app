"""The AMI-facing read API: authoritative numbers, explicit kinds, enforced team access, no writes."""

from __future__ import annotations

import pickle
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import fantasy_read_api as api
from fantasy_league_context import get_active_league_context, upsert_league_context
from fantasy_season_ledger import build_lineup_snapshot, configure_season_calendar, save_period_lineup
from fantasy_season_results import finalize_period, official_standings
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from fantasy_standings_snapshot import score_current_roster_standings
from fantasy_trade_evaluation import evaluate_trade
from tests.test_team_control_and_local_saves import STATS, _as, _league

AFTER = datetime(2026, 5, 1, 16, tzinfo=timezone.utc)
COMM = {"user_id": "local:qa", "acting_as": "owner"}


def _roster_stats(session) -> pd.DataFrame:
    ctx = get_active_league_context(session)
    rows = []
    for team, entry in ctx["league_rosters"].items():
        for p in entry["players"]:
            rec = STATS[STATS.Player == p["player_name"]].iloc[0].to_dict()
            rows.append({**rec, "Team": team})
    frame = pd.DataFrame(rows)
    frame["BA"] = frame["H"] / frame["AB"]
    frame["OPS"] = frame["BA"] + 0.400 + frame["HR"] / 100  # any fixed rate column; the page feed carries real OPS
    return frame


def _frozen(session) -> bytes:
    return pickle.dumps({k: session[k] for k in sorted(session, key=str)})


class ReadApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))
        self.session: dict = {}
        _league(self.session, claim_b="uuid-b")  # local:qa owns Team A + commissioner; B claimed by someone else; C unclaimed
        self.stats = _roster_stats(self.session)

    def tearDown(self):
        set_shared_league_store(None)
        self._tmp.cleanup()

    def test_active_league_summary(self):
        with _as("local:qa"):
            league = api.active_league(self.session)
        self.assertEqual(league.my_team, "Team A")
        self.assertEqual(sorted(league.team_names), ["Team A", "Team B", "Team C"])
        self.assertEqual(league.lineup_slots, ("C", "OF"))
        self.assertFalse(league.has_season_calendar)
        self.assertTrue(league.coherent)
        self.assertIsNone(api.active_league({}))

    def test_official_and_snapshot_standings_are_never_confused(self):
        with _as("local:qa"):
            official = api.official_standings_view(self.session)
        self.assertTrue(official.is_official)
        self.assertTrue(official.table.empty)
        self.assertIn("no season calendar", official.note)
        snapshot = api.current_roster_standings_view(self.stats)
        self.assertFalse(snapshot.is_official)
        self.assertEqual(snapshot.kind, "current_roster_snapshot")
        self.assertIn("not official", snapshot.label)
        pd.testing.assert_frame_equal(snapshot.table, score_current_roster_standings(self.stats, "5x5 Roto"))

    def test_official_view_equals_official_standings(self):
        with _as("local:qa"):
            ctx = get_active_league_context(self.session)
            configure_season_calendar(ctx, first_day="2026-04-06", period_count=2)
            for team, c, of in (("Team A", "Cal Raleigh", "Aaron Judge"), ("Team B", "Adley Rutschman", "Juan Soto"),
                                ("Team C", "Salvador Perez", "Kyle Tucker")):
                roster = self.stats[self.stats.Team == team]
                snap = build_lineup_snapshot(team=team, slots=["C", "OF"], slot_assignments={"C": c, "OF": of}, roster_df=roster)
                ok, err = save_period_lineup(ctx, number=1, team=team, snapshot=snap, actor=COMM, is_commissioner=True, now=AFTER)
                self.assertTrue(ok, err)
            week = self.stats.assign(PA=self.stats["AB"], **{"2B": 0, "3B": 0, "BB": 0, "HBP": 0, "SF": 0, "TB": self.stats["H"], "G": 6})
            ok, err, _ = finalize_period(ctx, 1, stats_df=week, actor=COMM, is_commissioner=True, now=AFTER)
            self.assertTrue(ok, err)
            upsert_league_context(self.session, ctx)
            view = api.official_standings_view(self.session)
        table, weeks = official_standings(get_active_league_context(self.session))
        self.assertEqual(view.finalized_weeks, (1,))
        pd.testing.assert_frame_equal(view.table, table)

    def test_trade_evaluation_matches_the_trade_center_and_enforces_team_access(self):
        with _as("local:qa"):
            mine = api.evaluate_trade_for_team(self.session, my_team="Team A", partner_team="Team C",
                                               give=["Aaron Judge"], receive=["Kyle Tucker"], roster_stats=self.stats)
            claimed = api.evaluate_trade_for_team(self.session, my_team="Team B", partner_team="Team A",
                                                  give=["Juan Soto"], receive=["Aaron Judge"], roster_stats=self.stats)
            proxy = api.evaluate_trade_for_team(self.session, my_team="Team C", partner_team="Team A",
                                                give=["Kyle Tucker"], receive=["Aaron Judge"], roster_stats=self.stats)
        self.assertTrue(mine.allowed, mine.reason)
        standings = score_current_roster_standings(self.stats, "5x5 Roto")
        table, verdict, gain = evaluate_trade(["Aaron Judge"], ["Kyle Tucker"], self.stats[self.stats.Team == "Team A"],
                                              self.stats, standings, "Team A")
        pd.testing.assert_frame_equal(mine.category_table, table)
        self.assertEqual((mine.verdict, mine.weighted_gain), (verdict, gain))
        self.assertTrue(mine.proposal_ok, mine.proposal_message)
        self.assertEqual(mine.acting_as, "owner")
        self.assertIn("not the official standings", mine.basis)
        self.assertFalse(claimed.allowed)
        self.assertIn("managed by", claimed.reason)
        self.assertTrue(claimed.category_table.empty)
        self.assertTrue(proxy.allowed)
        self.assertEqual(proxy.acting_as, "commissioner_proxy")

    def test_trade_proposal_rules_are_reported(self):
        with _as("local:qa"):
            bad = api.evaluate_trade_for_team(self.session, my_team="Team A", partner_team="Team C",
                                              give=["Juan Soto"], receive=["Kyle Tucker"], roster_stats=self.stats)
        self.assertTrue(bad.allowed)
        self.assertFalse(bad.proposal_ok)
        self.assertEqual(bad.proposal_message, "Juan Soto is not on Team A's roster.")

    def test_reads_never_touch_the_session(self):
        before = _frozen(self.session)
        with _as("local:qa"):
            api.active_league(self.session)
            api.official_standings_view(self.session)
            api.team_access(self.session, "Team C")
            api.loaded_roster_stats(self.session)
            api.evaluate_trade_for_team(self.session, my_team="Team A", partner_team="Team C", give=["Aaron Judge"],
                                        receive=["Kyle Tucker"], roster_stats=self.stats)
        self.assertEqual(_frozen(self.session), before)

    def test_loaded_roster_stats_never_fetches(self):
        frame, loaded_at = api.loaded_roster_stats(self.session)
        self.assertTrue(frame.empty)
        self.session["fantasy_current_roster_stats"] = self.stats
        self.session["_fantasy_standings_stats_loaded_at"] = "2026-10-16T12:00:00+00:00"
        frame, loaded_at = api.loaded_roster_stats(self.session)
        self.assertEqual(len(frame), len(self.stats))
        self.assertEqual(loaded_at, "2026-10-16T12:00:00+00:00")


class LineupApiTests(unittest.TestCase):
    def test_explain_slot_eligibility_uses_the_save_rule(self):
        busch = {"Player": "Michael Busch", "Primary Position": "1B", "Eligible Positions": "1B"}
        springer = {"Player": "George Springer", "Primary Position": "DH", "Eligible Positions": "OF, DH"}
        no_3b = api.explain_slot_eligibility(busch, "3B")
        self.assertFalse(no_3b["eligible"])  # no assumed 1B<->3B substitution in the save rule
        self.assertIn("can't play 3B", no_3b["reason"])
        self.assertTrue(api.explain_slot_eligibility(springer, "OF")["eligible"])
        self.assertTrue(api.explain_slot_eligibility(springer, "UTIL")["eligible"])
        self.assertIn("10 games", no_3b["rule"])

    def test_check_lineup_and_report(self):
        roster = STATS[STATS.Player.isin(["Cal Raleigh", "Aaron Judge", "Juan Soto"])].assign(Team="Team A")
        ok = api.check_lineup(["C", "OF"], {"C": "Cal Raleigh", "OF": "Aaron Judge"}, roster)
        self.assertTrue(ok["ok"], ok["messages"])
        wrong = api.check_lineup(["C", "OF"], {"C": "Aaron Judge", "OF": "Juan Soto"}, roster)
        self.assertFalse(wrong["ok"])
        report = api.lineup_report(roster, slots=["C", "OF"])
        self.assertEqual(report["recommended"]["Player"].tolist()[0], "Cal Raleigh")
        self.assertEqual(report["missing_slots"], [])
        self.assertIn("hitting_table", report["diagnosis"])


if __name__ == "__main__":
    unittest.main()
