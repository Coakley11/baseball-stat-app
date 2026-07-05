"""Tests for canonical draft shared settings sync."""

from __future__ import annotations

import unittest

from shared_draft_context import (
    CANONICAL_SETTINGS_KEY,
    GLOBAL_PROJECTION_STYLE_KEY,
    GLOBAL_WINDOW_KEY,
    apply_draft_shared_settings_to_widgets,
    is_draft_shared_session_key,
    is_draft_sync_page,
    prepare_shared_draft_context,
    read_canonical_draft_settings,
    write_canonical_draft_settings,
)


class TestCanonicalDraftSettings(unittest.TestCase):
    def test_single_blob_is_source_of_truth(self) -> None:
        session: dict = {}
        write_canonical_draft_settings(
            session,
            lookback_window=5,
            projection_style="Conservative",
            fantasy_format="Points League",
            source_page="Live Draft Room",
            reason="test",
        )
        blob = session[CANONICAL_SETTINGS_KEY]
        self.assertEqual(blob["lookback_window"], 5)
        self.assertEqual(blob["projection_style"], "Conservative")
        self.assertEqual(blob["fantasy_format"], "Points League")
        self.assertEqual(session[GLOBAL_WINDOW_KEY], 5)
        self.assertEqual(session["draft_window"], 5)
        self.assertEqual(session["fantasy_market_window"], 5)
        self.assertEqual(session[GLOBAL_PROJECTION_STYLE_KEY], "Conservative")
        self.assertEqual(session["live_draft_proj_style"], "Conservative")

    def test_live_draft_change_propagates_to_draft_assistant(self) -> None:
        session = {"draft_window": 3, "fantasy_draft_projection_style": "Balanced", "room_format": "5x5 Roto"}
        write_canonical_draft_settings(
            session,
            lookback_window=5,
            source_page="Live Draft Room",
            reason="lookback",
        )
        prepare_shared_draft_context(session, active_page="Draft Assistant Simulator", force_mirror=True)
        self.assertEqual(session["draft_window"], 5)

    def test_draft_assistant_change_propagates_to_sleepers(self) -> None:
        session = {"fantasy_market_window": 3, "fantasy_market_format": "5x5 Roto"}
        write_canonical_draft_settings(
            session,
            lookback_window=4,
            source_page="Draft Assistant Simulator",
        )
        apply_draft_shared_settings_to_widgets(session, active_page="Fantasy Sleepers & Busts")
        self.assertEqual(session["fantasy_market_window"], 4)

    def test_sleepers_style_propagates_to_draft_room(self) -> None:
        session = {"room_window": 3, "fantasy_draft_projection_style": "Balanced"}
        write_canonical_draft_settings(
            session,
            projection_style="Aggressive / Upside",
            source_page="Fantasy Sleepers & Busts",
        )
        prepare_shared_draft_context(session, active_page="Draft Room Simulator", force_mirror=True)
        self.assertEqual(session["fantasy_draft_projection_style"], "Aggressive / Upside")
        self.assertEqual(session["ml_projection_style"], "Aggressive")

    def test_cloud_hydrate_overrides_stale_page_alias(self) -> None:
        session = {
            "draft_window": 3,
            "room_window": 5,
            CANONICAL_SETTINGS_KEY: {
                "lookback_window": 5,
                "projection_style": "Conservative",
                "fantasy_format": "5x5 Roto",
            },
            "fantasy_draft_projection_style": "Conservative",
            "room_format": "5x5 Roto",
        }
        apply_draft_shared_settings_to_widgets(session, active_page="Draft Assistant Simulator")
        self.assertEqual(session["draft_window"], 5)

    def test_page_restore_cannot_overwrite_canonical(self) -> None:
        session = {
            CANONICAL_SETTINGS_KEY: {
                "lookback_window": 5,
                "projection_style": "Conservative",
                "fantasy_format": "5x5 Roto",
            },
            GLOBAL_WINDOW_KEY: 5,
            GLOBAL_PROJECTION_STYLE_KEY: "Conservative",
            "room_format": "5x5 Roto",
            "draft_window": 3,
        }
        apply_draft_shared_settings_to_widgets(session, active_page="Draft Assistant Simulator")
        self.assertEqual(session["draft_window"], 5)

    def test_research_pages_not_draft_sync(self) -> None:
        self.assertFalse(is_draft_sync_page("Historical Explorer"))
        self.assertTrue(is_draft_sync_page("Trend Value"))
        self.assertTrue(is_draft_sync_page("Draft Lab / Simulation"))
        session = {"draft_window": 3, GLOBAL_WINDOW_KEY: 5}
        prepare_shared_draft_context(session, active_page="Historical Explorer", force_mirror=True)
        self.assertEqual(session["draft_window"], 5)

    def test_shared_keys_excluded_from_page_snapshots(self) -> None:
        self.assertTrue(is_draft_shared_session_key("draft_window"))
        self.assertTrue(is_draft_shared_session_key("fantasy_market_window"))
        self.assertFalse(is_draft_shared_session_key("draft_top_n"))

    def test_cross_device_cloud_values_hydrate(self) -> None:
        from shared_draft_context import hydrate_canonical_draft_settings_from_session, record_cloud_draft_settings_snapshot

        session: dict = {
            GLOBAL_WINDOW_KEY: 5,
            GLOBAL_PROJECTION_STYLE_KEY: "Conservative",
            "room_format": "Points League",
        }
        record_cloud_draft_settings_snapshot(session, session)
        hydrate_canonical_draft_settings_from_session(session)
        cur = read_canonical_draft_settings(session)
        self.assertEqual(cur["lookback_window"], 5)
        self.assertEqual(cur["projection_style"], "Conservative")
        self.assertEqual(cur["fantasy_format"], "Points League")

    def test_ml_settings_in_canonical_blob(self) -> None:
        session: dict = {}
        write_canonical_draft_settings(
            session,
            ml_blend_enabled=False,
            ml_signal_weight=0.20,
            ml_min_recent_games=40,
            source_page="Draft Assistant Simulator",
        )
        cur = read_canonical_draft_settings(session)
        self.assertFalse(cur["ml_blend_enabled"])
        self.assertEqual(cur["ml_signal_weight"], 0.20)
        self.assertEqual(cur["ml_min_recent_games"], 40)
        self.assertFalse(session["draft_use_ml_blend"])
        self.assertEqual(session["draft_ml_blend_weight"], 0.20)
        self.assertEqual(session["draft_ml_min_games_signal"], 40)

    def test_ml_predictions_lookback_updates_canonical_and_aliases(self) -> None:
        session = {"draft_window": 3, "trend_lag": 3, "value_lag": 3, "ml_lookback": 3}
        write_canonical_draft_settings(session, lookback_window=4, source_page="ML Predictions")
        from shared_draft_context import prepare_canonical_scoring_context

        prepare_canonical_scoring_context(session, active_page="Trend Value")
        self.assertEqual(session["trend_lag"], 4)
        self.assertEqual(session["value_lag"], 4)
        self.assertEqual(session["ml_lookback"], 4)
        self.assertEqual(session["draft_window"], 4)

    def test_ml_predictions_style_updates_canonical(self) -> None:
        session = {"ml_projection_style": "Balanced", "fantasy_draft_projection_style": "Balanced"}
        write_canonical_draft_settings(session, projection_style="Aggressive", source_page="ML Predictions")
        self.assertEqual(session["ml_projection_style"], "Aggressive")
        self.assertEqual(session["fantasy_draft_projection_style"], "Aggressive / Upside")
        self.assertEqual(read_canonical_draft_settings(session)["projection_style"], "Aggressive / Upside")

    def test_draft_pool_kwargs_from_session(self) -> None:
        from shared_draft_context import draft_pool_kwargs_from_session

        session = {}
        write_canonical_draft_settings(
            session,
            lookback_window=5,
            projection_style="Conservative",
            fantasy_format="Points League",
            ml_blend_enabled=True,
            ml_signal_weight=0.18,
            ml_min_recent_games=60,
        )
        kw = draft_pool_kwargs_from_session(session)
        self.assertEqual(kw["draft_window"], 5)
        self.assertEqual(kw["projection_style"], "Conservative")
        self.assertEqual(kw["fantasy_format"], "Points League")
        self.assertTrue(kw["use_ml_blend"])
        self.assertEqual(kw["ml_blend_weight"], 0.18)
        self.assertEqual(kw["ml_min_games_for_signal"], 60)

    def test_draft_assistant_change_propagates_to_draft_lab(self) -> None:
        session: dict = {"draft_lab_window": 3, "draft_lab_projection_style": "Balanced", "draft_lab_scoring_type": "5x5 Roto"}
        write_canonical_draft_settings(
            session,
            lookback_window=5,
            projection_style="Conservative",
            fantasy_format="Points League",
            source_page="Draft Assistant Simulator",
        )
        apply_draft_shared_settings_to_widgets(session, active_page="Draft Lab / Simulation", force_all_pages=True)
        self.assertEqual(session["draft_lab_window"], 5)
        self.assertEqual(session["draft_lab_projection_style"], "Conservative")
        self.assertEqual(session["draft_lab_scoring_type"], "Points League")

    def test_draft_lab_is_sync_page(self) -> None:
        self.assertTrue(is_draft_sync_page("Draft Lab / Simulation"))


if __name__ == "__main__":
    unittest.main()
