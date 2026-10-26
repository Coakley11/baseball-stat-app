"""AMI over the shared fantasy readers (633538f): parity with the pages, access, and no side effects.

Fixture: the regular reader tests' league (``tests.test_ami_shared_readers._LeagueCase``): local:qa
owns Team A and is commissioner, Team B is claimed by someone else, Team C is unclaimed, and the
current stats, standings and hitter pool are loaded as League Standings leaves them. Each "page"
answer below is computed by that page's own functions on the same session.
"""

from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
import unittest
from collections.abc import MutableMapping
from pathlib import Path
from unittest import mock

import fantasy_read_api as api
import tests.test_ami_shared_readers as shared
from ami_assistant.engine import ask
from ami_assistant.tools import REGISTRY
from ami_assistant.tools import fantasy as ft
from ami_assistant.tools import registry as codes
from fantasy_league_context import get_active_league_context, upsert_league_context
from fantasy_season_ledger import build_lineup_snapshot, configure_season_calendar, get_period_lineup, save_period_lineup
from fantasy_season_results import period_category_table
from fantasy_standings_snapshot import score_current_roster_standings
from tests.ami_assistant_fixtures import synthetic_dataset

ROOT = Path(__file__).resolve().parents[1]
FANTASY_TOOLS = [s.name for s in REGISTRY.specs() if s.capability == "fantasy_team"]
CARD_FIELDS = ("verdict_label", "value_label", "verdict_headline", "verdict_body")


def call(session, name, **args):
    return REGISTRY.call(name, args, session=session)


def frozen(session) -> bytes:
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


def trade_center_card(session, my_team: str, give: list[str], receive: list[str], partner: str) -> dict:
    """Trade Center's own verdict card for this trade: its workspace, its roster checks, its package."""
    import fantasy_trade_center_ui as tc
    from fantasy_standings_snapshot import summarize_team_category_needs
    from fantasy_trade_analysis import build_trade_analysis_package
    from fantasy_trade_category_values import format_trade_category_value
    from fantasy_trade_evaluation import build_trade_verdict_text, evaluate_trade
    from u3_answers import trade_verdict

    ws = tc._trade_workspace(session, my_team=my_team)
    issues = tc._trade_roster_issues(session, proposer_team=my_team, recipient_team=partner,
                                     proposer_gives=give, proposer_receives=receive)
    package = build_trade_analysis_package(
        give_players=give, receive_players=receive, roster_stats=ws["roster_stats"], standings=ws["standings"],
        my_team=my_team, evaluate_trade_fn=evaluate_trade, build_trade_verdict_text_fn=build_trade_verdict_text,
        summarize_team_category_needs_fn=summarize_team_category_needs)
    card = trade_verdict(package, my_team=my_team, partner=partner, roster_issues=issues,
                         format_change=lambda c, v: format_trade_category_value(c, v, is_change=True))
    return {"verdict_label": card["label"], "value_label": card["value_label"], "verdict_headline": card["headline"],
            "verdict_body": card["body"], "roster_issues": issues}


class TradeParityTests(shared._LeagueCase):
    def assert_same_as_trade_center(self, my_team, give, receive, partner) -> str:
        res = call(self.session, "evaluate_trade", team=my_team, give=give, receive=receive)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(res.data["partner"], partner)  # the receive side's owner, from player_owner
        card = trade_center_card(self.session, my_team, give, receive, partner)
        self.assertEqual({k: res.data[k] for k in CARD_FIELDS}, {k: card[k] for k in CARD_FIELDS}, (give, receive))
        self.assertEqual([(i["team"], i["kind"], i["slot"], i["message"]) for i in res.data["roster_issues"]],
                         [(i["team"], i["kind"], i["slot"], i["message"]) for i in card["roster_issues"]])
        return res.data["verdict_label"]

    def test_every_verdict_equals_the_trade_center_card(self) -> None:
        labels = {
            self.assert_same_as_trade_center("Team A", ["Aaron Judge"], ["Juan Soto"], "Team B"),
            self.assert_same_as_trade_center("Team A", ["Cal Raleigh"], ["Kyle Tucker"], "Team C"),
            # Team C is unclaimed: the commissioner evaluates for it (proxy), and the reverse trade favors it.
            self.assert_same_as_trade_center("Team C", ["Salvador Perez"], ["Cal Raleigh"], "Team A"),
        }
        self.assertEqual(labels, {"Favors the other team", "Creates roster issue", "Favors your team"})

    def test_balanced(self) -> None:
        # Give Kyle Tucker Aaron Judge's stat line: the swap is value-neutral, so the card reads Balanced.
        stats = self.stats.copy()
        judge = stats[stats.Player == "Aaron Judge"].iloc[0]
        for col in ("H", "AB", "HR", "R", "RBI", "SB", "BA", "OBP", "SLG", "OPS"):
            stats.loc[stats.Player == "Kyle Tucker", col] = judge[col]
        self.session["fantasy_current_roster_stats"] = stats
        self.session["fantasy_current_standings"] = score_current_roster_standings(stats, "5x5 Roto")
        self.assertEqual(self.assert_same_as_trade_center("Team A", ["Aaron Judge"], ["Kyle Tucker"], "Team C"), "Balanced")

    def test_pending_trade_and_follow_up(self) -> None:
        from fantasy_trade_builder_state import builder_widget_keys

        keys = builder_widget_keys(shared.PendingTradeTests._scope_key(self))
        self.session.update({keys["give"]: ["Cal Raleigh"], keys["receive"]: ["Kyle Tucker"], keys["partner"]: "Any team"})
        res = call(self.session, "evaluate_trade")  # "What do you think of this trade?"
        self.assertEqual((res.data["source"], res.data["give"], res.data["receive"]), ("trade_center", ["Cal Raleigh"], ["Kyle Tucker"]))
        card = trade_center_card(self.session, "Team A", ["Cal Raleigh"], ["Kyle Tucker"], "Team C")
        self.assertEqual({k: res.data[k] for k in CARD_FIELDS}, {k: card[k] for k in CARD_FIELDS})
        ds = synthetic_dataset()
        answer = ask("What do you think of this trade?", session_state=self.session, active_page="Fantasy Lineup Assistant", dataset=ds)
        self.assertIn("(the trade in Trade Center)", answer.answer)
        self.assertIn("**Creates roster issue**", answer.answer)
        # A named trade, then "Would this leave me without a catcher?": the same trade, from the shared issues.
        session: dict = dict(self.session)
        session.pop(keys["give"])
        ask("Would trading Aaron Judge for Juan Soto help me?", session_state=session, active_page="Fantasy Lineup Assistant", dataset=ds)
        follow = ask("Would this leave me without a catcher?", session_state=session, active_page="Fantasy Lineup Assistant", dataset=ds)
        self.assertIn("**No** — you'd still have an eligible catcher", follow.answer)
        self.assertIn("Aaron Judge", follow.answer)

    def test_invalid_players_and_unauthorized_teams(self) -> None:
        self.assertEqual(call(self.session, "evaluate_trade", give=["Nobody Atall"], receive=["Kyle Tucker"]).error_code,
                         codes.UNKNOWN_PLAYER)
        not_mine = call(self.session, "evaluate_trade", give=["Juan Soto"], receive=["Kyle Tucker"])
        self.assertEqual(not_mine.error_code, codes.BAD_ARGUMENT)
        self.assertIn("not on Team A", not_mine.message)
        self.assertEqual(call(self.session, "evaluate_trade", team="Team B", give=["Juan Soto"], receive=["Aaron Judge"]).error_code,
                         ft.NOT_YOUR_TEAM)
        self.assertEqual(call(self.session, "evaluate_trade", team="Team Z", give=["Juan Soto"], receive=["Aaron Judge"]).error_code,
                         ft.UNKNOWN_TEAM)
        self.assertEqual(call(self.session, "evaluate_trade").error_code, ft.NO_PENDING_TRADE)  # nothing composed yet


class LineupParityTests(shared._LeagueCase):
    def page(self, team="Team A"):
        # The page words a commissioner-proxy lineup as "Team C's lineup…" (proxy=True), like the reader.
        return shared.LineupStatusTests._page_answer(self, team=team, proxy=team == "Team C")

    def assert_same_as_lineup_page(self, team="Team A") -> dict:
        res = call(self.session, "get_lineup_status", team=team)
        self.assertTrue(res.ok, res.message)
        state, page = self.page(team)
        self.assertEqual((res.data["status"], res.data["headline"], res.data["body"]),
                         (page["status"], page["headline"], page["body"]))
        self.assertEqual((res.data["locked"], res.data["edit_message"]), (state["locked"], state["edit_message"]))
        return res.data

    def test_not_saved_draft_and_saved_locked(self) -> None:
        from fantasy_weekly_lineup import persist_weekly_lineup_draft, save_weekly_lineup

        roster = self.stats[self.stats.Team == "Team A"]
        self.assertEqual(self.assert_same_as_lineup_page()["status"], "Not saved yet")
        persist_weekly_lineup_draft(self.session, week=1, slots=["C", "OF"], assignments={"C": "Cal Raleigh", "OF": ""},
                                    my_team="Team A", roster_df=roster)
        draft = self.assert_same_as_lineup_page()
        self.assertEqual((draft["status"], draft["open_positions"]), ("Draft (not submitted)", ["OF 1"]))
        ds = synthetic_dataset()
        open_answer = ask("Which positions are still open?", session_state=self.session,
                          active_page="Fantasy Lineup Assistant", dataset=ds).answer
        self.assertIn("Open: OF 1.", open_answer)
        save_weekly_lineup(self.session, week=1, slots=["C", "OF"], assignments={"C": "Cal Raleigh", "OF": "Aaron Judge"},
                           my_team="Team A", roster_df=roster)
        saved = self.assert_same_as_lineup_page()
        self.assertEqual((saved["status"], saved["complete"]), ("Saved and locked", True))
        answer = ask("Is my lineup saved?", session_state=self.session, active_page="Fantasy Lineup Assistant", dataset=ds).answer
        self.assertIn("Saved and locked", answer)
        self.assertIn(saved["headline"], answer)

    def test_eligibility_uses_save_lineups_rule(self) -> None:
        from fantasy_weekly_lineup import persist_weekly_lineup_draft

        roster = self.stats[self.stats.Team == "Team A"]
        persist_weekly_lineup_draft(self.session, week=1, slots=["C", "OF"], assignments={"C": "Aaron Judge", "OF": "Cal Raleigh"},
                                    my_team="Team A", roster_df=roster)
        data = self.assert_same_as_lineup_page()
        check = api.check_lineup(["C", "OF"], {"C": "Aaron Judge", "OF": "Cal Raleigh"}, roster)
        self.assertEqual(data["not_eligible"], [f"{i['player']} at {i['slot']}" for i in check["ineligible_slots"]])
        for player, slot in (("Cal Raleigh", "C"), ("Cal Raleigh", "OF"), ("Aaron Judge", "OF"), ("Aaron Judge", "C")):
            ami = call(self.session, "check_slot_eligibility", player=player, slot=slot).data["eligible"]
            self.assertEqual(ami, api.check_lineup([slot], {slot: player}, roster)["ok"], (player, slot))

    def test_commissioner_proxy_and_claimed_team(self) -> None:
        proxy = self.assert_same_as_lineup_page("Team C")
        self.assertEqual(proxy["access"]["mode"], "commissioner_proxy")
        self.assertEqual(proxy["access"]["text"], "You're viewing Team C as commissioner; the team is currently unclaimed.")
        self.assertEqual(call(self.session, "get_lineup_status", team="Team B").error_code, ft.NOT_YOUR_TEAM)
        self.assertEqual(call(self.session, "get_lineup_status", team="Team Z").error_code, ft.UNKNOWN_TEAM)
        # An invite-reserved team isn't unclaimed: the commissioner can't act for it.
        self._reserve("Team C")
        for tool in ("get_lineup_status", "get_waiver_recommendations", "get_lineup_report"):
            self.assertEqual(call(self.session, tool, team="Team C").error_code, ft.NOT_YOUR_TEAM, tool)
        self.assertFalse(api.team_access(self.session, "Team Z").can_manage)  # nonexistent: never manageable


class WaiverParityTests(shared._LeagueCase):
    def test_equals_the_waiver_wire_answer_card(self) -> None:
        import u1_answers as u1a
        from fantasy_waiver_wire import waiver_card_fields

        for position, ami_position in (("All positions", None), ("C", "C"), ("OF", "OF")):
            with self.subTest(position=position):
                page = shared._page_waiver_capture(dict(self.session, waiver_position_filter=position))
                self.assertTrue(page, "the page reached its answer card")
                args = {"position": ami_position} if ami_position else {}
                res = call(self.session, "get_waiver_recommendations", **args)
                self.assertTrue(res.ok, res.message)
                self.assertEqual(res.data["headline"], u1a.needs_headline(page["needs"]))
                expected = [waiver_card_fields(row, page["my_roster"]) for _, row in page["adds"].head(3).iterrows()]
                self.assertEqual([(c["player"], c["positions"], c["mlb_team"], c["why"], c["comparison"]) for c in res.data["adds"]],
                                 [(e["player"], e["positions"], e["mlb_team"], e["why"], e["comparison"]) for e in expected])
                self.assertEqual(res.data["open_roster_spots"], list(page["open_slots"]))
                for card in res.data["adds"]:  # every recommendation is a free agent, by the shared ownership reader
                    self.assertEqual(call(self.session, "get_player_owner", player=card["player"]).data["status"], "free_agent")

    def test_why_is_this_player_recommended(self) -> None:
        top = call(self.session, "get_waiver_recommendations").data["adds"][0]
        answer = ask(f"Why is {top['player']} recommended?", session_state=self.session,
                     active_page="Waiver Wire / Add-Drop Center", dataset=synthetic_dataset()).answer
        self.assertIn(top["why"], answer)
        self.assertIn(f"#{top['rank']}", answer)
        rostered = ask("Why is Juan Soto recommended?", session_state=self.session,
                       active_page="Waiver Wire / Add-Drop Center", dataset=synthetic_dataset()).answer
        self.assertIn("Juan Soto is on Team B's roster", rostered)

    def test_access(self) -> None:
        self.assertEqual(call(self.session, "get_waiver_recommendations", team="Team C").data["access"]["mode"], "commissioner_proxy")
        self.assertEqual(call(self.session, "get_waiver_recommendations", team="Team B").error_code, ft.NOT_YOUR_TEAM)
        pool = call(self.session, "find_available_players", position="C")
        self.assertTrue(pool.ok)
        self.assertTrue(all(call(self.session, "get_player_owner", player=r["player"]).data["status"] == "free_agent"
                            for r in pool.data["rows"]))


class WeekHistoryParityTests(shared._LeagueCase):
    def setUp(self) -> None:
        super().setUp()
        shared.WeekViewTests._finalize_week_one(self)

    def test_a_finalized_week_is_frozen_after_a_drop(self) -> None:
        # After Week 1 is final, Team A drops Aaron Judge (he leaves every roster).
        ctx = get_active_league_context(self.session)
        players = ctx["league_rosters"]["Team A"]["players"]
        ctx["league_rosters"]["Team A"]["players"] = [p for p in players if p.get("player_name") != "Aaron Judge"]
        upsert_league_context(self.session, ctx)
        self.assertEqual(api.player_owner(self.session, "Aaron Judge").status, "free_agent")
        res = call(self.session, "explain_player_week", player="Judge", week=1)
        self.assertEqual((res.data["reason"], res.data["player"], res.data["owner_status"]), ("counted", "Aaron Judge", "free_agent"))
        answer = ask("Why did Judge count in week 1 even though I dropped him later?", session_state=self.session,
                     active_page="Fantasy Lineup Assistant", dataset=synthetic_dataset()).answer
        self.assertIn("did count in Week 1", answer)
        self.assertIn("frozen", answer)
        # The week's lineup and table are the frozen ledger's, not today's roster.
        lineup = call(self.session, "get_week_lineup", week=1)
        self.assertEqual([s["player"] for s in lineup.data["starters"]],
                         [s["player_name"] for s in get_period_lineup(get_active_league_context(self.session), 1, "Team A")["starters"]])
        self.assertIn("Aaron Judge", [s["player"] for s in lineup.data["starters"]])
        week = call(self.session, "get_week", week=1)
        table = period_category_table(get_active_league_context(self.session), 1)
        mine = table[table.Team == "Team A"].iloc[0]
        self.assertEqual((week.data["rank"], week.data["points"]), (int(mine.Rank), float(mine["Total Points"])))

    def test_another_teams_week(self) -> None:
        soto = call(self.session, "explain_player_week", team="Team B", player="Juan Soto", week=1)
        self.assertTrue(soto.ok, soto.message)
        self.assertEqual(soto.data["reason"], "no_stats")  # started, but no games that week (matched_by: no_games)
        self.assertTrue(call(self.session, "get_week_lineup", team="Team B", week=1).ok)



class UnstartedWeekTests(shared._LeagueCase):
    def test_an_unstarted_week_stays_private(self) -> None:
        ctx = get_active_league_context(self.session)
        configure_season_calendar(ctx, first_day="2030-04-01", period_count=2)
        for team in ("Team A", "Team B"):
            snap = build_lineup_snapshot(team=team, slots=["C", "OF"], slot_assignments={},
                                         roster_df=self.stats[self.stats.Team == team])
            self.assertTrue(save_period_lineup(ctx, number=1, team=team, snapshot=snap, actor=shared.COMM, is_commissioner=True)[0])
        upsert_league_context(self.session, ctx)
        self.assertEqual(call(self.session, "get_week_lineup", team="Team B", week=1).error_code, ft.NOT_YOUR_TEAM)
        self.assertTrue(call(self.session, "get_week_lineup", team="Team A", week=1).ok)


class StandingsParityTests(shared._LeagueCase):
    def test_official_and_current_never_mix(self) -> None:
        shared.WeekViewTests._finalize_week_one(self)
        official = call(self.session, "get_official_standings")
        view = api.official_standings_view(self.session)
        self.assertEqual((official.data["kind"], official.data["label"]), (view.kind, view.label))
        self.assertEqual([(r["Rank"], r["Team"]) for r in official.data["rows"]],
                         [(int(r.Rank), r.Team) for _, r in view.table.iterrows()])
        current = call(self.session, "get_current_roster_standings")
        snap = api.current_roster_standings_view(self.stats)
        self.assertEqual((current.data["kind"], current.data["label"]), (snap.kind, snap.label))
        self.assertNotEqual(official.data["kind"], current.data["kind"])
        ds = synthetic_dataset()
        where = ask("Where am I in the official standings?", session_state=self.session, active_page="Fantasy Standings Tracker", dataset=ds)
        what_if = ask("How would my current roster rank?", session_state=self.session, active_page="Fantasy Standings Tracker", dataset=ds)
        self.assertIn(view.label, where.answer)
        self.assertNotIn(snap.label, where.answer.split("\n\n")[0])
        self.assertIn(snap.label, what_if.answer)
        self.assertIn(snap.label, what_if.basis)


def run_everything(session, stats) -> None:
    """Every fantasy tool and a fantasy question per reader."""
    args = {"check_slot_eligibility": {"player": "Cal Raleigh", "slot": "C"}, "find_eligible_players": {"slot": "C"},
            "explain_player_week": {"player": "Judge"}, "get_player_owner": {"player": "Juan Soto"},
            "evaluate_trade": {"give": ["Cal Raleigh"], "receive": ["Kyle Tucker"], "slot": "C"}}
    for name in FANTASY_TOOLS:
        REGISTRY.call(name, args.get(name, {}), session=session)
    REGISTRY.call("evaluate_trade", {}, session=session)  # the Trade Center draft
    ds = synthetic_dataset()
    for q in ("Is my lineup saved?", "Which positions are still open?", "Who should I consider adding?",
              "Why is Corbin Carroll recommended?", "What do you think of this trade?", "Who owns Juan Soto?",
              "Who's available at catcher?", "What happened in Week 1?", "Where am I in the standings?",
              "Use suggested lineup for me", "Drop Aaron Judge", "Accept the trade"):
        ask(q, session_state=session, active_page="Fantasy Lineup Assistant", dataset=ds)


class SideEffectTests(shared._LeagueCase):
    def test_session_is_byte_identical_dict_and_proxy(self) -> None:
        from fantasy_trade_builder_state import builder_widget_keys

        keys = builder_widget_keys(shared.PendingTradeTests._scope_key(self))
        self.session.update({keys["give"]: ["Cal Raleigh"], keys["receive"]: ["Kyle Tucker"]})
        for session in (self.session, ProxySession(self.session)):
            with self.subTest(kind=type(session).__name__):
                before = frozen(session)
                run_everything(session, self.stats)
                self.assertEqual(frozen(session), before)

    def test_no_sync_fetch_or_network(self) -> None:
        def boom(*_a, **_k):
            raise AssertionError("an AMI read tried to sync or fetch")

        with mock.patch("fantasy_shared_league_store.sync_context_with_shared_store", side_effect=boom), \
                mock.patch("fantasy_shared_league_store.push_league_context_to_shared", side_effect=boom), \
                mock.patch("fantasy_lineup_stats_loader.ensure_lineup_page_hitter_stats", side_effect=boom), \
                mock.patch("requests.sessions.Session.request", side_effect=boom):
            run_everything(self.session, self.stats)


WRITE_PROBE = r"""
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.getcwd())
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from fantasy_standings_snapshot import score_current_roster_standings
from tests.test_ami_shared_readers import POOL, _roster_stats
from tests.test_ami_assistant_readers import run_everything
from tests.test_team_control_and_local_saves import _as, _league
set_shared_league_store(LocalFileSharedLeagueStore(root=Path(tempfile.mkdtemp())))
session = {}
with _as("local:qa"):
    _league(session, claim_b="uuid-b")
    stats = _roster_stats(session)
    session.update(fantasy_current_roster_stats=stats, _fantasy_current_hitter_stats=POOL,
                   fantasy_current_standings=score_current_roster_standings(stats, "5x5 Roto"))
    run_everything(session, stats)  # warm imports and caches outside the audit
    writes, armed = [], [True]
    def audit(event, args):
        if not armed[0]:
            return
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            mode = str(args[1] or "r") if len(args) > 1 else "r"
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            if any(c in mode for c in "wax+") or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
                writes.append(str(args[0]))
        elif event in ("os.rename", "os.replace", "os.remove", "os.unlink", "shutil.rmtree"):
            writes.append(f"{event}:{args[0]}")
    sys.addaudithook(audit)
    run_everything(session, stats)
    armed[0] = False
print(json.dumps(sorted(set(writes))))
"""


class NoFileWriteTests(unittest.TestCase):
    def test_ami_reads_write_no_files(self) -> None:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        out = subprocess.run([sys.executable, "-c", WRITE_PROBE], cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
        self.assertEqual(out.returncode, 0, out.stderr[-3000:])
        self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]), [])


if __name__ == "__main__":
    unittest.main()
