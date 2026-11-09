"""Team ownership, trade privacy and lineup visibility (owner workflow brief 2026-11-09, items 10-11)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fantasy_trade_proposals import _team_control_error, get_trade_history


def _league(*, context_type: str = "real_league") -> dict:
    return {
        "league_context_id": "ctx_qa",
        "context_type": context_type,
        "my_team_name": "Dave",
        "metadata": {
            "commissioner_user_id": "uid-comm",
            "joined_via_invite": True,  # a member's copy of the shared league
            # Ownership kept in metadata only (the shape the lineup check used to miss).
            "team_ownership": {
                "Dave": {"user_id": "uid-dave", "claim_status": "claimed"},
                "Barry": {"user_id": "uid-barry", "claim_status": "claimed"},
                "Invited": {"claim_status": "reserved", "reserved_for_email": "qa-invitee@example.test"},
            },
        },
        "league_rosters": {"Dave": {"players": []}, "Barry": {"players": []}, "Cal": {"players": []},
                           "Invited": {"players": []}},
        "workflow": {
            "trade_proposals": [
                {"proposal_id": "p1", "status": "pending", "proposer_team": "Barry", "recipient_team": "Cal"},
                {"proposal_id": "p2", "status": "pending", "proposer_team": "Dave", "recipient_team": "Barry"},
                {"proposal_id": "p3", "status": "accepted", "proposer_team": "Barry", "recipient_team": "Cal"},
                {"proposal_id": "p4", "status": "declined", "proposer_team": "Cal", "recipient_team": "Barry"},
            ],
            "league_activity": [
                {"action": "trade_accepted", "team_name": "Barry", "counterparty": "Cal", "recorded_at": "2026-11-01"},
                {"action": "trade_declined", "team_name": "Cal", "counterparty": "Barry", "recorded_at": "2026-11-02"},
            ],
        },
    }


def _session(uid: str) -> dict:
    return {"_suite_auth_user_id": uid}


_NO_SYNC = patch("fantasy_shared_league_store.sync_context_with_shared_store", side_effect=lambda s, c: c)
_HOSTED = patch("fantasy_team_control.auth_required", return_value=True)


def setUpModule() -> None:
    # Offers in these fixtures carry no players; treat them as still valid so they stay "pending".
    global _VALID
    _VALID = patch("fantasy_trade_proposals.validate_proposal_for_acceptance", return_value=(True, ""))
    _VALID.start()


def tearDownModule() -> None:
    _VALID.stop()


class TradePrivacy(unittest.TestCase):
    def test_member_sees_own_offers_and_completed_trades_only(self) -> None:
        with _HOSTED:
            h = get_trade_history(_league(), _session("uid-dave"))
        self.assertEqual([p["proposal_id"] for p in h["pending"]], ["p2"])
        self.assertEqual([p["proposal_id"] for p in h["accepted"]], ["p3"])
        self.assertEqual(h["declined"], [])
        self.assertEqual([a["action"] for a in h["activity"]], ["trade_accepted"])

    def test_participant_sees_their_private_negotiations(self) -> None:
        with _HOSTED:
            h = get_trade_history(_league(), _session("uid-barry"))
        self.assertEqual(sorted(p["proposal_id"] for p in h["pending"]), ["p1", "p2"])
        self.assertEqual([p["proposal_id"] for p in h["declined"]], ["p4"])

    def test_commissioner_acting_for_unclaimed_team_sees_its_offers(self) -> None:
        with _HOSTED:
            h = get_trade_history(_league(), _session("uid-comm"))
        # Cal is unclaimed, so the commissioner acts for it; Dave<->Barry stays private.
        self.assertEqual([p["proposal_id"] for p in h["pending"]], ["p1"])

    def test_no_session_keeps_legacy_full_history(self) -> None:
        self.assertEqual(len(get_trade_history(_league())["pending"]), 2)


class TradeActionsNeedRealControl(unittest.TestCase):
    def test_owner_commissioner_proxy_and_strangers(self) -> None:
        ctx = _league()
        with _NO_SYNC, _HOSTED:
            self.assertEqual(_team_control_error(_session("uid-dave"), ctx, "Dave", "propose a trade"), "")
            self.assertTrue(_team_control_error(_session("uid-dave"), ctx, "Barry", "propose a trade"))
            # Commissioner may act for the unclaimed team, never for a claimed or reserved one.
            self.assertEqual(_team_control_error(_session("uid-comm"), ctx, "Cal", "accept this trade"), "")
            self.assertTrue(_team_control_error(_session("uid-comm"), ctx, "Barry", "accept this trade"))
            self.assertTrue(_team_control_error(_session("uid-comm"), ctx, "Invited", "accept this trade"))
            # A member with no team gains nothing by naming one.
            self.assertTrue(_team_control_error(_session("uid-stranger"), ctx, "Cal", "counter this offer"))
            self.assertTrue(_team_control_error(_session("uid-stranger"), ctx, "Not A Team", "propose a trade"))


class TeamRecognition(unittest.TestCase):
    def test_verified_owner_is_not_asked_which_team(self) -> None:
        from fantasy_league_team_ownership import team_claim_prompt_for_session

        with _NO_SYNC, _HOSTED:
            team, claimable = team_claim_prompt_for_session(_league(), _session("uid-dave"))
        self.assertEqual((team, claimable), ("Dave", []))

    def test_unclaimed_member_only_offered_unclaimed_unreserved_teams(self) -> None:
        from fantasy_league_team_ownership import team_claim_prompt_for_session

        with _NO_SYNC, _HOSTED:
            team, claimable = team_claim_prompt_for_session(_league(), _session("uid-new"))
        self.assertEqual(team, "")
        self.assertEqual(claimable, ["Cal"])

    def test_solo_mock_never_asks(self) -> None:
        from fantasy_league_team_ownership import team_claim_prompt_for_session

        ctx = _league(context_type="mock_draft_simulation")
        ctx["metadata"].pop("team_ownership")
        with _NO_SYNC, _HOSTED:
            team, claimable = team_claim_prompt_for_session(ctx, _session("uid-new"))
        self.assertEqual(claimable, [])


class LineupRules(unittest.TestCase):
    def test_metadata_ownership_blocks_another_teams_lineup(self) -> None:
        from fantasy_weekly_lineup import _assert_lineup_team_write

        with _HOSTED:
            err = _assert_lineup_team_write(_session("uid-dave"), _league(), "Barry")
        self.assertTrue(err)

    def test_published_lineups_are_view_only_and_exclude_own_team(self) -> None:
        from fantasy_weekly_lineup_ui import published_lineups_for_week

        ctx = _league()
        snaps = {"Dave": {"starters": [{"slot": "C", "player_name": "A"}]},
                 "Barry": {"starters": [{"slot": "C", "player_name": "B"}]}}
        with patch("fantasy_season_ledger.get_period_lineup", side_effect=lambda c, w, t: snaps.get(t)):
            rows = published_lineups_for_week(ctx, 1, own_team="Dave")
        self.assertEqual([r["team"] for r in rows], ["Barry"])


if __name__ == "__main__":
    unittest.main()
