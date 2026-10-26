"""Use Suggested Lineup: fills the board as a draft, validated by the canonical rule, never saved."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from fantasy_league_context import get_active_league_context
from fantasy_lineup_ui import build_slot_key_labels
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from fantasy_weekly_lineup import is_lineup_locked, validate_weekly_lineup
from suggested_lineup import apply_suggested_lineup, suggested_assignments
from tests.test_team_control_and_local_saves import STATS, _as, _league


def _row(name, primary, eligible, ops, hr=10):
    return {"Player": name, "Team": "Team A", "Primary Position": primary, "Eligible Positions": eligible,
            "AB": 100, "H": 25, "HR": hr, "RBI": 30, "R": 30, "SB": 2, "BA": 0.250, "OPS": ops}


class SuggestedAssignmentsTests(unittest.TestCase):
    def test_legal_recommendation_fills_every_slot_and_validates(self):
        roster = pd.DataFrame([_row("Cal Raleigh", "C", "C", 0.85), _row("Aaron Judge", "OF", "OF", 1.0),
                               _row("Juan Soto", "OF", "OF", 0.95), _row("Pete Alonso", "1B", "1B", 0.8)])
        slots = ["C", "OF", "OF", "UTIL"]
        labels = build_slot_key_labels(slots)
        assignments, unfilled = suggested_assignments(labels, roster)
        self.assertEqual(unfilled, [])
        self.assertEqual(sorted(v for v in assignments.values()), sorted(["Cal Raleigh", "Aaron Judge", "Juan Soto", "Pete Alonso"]))
        self.assertEqual(assignments[labels[0].key], "Cal Raleigh")
        self.assertTrue(validate_weekly_lineup(slots, assignments, roster)["ok"])

    def test_missing_position_is_left_empty_and_reported(self):
        roster = pd.DataFrame([_row("Aaron Judge", "OF", "OF", 1.0), _row("Pete Alonso", "1B", "1B", 0.8)])
        labels = build_slot_key_labels(["C", "OF", "1B"])
        assignments, unfilled = suggested_assignments(labels, roster)
        self.assertEqual(unfilled, ["C"])
        self.assertEqual(assignments[labels[0].key], "")
        result = validate_weekly_lineup(["C", "OF", "1B"], assignments, roster)
        self.assertIn("C", result["unfillable_slots"])

    def test_multi_position_player_uses_games_played_eligibility(self):
        roster = pd.DataFrame([_row("George Springer", "DH", "OF, DH", 0.9), _row("Cal Raleigh", "C", "C", 0.85)])
        labels = build_slot_key_labels(["C", "OF"])
        assignments, unfilled = suggested_assignments(labels, roster)
        self.assertEqual(assignments[labels[1].key], "George Springer")
        self.assertEqual(unfilled, [])

    def test_never_suggests_a_slot_the_save_rule_rejects(self):
        roster = pd.DataFrame([_row("Michael Busch", "1B", "1B", 0.9), _row("Pete Alonso", "1B", "1B", 0.85)])
        labels = build_slot_key_labels(["1B", "3B"])
        assignments, unfilled = suggested_assignments(labels, roster)
        self.assertEqual(unfilled, ["3B"])
        self.assertEqual(assignments[labels[1].key], "")


class ApplySuggestedLineupTests(unittest.TestCase):
    """Applies as a draft through the same ownership checks as dragging; never saves or locks."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))
        self.session: dict = {}
        _league(self.session, claim_b="uuid-b")  # local:qa owns Team A + commissioner; B claimed; C unclaimed

    def tearDown(self):
        set_shared_league_store(None)
        self._tmp.cleanup()

    def _roster(self, team):
        ctx = get_active_league_context(self.session)
        names = [p["player_name"] for p in ctx["league_rosters"][team]["players"]]
        df = STATS[STATS["Player"].isin(names)].copy()
        df["Team"] = team
        df["OPS"] = 0.8
        return df

    def _apply(self, team):
        return apply_suggested_lineup(self.session, week=1, slots=["C", "OF"], slot_labels=build_slot_key_labels(["C", "OF"]),
                                      team_roster=self._roster(team), team=team)

    def _draft(self, team):
        ctx = get_active_league_context(self.session)
        drafts = (ctx.get("workflow") or {}).get("weekly_lineup_drafts") or {}
        return next((v for k, v in drafts.items() if team in k), None)

    def test_local_no_auth_own_team_fills_a_draft_only(self):
        with _as("local:qa"):
            result = self._apply("Team A")
        self.assertTrue(result["ok"], result)
        self.assertIn("Save Lineup", result["message"])
        draft = self._draft("Team A")
        self.assertIsNotNone(draft)
        self.assertEqual(draft.get("status"), "draft")
        ctx = get_active_league_context(self.session)
        self.assertFalse(is_lineup_locked(ctx, 1, team="Team A", session=self.session))
        self.assertFalse(((ctx.get("workflow") or {}).get("weekly_lineups") or {}))  # nothing saved

    def test_commissioner_acting_for_unclaimed_team(self):
        with _as("local:qa"):
            result = self._apply("Team C")
        self.assertTrue(result["ok"], result)
        self.assertEqual(self._draft("Team C").get("status"), "draft")

    def test_claimed_team_is_refused(self):
        with _as("local:qa"):
            result = self._apply("Team B")
        self.assertFalse(result["ok"])
        self.assertIn("managed by", " ".join(result["errors"]))
        self.assertIsNone(self._draft("Team B"))

    def test_write_check_failure_stops_before_anything_is_written(self):
        with _as("local:qa"):
            result = apply_suggested_lineup(self.session, week=1, slots=["C", "OF"],
                                            slot_labels=build_slot_key_labels(["C", "OF"]),
                                            team_roster=self._roster("Team A"), team="Team A",
                                            write_check=lambda: (False, "Sign in to save lineup changes."))
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"], ["Sign in to save lineup changes."])
        self.assertIsNone(self._draft("Team A"))


class BoardWiringTests(unittest.TestCase):
    def test_button_only_sets_a_flag_and_the_apply_path_never_saves(self):
        src = (Path(__file__).resolve().parents[1] / "fantasy_weekly_lineup_ui.py").read_text(encoding="utf-8")
        start = src.index('"Use Suggested Lineup",')
        block = src[start:start + 500]
        self.assertIn("on_click=lambda: session.__setitem__(suggest_flag, True)", block)
        apply_block = src[src.index("suggest_flag = f\"{canon_key}|apply_suggested\""):src.index('"Use Suggested Lineup",')]
        self.assertNotIn("save_weekly_lineup", apply_block)
        self.assertIn("apply_suggested_lineup", apply_block)
        module = (Path(__file__).resolve().parents[1] / "suggested_lineup.py").read_text(encoding="utf-8")
        self.assertNotIn("save_weekly_lineup", module.split('"""', 2)[2])
        self.assertNotIn("finalize", module.split('"""', 2)[2])


if __name__ == "__main__":
    unittest.main()
