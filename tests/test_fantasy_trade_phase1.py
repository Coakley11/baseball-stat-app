"""Trade System Phase 1 — shared league identity, ownership, cross-account flow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from draft_archive_state import get_draft_archive
from fantasy_league_context import (
    get_active_league_context,
    get_league_context,
    save_simulator_league_context,
    upsert_league_context,
)
from fantasy_league_identity import compute_draft_fingerprint, ensure_league_identity, resolve_canonical_league_id
from fantasy_league_team_ownership import (
    TRADES_DISABLED_MESSAGE,
    assign_team_owner_to_context,
    trades_enabled,
)
from fantasy_shared_league_store import (
    LocalFileSharedLeagueStore,
    load_shared_league,
    set_shared_league_store,
    sync_context_with_shared_store,
)
from fantasy_trade_proposals import (
    TRADE_PROPOSAL_STATUS_ACCEPTED,
    TRADE_PROPOSAL_STATUS_PENDING,
    get_incoming_trade_proposals,
    get_trade_history,
    get_trade_notifications,
)
from tests.test_fantasy_trade_proposals import (
    _accept_proposal,
    _as_user,
    _create_proposal,
    _decline_proposal,
    _league_board,
    _seed_league,
)


class TradePhase1IdentityTests(unittest.TestCase):
    def test_fingerprint_stable_across_metadata_timestamps(self) -> None:
        session: dict = {}
        context = _seed_league(session, assign_ownership=False)
        fp1 = compute_draft_fingerprint(context)
        meta = dict(context.get("metadata") or {})
        meta["updated_at"] = "2099-01-01T00:00:00+00:00"
        context["metadata"] = meta
        fp2 = compute_draft_fingerprint(context)
        self.assertEqual(fp1, fp2)

    def test_same_content_different_save_times_share_league_id(self) -> None:
        board = _league_board()
        session_a: dict = {}
        session_b: dict = {}
        _, ctx_a = save_simulator_league_context(session_a, board, my_team_name="Donny", draft_name="Save A")
        _, ctx_b = save_simulator_league_context(session_b, board, my_team_name="Team 2", draft_name="Save B")
        ctx_a = ensure_league_identity(ctx_a)
        ctx_b = ensure_league_identity(ctx_b)
        self.assertEqual(ctx_a.get("league_id"), ctx_b.get("league_id"))


class TradePhase1EligibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmp.cleanup()

    def test_solo_simulator_without_ownership_disables_trades(self) -> None:
        session: dict = {}
        context = _seed_league(session, assign_ownership=False)
        enabled, msg = trades_enabled(context, session)
        self.assertFalse(enabled)
        self.assertEqual(msg, TRADES_DISABLED_MESSAGE)

    def test_two_account_ownership_enables_trades(self) -> None:
        session: dict = {}
        context = _seed_league(session)
        with _as_user("user:donny"):
            enabled, msg = trades_enabled(context, session)
        self.assertTrue(enabled)
        self.assertEqual(msg, "")


_SHARED_DRAFT_CFG = {
    "fantasy_format": "5x5 Roto",
    "scoring_type": "Roto (5x5)",
    "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 1},
    "slot_instances": [],
}


class TradePhase1CrossAccountTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmp.cleanup()

    def test_two_account_propose_accept_updates_shared_store_and_history(self) -> None:
        session_a: dict = {"draft_shared_settings": dict(_SHARED_DRAFT_CFG)}
        context = _seed_league(session_a)
        league_id = str(context.get("league_id") or (context.get("metadata") or {}).get("league_id") or "")

        proposal, err = _create_proposal(
            session_a,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        self.assertEqual(err, "")
        assert proposal is not None
        shared = load_shared_league(league_id)
        assert shared is not None
        self.assertEqual(len(shared.get("trade_proposals") or []), 1)

        session_b: dict = {"draft_shared_settings": dict(_SHARED_DRAFT_CFG)}
        board = _league_board()
        _, ctx_b = save_simulator_league_context(session_b, board, my_team_name="Team 2", config=_SHARED_DRAFT_CFG)
        loaded = get_league_context(session_b, str(ctx_b.get("league_context_id") or ""))
        assert loaded is not None
        loaded = assign_team_owner_to_context(loaded, "Donny", user_id="user:donny", email="donny@test", display_name="Daniel")
        loaded = assign_team_owner_to_context(loaded, "Team 2", user_id="user:seal11", email="seal11@test", display_name="Seal11")
        upsert_league_context(session_b, loaded)
        with _as_user("user:seal11"):
            synced = sync_context_with_shared_store(session_b, loaded)
        incoming = get_incoming_trade_proposals(session_b, "Team 2")
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0]["status"], TRADE_PROPOSAL_STATUS_PENDING)

        alerts = get_trade_notifications(session_b, "Team 2")
        self.assertTrue(any("New trade offer from Daniel" in str(a.get("message") or "") for a in alerts))

        accepted, accept_err = _accept_proposal(session_b, str(proposal["proposal_id"]))
        self.assertEqual(accept_err, "")
        assert accepted is not None
        self.assertEqual(accepted["status"], TRADE_PROPOSAL_STATUS_ACCEPTED)

        shared_after = load_shared_league(league_id)
        assert shared_after is not None
        ownership = (get_active_league_context(session_b) or {}).get("league_rosters") or {}
        donny_players = [p.get("player_name") for p in (ownership.get("Donny") or {}).get("players") or []]
        team2_players = [p.get("player_name") for p in (ownership.get("Team 2") or {}).get("players") or []]
        self.assertIn("Player B", donny_players)
        self.assertIn("Player A", team2_players)

        with _as_user("user:donny"):
            ctx_a = get_active_league_context(session_a)
            assert ctx_a is not None
            self.assertEqual(resolve_canonical_league_id(ctx_a), league_id)
            sync_context_with_shared_store(session_a, ctx_a)
        refreshed = get_active_league_context(session_a)
        assert refreshed is not None
        donny_after = [p.get("player_name") for p in (refreshed.get("league_rosters") or {}).get("Donny", {}).get("players") or []]
        self.assertIn("Player B", donny_after)

        history = get_trade_history(refreshed)
        self.assertEqual(len(history["accepted"]), 1)
        self.assertEqual(len(history["pending"]), 0)

    def test_decline_leaves_rosters_unchanged(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, _ = _create_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal is not None
        before = get_active_league_context(session)
        assert before is not None
        declined, err = _decline_proposal(session, str(proposal["proposal_id"]))
        self.assertEqual(err, "")
        assert declined is not None
        after = get_active_league_context(session)
        assert after is not None
        self.assertEqual(
            (before.get("league_rosters") or {}).get("Donny"),
            (after.get("league_rosters") or {}).get("Donny"),
        )
        history = get_trade_history(after)
        self.assertEqual(len(history["declined"]), 1)

    def test_accept_updates_linked_archive(self) -> None:
        session: dict = {}
        context = _seed_league(session)
        meta = context.get("metadata") or {}
        draft_id = str(meta.get("source_draft_id") or "")
        proposal, _ = _create_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal is not None
        _accept_proposal(session, str(proposal["proposal_id"]))
        entry = get_draft_archive(session, draft_id)
        assert entry is not None
        archive_rosters = entry.get("league_rosters") or {}
        donny_players = [p.get("player_name") for p in (archive_rosters.get("Donny") or {}).get("players") or []]
        self.assertIn("Player B", donny_players)


if __name__ == "__main__":
    unittest.main()
