"""Tests for shared draft UI helpers."""

from __future__ import annotations

import unittest
import unittest.mock

from draft_ui import (
    assess_required_live_settings,
    copy_sim_convert_settings_to_live,
    draft_disabled_hint,
    lookup_player_draft_meta,
    on_confirm_convert_simulator_to_live,
)


class TestDraftDisabledHint(unittest.TestCase):
    def test_not_your_pick_shortened(self) -> None:
        self.assertEqual(
            draft_disabled_hint("Not your pick (Pick 8: Team B)."),
            "Not your pick",
        )

    def test_other_reason_passthrough(self) -> None:
        self.assertEqual(draft_disabled_hint("Draft is complete."), "Draft is complete.")


class TestLookupPlayerDraftMeta(unittest.TestCase):
    def test_empty_name(self) -> None:
        self.assertEqual(lookup_player_draft_meta({}, ""), {"position": "—", "team": "—"})


class TestSimulatorConvertSettings(unittest.TestCase):
    def test_assess_incomplete_when_keys_missing(self) -> None:
        complete, missing, reason = assess_required_live_settings({})
        self.assertFalse(complete)
        self.assertEqual(len(missing), 4)
        self.assertIn("Missing:", reason)

    def test_assess_complete_when_all_keys_set(self) -> None:
        session = {
            "sim_convert_live_draft_timer": "90 seconds",
            "sim_convert_live_draft_proj_window": 3,
            "sim_convert_live_draft_proj_style": "Balanced",
            "sim_convert_live_draft_auto_rule": "best model rank",
        }
        complete, missing, reason = assess_required_live_settings(session)
        self.assertTrue(complete)
        self.assertEqual(missing, [])
        self.assertEqual(reason, "")

    def test_copy_sim_convert_settings_to_live(self) -> None:
        session = {
            "sim_convert_live_draft_timer": "60 seconds",
            "sim_convert_live_draft_proj_window": 4,
            "sim_convert_live_draft_proj_style": "Aggressive",
            "sim_convert_live_draft_auto_rule": "best roster need",
        }
        copy_sim_convert_settings_to_live(session)
        self.assertEqual(session["live_draft_timer"], "60 seconds")
        self.assertEqual(session["live_draft_proj_window"], 4)
        self.assertEqual(session["live_draft_proj_style"], "Aggressive")
        self.assertEqual(session["live_draft_auto_rule"], "best roster need")

    def test_on_confirm_sets_pending_and_trace(self) -> None:
        import streamlit as st

        session = {
            "sim_convert_live_draft_timer": "90 seconds",
            "sim_convert_live_draft_proj_window": 3,
            "sim_convert_live_draft_proj_style": "Balanced",
            "sim_convert_live_draft_auto_rule": "best model rank",
            "_simulator_to_live_show_confirm": True,
        }
        with unittest.mock.patch.object(st, "session_state", session):
            on_confirm_convert_simulator_to_live()
        self.assertTrue(session.get("_start_live_draft_pending"))
        self.assertEqual(session.get("_start_live_draft_mode"), "simulator")
        self.assertNotIn("_simulator_to_live_show_confirm", session)
        trace = session.get("_start_live_draft_trace") or {}
        self.assertTrue(trace.get("confirm_convert_clicked"))
        self.assertEqual(trace.get("start_live_draft_mode"), "simulator")


if __name__ == "__main__":
    unittest.main()
