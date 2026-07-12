"""Trade Center workflow tests — ideas, tabs, offers, and roster loading."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from fantasy_league_context import get_active_league_context
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from fantasy_trade_ideas import (
    LINEUP_ASSISTANT_TAB_OPTIONS,
    empty_trade_ideas_message,
    generate_trade_ideas,
    resolve_lineup_assistant_tab,
)
from fantasy_trade_proposals import (
    accept_trade_proposal,
    archive_offer_from_inbox,
    archived_offer_ids,
    consume_trade_proposal_handoff,
    create_trade_proposal,
    get_trade_history,
)


def _mookie_rosters() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Team": "Daniel",
                "Player": "Mookie Betts",
                "HR": 18,
                "RBI": 62,
                "R": 75,
                "SB": 10,
                "BA": 0.285,
                "OPS": 0.860,
            },
            {
                "Team": "Daniel",
                "Player": "Contact Guy",
                "HR": 8,
                "RBI": 45,
                "R": 55,
                "SB": 12,
                "BA": 0.310,
                "OPS": 0.760,
            },
            {
                "Team": "Team 2",
                "Player": "Oak Power",
                "HR": 22,
                "RBI": 68,
                "R": 58,
                "SB": 4,
                "BA": 0.255,
                "OPS": 0.820,
            },
            {
                "Team": "Team 2",
                "Player": "Oak Contact",
                "HR": 6,
                "RBI": 40,
                "R": 50,
                "SB": 15,
                "BA": 0.320,
                "OPS": 0.780,
            },
        ]
    )


class TradeCenterWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmp.cleanup()

    def test_lineup_and_trade_center_tabs_are_separate(self) -> None:
        self.assertEqual(LINEUP_ASSISTANT_TAB_OPTIONS, ("Lineup Management", "Trade Center"))
        session: dict = {}
        self.assertEqual(resolve_lineup_assistant_tab(session), "Lineup Management")
        session["_lineup_focus_trade_center"] = True
        self.assertEqual(resolve_lineup_assistant_tab(session), "Trade Center")

    def test_mookie_give_only_generates_team_2_ideas(self) -> None:
        ideas, diag = generate_trade_ideas(
            "Daniel",
            _mookie_rosters(),
            None,
            forced_give=["Mookie Betts"],
            summarize_team_category_needs_fn=lambda *_: {},
            league_context_id="league:test",
        )
        self.assertFalse(ideas.empty, diag)
        self.assertTrue(all(ideas["Other Team"].astype(str) == "Team 2"))
        self.assertGreaterEqual(diag.get("final_idea_count", 0), 1)

    def test_receive_only_resolves_owner_and_generates_packages(self) -> None:
        ideas, diag = generate_trade_ideas(
            "Daniel",
            _mookie_rosters(),
            None,
            forced_get=["Oak Contact"],
            summarize_team_category_needs_fn=lambda *_: {},
            league_context_id="league:test",
        )
        self.assertFalse(ideas.empty, diag)
        self.assertEqual(diag.get("target_owner_teams", {}).get("Oak Contact"), "Team 2")

    def test_both_sides_still_allow_trade_ideas(self) -> None:
        ideas, diag = generate_trade_ideas(
            "Daniel",
            _mookie_rosters(),
            None,
            forced_give=["Mookie Betts"],
            forced_get=["Oak Power"],
            summarize_team_category_needs_fn=lambda *_: {},
            league_context_id="league:test",
        )
        self.assertIn("selected_give_players", diag)
        self.assertIn("selected_get_players", diag)
        self.assertGreaterEqual(diag.get("candidate_count_raw", 0), 0)

    def test_empty_opposing_roster_returns_reason(self) -> None:
        rosters = _mookie_rosters()
        rosters = rosters[rosters["Team"].astype(str) != "Team 2"]
        _, diag = generate_trade_ideas(
            "Daniel",
            rosters,
            None,
            forced_give=["Mookie Betts"],
            summarize_team_category_needs_fn=lambda *_: {},
            league_context_id="league:test",
        )
        msg = empty_trade_ideas_message(diag)
        self.assertTrue(
            "roster could not be loaded" in msg.lower() or "no other claimed team" in msg.lower(),
            msg,
        )

    def test_trade_workspace_auto_loads_from_league_context(self) -> None:
        from fantasy_trade_center_ui import _trade_workspace
        from tests.test_fantasy_trade_proposals import _seed_league

        session: dict = {}
        _seed_league(session)
        session["_fantasy_current_hitter_stats"] = pd.DataFrame(
            [
                {"Player": "Player A", "HR": 10, "RBI": 40, "R": 50, "SB": 5, "H": 80, "AB": 280, "BA": 0.290},
                {"Player": "Player B", "HR": 12, "RBI": 42, "R": 48, "SB": 4, "H": 75, "AB": 270, "BA": 0.275},
            ]
        )
        ws = _trade_workspace(session, my_team="Donny")
        self.assertFalse(ws["roster_stats"].empty)
        counts = {
            team: len(ws["roster_stats"][ws["roster_stats"]["Team"].astype(str) == team])
            for team in ["Donny", "Team 2"]
        }
        self.assertGreaterEqual(counts.get("Donny", 0), 1)
        self.assertGreaterEqual(counts.get("Team 2", 0), 1)

    def test_incoming_handoff_sets_source_offer_id(self) -> None:
        from fantasy_trade_proposals import TRADE_HANDOFF_SESSION_KEY
        from tests.test_fantasy_trade_proposals import _as_user, _seed_league

        session: dict = {}
        _seed_league(session)
        with _as_user("user:seal11"):
            proposal, err = create_trade_proposal(
                session,
                proposer_team="Team 2",
                recipient_team="Donny",
                proposer_gives=["Player B"],
                proposer_receives=["Player A"],
            )
        self.assertFalse(err, err)
        assert proposal is not None
        pid = str(proposal.get("proposal_id") or "")
        session[TRADE_HANDOFF_SESSION_KEY] = {
            "proposal_id": pid,
            "view_as_team": "Donny",
        }
        view = consume_trade_proposal_handoff(session)
        self.assertIsNotNone(view)
        handoff = session.get("_trade_center_handoff") or {}
        self.assertEqual(handoff.get("source_offer_id"), pid)
        self.assertEqual(session.get("lineup_trade_give_players"), ["Player A"])
        self.assertEqual(session.get("lineup_trade_get_players"), ["Player B"])

    def test_archive_offer_hides_from_inbox_not_history(self) -> None:
        from tests.test_fantasy_trade_proposals import _as_user, _decline_proposal, _seed_league

        session: dict = {}
        ctx = _seed_league(session)
        with _as_user("user:seal11"):
            proposal, err = create_trade_proposal(
                session,
                proposer_team="Team 2",
                recipient_team="Donny",
                proposer_gives=["Player B"],
                proposer_receives=["Player A"],
            )
        self.assertFalse(err)
        assert proposal is not None
        pid = str(proposal.get("proposal_id") or "")
        _decline_proposal(session, pid)
        league_id = str(ctx.get("league_id") or "league:test")
        archive_offer_from_inbox(session, pid, league_id=league_id)
        self.assertIn(pid, archived_offer_ids(session, league_id))
        history = get_trade_history(get_active_league_context(session))
        declined = history.get("declined") or []
        self.assertTrue(any(str(p.get("proposal_id") or "") == pid for p in declined))

    def test_accepted_trade_appears_once_in_history(self) -> None:
        from tests.test_fantasy_trade_proposals import _as_user, _seed_league

        session: dict = {}
        _seed_league(session)
        with _as_user("user:seal11"):
            proposal, err = create_trade_proposal(
                session,
                proposer_team="Team 2",
                recipient_team="Donny",
                proposer_gives=["Player B"],
                proposer_receives=["Player A"],
            )
        self.assertFalse(err)
        assert proposal is not None
        pid = str(proposal.get("proposal_id") or "")
        with _as_user("user:donny"):
            accepted, accept_err = accept_trade_proposal(session, pid)
        self.assertFalse(accept_err, accept_err)
        self.assertIsNotNone(accepted)
        history = get_trade_history(get_active_league_context(session))
        accepted_rows = [
            row for row in (history.get("accepted") or []) if str(row.get("proposal_id") or "") == pid
        ]
        self.assertEqual(len(accepted_rows), 1)


if __name__ == "__main__":
    unittest.main()
