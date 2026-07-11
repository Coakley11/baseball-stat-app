"""Regression tests for weekly stats visibility and unified Trade Center."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import pandas as pd

from fantasy_trade_ideas import (
    LINEUP_ASSISTANT_TAB_KEY,
    resolve_lineup_assistant_tab,
    resolve_player_owner_team,
    resolve_receive_target_teams,
)
from fantasy_weekly_hitter_scoring import (
    create_weekly_baseline_on_lock,
    get_weekly_scoring_record,
    maybe_mark_legacy_lineup_scoring,
    refresh_weekly_scoring,
    resolve_hitter_scoring_profile,
)
from fantasy_weekly_lineup import save_weekly_lineup
from tests.test_fantasy_weekly_hitter_scoring import _league_context, _roster


class WeeklyStatsVisibilityTests(unittest.TestCase):
    def test_save_creates_scoring_record_with_starters(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        slots = ["1B", "2B"]
        assignments = {"1B": "Corner Bat", "2B": "Middle Man"}
        result = save_weekly_lineup(
            session,
            week=3,
            slots=slots,
            assignments=assignments,
            my_team="Donny",
            roster_df=_roster(),
        )
        self.assertTrue(result.get("ok"), result.get("errors"))
        from fantasy_league_context import get_active_league_context

        ctx = get_active_league_context(session) or ctx
        record = get_weekly_scoring_record(ctx, week=3, team="Donny")
        self.assertIsNotNone(record)
        self.assertTrue(record.get("baseline_created_at"))
        self.assertGreaterEqual(len(record.get("starters") or {}), 1)
        self.assertFalse(record.get("legacy"))

    def test_zero_delta_refresh_still_has_player_results(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        profile = resolve_hitter_scoring_profile(ctx)
        assignments = {"slot_1B": "Corner Bat", "slot_2B": "Middle Man"}
        create_weekly_baseline_on_lock(
            ctx,
            week=1,
            team="Donny",
            assignments=assignments,
            roster_df=_roster(),
            profile=profile,
        )
        refresh_weekly_scoring(ctx, week=1, team="Donny", roster_df=_roster(), profile=profile)
        record = get_weekly_scoring_record(ctx, week=1, team="Donny")
        self.assertGreater(len(record.get("player_results") or {}), 0)
        first = next(iter((record.get("player_results") or {}).values()))
        display = first.get("display") or {}
        self.assertIn("HR", display)

    def test_maybe_mark_legacy_skips_post_scoring_save(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        saved = {
            "status": "locked",
            "weekly_scoring_record_key": "league|Donny|week_1",
        }
        out = maybe_mark_legacy_lineup_scoring(session, ctx, week=1, team="Donny", saved_lineup=saved)
        self.assertIsNone(get_weekly_scoring_record(out, week=1, team="Donny"))

    def test_refresh_preserves_baseline(self) -> None:
        session: dict = {}
        ctx = _league_context(session)
        profile = resolve_hitter_scoring_profile(ctx)
        assignments = {"slot_1B": "Corner Bat"}
        create_weekly_baseline_on_lock(
            ctx,
            week=1,
            team="Donny",
            assignments=assignments,
            roster_df=_roster(),
            profile=profile,
        )
        baseline_at = get_weekly_scoring_record(ctx, week=1, team="Donny")["baseline_created_at"]
        roster2 = _roster().copy()
        roster2.loc[roster2["Player"] == "Corner Bat", "HR"] = 20
        refresh_weekly_scoring(ctx, week=1, team="Donny", roster_df=roster2, profile=profile)
        record = get_weekly_scoring_record(ctx, week=1, team="Donny")
        self.assertEqual(record["baseline_created_at"], baseline_at)


class TradeCenterTests(unittest.TestCase):
    def _rosters(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Power Guy", "HR": 25, "RBI": 70, "R": 60, "SB": 3, "BA": 0.240, "OPS": 0.800},
                {"Team": "C. Oakley", "Player": "Oak Contact", "HR": 6, "RBI": 40, "R": 50, "SB": 15, "BA": 0.320, "OPS": 0.780},
            ]
        )

    def test_resolve_player_owner_team(self) -> None:
        owner = resolve_player_owner_team("Oak Contact", self._rosters(), my_team="Daniel")
        self.assertEqual(owner, "C. Oakley")

    def test_resolve_receive_target_teams(self) -> None:
        owners = resolve_receive_target_teams(["Oak Contact"], self._rosters(), my_team="Daniel")
        self.assertEqual(owners.get("Oak Contact"), "C. Oakley")

    def test_player_action_handoff_opens_trade_center(self) -> None:
        session: dict = {"_lineup_focus_trade_center": True}
        tab = resolve_lineup_assistant_tab(session)
        self.assertEqual(tab, "Trade Center")
        self.assertEqual(session[LINEUP_ASSISTANT_TAB_KEY], "Trade Center")

    @patch("fantasy_trade_ideas.derive_category_needs", return_value={"BA": True})
    def test_receive_only_uses_owner_team(self, _mock_needs) -> None:
        from fantasy_trade_ideas import generate_trade_ideas

        rosters = self._rosters()
        ideas, diag = generate_trade_ideas(
            "Daniel",
            rosters,
            None,
            forced_get=["Oak Contact"],
            target_owner_teams={"Oak Contact": "C. Oakley"},
            summarize_team_category_needs_fn=lambda *_: {"BA": True},
        )
        self.assertEqual(diag["opposing_teams_searched"], ["C. Oakley"])


if __name__ == "__main__":
    unittest.main()
