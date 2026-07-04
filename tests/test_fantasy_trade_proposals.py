"""Tests for Fantasy Trade Proposal System (Phase 1)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY
from fantasy_league_context import (
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    apply_fantasy_league_context_disk_state,
    build_ownership_map,
    get_active_league_context,
    save_simulator_league_context,
)
from fantasy_trade_proposals import (
    STALE_TRADE_MESSAGE,
    TRADE_PROPOSAL_STATUS_ACCEPTED,
    TRADE_PROPOSAL_STATUS_CANCELED,
    TRADE_PROPOSAL_STATUS_COUNTERED,
    TRADE_PROPOSAL_STATUS_DECLINED,
    TRADE_PROPOSAL_STATUS_EXPIRED,
    TRADE_PROPOSAL_STATUS_PENDING,
    accept_trade_proposal,
    cancel_trade_proposal,
    counter_trade_proposal,
    consume_trade_proposal_handoff,
    create_trade_proposal,
    decline_trade_proposal,
    get_incoming_trade_proposals,
    get_outgoing_trade_proposals,
    get_trade_notifications,
    get_display_status,
    mark_trade_notification_seen,
    navigate_to_trade_proposal,
    recipient_view,
    set_trade_proposal_handoff,
    validate_proposal_for_acceptance,
)
from fantasy_league_context import LINEUP_ASSISTANT_PAGE
from fantasy_waiver_wire import build_waiver_pool, get_league_activity, rostered_player_names


def _league_board() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Team": "Donny", "Player": "Player A", "Pick": 1},
            {"Team": "Team 2", "Player": "Player B", "Pick": 2},
        ]
    )


def _multi_player_board() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Team": "Donny", "Player": "Player A", "Pick": 1},
            {"Team": "Team 2", "Player": "Player B", "Pick": 2},
            {"Team": "Donny", "Player": "Player C", "Pick": 3},
            {"Team": "Team 2", "Player": "Player D", "Pick": 4},
            {"Team": "Donny", "Player": "Player E", "Pick": 5},
            {"Team": "Team 2", "Player": "Player F", "Pick": 6},
        ]
    )


def _seed_league(session: dict) -> dict:
    _, context = save_simulator_league_context(session, _league_board(), my_team_name="Donny")
    return context


def _seed_multi_player_league(session: dict) -> dict:
    _, context = save_simulator_league_context(session, _multi_player_board(), my_team_name="Donny")
    return context


class TradeProposalCreateTests(unittest.TestCase):
    def test_create_trade_proposal_in_active_league(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, err = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
            verdict="Good for your team",
        )
        self.assertEqual(err, "")
        assert proposal is not None
        self.assertEqual(proposal["status"], TRADE_PROPOSAL_STATUS_PENDING)
        self.assertEqual(proposal["proposer_team"], "Donny")
        self.assertEqual(proposal["recipient_team"], "Team 2")

    def test_cannot_create_without_active_league(self) -> None:
        proposal, err = create_trade_proposal(
            {},
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        self.assertIsNone(proposal)
        self.assertIn("active league context", err.lower())

    def test_cannot_propose_to_missing_team(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, err = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Missing Team",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        self.assertIsNone(proposal)
        self.assertIn("not in this league", err)

    def test_cannot_propose_player_not_on_proposer_roster(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, err = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player B"],
            proposer_receives=["Player A"],
        )
        self.assertIsNone(proposal)
        self.assertIn("not on Donny", err)


class TradeProposalInboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session: dict = {}
        _seed_league(self.session)
        create_trade_proposal(
            self.session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )

    def test_recipient_inbox_shows_pending(self) -> None:
        incoming = get_incoming_trade_proposals(self.session, "Team 2")
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0]["status"], TRADE_PROPOSAL_STATUS_PENDING)

    def test_recipient_view_reverses_perspective(self) -> None:
        incoming = get_incoming_trade_proposals(self.session, "Team 2")
        view = recipient_view(incoming[0])
        self.assertEqual(view["give_players"], ["Player B"])
        self.assertEqual(view["receive_players"], ["Player A"])
        self.assertEqual(view["viewer_team"], "Team 2")
        self.assertEqual(view["other_team"], "Donny")

    def test_handoff_prefills_recipient_analyzer(self) -> None:
        incoming = get_incoming_trade_proposals(self.session, "Team 2")
        pid = str(incoming[0]["proposal_id"])
        set_trade_proposal_handoff(self.session, proposal_id=pid, view_as_team="Team 2")
        view = consume_trade_proposal_handoff(self.session)
        assert view is not None
        self.assertEqual(self.session["lineup_trade_other_team"], "Donny")
        self.assertEqual(self.session["lineup_trade_give_players"], ["Player B"])
        self.assertEqual(self.session["lineup_trade_get_players"], ["Player A"])


class TradeProposalAcceptDeclineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session: dict = {}
        _seed_league(self.session)
        self.proposal, _ = create_trade_proposal(
            self.session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )

    def test_accept_swaps_players_and_updates_ownership(self) -> None:
        assert self.proposal is not None
        pid = str(self.proposal["proposal_id"])
        accepted, err = accept_trade_proposal(self.session, pid)
        self.assertEqual(err, "")
        assert accepted is not None
        self.assertEqual(accepted["status"], TRADE_PROPOSAL_STATUS_ACCEPTED)
        context = get_active_league_context(self.session)
        assert context is not None
        ownership = build_ownership_map(context)
        self.assertEqual(ownership["player a"]["owner_team"], "Team 2")
        self.assertEqual(ownership["player b"]["owner_team"], "Donny")

    def test_decline_does_not_change_rosters(self) -> None:
        assert self.proposal is not None
        pid = str(self.proposal["proposal_id"])
        before = get_active_league_context(self.session)
        assert before is not None
        before_map = build_ownership_map(before)
        declined, err = decline_trade_proposal(self.session, pid)
        self.assertEqual(err, "")
        assert declined is not None
        self.assertEqual(declined["status"], TRADE_PROPOSAL_STATUS_DECLINED)
        after = get_active_league_context(self.session)
        assert after is not None
        self.assertEqual(build_ownership_map(after), before_map)

    def test_cannot_accept_same_trade_twice(self) -> None:
        assert self.proposal is not None
        pid = str(self.proposal["proposal_id"])
        accept_trade_proposal(self.session, pid)
        again, err = accept_trade_proposal(self.session, pid)
        self.assertIsNone(again)
        self.assertIn("no longer pending", err)

    def test_cannot_accept_stale_trade_after_roster_changed(self) -> None:
        assert self.proposal is not None
        pid = str(self.proposal["proposal_id"])
        context = get_active_league_context(self.session)
        assert context is not None
        league_id = str(context.get("league_context_id") or "")
        from fantasy_league_context import get_league_context, upsert_league_context

        ctx = get_league_context(self.session, league_id)
        assert ctx is not None
        rosters = ctx.get("league_rosters") or {}
        team2 = rosters.get("Team 2") or {}
        players = [dict(p) for p in (team2.get("players") or []) if isinstance(p, dict)]
        team2["players"] = [p for p in players if str(p.get("player_name")) != "Player B"]
        rosters["Team 2"] = team2
        ctx["league_rosters"] = rosters
        upsert_league_context(self.session, ctx)
        accepted, err = accept_trade_proposal(self.session, pid)
        self.assertIsNone(accepted)
        self.assertEqual(err, STALE_TRADE_MESSAGE)

    def test_outgoing_status_updates_on_accept_and_decline(self) -> None:
        assert self.proposal is not None
        pid = str(self.proposal["proposal_id"])
        accept_trade_proposal(self.session, pid)
        outgoing = get_outgoing_trade_proposals(self.session, "Donny")
        self.assertEqual(outgoing[0]["status"], TRADE_PROPOSAL_STATUS_ACCEPTED)

        session2: dict = {}
        _seed_league(session2)
        proposal2, _ = create_trade_proposal(
            session2,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal2 is not None
        decline_trade_proposal(session2, str(proposal2["proposal_id"]))
        outgoing2 = get_outgoing_trade_proposals(session2, "Donny")
        self.assertEqual(outgoing2[0]["status"], TRADE_PROPOSAL_STATUS_DECLINED)


class TradeProposalIntegrationTests(unittest.TestCase):
    def test_waiver_pool_correct_after_accepted_trade(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, _ = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal is not None
        accept_trade_proposal(session, str(proposal["proposal_id"]))
        context = get_active_league_context(session)
        assert context is not None
        pool = pd.DataFrame(
            [
                {"Player": "Player A"},
                {"Player": "Player B"},
                {"Player": "Free Agent"},
            ]
        )
        waiver = build_waiver_pool(pool, context)
        names = set(waiver["Player"].astype(str))
        self.assertNotIn("Player A", names)
        self.assertNotIn("Player B", names)
        self.assertIn("Free Agent", names)
        self.assertEqual(len(rostered_player_names(context)), 2)

    def test_active_context_restores_with_proposals(self) -> None:
        session: dict = {}
        _seed_league(session)
        create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        disk = {
            FANTASY_LEAGUE_CONTEXT_STATE_KEY: session.get(FANTASY_LEAGUE_CONTEXT_STATE_KEY),
            ACTIVE_DRAFT_ARCHIVE_KEY: session.get(ACTIVE_DRAFT_ARCHIVE_KEY),
        }
        restored: dict = {}
        apply_fantasy_league_context_disk_state(restored, disk)
        incoming = get_incoming_trade_proposals(restored, "Team 2")
        self.assertEqual(len(incoming), 1)
        context = get_active_league_context(restored)
        assert context is not None
        proposal = incoming[0]
        ok, _ = validate_proposal_for_acceptance(context, proposal)
        self.assertTrue(ok)


class TradeProposalPhase2Tests(unittest.TestCase):
    def test_incoming_notification_for_recipient(self) -> None:
        session: dict = {}
        _seed_league(session)
        create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        alerts = get_trade_notifications(session, "Team 2")
        self.assertTrue(any(a.get("kind") == "incoming" for a in alerts))

    def test_outgoing_accepted_declined_notifications_for_proposer(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, _ = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal is not None
        pid = str(proposal["proposal_id"])
        accept_trade_proposal(session, pid)
        alerts = get_trade_notifications(session, "Donny")
        self.assertTrue(any(a.get("kind") == "accepted" for a in alerts))

        session2: dict = {}
        _seed_league(session2)
        proposal2, _ = create_trade_proposal(
            session2,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal2 is not None
        decline_trade_proposal(session2, str(proposal2["proposal_id"]))
        alerts2 = get_trade_notifications(session2, "Donny")
        self.assertTrue(any(a.get("kind") == "declined" for a in alerts2))

    def test_notification_deep_link_loads_proposal(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, _ = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal is not None
        pid = str(proposal["proposal_id"])
        navigate_to_trade_proposal(session, proposal_id=pid, view_as_team="Team 2", alert_key=f"{pid}:incoming")
        self.assertEqual(session["_navigate_to_page"], LINEUP_ASSISTANT_PAGE)
        view = consume_trade_proposal_handoff(session)
        assert view is not None
        self.assertEqual(session["lineup_trade_give_players"], ["Player B"])
        self.assertEqual(session["lineup_trade_get_players"], ["Player A"])

    def test_proposer_deep_link_shows_outgoing_perspective(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, _ = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal is not None
        navigate_to_trade_proposal(session, proposal_id=str(proposal["proposal_id"]), view_as_team="Donny")
        view = consume_trade_proposal_handoff(session)
        assert view is not None
        self.assertEqual(view["give_players"], ["Player A"])
        self.assertEqual(view["receive_players"], ["Player B"])

    def test_cancel_pending_trade(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, _ = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal is not None
        canceled, err = cancel_trade_proposal(session, str(proposal["proposal_id"]), canceled_by_team="Donny")
        self.assertEqual(err, "")
        assert canceled is not None
        self.assertEqual(canceled["status"], TRADE_PROPOSAL_STATUS_CANCELED)

    def test_canceled_trade_cannot_be_accepted(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, _ = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal is not None
        pid = str(proposal["proposal_id"])
        cancel_trade_proposal(session, pid, canceled_by_team="Donny")
        accepted, err = accept_trade_proposal(session, pid)
        self.assertIsNone(accepted)
        self.assertIn("no longer pending", err.lower())

    def test_accepted_trade_cannot_be_canceled(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, _ = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal is not None
        pid = str(proposal["proposal_id"])
        accept_trade_proposal(session, pid)
        canceled, err = cancel_trade_proposal(session, pid, canceled_by_team="Donny")
        self.assertIsNone(canceled)
        self.assertIn("pending", err.lower())

    def test_declined_trade_cannot_be_accepted(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, _ = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal is not None
        pid = str(proposal["proposal_id"])
        decline_trade_proposal(session, pid)
        accepted, err = accept_trade_proposal(session, pid)
        self.assertIsNone(accepted)
        self.assertIn("no longer pending", err.lower())

    def test_league_activity_includes_accepted_trade_summary(self) -> None:
        session: dict = {}
        _seed_league(session)
        proposal, _ = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert proposal is not None
        accept_trade_proposal(session, str(proposal["proposal_id"]))
        context = get_active_league_context(session)
        assert context is not None
        activity = get_league_activity(context)
        summaries = [str(a.get("summary") or "") for a in activity]
        self.assertTrue(any("Donny traded Player A to Team 2 for Player B" in s for s in summaries))

    def test_notifications_survive_disk_restore(self) -> None:
        session: dict = {}
        _seed_league(session)
        create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        alerts_before = get_trade_notifications(session, "Team 2")
        disk = {FANTASY_LEAGUE_CONTEXT_STATE_KEY: session.get(FANTASY_LEAGUE_CONTEXT_STATE_KEY)}
        restored: dict = {}
        apply_fantasy_league_context_disk_state(restored, disk)
        alerts_after = get_trade_notifications(restored, "Team 2")
        self.assertEqual(len(alerts_before), len(alerts_after))

    def test_notifications_scoped_to_active_team(self) -> None:
        session: dict = {}
        _seed_league(session)
        create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        self.assertTrue(get_trade_notifications(session, "Team 2"))
        self.assertFalse(get_trade_notifications(session, "Rivals"))


class TradeProposalPhase3Tests(unittest.TestCase):
    def test_accept_multi_player_trade_updates_all_rosters(self) -> None:
        session: dict = {}
        _seed_multi_player_league(session)
        proposal, err = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A", "Player C"],
            proposer_receives=["Player B"],
        )
        self.assertEqual(err, "")
        assert proposal is not None

        accepted, accept_err = accept_trade_proposal(session, str(proposal["proposal_id"]))
        self.assertEqual(accept_err, "")
        assert accepted is not None
        self.assertEqual(accepted["status"], TRADE_PROPOSAL_STATUS_ACCEPTED)

        context = get_active_league_context(session)
        assert context is not None
        ownership = build_ownership_map(context)
        self.assertEqual(ownership["player a"]["owner_team"], "Team 2")
        self.assertEqual(ownership["player c"]["owner_team"], "Team 2")
        self.assertEqual(ownership["player b"]["owner_team"], "Donny")

    def test_rejects_over_limit_trade_shape(self) -> None:
        session: dict = {}
        _seed_multi_player_league(session)
        proposal, err = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A", "Player C", "Player E"],
            proposer_receives=["Player B", "Player D", "Player F"],
        )
        self.assertIsNone(proposal)
        self.assertIn("five total players", err)

    def test_counteroffer_closes_original_and_alerts_original_proposer(self) -> None:
        session: dict = {}
        _seed_multi_player_league(session)
        original, err = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        self.assertEqual(err, "")
        assert original is not None

        counter, counter_err = counter_trade_proposal(
            session,
            str(original["proposal_id"]),
            countered_by_team="Team 2",
            counter_gives=["Player B"],
            counter_receives=["Player A", "Player C"],
        )
        self.assertEqual(counter_err, "")
        assert counter is not None
        self.assertEqual(counter["status"], TRADE_PROPOSAL_STATUS_PENDING)
        self.assertEqual(counter["proposer_team"], "Team 2")
        self.assertEqual(counter["recipient_team"], "Donny")
        self.assertEqual(counter["countered_from_proposal_id"], original["proposal_id"])

        outgoing = get_outgoing_trade_proposals(session, "Donny")
        original_after = next(p for p in outgoing if p["proposal_id"] == original["proposal_id"])
        self.assertEqual(original_after["status"], TRADE_PROPOSAL_STATUS_COUNTERED)

        alerts = get_trade_notifications(session, "Donny")
        self.assertTrue(any(a.get("kind") == "counteroffer" and a.get("proposal_id") == counter["proposal_id"] for a in alerts))

    def test_countered_trade_cannot_be_accepted_later(self) -> None:
        session: dict = {}
        _seed_multi_player_league(session)
        original, _ = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        assert original is not None
        counter_trade_proposal(
            session,
            str(original["proposal_id"]),
            countered_by_team="Team 2",
            counter_gives=["Player B"],
            counter_receives=["Player A"],
        )
        accepted, err = accept_trade_proposal(session, str(original["proposal_id"]))
        self.assertIsNone(accepted)
        self.assertIn("no longer pending", err.lower())

    def test_expired_trade_cannot_be_accepted_and_is_persisted(self) -> None:
        session: dict = {}
        _seed_league(session)
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(microsecond=0).isoformat()
        proposal, err = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
            expires_at=expired_at,
        )
        self.assertEqual(err, "")
        assert proposal is not None
        context = get_active_league_context(session)
        assert context is not None
        self.assertEqual(get_display_status(context, proposal), TRADE_PROPOSAL_STATUS_EXPIRED)

        accepted, accept_err = accept_trade_proposal(session, str(proposal["proposal_id"]))
        self.assertIsNone(accepted)
        self.assertIn("expired", accept_err.lower())
        incoming = get_incoming_trade_proposals(session, "Team 2")
        self.assertEqual(incoming[0]["status"], TRADE_PROPOSAL_STATUS_EXPIRED)

    def test_trade_history_records_non_accept_terminal_statuses(self) -> None:
        session: dict = {}
        _seed_multi_player_league(session)
        declined, _ = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player A"],
            proposer_receives=["Player B"],
        )
        canceled, _ = create_trade_proposal(
            session,
            proposer_team="Donny",
            recipient_team="Team 2",
            proposer_gives=["Player C"],
            proposer_receives=["Player D"],
        )
        assert declined is not None and canceled is not None
        decline_trade_proposal(session, str(declined["proposal_id"]))
        cancel_trade_proposal(session, str(canceled["proposal_id"]), canceled_by_team="Donny")
        context = get_active_league_context(session)
        assert context is not None
        summaries = [str(a.get("summary") or "") for a in get_league_activity(context)]
        self.assertTrue(any("declined" in s.lower() for s in summaries))
        self.assertTrue(any("canceled" in s.lower() for s in summaries))


if __name__ == "__main__":
    unittest.main()
