"""Local no-auth lineup saves and commissioner proxy control of unclaimed teams."""

from __future__ import annotations

import copy
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

import pandas as pd

from fantasy_league_context import (
    activate_archive_league_context,
    get_active_league_context,
    save_imported_league_context,
    upsert_league_context,
)
from fantasy_league_lineup_format import apply_lineup_format_to_context
from fantasy_league_team_ownership import assign_team_owner_to_context, trades_enabled
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from fantasy_team_control import (
    MODE_COMMISSIONER_PROXY,
    MODE_NONE,
    MODE_OWNER,
    current_user_id,
    manageable_teams,
    resolve_team_control,
)

BOARD = pd.DataFrame(
    [
        {"Pick": 1, "Round": 1, "Team": "Team A", "Player": "Cal Raleigh"},
        {"Pick": 2, "Round": 1, "Team": "Team B", "Player": "Adley Rutschman"},
        {"Pick": 3, "Round": 1, "Team": "Team C", "Player": "Salvador Perez"},
        {"Pick": 4, "Round": 2, "Team": "Team A", "Player": "Aaron Judge"},
        {"Pick": 5, "Round": 2, "Team": "Team B", "Player": "Juan Soto"},
        {"Pick": 6, "Round": 2, "Team": "Team C", "Player": "Kyle Tucker"},
    ]
)
STATS = pd.DataFrame(
    [{"Player": n, "Primary Position": p, "H": 10, "AB": 40, "HR": 2, "R": 5, "RBI": 6, "SB": 0}
     for n, p in [("Cal Raleigh", "C"), ("Adley Rutschman", "C"), ("Salvador Perez", "C"), ("Aaron Judge", "OF"),
                  ("Juan Soto", "OF"), ("Kyle Tucker", "OF"), ("Mike Trout", "OF"), ("Will Smith", "C")]]
)


@contextmanager
def _as(user_id: str, *, auth: bool = False, session: dict | None = None):
    """Run as a user. auth=True mimics a hosted deployment with sign-in."""
    with ExitStack() as stack:
        stack.enter_context(mock.patch("fantasy_league_team_ownership._resolve_user_id", return_value=user_id))
        stack.enter_context(mock.patch("fantasy_league_invites._resolve_user_id", return_value=user_id))
        stack.enter_context(mock.patch("suite_user.get_account_user_id", return_value=user_id))
        stack.enter_context(mock.patch("fantasy_team_control.auth_required", return_value=auth))
        if session is not None and auth:
            session["_suite_auth_user_id"] = user_id
        yield


def _league(session: dict, *, claim_b: str = "") -> dict:
    """Imported 3-team league; local:qa owns Team A and is commissioner."""
    with _as("local:qa"):
        entry, _ = save_imported_league_context(session, BOARD, my_team_name="Team A", draft_name="QA", league_name="QA",
                                                save_only=True, assign_team=True)
        activate_archive_league_context(session, entry["draft_id"])
        ctx = get_active_league_context(session)
        ctx = apply_lineup_format_to_context(ctx, lineup_slots=["C", "OF"], roster_capacity=2, configured_by="qa",
                                             configuration_source="uploaded")
        if claim_b:
            ctx = assign_team_owner_to_context(ctx, "Team B", user_id=claim_b, email="b@qa")
        upsert_league_context(session, ctx)
    return entry


def _roster(team: str) -> pd.DataFrame:
    names = [str(r["Player"]) for _, r in BOARD.iterrows() if r["Team"] == team]
    df = STATS[STATS["Player"].isin(names)].copy()
    df["Team"] = team
    return df


def _save_lineup(session: dict, team: str):
    from fantasy_weekly_lineup import save_weekly_lineup

    names = list(_roster(team)["Player"])
    return save_weekly_lineup(session, week=1, slots=["C", "OF"], assignments={"C": names[0], "OF": names[1]},
                              my_team=team, roster_df=_roster(team))


class LocalNoAuthIdentityTests(unittest.TestCase):
    def test_local_install_uses_the_local_account(self):
        with _as("local:qa", auth=False):
            self.assertEqual(current_user_id({}), "local:qa")

    def test_hosted_install_still_requires_sign_in(self):
        with _as("local:qa", auth=True):
            self.assertEqual(current_user_id({}), "")
            self.assertEqual(current_user_id({"_suite_auth_user_id": "uuid-a"}), "uuid-a")

    def test_lineup_scope_write_allowed_locally_and_blocked_unsigned_hosted(self):
        from fantasy_lineup_scope import assert_lineup_write_identity, resolve_lineup_scope

        session: dict = {}
        _league(session)
        ctx = get_active_league_context(session)
        with _as("local:qa", auth=False):
            ok, err = assert_lineup_write_identity(resolve_lineup_scope(session, ctx, week=1, page_lineup_team="Team A"))
            self.assertTrue(ok, err)  # was "Sign in to save lineup changes."
        with _as("local:qa", auth=True):
            ok, err = assert_lineup_write_identity(resolve_lineup_scope({}, ctx, week=1, page_lineup_team="Team A"))
            self.assertEqual(err, "Sign in to save lineup changes.")

    def test_local_save_survives_reopen(self):
        from fantasy_league_context import FANTASY_LEAGUE_CONTEXT_STATE_KEY
        from fantasy_weekly_lineup import get_saved_weekly_lineup

        session: dict = {}
        _league(session)
        with _as("local:qa"):
            self.assertTrue(_save_lineup(session, "Team A")["ok"])
        reopened = {FANTASY_LEAGUE_CONTEXT_STATE_KEY: copy.deepcopy(session[FANTASY_LEAGUE_CONTEXT_STATE_KEY])}
        with _as("local:qa"):
            saved = get_saved_weekly_lineup(get_active_league_context(reopened), 1, team="Team A")
        self.assertEqual(saved["assignments"], {"C": "Cal Raleigh", "OF": "Aaron Judge"})
        self.assertEqual(saved["saved_by"]["acting_as"], MODE_OWNER)


class TeamControlRulesTests(unittest.TestCase):
    def setUp(self):
        self.session: dict = {}
        _league(self.session, claim_b="uuid-b")
        self.ctx = get_active_league_context(self.session)

    def test_owner_proxy_and_claimed(self):
        with _as("local:qa"):
            self.assertEqual(resolve_team_control(self.session, self.ctx, "Team A").mode, MODE_OWNER)
            self.assertEqual(resolve_team_control(self.session, self.ctx, "Team C").mode, MODE_COMMISSIONER_PROXY)
            claimed = resolve_team_control(self.session, self.ctx, "Team B")
            self.assertEqual(claimed.mode, MODE_NONE)  # commissioner never overrides a claimed team
            self.assertEqual([c.team for c in manageable_teams(self.session, self.ctx)], ["Team A", "Team C"])
            self.assertEqual(resolve_team_control(self.session, self.ctx, "Team C").banner(), "Commissioner acting for Team C")

    def test_account_b_manages_only_its_team(self):
        with _as("uuid-b", auth=True, session=self.session):
            self.assertEqual(resolve_team_control(self.session, self.ctx, "Team B").mode, MODE_OWNER)
            self.assertEqual(resolve_team_control(self.session, self.ctx, "Team A").mode, MODE_NONE)
            self.assertEqual(resolve_team_control(self.session, self.ctx, "Team C").mode, MODE_NONE)  # not commissioner

    def test_proxy_ends_when_the_team_is_claimed(self):
        ctx = assign_team_owner_to_context(self.ctx, "Team C", user_id="uuid-c", email="c@qa")
        with _as("local:qa"):
            self.assertEqual(resolve_team_control(self.session, ctx, "Team C").mode, MODE_NONE)


class ProxyActionsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))
        self.session: dict = {}
        _league(self.session, claim_b="uuid-b")

    def tearDown(self):
        set_shared_league_store(None)
        self._tmp.cleanup()

    def _activity(self):
        return (get_active_league_context(self.session).get("workflow") or {}).get("league_activity") or []

    def test_commissioner_sets_an_unclaimed_lineup_and_it_is_logged(self):
        with _as("local:qa"):
            result = _save_lineup(self.session, "Team C")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["lineup"]["saved_by"]["acting_as"], MODE_COMMISSIONER_PROXY)
        last = self._activity()[-1]
        self.assertEqual((last["team_name"], last["action"], last["acting_as"], last["note"]),
                         ("Team C", "lineup_saved", MODE_COMMISSIONER_PROXY, "Commissioner acting for Team C"))

    def test_commissioner_cannot_set_a_claimed_teams_lineup(self):
        with _as("local:qa"):
            result = _save_lineup(self.session, "Team B")
        self.assertFalse(result["ok"])
        self.assertIn("managed by", " ".join(result["errors"]))

    def test_waiver_move_for_an_unclaimed_team(self):
        from fantasy_waiver_wire import apply_waiver_move_pairs

        with _as("local:qa"):
            result = apply_waiver_move_pairs(self.session, [{"add_player": "Will Smith", "drop_player": "Salvador Perez"}],
                                             stats_pool=STATS, team="Team C")
            refused = apply_waiver_move_pairs(self.session, [{"add_player": "Mike Trout", "drop_player": "Juan Soto"}],
                                              stats_pool=STATS, team="Team B")
        self.assertTrue(result["ok"], result)
        roster_c = {p["player_name"] for p in get_active_league_context(self.session)["league_rosters"]["Team C"]["players"]}
        self.assertEqual(roster_c, {"Will Smith", "Kyle Tucker"})
        self.assertEqual(self._activity()[-1]["note"], "Commissioner acting for Team C")
        self.assertFalse(refused["ok"])

    def test_commissioner_trade_with_an_unclaimed_team(self):
        from fantasy_trade_proposals import COMMISSIONER_TRADE_CONFIRM_MESSAGE, execute_commissioner_trade

        with _as("local:qa"):
            self.assertEqual(trades_enabled(get_active_league_context(self.session))[0], True)
            _p, err = execute_commissioner_trade(self.session, team_a="Team A", team_b="Team C", team_a_gives=["Aaron Judge"],
                                                 team_b_gives=["Kyle Tucker"], confirmed=False)
            self.assertEqual(err, COMMISSIONER_TRADE_CONFIRM_MESSAGE)
            proposal, err = execute_commissioner_trade(self.session, team_a="Team A", team_b="Team C",
                                                       team_a_gives=["Aaron Judge"], team_b_gives=["Kyle Tucker"], confirmed=True)
        self.assertEqual(err, "")
        self.assertEqual(proposal["commissioner_acting_for"], ["Team C"])
        rosters = get_active_league_context(self.session)["league_rosters"]
        self.assertIn("Kyle Tucker", {p["player_name"] for p in rosters["Team A"]["players"]})
        self.assertIn("Aaron Judge", {p["player_name"] for p in rosters["Team C"]["players"]})
        trade_log = [a for a in self._activity() if a.get("action") == "trade"]
        self.assertEqual([(a["team_name"], a["acting_as"]) for a in trade_log], [("Team A", MODE_OWNER), ("Team C", MODE_COMMISSIONER_PROXY)])

    def test_commissioner_trade_never_speaks_for_a_claimed_team(self):
        from fantasy_trade_proposals import execute_commissioner_trade

        with _as("local:qa"):
            _p, err = execute_commissioner_trade(self.session, team_a="Team A", team_b="Team B", team_a_gives=["Aaron Judge"],
                                                 team_b_gives=["Juan Soto"], confirmed=True)
        self.assertIn("managed by", err)

    def test_commissioner_trade_keeps_ownership_validation(self):
        from fantasy_trade_proposals import execute_commissioner_trade

        with _as("local:qa"):
            _p, err = execute_commissioner_trade(self.session, team_a="Team A", team_b="Team C", team_a_gives=["Juan Soto"],
                                                 team_b_gives=["Kyle Tucker"], confirmed=True)
        self.assertEqual(err, "Juan Soto is not on Team A's roster.")


if __name__ == "__main__":
    unittest.main()


class SharedLeagueWaiverPublishTests(unittest.TestCase):
    def test_waiver_move_survives_the_next_shared_sync(self):
        from fantasy_waiver_wire import apply_waiver_move_pairs, resolve_waiver_league_context

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(tmp.name)))
        self.addCleanup(set_shared_league_store, None)
        session: dict = {"_suite_auth_user_id": "local:qa"}
        _league(session)
        with _as("local:qa"):
            result = apply_waiver_move_pairs(session, [{"add_player": "Will Smith", "drop_player": "Cal Raleigh"}], stats_pool=STATS)
            self.assertTrue(result["ok"], result)
            resolve_waiver_league_context(session)  # the Waiver page's next render force-syncs
        roster_a = {p["player_name"] for p in get_active_league_context(session)["league_rosters"]["Team A"]["players"]}
        self.assertIn("Will Smith", roster_a)  # was pulled back to Cal Raleigh
        self.assertNotIn("Cal Raleigh", roster_a)


class IncompleteRosterLineupTests(unittest.TestCase):
    ROSTER = pd.DataFrame([{"Player": "Cal Raleigh", "Primary Position": "C"}, {"Player": "Juan Soto", "Primary Position": "OF"},
                           {"Player": "Kyle Tucker", "Primary Position": "OF"}])

    def test_slot_no_rostered_player_can_fill_may_stay_empty(self):
        from fantasy_weekly_lineup import validate_weekly_lineup

        result = validate_weekly_lineup(["C", "SS", "OF"], {"C": "Cal Raleigh", "SS": "", "OF": "Juan Soto"}, self.ROSTER)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["unfillable_slots"], ["SS"])
        self.assertIn("Shortstop stays empty: no eligible player on the roster (it scores nothing).", result["messages"])

    def test_slot_a_bench_player_could_fill_still_blocks_saving(self):
        from fantasy_weekly_lineup import validate_weekly_lineup

        result = validate_weekly_lineup(["C", "OF", "OF"], {"C": "Cal Raleigh", "OF": "Juan Soto", "OF_2": ""}, self.ROSTER)
        self.assertFalse(result["ok"])
        self.assertIn("Outfield is empty.", result["messages"])


class OneTimeFlagsNotPersistedTests(unittest.TestCase):
    def test_lineup_flash_and_team_picker_are_not_saved_with_lineup_state(self):
        from fantasy_state import is_fantasy_lineup_state_key

        for key in ("lineup_format_saved_flash", "lineup_format_editing", "lineup_manage_team"):
            self.assertFalse(is_fantasy_lineup_state_key(key), key)
        self.assertTrue(is_fantasy_lineup_state_key("lineup_team"))
