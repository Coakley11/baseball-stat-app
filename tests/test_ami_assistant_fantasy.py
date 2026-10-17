"""AMI's read-only fantasy tools: parity with the shared functions the UI uses, access rules,
missing states, and proof that reading never changes the session.

League fixture: the shared-API tests' 3-team league (local:qa owns Team A and is commissioner,
Team B is claimed by another account, Team C is unclaimed), plus a season calendar with Week 1
finalized and the roster stats a page would have loaded.
"""

from __future__ import annotations

import pickle
import tempfile
import unittest
from collections.abc import MutableMapping
from pathlib import Path

import pandas as pd

import fantasy_read_api as api
import u1_answers
from ami_assistant.engine import ask
from ami_assistant.fantasy_router import F_FIND_ELIGIBLE, F_GAINS, F_STANDINGS, F_WAIVER
from ami_assistant.tools import REGISTRY
from ami_assistant.tools import fantasy as ft
from ami_assistant.tools import registry as codes
from fantasy_league_context import get_active_league_context, upsert_league_context
from fantasy_season_ledger import build_lineup_snapshot, configure_season_calendar, get_period_lineup, save_period_lineup
from fantasy_season_results import finalize_period, official_standings, period_category_table, scoring_categories
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from fantasy_standings_snapshot import SNAPSHOT_LABEL, score_current_roster_standings
from tests.ami_assistant_fixtures import synthetic_dataset
from tests.test_fantasy_read_api import AFTER, COMM, _roster_stats
from tests.test_team_control_and_local_saves import _as, _league

ME = "local:qa"
SLOTS = ("C", "1B", "2B", "3B", "SS", "OF", "UTIL")
FANTASY_TOOLS = [s.name for s in REGISTRY.specs() if s.capability == "fantasy_team"]


def _frozen(session) -> bytes:
    return pickle.dumps({k: session[k] for k in sorted(session, key=str) if k != "_ami_assistant_conversation"})


class ProxySession(MutableMapping):
    """Like Streamlit's SessionStateProxy: a MutableMapping that is not a dict."""

    def __init__(self, data: dict) -> None:
        self._d = data

    def __getitem__(self, k):
        return self._d[k]

    def __setitem__(self, k, v):
        self._d[k] = v

    def __delitem__(self, k):
        del self._d[k]

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)


class LeagueCase(unittest.TestCase):
    calendar = True
    finalize = True
    stats_loaded = True

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))
        self.session: dict = {}
        _league(self.session, claim_b="uuid-b")
        stats = _roster_stats(self.session)
        # Multi-position eligibility as the page feed carries it (Phase D3 "Eligible Positions").
        stats["Eligible Positions"] = stats["Player"].map({"Cal Raleigh": "C, 1B", "Aaron Judge": "OF, DH"}).fillna(stats["Primary Position"])
        self.stats = stats
        with _as(ME):
            ctx = get_active_league_context(self.session)
            if self.calendar:
                configure_season_calendar(ctx, first_day="2026-04-06", period_count=30)
            if self.calendar and self.finalize:
                for team, c, of in (("Team A", "Cal Raleigh", "Aaron Judge"), ("Team B", "Adley Rutschman", "Juan Soto"),
                                    ("Team C", "Salvador Perez", "Kyle Tucker")):
                    snap = build_lineup_snapshot(team=team, slots=["C", "OF"], slot_assignments={"C": c, "OF": of},
                                                 roster_df=stats[stats.Team == team])
                    ok, err = save_period_lineup(ctx, number=1, team=team, snapshot=snap, actor=COMM, is_commissioner=True, now=AFTER)
                    self.assertTrue(ok, err)
                week = stats.assign(PA=stats["AB"], **{"2B": 0, "3B": 0, "BB": 0, "HBP": 0, "SF": 0, "TB": stats["H"], "G": 6})
                week.loc[week.Player == "Kyle Tucker", "HR"] = 6
                week.loc[week.Player == "Juan Soto", "SB"] = 3
                ok, err, _ = finalize_period(ctx, 1, stats_df=week, actor=COMM, is_commissioner=True, now=AFTER)
                self.assertTrue(ok, err)
            upsert_league_context(self.session, ctx)
        if self.stats_loaded:
            self.session["fantasy_current_roster_stats"] = stats
            self.session["_fantasy_standings_stats_loaded_at"] = "2026-10-17T12:00:00+00:00"

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmp.cleanup()

    def call(self, name: str, **args):
        with _as(ME):
            return REGISTRY.call(name, args, session=self.session)

    def context(self) -> dict:
        with _as(ME):
            return get_active_league_context(self.session)


class ParityTests(LeagueCase):
    def test_official_standings_are_the_ledger_table_and_the_page_chips(self) -> None:
        res = self.call("get_official_standings")
        self.assertTrue(res.ok, res.message)
        ctx = self.context()
        table, weeks = official_standings(ctx)
        self.assertEqual((res.data["kind"], res.data["label"]), (api.OFFICIAL_KIND, api.OFFICIAL_LABEL))
        self.assertEqual(res.data["finalized_weeks"], weeks)
        self.assertEqual([(r["Rank"], r["Team"], r["Total Points"]) for r in res.data["rows"]],
                         [(int(r.Rank), r.Team, float(r["Total Points"])) for _, r in table.iterrows()])
        cats = scoring_categories(ctx)
        notes = u1_answers.category_strengths_and_gaps(table, "Team A", cats, max_gaps=len(cats))
        self.assertEqual((res.data["strengths"], res.data["opportunities"]), (notes["strengths"], notes["opportunities"]))
        mine = table[table.Team == "Team A"].iloc[0]
        self.assertEqual(res.data["position"]["rank"], int(mine.Rank))
        self.assertEqual(res.data["position"]["behind_first"], float(table["Total Points"].max() - mine["Total Points"]))

    def test_current_roster_snapshot_matches_and_keeps_its_label(self) -> None:
        res = self.call("get_current_roster_standings")
        self.assertTrue(res.ok, res.message)
        self.assertEqual(res.data["kind"], "current_roster_snapshot")
        self.assertEqual(res.data["label"], SNAPSHOT_LABEL)
        self.assertIn("not official", res.data["label"])
        expected = score_current_roster_standings(self.stats, "5x5 Roto")
        self.assertEqual([r["Fantasy Team"] for r in res.data["rows"]], expected["Fantasy Team"].tolist())
        self.assertEqual([r["Total Roto Points"] for r in res.data["rows"]], expected["Total Roto Points"].tolist())
        mine = expected[expected["Fantasy Team"] == "Team A"].iloc[0]
        self.assertEqual(res.data["position"]["tied"], int((expected["League Rank"] == mine["League Rank"]).sum()) > 1)

    def test_trade_is_evaluate_trade_for_team(self) -> None:
        res = self.call("evaluate_trade", give=["Cal Raleigh"], receive=["Kyle Tucker"], slot="C")
        self.assertTrue(res.ok, res.message)
        with _as(ME):
            ev = api.evaluate_trade_for_team(self.session, my_team="Team A", partner_team="Team C", give=["Cal Raleigh"],
                                             receive=["Kyle Tucker"], roster_stats=self.stats)
        self.assertEqual((res.data["verdict"], res.data["weighted_gain"]), (ev.verdict, ev.weighted_gain))
        self.assertEqual(res.data["legality_warnings"], list(ev.legality_warnings))
        self.assertEqual(res.data["partner"], "Team C")  # inferred from who owns Kyle Tucker
        self.assertEqual(res.data["slot_check"]["eligible_after"], [])  # no catcher left, by Save Lineup's rule
        self.assertTrue(any("without an eligible C" in w for w in res.data["legality_warnings"]))

    def test_lineup_report_is_the_lineup_assistants(self) -> None:
        res = self.call("get_lineup_report")
        self.assertTrue(res.ok, res.message)
        frame = self.stats[self.stats.Team == "Team A"]
        report = api.lineup_report(frame, slots=["C", "OF"], scoring_format="5x5 Roto")
        self.assertEqual([r["player"] for r in res.data["recommended"]], report["recommended"]["Player"].tolist())
        self.assertEqual(res.data["missing_slots"], list(report["missing_slots"]))
        starters = set(report["recommended"]["Player"])
        self.assertEqual(res.data["bench"], [p for p in frame.Player if p not in starters])
        self.assertEqual(set(res.data["bench"]) | starters, set(frame.Player))

    def test_slot_eligibility_matches_save_lineup_for_every_player_and_slot(self) -> None:
        for _, row in self.stats.iterrows():
            team_frame = self.stats[self.stats.Team == row.Team]
            for slot in SLOTS:
                res = self.call("check_slot_eligibility", player=row.Player, slot=slot)
                self.assertTrue(res.ok, res.message)
                expected = api.explain_slot_eligibility(row, slot)["eligible"]
                save_ok = api.check_lineup([slot], {slot: row.Player}, team_frame)["ok"]
                self.assertEqual(res.data["eligible"], expected, (row.Player, slot))
                self.assertEqual(res.data["eligible"], save_ok, (row.Player, slot))
        # Multi-position from the shared rule, no intuition: Raleigh 1B yes, 3B no; Judge never SS.
        self.assertTrue(self.call("check_slot_eligibility", player="Cal Raleigh", slot="1B").data["eligible"])
        self.assertFalse(self.call("check_slot_eligibility", player="Cal Raleigh", slot="3B").data["eligible"])
        self.assertFalse(self.call("check_slot_eligibility", player="Judge", slot="SS").data["eligible"])

    def test_week_tools_read_the_ledger(self) -> None:
        week = self.call("get_week", week=1)
        self.assertTrue(week.ok, week.message)
        table = period_category_table(self.context(), 1)
        mine = table[table.Team == "Team A"].iloc[0]
        self.assertEqual((week.data["rank"], week.data["points"]), (int(mine.Rank), float(mine["Total Points"])))
        lineup = self.call("get_week_lineup", week=1)
        snap = get_period_lineup(self.context(), 1, "Team A")
        self.assertEqual([s["player"] for s in lineup.data["starters"]], [s["player_name"] for s in snap["starters"]])
        bench_or_not = self.call("explain_player_week", player="Juan Soto", week=1)
        self.assertEqual((bench_or_not.data["reason"], bench_or_not.data["owner_now"]), ("not_in_lineup", "Team B"))
        counted = self.call("explain_player_week", player="Judge")
        self.assertEqual((counted.data["reason"], counted.data["player"]), ("counted", "Aaron Judge"))


class AccessTests(LeagueCase):
    def test_commissioner_viewing_an_unclaimed_team_is_said_plainly(self) -> None:
        res = self.call("get_lineup_report", team="Team C")
        self.assertTrue(res.ok, res.message)
        self.assertEqual(res.data["access"]["mode"], "commissioner_proxy")
        self.assertEqual(res.data["access"]["text"], "You're viewing Team C as commissioner; the team is currently unclaimed.")

    def test_another_managers_team_private_data_is_refused(self) -> None:
        for name, args in (("get_lineup_report", {"team": "Team B"}), ("find_eligible_players", {"team": "Team B", "slot": "C"}),
                           ("explain_player_week", {"team": "Team B", "player": "Juan Soto"}),
                           ("evaluate_trade", {"team": "Team B", "give": ["Juan Soto"], "receive": ["Aaron Judge"]})):
            res = self.call(name, **args)
            self.assertEqual(res.error_code, ft.NOT_YOUR_TEAM, name)
        self.assertTrue(self.call("get_official_standings", team="Team B").ok)  # league-wide data stays readable
        self.assertTrue(self.call("get_week_lineup", team="Team B", week=1).ok)  # a week that has started
        self.assertEqual(self.call("get_week_lineup", team="Team B", week=30).error_code, ft.NOT_YOUR_TEAM)  # upcoming

    def test_a_team_must_exist_before_access_is_trusted(self) -> None:
        # The shared team_access treats unknown names like unclaimed teams; AMI checks the league first.
        with _as(ME):
            self.assertTrue(api.team_access(self.session, "Nope").can_manage)
        for name in ("get_lineup_report", "get_official_standings", "find_eligible_players"):
            args = {"team": "Nope"} if name != "find_eligible_players" else {"team": "Nope", "slot": "C"}
            self.assertEqual(self.call(name, **args).error_code, ft.UNKNOWN_TEAM, name)


class NoLeagueTests(unittest.TestCase):
    def test_every_fantasy_tool_says_there_is_no_league(self) -> None:
        args = {"check_slot_eligibility": {"player": "Judge", "slot": "SS"}, "find_eligible_players": {"slot": "SS"},
                "explain_player_week": {"player": "Judge"}, "evaluate_trade": {"give": ["A"], "receive": ["B"]}}
        for name in FANTASY_TOOLS:
            res = REGISTRY.call(name, args.get(name, {}), session={})
            expected = codes.NOT_WIRED if name == "get_waiver_recommendations" else codes.MISSING_ACTIVE_LEAGUE
            self.assertEqual(res.error_code, expected, name)


class NoCalendarTests(LeagueCase):
    calendar = False

    def test_no_calendar(self) -> None:
        official = self.call("get_official_standings")
        self.assertTrue(official.ok)
        self.assertEqual(official.data["rows"], [])
        self.assertIn("no season calendar", official.data["note"])
        self.assertEqual(self.call("get_week").error_code, ft.NO_SEASON_CALENDAR)


class NoFinalizedWeekTests(LeagueCase):
    finalize = False

    def test_no_final_week(self) -> None:
        official = self.call("get_official_standings")
        self.assertEqual((official.data["rows"], official.data["note"]), ([], "No week is final yet."))
        self.assertEqual(self.call("get_week").message, "No week is final yet.")
        with _as(ME):
            answer = ask("Where am I in the standings?", session_state=self.session, active_page="Fantasy Standings Tracker",
                         dataset=synthetic_dataset()).answer
        self.assertIn("No week is final yet.", answer)
        self.assertIn("How would my current roster rank", answer)  # offered, not substituted


class NoRosterStatsTests(LeagueCase):
    stats_loaded = False

    def test_tools_needing_stats_say_where_to_load_them(self) -> None:
        for name, args in (("get_lineup_report", {}), ("check_slot_eligibility", {"player": "Judge", "slot": "OF"}),
                           ("evaluate_trade", {"give": ["Cal Raleigh"], "receive": ["Kyle Tucker"]}),
                           ("get_current_roster_standings", {}), ("find_eligible_players", {"slot": "C"})):
            res = self.call(name, **args)
            self.assertEqual(res.error_code, ft.NO_ROSTER_STATS, name)
            self.assertIn("League Standings", res.message)
        self.assertTrue(self.call("get_official_standings").ok)  # official standings don't need the stats feed


class SideEffectTests(LeagueCase):
    ARGS = {"get_week": {"week": 1}, "get_week_lineup": {"week": 1}, "explain_player_week": {"player": "Judge"},
            "check_slot_eligibility": {"player": "Cal Raleigh", "slot": "1B"}, "find_eligible_players": {"slot": "C"},
            "evaluate_trade": {"give": ["Cal Raleigh"], "receive": ["Kyle Tucker"], "slot": "C"}}

    def test_every_fantasy_tool_leaves_the_session_byte_identical(self) -> None:
        for session in (self.session, ProxySession(self.session)):
            before = _frozen(session)
            with _as(ME):
                for name in FANTASY_TOOLS:
                    REGISTRY.call(name, self.ARGS.get(name, {}), session=session)
            self.assertEqual(_frozen(session), before)

    def test_questions_change_nothing_but_the_conversation(self) -> None:
        before = _frozen(self.session)
        ds = synthetic_dataset()
        with _as(ME):
            for q in ("Where am I in the standings?", "Where could I gain a roto point?", "What happened last week?",
                      "Who was in my Week 1 lineup?", "Can Cal Raleigh play first base?", "Which positions are empty?",
                      "Would trading Cal Raleigh for Kyle Tucker leave me without a catcher?",
                      "How would my current roster rank right now?", "Use suggested lineup for me", "Finalize week 2",
                      "Drop Aaron Judge", "What about waivers?"):
                ask(q, session_state=self.session, active_page="Fantasy Lineup Assistant", dataset=ds)
        self.assertEqual(_frozen(self.session), before)


class ConversationTests(LeagueCase):
    def test_standings_then_gains_then_bench_then_waivers(self) -> None:
        ds = synthetic_dataset()
        with _as(ME):
            first = ask("Where am I in the standings?", session_state=self.session, active_page="Fantasy Standings Tracker", dataset=ds)
            second = ask("Where can I gain points?", session_state=self.session, active_page="Fantasy Standings Tracker", dataset=ds)
            third = ask("Do I have anyone on my bench who can help at catcher?", session_state=self.session,
                        active_page="Fantasy Lineup Assistant", dataset=ds)
            fourth = ask("What about waivers?", session_state=self.session, active_page="Fantasy Lineup Assistant", dataset=ds)
        self.assertEqual(first.intent, F_STANDINGS)
        self.assertIn(api.OFFICIAL_LABEL, first.answer)
        self.assertIn("3rd of 3", first.answer)
        self.assertNotIn("behind Team B", first.answer)  # Team B is (tied for) first: "behind first" already says it
        self.assertEqual(second.intent, F_GAINS)
        self.assertIn("HR: 4 behind Team C", second.answer)
        self.assertEqual(third.intent, F_FIND_ELIGIBLE)
        self.assertIn("Cal Raleigh", third.answer)
        self.assertEqual(fourth.intent, F_WAIVER)
        self.assertIn("For C", fourth.answer)  # the catcher context carried over
        self.assertIn("can't read the Waiver Wire", fourth.answer)
        # Nothing was read from the league, so the source line must not say so.
        self.assertFalse(any("Your league" in b for b in fourth.basis), fourth.basis)
        self.assertEqual(fourth.grounding_label, "App help")

    def test_snapshot_answer_never_claims_to_be_the_standings(self) -> None:
        with _as(ME):
            res = ask("How would my current roster rank right now?", session_state=self.session,
                      active_page="Fantasy Standings Tracker", dataset=synthetic_dataset())
        self.assertIn(SNAPSHOT_LABEL, res.answer)
        self.assertIn("tied for 1st", res.answer)  # all three rosters score the same in this fixture
        self.assertNotIn(api.OFFICIAL_LABEL + " after", res.answer)
        self.assertIn(SNAPSHOT_LABEL, res.basis)


if __name__ == "__main__":
    unittest.main()
