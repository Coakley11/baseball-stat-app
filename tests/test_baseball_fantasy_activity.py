"""Suite activity emitters for fantasy workflows."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from baseball_fantasy_activity import (
    emit_incoming_trade_offers_once,
    log_trade_offer_sent,
    log_trade_terminal,
    log_waiver_transaction,
)


class TestBaseballFantasyActivity(unittest.TestCase):
    @patch("baseball_fantasy_activity._record")
    def test_trade_offer_sent_records_continue_key(self, record) -> None:
        proposal = {
            "proposal_id": "tp:1",
            "proposer_team": "Team X",
            "recipient_team": "Team Y",
            "proposer_gives": [{"player_name": "A"}],
            "proposer_receives": [{"player_name": "B"}],
        }
        log_trade_offer_sent({"league_name": "Test League", "league_id": "lg"}, proposal)
        self.assertTrue(record.called)
        args, kwargs = record.call_args
        self.assertEqual(args[0], "trade_offer_sent")
        self.assertEqual(kwargs["resume_key"], "bb:trade_center:tp:1")
        self.assertEqual(kwargs["page"], "Trade Center")

    @patch("baseball_fantasy_activity._invalidate_trade_resume")
    @patch("baseball_fantasy_activity._record")
    def test_trade_accepted_invalidates_resume(self, record, invalidate) -> None:
        proposal = {
            "proposal_id": "tp:2",
            "proposer_team": "Team X",
            "recipient_team": "Team Y",
            "proposer_gives": [],
            "proposer_receives": [],
        }
        log_trade_terminal({}, proposal, status="accepted")
        invalidate.assert_called_once_with("tp:2")
        self.assertEqual(record.call_args[0][0], "trade_accepted")

    @patch("baseball_fantasy_activity._invalidate_resume")
    @patch("baseball_fantasy_activity._record")
    def test_waiver_transaction_is_activity_only(self, record, invalidate) -> None:
        log_waiver_transaction(
            {"league_name": "Test", "league_id": "lg-1", "my_team_name": "Team X"},
            added=["Tyler Soderstrom"],
            dropped=["Jose Abreu"],
        )
        self.assertEqual(record.call_args[0][0], "waiver_transaction")
        self.assertEqual(record.call_args.kwargs.get("resume_key"), "")
        self.assertEqual(record.call_args.kwargs.get("cc_card_kind"), "activity")
        invalidate.assert_any_call("bb:waiver:lg-1")
        self.assertIn("Soderstrom", record.call_args.kwargs["summary"])

    @patch("baseball_fantasy_activity.log_trade_offer_received")
    def test_incoming_offers_emitted_once(self, received) -> None:
        session: dict = {}
        offer = {"proposal_id": "tp:9", "status": "pending", "proposer_team": "X"}
        emit_incoming_trade_offers_once(session, {}, [offer])
        emit_incoming_trade_offers_once(session, {}, [offer])
        self.assertEqual(received.call_count, 1)


if __name__ == "__main__":
    unittest.main()
