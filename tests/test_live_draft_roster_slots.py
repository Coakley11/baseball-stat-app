"""Regression tests for host-configured roster slots (Live Draft Room)."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from live_draft_pick_scoring import _draft_compute_position_replacement
from live_draft_roster_slots import (
    freeze_slot_instances_on_config,
    format_open_position_needs,
    get_active_draft_roster_slots,
    get_remaining_position_needs,
    get_required_position_counts,
    normalize_draft_slot_config,
    session_slot_count,
    sync_live_slot_widgets_from_config,
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

    def test_infer_draft_assistant_needs_respects_host_slots(self) -> None:
        from draft_ami_helpers import infer_draft_assistant_needs

        cfg = _minimal_config()
        roster = pd.DataFrame([{"fullName": "Catcher", "Primary Position": "C"}])
        pool = pd.DataFrame(
            [
                {"fullName": "Catcher", "Primary Position": "C", "proj_HR": 20, "proj_RBI": 80},
                {"fullName": "Other", "Primary Position": "SS", "proj_HR": 25, "proj_RBI": 90},
            ]
        )
        needed, _cats = infer_draft_assistant_needs(roster, pool, draft_format="5x5 Roto", config=cfg)
        self.assertIn("SS", needed)
        self.assertIn("OF", needed)
        self.assertNotIn("3B", needed)
        self.assertNotIn("DH", needed)

    def test_resolve_draft_slot_config_from_session(self) -> None:
        from live_draft_roster_slots import position_codes_in_slot_order, resolve_draft_slot_config_from_session

        cfg = _minimal_config()
        session = {"live_draft_room": {"config": cfg, "status": "in_progress"}}
        resolved = resolve_draft_slot_config_from_session(session)
        self.assertEqual(resolved.get("slots"), cfg["slots"])
        order = position_codes_in_slot_order(resolved)
        self.assertEqual(order, ["C", "1B", "2B", "SS", "OF"])
        self.assertNotIn("3B", order)
        self.assertNotIn("DH", order)

    def test_resolve_draft_slot_config_from_live_draft_state_blob(self) -> None:
        from live_draft_roster_slots import resolve_draft_slot_config_from_session

        cfg = _minimal_config()
        session = {"live_draft_state": {"config": cfg, "draft_room_id": "ROOM1", "status": "in_progress"}}
        resolved = resolve_draft_slot_config_from_session(session)
        self.assertEqual(resolved.get("slots"), cfg["slots"])

    def test_infer_draft_assistant_needs_without_host_slots_returns_empty(self) -> None:
        from draft_ami_helpers import infer_draft_assistant_needs

        needed, _cats = infer_draft_assistant_needs(pd.DataFrame(), pd.DataFrame(), config={})
        self.assertEqual(needed, [])

    def test_completion_panel_has_analyze_and_save_actions(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("render_live_draft_completion_panel", text)
        self.assertIn("export_frames_fn=live_draft_export_frames", text)
        ui_text = (_REPO / "draft_archive_ui.py").read_text(encoding="utf-8")
        self.assertIn('"Save Draft"', ui_text)
        self.assertIn('"Analyze Draft"', ui_text)
        self.assertIn('"Set Active Draft"', ui_text)

    def test_rec_table_drops_redundant_score_columns(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        marker = 'key="live_draft_rec_top"'
        idx = text.find(marker)
        self.assertNotEqual(idx, -1)
        chunk = text[max(0, idx - 4000) : idx]
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

    def test_structured_pick_verdict_uses_short_value_prose(self) -> None:
        from live_draft_pick_engine import build_structured_pick_verdict

        text = build_structured_pick_verdict(
            {
                "Pick": 50,
                "Primary Position": "OF",
                "Market Rank": 145,
                "Fantasy Edge": 31,
                "Decision Score": 0.82,
            },
            pick_source="Draft Assistant Pick",
            gaps=["OF", "OF"],
        )
        self.assertNotIn("Draft Assistant Pick:", text)
        self.assertIn("ADP", text)

    def test_session_slot_count_preserves_zero(self) -> None:
        session = {"live_slot_3b": 0, "live_slot_dh": 0, "live_slot_bench": 0}
        self.assertEqual(session_slot_count(session, "live_slot_3b", 1), 0)
        self.assertEqual(session_slot_count(session, "live_slot_dh", 1), 0)
        self.assertEqual(session_slot_count(session, "live_slot_bench", 5), 0)
        self.assertEqual(session_slot_count(session, "live_slot_c", 1), 1)

    def test_normalize_draft_slot_config_drops_stale_slot_instances(self) -> None:
        cfg = _minimal_config()
        stale = freeze_slot_instances_on_config(
            {
                "slots": {
                    "C": 1,
                    "1B": 1,
                    "2B": 1,
                    "3B": 1,
                    "SS": 1,
                    "OF": 3,
                    "DH": 1,
                    "P": 0,
                    "BN": 5,
                }
            }
        )
        cfg["slot_instances"] = stale["slot_instances"]
        normalized = normalize_draft_slot_config(cfg)
        labels = [s["label"] for s in get_active_draft_roster_slots(normalized)]
        self.assertEqual(labels, ["C", "1B", "2B", "SS", "OF"])
        self.assertEqual(len(labels), 5)

    def test_restore_round_trip_preserves_five_position_format(self) -> None:
        from live_draft_state import LIVE_DRAFT_STATE_KEY, prepare_live_draft_state, room_from_persist_dict, room_to_persist_dict

        cfg = _minimal_config()
        room = {
            "draft_room_id": "ROOM5",
            "status": "in_progress",
            "config": cfg,
            "teams": ["Team A", "Team B"],
            "pick_order": [
                {"Pick": 1, "Round": 1, "Team": "Team A"},
                {"Pick": 2, "Round": 1, "Team": "Team B"},
            ],
            "current_pick_index": 0,
            "draft_board": [],
            "rosters": {"Team A": [], "Team B": []},
            "drafted_player_ids": [],
            "pool": pd.DataFrame(
                [
                    {"fullName": "C1", "Primary Position": "C", "Expected Fantasy Value": 0.9, "playerID": "c1"},
                    {"fullName": "SS1", "Primary Position": "SS", "Expected Fantasy Value": 0.85, "playerID": "s1"},
                ]
            ),
        }
        blob = room_to_persist_dict(room)
        session = {LIVE_DRAFT_STATE_KEY: blob}
        restored_room = prepare_live_draft_state(session)
        self.assertIsNotNone(restored_room)
        restored_cfg = normalize_draft_slot_config(dict(restored_room.get("config") or {}))
        checklist = build_roster_checklist(pd.DataFrame(), restored_cfg)
        self.assertEqual(checklist["target"], 5)
        needs = get_remaining_position_needs(pd.DataFrame(), restored_cfg)
        need_label = format_open_position_needs(needs)
        self.assertNotIn("3B", need_label)
        self.assertNotIn("DH", need_label)
        self.assertNotIn("BN", need_label)
        active = {s["position"] for s in get_active_draft_roster_slots(restored_cfg)}
        self.assertEqual(active, {"C", "1B", "2B", "SS", "OF"})
        round_trip = room_from_persist_dict(blob)
        assert round_trip is not None
        self.assertEqual(
            [s["label"] for s in get_active_draft_roster_slots(round_trip["config"])],
            ["C", "1B", "2B", "SS", "OF"],
        )

    def test_sync_live_slot_widgets_from_config(self) -> None:
        session: dict = {"live_slot_3b": 1, "live_slot_dh": 1, "live_slot_bench": 5}
        sync_live_slot_widgets_from_config(session, _minimal_config())
        self.assertEqual(session["live_slot_3b"], 0)
        self.assertEqual(session["live_slot_dh"], 0)
        self.assertEqual(session["live_slot_bench"], 0)
        self.assertEqual(session["live_slot_c"], 1)

    def test_full_fifteen_player_roster_fills_util_and_bench(self) -> None:
        cfg = freeze_slot_instances_on_config(
            {
                "slots": {
                    "C": 1,
                    "1B": 1,
                    "2B": 1,
                    "3B": 1,
                    "SS": 1,
                    "OF": 3,
                    "DH": 1,
                    "P": 0,
                    "BN": 5,
                }
            }
        )
        roster = pd.DataFrame(
            [
                {"fullName": "C1", "Primary Position": "C"},
                {"fullName": "B1", "Primary Position": "1B"},
                {"fullName": "B2", "Primary Position": "2B"},
                {"fullName": "B3", "Primary Position": "3B"},
                {"fullName": "SS1", "Primary Position": "SS"},
                {"fullName": "OF1", "Primary Position": "OF"},
                {"fullName": "OF2", "Primary Position": "OF"},
                {"fullName": "OF3", "Primary Position": "OF"},
                {"fullName": "UTIL1", "Primary Position": "SS"},
                {"fullName": "BN1", "Primary Position": "1B"},
                {"fullName": "BN2", "Primary Position": "2B"},
                {"fullName": "BN3", "Primary Position": "3B"},
                {"fullName": "BN4", "Primary Position": "OF"},
                {"fullName": "BN5", "Primary Position": "C"},
            ]
        )
        checklist = build_roster_checklist(roster, cfg)
        self.assertEqual(checklist["filled"], 14)
        self.assertEqual(checklist["target"], 14)
        self.assertEqual(checklist["gaps"], [])
        labels = [ln["label"] for ln in checklist["lines"]]
        self.assertIn("UTIL", labels)
        self.assertIn("BN 1", labels)
        self.assertTrue(all(ln["filled"] for ln in checklist["lines"]))

    def test_util_filled_by_non_dh_overflow_hitter(self) -> None:
        cfg = freeze_slot_instances_on_config(
            {"slots": {"C": 1, "1B": 1, "2B": 0, "3B": 0, "SS": 1, "OF": 1, "DH": 1, "P": 0, "BN": 0}}
        )
        roster = pd.DataFrame(
            [
                {"fullName": "C1", "Primary Position": "C"},
                {"fullName": "B1", "Primary Position": "1B"},
                {"fullName": "SS1", "Primary Position": "SS"},
                {"fullName": "OF1", "Primary Position": "OF"},
                {"fullName": "Extra", "Primary Position": "SS"},
            ]
        )
        checklist = build_roster_checklist(roster, cfg)
        util_line = next(ln for ln in checklist["lines"] if ln["label"] == "UTIL")
        self.assertTrue(util_line["filled"])
        self.assertEqual(checklist["filled"], 5)


if __name__ == "__main__":
    unittest.main()
