"""Trades: both rosters are checked against the league lineup, and an accepted trade moves
the players everywhere (rosters, ownership, archive) without touching the lineup format."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from fantasy_league_context import (
    activate_archive_league_context,
    get_active_league_context,
    save_imported_league_context,
    upsert_league_context,
)
from fantasy_league_lineup_format import save_league_lineup_format
from fantasy_league_team_ownership import assign_team_owner_to_context
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from fantasy_trade_legality import trade_roster_warnings
from fantasy_trade_proposals import accept_trade_proposal, create_trade_proposal

STANDARD = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"]
TEAM_1 = [("Cal Raleigh", "C"), ("Pete Alonso", "1B"), ("Brandon Lowe", "2B"), ("Jose Ramirez", "3B"),
          ("Willy Adames", "SS"), ("James Wood", "OF"), ("Seiya Suzuki", "OF"), ("Randy Arozarena", "OF"),
          ("Jo Adell", "OF"), ("Michael Busch", "1B")]
TEAM_2 = [("Adley Rutschman", "C"), ("Freddie Freeman", "1B"), ("Ketel Marte", "2B"), ("Manny Machado", "3B"),
          ("Bobby Witt Jr.", "SS"), ("Aaron Judge", "OF"), ("Juan Soto", "OF"), ("Kyle Tucker", "OF"),
          ("Corbin Carroll", "OF"), ("Kyle Schwarber", "DH")]


@contextmanager
def _as_user(user_id: str):
    with patch("fantasy_league_team_ownership._resolve_user_id", return_value=user_id), patch(
        "suite_user.get_account_user_id", return_value=user_id
    ):
        yield


def _league(session: dict, *, with_positions: bool = True) -> dict:
    rows, pick = [], 0
    for team, players in (("Team 1", TEAM_1), ("Team 2", TEAM_2)):
        for name, pos in players:
            pick += 1
            row = {"Pick": pick, "Round": 1, "Team": team, "Player": name}
            if with_positions:
                row["Primary Position"] = pos
            rows.append(row)
    entry, ctx = save_imported_league_context(
        session, pd.DataFrame(rows), my_team_name="Team 1", draft_name="QA", league_name="QA",
        save_only=True, assign_team=False,
    )
    activate_archive_league_context(session, entry["draft_id"])
    ctx = get_active_league_context(session)
    ctx = assign_team_owner_to_context(ctx, "Team 1", user_id="user:one", email="one@qa")
    ctx = assign_team_owner_to_context(ctx, "Team 2", user_id="user:two", email="two@qa")
    ctx["my_team_name"] = "Team 1"
    ctx["metadata"] = {**(ctx.get("metadata") or {}), "commissioner_user_id": "user:one"}
    upsert_league_context(session, ctx)
    with _as_user("user:one"):
        result = save_league_lineup_format(session, lineup_slots=STANDARD, roster_capacity=10)
    assert result["ok"], result
    return entry


def _warnings(session, gives, receives, **kw):
    with _as_user("user:one"):  # the page runs as Team 1's owner
        return trade_roster_warnings(
            get_active_league_context(session), proposer_team="Team 1", recipient_team="Team 2",
            proposer_gives=gives, proposer_receives=receives, **kw,
        )


class TradeLegalityWarningTests(unittest.TestCase):
    def setUp(self):
        self.session: dict = {}
        _league(self.session)

    def test_trading_the_only_shortstop_for_an_outfielder(self):
        self.assertEqual(
            _warnings(self.session, ["Willy Adames"], ["Aaron Judge"]),
            ["This trade leaves your team without an eligible SS for the required lineup."],
        )

    def test_like_for_like_trade_is_clean(self):
        self.assertEqual(_warnings(self.session, ["Willy Adames"], ["Bobby Witt Jr."]), [])

    def test_spare_player_trade_is_clean(self):
        # Busch is a second 1B; UTIL is covered by Adell either way.
        self.assertEqual(_warnings(self.session, ["Michael Busch"], ["Kyle Schwarber"]), [])

    def test_both_sides_and_roster_size(self):
        msgs = _warnings(self.session, ["Willy Adames", "Cal Raleigh"], ["Bobby Witt Jr."])
        self.assertEqual(
            msgs,
            [
                "This trade leaves your team without an eligible C for the required lineup.",
                "Your team would carry 9 players, leaving 1 open roster spot.",
                "Team 2 would carry 11 players — 1 over the 10-player roster, so a drop will be needed.",
            ],
        )  # Team 2 keeps Rutschman at C and gets Adames for SS: no lineup gap there

    def test_multi_slot_position_wording(self):
        msgs = _warnings(self.session, ["James Wood", "Seiya Suzuki", "Jo Adell"], ["Adley Rutschman", "Freddie Freeman", "Ketel Marte"])
        self.assertIn("This trade leaves your team with 1 eligible OF for the 3 OF spots in the required lineup.", msgs)

    def test_positions_come_from_stats_when_the_import_had_none(self):
        session: dict = {}
        _league(session, with_positions=False)
        feed = pd.DataFrame([{"Player": n, "Primary Position": p} for n, p in TEAM_1 + TEAM_2])
        self.assertEqual(
            _warnings(session, ["Willy Adames"], ["Aaron Judge"], stats_pool=feed),
            ["This trade leaves your team without an eligible SS for the required lineup."],
        )


class AcceptedTradeMovesPlayersTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))
        self.session: dict = {}
        self.entry = _league(self.session)

    def tearDown(self):
        set_shared_league_store(None)
        self._tmp.cleanup()

    def test_swap_reaches_rosters_ownership_and_archive(self):
        from draft_archive_state import get_draft_archive

        with _as_user("user:one"):
            proposal, err = create_trade_proposal(
                self.session, proposer_team="Team 1", recipient_team="Team 2",
                proposer_gives=["Willy Adames"], proposer_receives=["Bobby Witt Jr."],
            )
        self.assertEqual(err, "")
        with _as_user("user:two"):
            accepted, err = accept_trade_proposal(self.session, proposal["proposal_id"])
        self.assertEqual(err, "")
        ctx = get_active_league_context(self.session)
        team1 = {p["player_name"] for p in ctx["league_rosters"]["Team 1"]["players"]}
        team2 = {p["player_name"] for p in ctx["league_rosters"]["Team 2"]["players"]}
        self.assertIn("Bobby Witt Jr.", team1)
        self.assertNotIn("Willy Adames", team1)
        self.assertIn("Willy Adames", team2)
        from fantasy_league_context import normalize_player_key

        self.assertEqual(ctx["ownership_map"][normalize_player_key("Bobby Witt Jr.")]["owner_team"], "Team 1")
        self.assertEqual(ctx["ownership_map"][normalize_player_key("Willy Adames")]["owner_team"], "Team 2")
        self.assertEqual(ctx["roster_settings"]["lineup_format"]["lineup_slots"], STANDARD)
        archive = get_draft_archive(self.session, self.entry["draft_id"])
        archived = {p.get("player_name") for p in archive["league_rosters"]["Team 1"]["players"]}
        self.assertIn("Bobby Witt Jr.", archived)
        self.assertNotIn("Willy Adames", archived)

    def test_cannot_trade_with_yourself_or_players_you_do_not_own(self):
        with _as_user("user:one"):
            _p, err = create_trade_proposal(
                self.session, proposer_team="Team 1", recipient_team="Team 1",
                proposer_gives=["Willy Adames"], proposer_receives=["Cal Raleigh"],
            )
            self.assertEqual(err, "Proposer and recipient must be different teams.")
            _p, err = create_trade_proposal(
                self.session, proposer_team="Team 1", recipient_team="Team 2",
                proposer_gives=["Aaron Judge"], proposer_receives=["Juan Soto"],
            )
            self.assertEqual(err, "Aaron Judge is not on Team 1's roster.")


if __name__ == "__main__":
    unittest.main()
