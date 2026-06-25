"""Tests for Draft Simulation Test Mode post-draft analysis."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_lab_analysis import (
    build_team_roster_needs_rows,
    classify_team_picks,
    count_team_position_haves,
    draft_lab_roster_team_options,
    enrich_lab_draft_metrics,
    format_snake_draft_caption,
    roster_position_targets,
)
from draft_lab_state import _handoff_picks, draft_lab_roster_view_options, ensure_draft_lab_widget_keys


def _sample_draft() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Fantasy Team": "Ariel", "Pick": 1, "fullName": "Player A", "Primary Position": "OF", "playerID": "a", "Decision Score": 0.82, "Fantasy Edge": 12, "Draft Fit Score": 0.7, "Model Rank": 40, "Market Rank": 80},
            {"Fantasy Team": "Ariel", "Pick": 3, "fullName": "Player B", "Primary Position": "SS", "playerID": "b", "Decision Score": 0.55, "Fantasy Edge": -3, "Draft Fit Score": 0.4, "Model Rank": 20, "Market Rank": 10},
            {"Fantasy Team": "Daniel", "Pick": 2, "fullName": "Player C", "Primary Position": "C", "playerID": "c", "Decision Score": 0.75, "Fantasy Edge": 8, "Draft Fit Score": 0.65, "Model Rank": 30, "Market Rank": 35},
            {"Fantasy Team": "Daniel", "Pick": 4, "fullName": "Player D", "Primary Position": "OF", "playerID": "d", "Decision Score": 0.62, "Fantasy Edge": 4, "Draft Fit Score": 0.5, "Model Rank": 50, "Market Rank": 48},
        ]
    )


class DraftLabAnalysisTests(unittest.TestCase):
    def test_snake_caption_uses_actual_team_names(self) -> None:
        text = format_snake_draft_caption(["Ariel", "Daniel"])
        self.assertIn("Ariel → Daniel", text)
        self.assertIn("Daniel → Ariel", text)
        self.assertNotIn("Team A", text)

    def test_roster_needs_shows_all_positions_with_zero_have(self) -> None:
        targets = roster_position_targets({"slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "BN": 5}})
        roster = _sample_draft()[_sample_draft()["Fantasy Team"] == "Ariel"]
        rows = build_team_roster_needs_rows("Ariel", roster, targets)
        positions = {r["Position"] for r in rows}
        self.assertIn("1B", positions)
        self.assertIn("Bench", positions)
        one_b = next(r for r in rows if r["Position"] == "1B")
        self.assertEqual(one_b["Have"], 0)
        self.assertEqual(one_b["Gap"], 1)
        self.assertEqual(sum(int(r["Have"]) for r in rows), len(roster))

    def test_position_counts_do_not_double_count(self) -> None:
        roster = _sample_draft()[_sample_draft()["Fantasy Team"] == "Ariel"]
        haves = count_team_position_haves(roster)
        self.assertEqual(sum(haves.values()), len(roster))

    def test_exactly_one_best_pick_per_team(self) -> None:
        draft = _sample_draft()
        targets = roster_position_targets({"slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "BN": 5}})
        for team in ["Ariel", "Daniel"]:
            team_df = draft[draft["Fantasy Team"] == team]
            rows = classify_team_picks(team, team_df, draft, targets=targets, pool_df=None)
            best = [r for r in rows if r["Pick Type"] == "Best Pick"]
            self.assertEqual(len(best), 1)
            questionable = [r for r in rows if r["Pick Type"] == "Questionable Pick"]
            best_name = best[0]["Player"]
            for q in questionable:
                self.assertNotEqual(q["Player"], best_name)

    def test_good_pick_not_forced_questionable(self) -> None:
        draft = _sample_draft()
        targets = roster_position_targets({"slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "BN": 5}})
        rows = classify_team_picks("Daniel", draft[draft["Fantasy Team"] == "Daniel"], draft, targets=targets, pool_df=None)
        types = {r["Pick Type"] for r in rows}
        self.assertIn("Best Pick", types)
        self.assertTrue("Good Pick" in types or "Questionable Pick" in types)
        self.assertTrue(all(str(r.get("Reason") or "").strip() for r in rows))

    def test_roster_team_options_for_two_team_live_draft(self) -> None:
        opts = draft_lab_roster_team_options(["Daniel", "Ariel"])
        self.assertEqual(opts, ["All Teams", "Daniel", "Ariel"])

    def test_handoff_picks_from_live_room(self) -> None:
        session = {
            "live_draft_room": {"config": {"picks_per_team": 4}},
            "draft_lab_results": {"handoff": {"picks_per_team": 4, "team_names": ["Ariel", "Daniel"]}},
        }
        self.assertEqual(_handoff_picks(session), 4)
        ensure_draft_lab_widget_keys(session)
        self.assertEqual(session["draft_lab_picks_per_team"], 4)
        opts = draft_lab_roster_view_options(session)
        self.assertEqual(opts, ["All Teams", "Ariel", "Daniel"])

    def test_enrich_draft_metrics_no_crash_without_pool(self) -> None:
        out = enrich_lab_draft_metrics(_sample_draft(), None, {})
        self.assertEqual(len(out), 4)


if __name__ == "__main__":
    unittest.main()
