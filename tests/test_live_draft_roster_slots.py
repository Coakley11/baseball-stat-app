"""Regression tests for host-configured roster slots (Live Draft Room)."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from live_draft_pick_scoring import _draft_compute_position_replacement
from live_draft_roster_slots import (
    freeze_slot_instances_on_config,
    get_active_draft_roster_slots,
    get_remaining_position_needs,
    get_required_position_counts,
)
from live_draft_roster_tracker import build_roster_checklist

_REPO = Path(__file__).resolve().parents[1]


def _minimal_config(**slot_overrides) -> dict:
    slots = {
        "C": 1,
        "1B": 1,
        "2B": 1,
        "3B": 0,
        "SS": 1,
        "OF": 1,
        "DH": 0,
        "P": 0,
        "BN": 0,
    }
    slots.update(slot_overrides)
    return freeze_slot_instances_on_config({"slots": slots})


class LiveDraftRosterSlotsTests(unittest.TestCase):
    def test_required_counts_respect_host_zeros(self) -> None:
        cfg = _minimal_config()
        counts = get_required_position_counts(cfg)
        self.assertEqual(counts["3B"], 0)
        self.assertEqual(counts["P"], 0)
        self.assertNotIn("3B", {s["position"] for s in get_active_draft_roster_slots(cfg)})

    def test_three_of_slots_are_separate_instances(self) -> None:
        cfg = freeze_slot_instances_on_config(
            {"slots": {"C": 1, "1B": 1, "2B": 0, "3B": 0, "SS": 0, "OF": 3, "DH": 0, "P": 0, "BN": 0}}
        )
        slots = get_active_draft_roster_slots(cfg)
        of_labels = [s["label"] for s in slots if s["position"] == "OF"]
        self.assertEqual(of_labels, ["OF 1", "OF 2", "OF 3"])
        self.assertEqual(len(of_labels), 3)

    def test_remaining_of_need_after_one_drafted(self) -> None:
        cfg = freeze_slot_instances_on_config(
            {"slots": {"C": 0, "1B": 0, "2B": 0, "3B": 0, "SS": 0, "OF": 3, "DH": 0, "P": 0, "BN": 0}}
        )
        roster = pd.DataFrame([{"fullName": "Player A", "Primary Position": "OF"}])
        needs = get_remaining_position_needs(roster, cfg)
        self.assertEqual(needs.count("OF"), 2)

    def test_checklist_reflects_slot_instances(self) -> None:
        cfg = _minimal_config()
        checklist = build_roster_checklist(pd.DataFrame(), cfg)
        labels = [ln["label"] for ln in checklist["lines"]]
        self.assertEqual(labels, ["C", "1B", "2B", "SS", "OF"])
        self.assertEqual(checklist["target"], 5)

    def test_scarcity_map_only_active_positions(self) -> None:
        cfg = _minimal_config()
        pool = pd.DataFrame(
            [
                {"fullName": "C1", "Primary Position": "C", "Expected Fantasy Value": 0.9},
                {"fullName": "3B1", "Primary Position": "3B", "Expected Fantasy Value": 0.8},
                {"fullName": "SS1", "Primary Position": "SS", "Expected Fantasy Value": 0.85},
            ]
        )
        active = {s["position"] for s in get_active_draft_roster_slots(cfg)}
        _, rows = _draft_compute_position_replacement(pool, active_positions=active, league_demand={"C": 1})
        positions = {r["Position"] for r in rows}
        self.assertIn("C", positions)
        self.assertIn("SS", positions)
        self.assertNotIn("3B", positions)

    def test_view_results_uses_safe_navigation(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        marker = 'key="live_draft_view_results_btn"'
        idx = text.find(marker)
        self.assertNotEqual(idx, -1)
        chunk = text[max(0, idx - 120) : idx + 200]
        self.assertIn("navigate_to_page", chunk)
        self.assertNotIn('main_sidebar_page"] = "Draft Room Simulator"', chunk)

    def test_rec_table_drops_redundant_score_columns(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        marker = 'key="live_draft_rec_top"'
        idx = text.find(marker)
        self.assertNotEqual(idx, -1)
        chunk = text[max(0, idx - 1200) : idx]
        self.assertIn('"Why this pick"', chunk)
        self.assertNotIn('"Sleeper Score"', chunk)
        self.assertNotIn('"Positional Fit"', chunk)

    def test_pick_snapshots_persisted_on_make_pick(self) -> None:
        from live_draft_pick_engine import live_draft_make_pick

        room = {
            "status": "in_progress",
            "current_pick_index": 0,
            "config": _minimal_config(),
            "teams": ["Team A"],
            "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team A"}],
            "draft_board": [],
            "rosters": {"Team A": []},
            "drafted_player_ids": [],
            "pool": pd.DataFrame(),
        }
        row = {
            "playerID": "p1",
            "fullName": "Test Player",
            "Primary Position": "SS",
            "Decision Score": 0.88,
            "Draft Fit Score": 1.2,
            "Scarcity Score": 0.4,
        }
        ok, _ = live_draft_make_pick(room, row, verdict="Manual Pick", pick_source="Manual Pick")
        self.assertTrue(ok)
        pick = room["draft_board"][0]
        self.assertEqual(pick.get("decision_score_at_pick"), 0.88)
        self.assertEqual(pick.get("roster_fit_score_at_pick"), 1.2)
        self.assertEqual(pick.get("pick_source"), "Manual Pick")

    def test_apply_pick_time_snapshots_prefers_frozen_scores(self) -> None:
        from draft_lab_analysis import apply_pick_time_snapshots, enrich_lab_draft_metrics

        draft = pd.DataFrame(
            [
                {
                    "Pick": 1,
                    "Fantasy Team": "Team A",
                    "playerID": "p1",
                    "fullName": "Test Player",
                    "decision_score_at_pick": 0.91,
                    "roster_fit_score_at_pick": 1.05,
                }
            ]
        )
        out = apply_pick_time_snapshots(draft)
        self.assertAlmostEqual(float(out.iloc[0]["Decision Score"]), 0.91)
        self.assertAlmostEqual(float(out.iloc[0]["Draft Fit Score"]), 1.05)
        enriched = enrich_lab_draft_metrics(out, pd.DataFrame(), _minimal_config())
        self.assertAlmostEqual(float(enriched.iloc[0]["Decision Score"]), 0.91)

    def test_structured_pick_verdict_includes_source_label(self) -> None:
        from live_draft_pick_engine import build_structured_pick_verdict

        text = build_structured_pick_verdict(
            {"Primary Position": "OF", "Decision Score": 0.82, "strong_categories_at_pick": ["HR", "RBI"]},
            pick_source="Draft Assistant Pick",
            gaps=["OF", "OF"],
        )
        self.assertTrue(text.startswith("Draft Assistant Pick:"))
        self.assertIn("OF", text)


if __name__ == "__main__":
    unittest.main()
