"""Tests for imported shared league creation (UDSL-2/3)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from draft_archive_state import DRAFT_TYPE_IMPORTED, get_active_draft_archive, list_draft_archives
from draft_import_validation import import_review_ready_for_league, validate_imported_draft_df
from fantasy_league_context import (
    CONTEXT_TYPE_REAL_LEAGUE,
    get_active_league_context,
    get_league_context,
    save_imported_league_context,
    upsert_league_context,
)
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_team_ownership import (
    TRADES_AWAITING_CLAIMS_MESSAGE,
    TRADES_MOCK_SIM_DISABLED_MESSAGE,
    assign_team_owner_to_context,
    get_team_ownership,
    owned_team_for_user,
    trades_enabled,
)
from fantasy_shared_league_store import LocalFileSharedLeagueStore, load_shared_league, set_shared_league_store
from fantasy_trade_proposals import create_trade_proposal
from tests.test_fantasy_trade_proposals import (
    _accept_proposal,
    _as_user,
    _create_proposal,
    _league_board,
)


def _sample_board() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Round": [1, 1, 1, 1],
            "Pick": [1, 2, 3, 4],
            "Team": ["Daniel", "Team 2", "Team 3", "Team 4"],
            "Player": ["Aaron Judge", "Francisco Lindor", "Juan Soto", "Juan Yepez"],
        }
    )


class TestImportedSharedLeague(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmpdir.name)))
        self.pool = pd.DataFrame(
            {
                "fullName": [
                    "Aaron Judge",
                    "Francisco Lindor",
                    "Juan Soto",
                    "Juan Yepez",
                ]
            }
        )
        self.session: dict = {"draft_shared_settings": {"fantasy_format": "5x5 Roto"}}

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmpdir.cleanup()

    def test_save_imported_league_context_creates_real_league(self) -> None:
        board = _sample_board()
        entry, context = save_imported_league_context(
            self.session,
            board,
            my_team_name="Daniel",
            draft_name="Office League 2026",
            league_name="Office League 2026",
            assign_team=False,
        )
        self.assertEqual(entry.get("draft_type"), DRAFT_TYPE_IMPORTED)
        self.assertEqual(context.get("context_type"), CONTEXT_TYPE_REAL_LEAGUE)
        self.assertEqual(context.get("my_team_name"), "Daniel")
        self.assertTrue(resolve_canonical_league_id(context))
        self.assertEqual(get_active_draft_archive(self.session), entry)
        active_ctx = get_active_league_context(self.session, respect_source_priority=False)
        self.assertEqual(active_ctx.get("league_context_id"), context.get("league_context_id"))

    def test_identical_import_reuses_fingerprint_ids(self) -> None:
        board = _sample_board()
        entry_a, ctx_a = save_imported_league_context(
            self.session,
            board,
            my_team_name="Daniel",
            draft_name="Office League",
            assign_team=False,
        )
        entry_b, ctx_b = save_imported_league_context(
            self.session,
            board,
            my_team_name="Team 2",
            draft_name="Office League copy",
            assign_team=False,
        )
        self.assertEqual(entry_a.get("draft_id"), entry_b.get("draft_id"))
        self.assertEqual(
            resolve_canonical_league_id(ctx_a),
            resolve_canonical_league_id(ctx_b),
        )
        self.assertEqual(len(list_draft_archives(self.session)), 1)

    def test_assign_team_on_save_records_ownership(self) -> None:
        board = _sample_board()
        _entry, context = save_imported_league_context(
            self.session,
            board,
            my_team_name="Daniel",
            draft_name="Claim Test League",
            assign_team=True,
        )
        league_context_id = str(context.get("league_context_id") or "")
        refreshed = get_league_context(self.session, league_context_id)
        self.assertIsNotNone(refreshed)
        ownership = get_team_ownership(refreshed)
        self.assertIn("Daniel", ownership)
        self.assertTrue(str(ownership["Daniel"].get("user_id") or "").strip())
        self.assertEqual(owned_team_for_user(refreshed), "Daniel")

    def test_league_gate_blocks_unresolved_before_save(self) -> None:
        import_df = pd.DataFrame(
            {
                "Round": [1, 1],
                "Pick": [1, 2],
                "Team": ["Daniel", "Team 2"],
                "Player": ["Aaron Judge", "Francsco Lindor"],
            }
        )
        review = validate_imported_draft_df(import_df, self.pool)
        self.assertFalse(import_review_ready_for_league(review, self.pool))
        review["rows"][1]["resolved_canonical"] = "Francisco Lindor"
        self.assertTrue(import_review_ready_for_league(review, self.pool))


class TestImportedLeagueTradeActivation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmpdir.name)))
        self.session: dict = {
            "draft_shared_settings": {
                "fantasy_format": "5x5 Roto",
                "scoring_type": "Roto (5x5)",
            }
        }

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmpdir.cleanup()

    def _save_imported_two_team_league(self) -> tuple[dict, dict]:
        board = _league_board()
        entry, context = save_imported_league_context(
            self.session,
            board,
            my_team_name="Donny",
            draft_name="Imported Trade League",
            league_name="Imported Trade League",
            assign_team=False,
        )
        return entry, context

    def test_mock_draft_blocks_trades(self) -> None:
        from fantasy_league_context import save_simulator_league_context

        session: dict = {"draft_shared_settings": {"fantasy_format": "5x5 Roto"}}
        _, context = save_simulator_league_context(session, _league_board(), my_team_name="Donny")
        enabled, msg = trades_enabled(context, session)
        self.assertFalse(enabled)
        self.assertEqual(msg, TRADES_MOCK_SIM_DISABLED_MESSAGE)

    def test_one_claimed_team_blocks_trades(self) -> None:
        _entry, context = self._save_imported_two_team_league()
        league_context_id = str(context.get("league_context_id") or "")
        loaded = get_league_context(self.session, league_context_id) or context
        loaded = assign_team_owner_to_context(
            loaded, "Donny", user_id="user:donny", email="donny@test", display_name="Daniel"
        )
        upsert_league_context(self.session, loaded)
        with _as_user("user:donny"):
            enabled, msg = trades_enabled(loaded, self.session)
        self.assertFalse(enabled)
        self.assertEqual(msg, TRADES_AWAITING_CLAIMS_MESSAGE)

    def test_two_claimed_teams_enables_trades_for_owner(self) -> None:
        _entry, context = self._save_imported_two_team_league()
        league_context_id = str(context.get("league_context_id") or "")
        loaded = get_league_context(self.session, league_context_id) or context
        loaded = assign_team_owner_to_context(
            loaded, "Donny", user_id="user:donny", email="donny@test", display_name="Daniel"
        )
        loaded = assign_team_owner_to_context(
            loaded, "Team 2", user_id="user:seal11", email="seal11@test", display_name="Seal11"
        )
        upsert_league_context(self.session, loaded)
        with _as_user("user:donny"):
            enabled, msg = trades_enabled(loaded, self.session)
        self.assertTrue(enabled)
        self.assertEqual(msg, "")

    def test_proposer_must_own_claimed_team(self) -> None:
        _entry, context = self._save_imported_two_team_league()
        league_context_id = str(context.get("league_context_id") or "")
        loaded = get_league_context(self.session, league_context_id) or context
        loaded = assign_team_owner_to_context(
            loaded, "Donny", user_id="user:donny", email="donny@test", display_name="Daniel"
        )
        loaded = assign_team_owner_to_context(
            loaded, "Team 2", user_id="user:seal11", email="seal11@test", display_name="Seal11"
        )
        upsert_league_context(self.session, loaded)
        with _as_user("user:seal11"):
            proposal, err = create_trade_proposal(
                self.session,
                proposer_team="Donny",
                recipient_team="Team 2",
                proposer_gives=["Player A"],
                proposer_receives=["Player B"],
            )
        self.assertIsNone(proposal)
        self.assertIn("owns Team 2", err)

    def test_accepted_trade_updates_shared_league_rosters(self) -> None:
        _entry, context = self._save_imported_two_team_league()
        league_context_id = str(context.get("league_context_id") or "")
        loaded = get_league_context(self.session, league_context_id) or context
        loaded = assign_team_owner_to_context(
            loaded, "Donny", user_id="user:donny", email="donny@test", display_name="Daniel"
        )
        loaded = assign_team_owner_to_context(
            loaded, "Team 2", user_id="user:seal11", email="seal11@test", display_name="Seal11"
        )
        upsert_league_context(self.session, loaded)
        league_id = resolve_canonical_league_id(loaded)

        proposal, err = _create_proposal(
            self.session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        self.assertEqual(err, "")
        assert proposal is not None

        accepted, accept_err = _accept_proposal(self.session, str(proposal["proposal_id"]))
        self.assertEqual(accept_err, "")
        assert accepted is not None

        shared = load_shared_league(league_id)
        assert shared is not None
        donny_players = [
            p.get("player_name")
            for p in (shared.get("league_rosters") or {}).get("Donny", {}).get("players") or []
        ]
        team2_players = [
            p.get("player_name")
            for p in (shared.get("league_rosters") or {}).get("Team 2", {}).get("players") or []
        ]
        self.assertIn("Player B", donny_players)
        self.assertIn("Player A", team2_players)

        refreshed = get_active_league_context(self.session, respect_source_priority=False)
        assert refreshed is not None
        donny_after = [
            p.get("player_name")
            for p in (refreshed.get("league_rosters") or {}).get("Donny", {}).get("players") or []
        ]
        self.assertIn("Player B", donny_after)


if __name__ == "__main__":
    unittest.main()
