"""Regression tests for lineup scope isolation and trade center behavior."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_lineup_scope import (
    LINEUP_IDENTITY_SYNC_ERROR,
    apply_lineup_scope_change,
    assert_lineup_write_identity,
    build_lineup_scope_fingerprint,
    resolve_canonical_lineup_team,
    resolve_lineup_scope,
    roster_stats_cache_valid,
    stamp_roster_stats_cache_scope,
)
from fantasy_trade_ideas import generate_trade_ideas
from fantasy_weekly_hitter_scoring import (
    get_active_scoring_week,
    set_active_scoring_week,
    week_editability_message,
)
from fantasy_weekly_lineup_ui import canonical_week_key, ensure_canonical_assignments


def _daniel_session() -> dict:
    return {
        "_suite_auth_user_id": "supabase-uuid-daniel",
        "_suite_auth_external_id": "daniel",
        "_suite_owned_workspace_id": "daniel",
        "_suite_active_workspace_id": "daniel",
        "_suite_auth_user_email": "daniel.cohen11@yahoo.com",
        "weekly_lineup_canon_1": {"OF_1": "Aaron Judge"},
    }


def _coakley_session() -> dict:
    return {
        "_suite_auth_user_id": "supabase-uuid-coakley",
        "_suite_auth_external_id": "coakley11",
        "_suite_owned_workspace_id": "coakley11",
        "_suite_active_workspace_id": "coakley11",
        "_suite_auth_user_email": "coakley11@aol.com",
        "weekly_lineup_canon_1": {"OF_1": "Aaron Judge"},
        "fantasy_current_roster_stats": pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge"}]),
    }


def _shared_context(team: str = "Daniel") -> dict:
    return {
        "context_type": "real_league",
        "my_team_name": team,
        "metadata": {"league_id": "league:flc-test"},
        "team_ownership": {
            "Daniel": {
                "user_id": "supabase-uuid-daniel",
                "email": "daniel.cohen11@yahoo.com",
            },
            "Team 2": {
                "user_id": "supabase-uuid-coakley",
                "email": "coakley11@aol.com",
            },
        },
        "league_rosters": {"Daniel": {"players": []}, "Team 2": {"players": []}},
        "workflow": {"weekly_hitter_scoring": {"active_week": 1}},
    }


class LineupScopeIsolationTests(unittest.TestCase):
    def test_daniel_resolves_owned_team(self) -> None:
        session = _daniel_session()
        context = _shared_context(team="Team 2")
        self.assertEqual(
            resolve_canonical_lineup_team(session, context, page_lineup_team="Team 2"),
            "Daniel",
        )

    def test_coakley_resolves_team_2(self) -> None:
        session = _coakley_session()
        context = _shared_context(team="Daniel")
        self.assertEqual(
            resolve_canonical_lineup_team(session, context, page_lineup_team="Daniel"),
            "Team 2",
        )

    def test_scope_keys_differ_across_accounts(self) -> None:
        daniel_scope = resolve_lineup_scope(_daniel_session(), _shared_context(), week=1, page_lineup_team="Daniel")
        coakley_scope = resolve_lineup_scope(_coakley_session(), _shared_context(), week=1, page_lineup_team="Team 2")
        assert daniel_scope is not None and coakley_scope is not None
        self.assertNotEqual(daniel_scope.fingerprint, coakley_scope.fingerprint)
        self.assertNotEqual(daniel_scope.assignments_key, coakley_scope.assignments_key)

    def test_scope_change_discards_legacy_nonempty_assignments(self) -> None:
        session = _coakley_session()
        context = _shared_context(team="Daniel")
        scope = resolve_lineup_scope(session, context, week=1, page_lineup_team="Team 2")
        assert scope is not None
        self.assertTrue(apply_lineup_scope_change(session, scope))
        slot_keys = [("OF_1", "Outfield 1"), ("C_1", "Catcher")]
        saved = {"OF_1": "Juan Soto", "C_1": ""}
        assignments = ensure_canonical_assignments(
            session,
            canon_key=scope.assignments_key,
            slot_keys=slot_keys,
            saved_assignments=saved,
            scope_changed=True,
        )
        self.assertEqual(assignments.get("OF_1"), "Juan Soto")
        self.assertNotIn("weekly_lineup_canon_1", session)

    def test_roster_stats_cache_rejects_different_scope(self) -> None:
        session = _daniel_session()
        context = _shared_context()
        scope = resolve_lineup_scope(session, context, week=1)
        assert scope is not None
        stamp_roster_stats_cache_scope(session, scope)
        other_scope = resolve_lineup_scope(_coakley_session(), context, week=1)
        assert other_scope is not None
        self.assertFalse(roster_stats_cache_valid(session, other_scope))

    def test_save_blocked_when_identity_out_of_sync(self) -> None:
        context = _shared_context(team="Daniel")
        scope = resolve_lineup_scope(_daniel_session(), context, week=1, page_lineup_team="Team 2")
        ok, err = assert_lineup_write_identity(scope)
        self.assertFalse(ok)
        self.assertEqual(err, LINEUP_IDENTITY_SYNC_ERROR)

    def test_component_keys_use_scope(self) -> None:
        scope = resolve_lineup_scope(_daniel_session(), _shared_context(), week=3)
        assert scope is not None
        self.assertIn("week_3", scope.component_key_base)
        self.assertNotEqual(canonical_week_key("weekly_lineup", 3), scope.assignments_key)


class ActiveWeekLifecycleTests(unittest.TestCase):
    def test_week_1_active_by_default(self) -> None:
        context = _shared_context()
        self.assertEqual(get_active_scoring_week(context), 1)
        self.assertEqual(week_editability_message(context, 1)[0], "active")
        self.assertEqual(week_editability_message(context, 2)[0], "future")
        self.assertIn("not open yet", week_editability_message(context, 3)[1])

    def test_finalize_advances_active_week(self) -> None:
        context = _shared_context()
        set_active_scoring_week(context, 2)
        self.assertEqual(get_active_scoring_week(context), 2)
        self.assertEqual(week_editability_message(context, 1)[0], "past")


class TradeIdeasRegressionTests(unittest.TestCase):
    def _ramirez_rosters(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Team": "Daniel",
                    "Player": "José Ramírez",
                    "HR": 18,
                    "RBI": 62,
                    "R": 55,
                    "SB": 12,
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

    def test_give_only_jose_ramirez_returns_ideas_from_team_2(self) -> None:
        ideas, diag = generate_trade_ideas(
            "Daniel",
            self._ramirez_rosters(),
            None,
            forced_give=["José Ramírez"],
            summarize_team_category_needs_fn=lambda *_: {},
            league_context_id="league:test",
        )
        self.assertFalse(ideas.empty, diag)
        self.assertTrue(all(ideas["Other Team"].astype(str) == "Team 2"))
        self.assertTrue(all(ideas["Give"].astype(str) == "José Ramírez"))

    def test_empty_category_needs_still_returns_fair_candidates(self) -> None:
        ideas, diag = generate_trade_ideas(
            "Daniel",
            self._ramirez_rosters(),
            None,
            forced_give=["José Ramírez"],
            summarize_team_category_needs_fn=lambda *_: {},
        )
        self.assertGreater(diag.get("candidate_count_after_fairness", 0), 0)
        self.assertFalse(ideas.empty)


if __name__ == "__main__":
    unittest.main()
