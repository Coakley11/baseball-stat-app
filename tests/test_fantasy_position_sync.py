"""Regression tests for fantasy position filter sync and multi-select."""

from __future__ import annotations

import unittest

from fantasy_position_sync import (
    SYNC_POSITION_NEEDS_KEY,
    clear_research_position_overrides,
    draft_needs_to_fantasy_slots,
    draft_needs_to_sleepers_raw,
    has_research_position_override,
    is_position_sync_enabled,
    normalize_position_filter_list,
    on_research_position_filter_changed,
    on_sync_position_needs_toggled,
    prepare_research_position_filter,
    read_draft_assistant_position_needs,
    read_research_position_filters,
    update_draft_assistant_position_needs,
    write_position_sync_settings,
)
from shared_draft_context import CANONICAL_SETTINGS_KEY, read_canonical_draft_settings, write_canonical_draft_settings


class FantasyPositionSyncTests(unittest.TestCase):
    def test_multiselect_normalization(self) -> None:
        self.assertEqual(normalize_position_filter_list(["2B", "SS"]), ["2B", "SS"])
        self.assertEqual(normalize_position_filter_list("2B"), ["2B"])
        self.assertEqual(normalize_position_filter_list("All positions"), [])
        self.assertEqual(normalize_position_filter_list([]), [])

    def test_draft_needs_map_to_fantasy_slots(self) -> None:
        self.assertEqual(draft_needs_to_fantasy_slots(["2B", "SS", "DH"]), ["2B", "SS", "DH/UTIL"])
        self.assertEqual(draft_needs_to_sleepers_raw(["C", "OF"]), ["C", "OF"])

    def test_sync_on_loads_draft_needs(self) -> None:
        session = {
            SYNC_POSITION_NEEDS_KEY: True,
            CANONICAL_SETTINGS_KEY: {
                "sync_position_needs_to_research": True,
                "draft_assistant_position_needs": ["2B", "SS"],
            },
        }
        prepare_research_position_filter(session, page="Trend Value", widget_key="trend_position_filter")
        self.assertEqual(session["trend_position_filter"], ["2B", "SS"])

    def test_sync_on_temp_override_until_refresh(self) -> None:
        session = {
            SYNC_POSITION_NEEDS_KEY: True,
            CANONICAL_SETTINGS_KEY: {
                "sync_position_needs_to_research": True,
                "draft_assistant_position_needs": ["C"],
            },
            "trend_position_filter": ["1B"],
        }
        on_research_position_filter_changed(session, page="Trend Value", widget_key="trend_position_filter")
        self.assertTrue(has_research_position_override(session, "Trend Value"))
        prepare_research_position_filter(session, page="Trend Value", widget_key="trend_position_filter")
        self.assertEqual(session["trend_position_filter"], ["1B"])
        clear_research_position_overrides(session)
        prepare_research_position_filter(session, page="Trend Value", widget_key="trend_position_filter")
        self.assertEqual(session["trend_position_filter"], ["C"])

    def test_sync_off_keeps_independent_filters_after_refresh(self) -> None:
        session = {
            SYNC_POSITION_NEEDS_KEY: False,
            CANONICAL_SETTINGS_KEY: {
                "sync_position_needs_to_research": False,
                "draft_assistant_position_needs": ["C"],
                "research_position_filters": {"ML Predictions": ["1B"]},
            },
        }
        clear_research_position_overrides(session)
        prepare_research_position_filter(session, page="ML Predictions", widget_key="ml_position_filter")
        self.assertEqual(session["ml_position_filter"], ["1B"])

    def test_update_draft_assistant_needs_persists(self) -> None:
        session: dict = {}
        update_draft_assistant_position_needs(session, ["2B", "SS"])
        self.assertEqual(read_draft_assistant_position_needs(session), ["2B", "SS"])

    def test_sync_toggle_clears_overrides(self) -> None:
        session = {SYNC_POSITION_NEEDS_KEY: True, "_fantasy_position_page_override:Trend Value": True}
        on_sync_position_needs_toggled(session, source_page="Draft Assistant Simulator")
        self.assertTrue(is_position_sync_enabled(session))
        self.assertFalse(has_research_position_override(session, "Trend Value"))

    def test_independent_filter_saved_when_sync_off(self) -> None:
        session = {
            SYNC_POSITION_NEEDS_KEY: False,
            CANONICAL_SETTINGS_KEY: {"sync_position_needs_to_research": False},
            "value_position_filter": ["OF", "SS"],
        }
        on_research_position_filter_changed(session, page="Valuation", widget_key="value_position_filter")
        saved = read_research_position_filters(session).get("Valuation")
        self.assertEqual(saved, ["OF", "SS"])


class CanonicalSampleSizeTests(unittest.TestCase):
    def test_min_games_syncs_aliases(self) -> None:
        session: dict = {}
        write_canonical_draft_settings(session, min_games=10, min_at_bats=100, source_page="Fantasy Sleepers & Busts")
        self.assertEqual(read_canonical_draft_settings(session)["min_games"], 10)
        self.assertEqual(read_canonical_draft_settings(session)["min_at_bats"], 100)
        self.assertEqual(session["trend_min_g"], 10)
        self.assertEqual(session["ml_min_games"], 10)
        self.assertEqual(session["fantasy_market_min_g"], 10)
        self.assertEqual(session["ml_min_ab"], 100)
        self.assertEqual(session["fantasy_market_min_ab"], 100)

    def test_projection_style_live_draft_to_ml(self) -> None:
        session = {"live_draft_proj_style": "Aggressive / Upside"}
        write_canonical_draft_settings(
            session,
            projection_style=session["live_draft_proj_style"],
            source_page="Live Draft Room",
        )
        self.assertEqual(read_canonical_draft_settings(session)["projection_style"], "Aggressive / Upside")
        self.assertEqual(session["ml_projection_style"], "Aggressive")
        self.assertEqual(session["fantasy_draft_projection_style"], "Aggressive / Upside")

    def test_ml_aggressive_writes_canonical_draft_style(self) -> None:
        session = {"ml_projection_style": "Aggressive"}
        write_canonical_draft_settings(
            session,
            projection_style=session["ml_projection_style"],
            source_page="ML Predictions",
        )
        self.assertEqual(read_canonical_draft_settings(session)["projection_style"], "Aggressive / Upside")
        self.assertEqual(session["live_draft_proj_style"], "Aggressive / Upside")


if __name__ == "__main__":
    unittest.main()
